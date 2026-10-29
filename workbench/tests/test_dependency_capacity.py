"""Large synthetic inventories retain one exact plan; request byte limits precede side effects."""
# ruff: noqa: F401,F811

import asyncio
import json
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import fastapi.routing
import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from test_package_input_dependencies import case, declaration, rebind, run, uid

from apps.api import bid_package_dependency_plan_routes as plan_routes
from apps.api import bid_package_dependency_routes as check_routes
from packages.contracts.bid_package_requirements_api import validate
from packages.domain import bid_package_dependency_plans as service
from packages.domain import bid_package_input_dependencies as checks
from packages.domain import package_dependency_plan as plans
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError

MAX_BYTES = 4 * 1024 * 1024
MAX_WIRE_BYTES = 5 * 1024 * 1024


def readonly_commands(monkeypatch, old=None):
    lookups = []

    class ReadOnly:
        def execute(self, query, args=None):
            if query == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY":
                return None
            assert query.startswith("SELECT request_digest,response FROM design.commands")
            lookups.append(args)
            return SimpleNamespace(fetchone=lambda: old)

    @contextmanager
    def connection():
        assert not lookups, "must never enter a new writable transaction"
        yield ReadOnly()

    monkeypatch.setattr(service, "connection", connection)
    return lookups


def enlarge(case, count):
    rows = []
    for number in range(1000, count + 1000):
        row = deepcopy(case["row"])
        row["rule_id"] = row["rule_snapshot"]["id"] = row["requirement"]["requirement_id"] = uid(
            number
        )
        row["rule_digest"] = digest(row["rule_snapshot"])
        row["requirement_digest"] = digest(row["requirement"])
        rows.append(row)
    case["root"]["selection"]["inventory"]["manifest"]["requirements"] = rows
    rebind(case)
    return [
        declaration(case, "not_needed", [])
        | {"requirement_id": row["rule_id"], "requirement_digest": row["requirement_digest"]}
        for row in rows
    ]


def request(case, dependencies):
    return {
        "execution_input_digest": case["prepared"].digest,
        "purpose": "prebid_compliance",
        "fact_ids": [],
        "dependencies": dependencies,
    }


def test_501_annotations_form_one_exact_plan_and_omitted_last_row_stays_unknown(case, monkeypatch):
    declarations = enlarge(case, 501)
    partial, _, _ = run(case, declarations[:500], selected=())
    assert partial.view()["manifest"]["required_facts_assessment"] == "unknown"
    body = request(case, declarations)
    validate("CheckPackageInputDependencies", body)
    assessment, usage, _ = run(case, declarations, selected=())
    am = assessment.view()["manifest"]
    assert am["requirement_count"] == 501
    assert am["dependency_review_status"] == "declared"
    assert am["required_facts_assessment"] == "not_used"
    assert am["review_ready"] is am["facts_qualified"] is am["inventory_complete"] is False
    body.update(assessment_digest=assessment.digest, reason="明确保存同一准备输入的全部501条标注")
    validate("SavePackageDependencyPlan", body)
    plan = plans.build(
        case["frozen"],
        case["prepared"],
        usage,
        assessment,
        record_id=uid(90),
        actor_id=uid(91),
        command_id=uid(92),
        saved_at="2026-10-21T08:00:00.000000Z",
        body=body,
    )
    monkeypatch.setattr(
        plans.dependencies, "assess", lambda *_: pytest.fail("history recomputed policy")
    )
    assert plans.read(plan.view(), case["frozen"], case["prepared"]).view() == plan.view()


def test_dependency_count_limit_is_ten_thousand_without_expanding_fact_limits(case):
    rows = enlarge(case, 10000)
    body = request(case, rows)
    validate("CheckPackageInputDependencies", body)
    result, _, _ = run(case, rows, selected=())
    assert result.view()["manifest"]["requirement_count"] == 10000
    assert result.view()["manifest"]["dependency_review_status"] == "declared"
    assert result.view()["manifest"]["required_facts_assessment"] == "not_used"
    extra = rows + [deepcopy(rows[0]) | {"requirement_id": uid(20000)}]
    with pytest.raises(DomainError):
        validate("CheckPackageInputDependencies", request(case, extra))
    with pytest.raises(ValueError, match="contract"):
        run(case, extra, selected=())
    body["dependencies"] = [deepcopy(rows[0])]
    body["dependencies"][0]["fact_ids"] = [uid(n) for n in range(501)]
    body["dependencies"][0]["state"] = "required"
    with pytest.raises(DomainError):
        validate("CheckPackageInputDependencies", body)


def oversized():
    # Still within the old per-field and 500-row structural limits; UTF-8 bytes,
    # not Python/JavaScript string length, exceed 4 MiB.
    return {
        "execution_input_digest": "a" * 64,
        "purpose": "prebid_compliance",
        "fact_ids": [uid(n) for n in range(60)],
        "dependencies": [
            {
                "requirement_id": uid(1000 + n),
                "requirement_digest": "b" * 64,
                "state": "required",
                "fact_ids": [uid(j) for j in range(60)],
                "evidence_ids": [uid(900)],
                "reason": "据" * 2000,
            }
            for n in range(500)
        ],
    }


@pytest.mark.parametrize("operation", ["check", "save"])
def test_oversized_final_body_is_413_before_observation_or_a_new_writable_transaction(
    monkeypatch, operation
):
    body = oversized()
    if operation == "save":
        body.update(assessment_digest="c" * 64, reason="明确保存")
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    assert len(raw) < MAX_BYTES < len(raw.encode("utf-8"))
    monkeypatch.setattr(
        checks, "observe", lambda *_args, **_kw: pytest.fail("oversized check processed")
    )
    lookups = readonly_commands(monkeypatch)
    with pytest.raises(DomainError) as failure:
        if operation == "check":
            checks.check(tuple(uid(n) for n in range(1, 5)), uid(5), uid(6), body)
        else:
            service.save(uid(90), tuple(uid(n) for n in range(1, 5)), uid(5), uid(6), "key", body)
    assert failure.value.status == 413
    assert failure.value.code == "PACKAGE_DEPENDENCY_BODY_TOO_LARGE"
    assert len(lookups) == (1 if operation == "save" else 0)


def test_existing_large_plan_ack_is_verified_and_replayed_before_the_new_write_budget(
    case, monkeypatch
):
    declarations = enlarge(case, 500)
    evidence = [uid(n) for n in range(20000, 20100)]
    case["root"]["documents"][0]["blocks"] = [{"id": value} for value in evidence]
    for row, annotated in zip(
        case["root"]["selection"]["inventory"]["manifest"]["requirements"],
        declarations,
        strict=True,
    ):
        row["rule_snapshot"]["evidence_ids"] = evidence
        row["rule_digest"] = digest(row["rule_snapshot"])
        annotated.update(evidence_ids=evidence, reason="据" * 2000)
    rebind(case)
    assessment, usage, _ = run(case, declarations, selected=())
    body = request(case, declarations) | {
        "assessment_digest": assessment.digest,
        "reason": "旧版已保存的大请求",
    }
    size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert MAX_BYTES < size < MAX_WIRE_BYTES
    plan = plans.build(
        case["frozen"],
        case["prepared"],
        usage,
        assessment,
        record_id=uid(90),
        actor_id=uid(91),
        command_id=uid(92),
        saved_at="2026-10-20T08:00:00.000000Z",
        body=body,
    ).view()
    response = {"body": plan, "status": 201, "headers": {}}
    lookups = readonly_commands(
        monkeypatch,
        {"request_digest": digest({"body": body, "if_match": None}), "response": response},
    )
    # Keep actual historical binding/digest validation; only the database port
    # supplying the already persisted immutable plan is controlled.
    monkeypatch.setattr(
        service.repository,
        "load",
        lambda *_: plans.read(plan, case["frozen"], case["prepared"]).view(),
    )
    monkeypatch.setattr(
        plans.dependencies, "assess", lambda *_: pytest.fail("ACK must not reassess today's policy")
    )
    assert service.save(
        uid(91),
        case["prepared"].scope,
        case["prepared"].frozen_id,
        case["prepared"].input_id,
        "old-key",
        body,
    ) == (response, True)
    assert len(lookups) == 1


@pytest.mark.parametrize("endpoint", ["dependency-check", "dependency-plans"])
@pytest.mark.parametrize("extra", [0, 1])
def test_http_limit_counts_exact_wire_bytes_including_json_whitespace(monkeypatch, endpoint, extra):
    # This sandbox's sync-to-worker bridge can stall. Keep real ASGI routing,
    # JSON parsing, and dependency execution; thread scheduling is not asserted.
    async def inline_sync(call, *args, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(fastapi.routing, "run_in_threadpool", inline_sync)
    processed = []
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def error_handler(_, error):
        return JSONResponse({"code": error.code}, status_code=error.status)

    prefix = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories"
    app.include_router(check_routes.router, prefix=prefix)
    app.include_router(plan_routes.router, prefix=prefix)
    monkeypatch.setattr(check_routes, "auth", lambda *_: None)
    monkeypatch.setattr(plan_routes, "auth", lambda *_: {"member_id": uid(90)})
    monkeypatch.setattr(
        check_routes, "check", lambda *_: processed.append(True) or {"processed": True}
    )
    monkeypatch.setattr(
        service,
        "save",
        lambda *_: (
            processed.append(True) or {"body": {"processed": True}, "status": 201, "headers": {}},
            False,
        ),
    )
    body = {
        "execution_input_digest": "a" * 64,
        "purpose": "prebid_compliance",
        "fact_ids": [],
        "dependencies": [],
    }
    if endpoint == "dependency-plans":
        body.update(assessment_digest="b" * 64, reason="保存")
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raw += b" " * (MAX_WIRE_BYTES + extra - len(raw))
    path = f"/api/v1/bids/{uid(1)}/packages/{uid(2)}/revisions/{uid(3)}/requirement-inventories/{uid(4)}/frozen-review-inputs/{uid(5)}/execution-inputs/{uid(6)}/{endpoint}"

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                path,
                content=raw,
                headers={"Content-Type": "application/json", "Idempotency-Key": "test"},
            )

    response = asyncio.run(send())
    if extra:
        assert response.status_code == 413
        assert processed == []
    else:
        assert response.status_code in (200, 201)
        assert processed == [True]
