"""Actual BASE-only HTTP formal refusal before any producer/budget effects."""
# ruff: noqa: F401,F811

import json
import os
from pathlib import Path

import pytest
from test_package_technical_eligibility_pg import frozen
from test_package_technical_scope_pg import api as scope_api
from test_package_technical_scope_pg import database, exact, headers, requirements, world

from apps.api.package_technical_execution import router
from packages.contracts import package_technical_execution_api as contracts
from packages.domain.runtime import connection
from packages.model_governance import package_scoring_profile as method

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_TECHNICAL_SCOPE_PG") != "1",
    reason="fresh F06 BASE-only database explicitly required",
)


@pytest.fixture
def api(database):
    source = scope_api.__wrapped__(database)
    value = next(source)
    app = value["app"]
    if not any(
        getattr(route, "path", "").endswith("/technical-scopes/{scope_id}/execution-context")
        for route in app.router.routes
    ):
        app.include_router(router)
    app.openapi_schema = None
    try:
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def formal_refusal(w, saved, path, foundation):
    if not any(
        getattr(route, "path", "").endswith("/technical-scopes/{scope_id}/execution-context")
        for route in w["app"].router.routes
    ):
        w["app"].include_router(router)
    w["app"].openapi_schema = None
    result = w["client"].get(path + "/execution-context")
    assert result.status_code == 200, result.text
    context = result.json()
    contracts.validate("PackageTechnicalExecutionContext", context)
    assert context["producer"]["software_foundation"] == foundation
    assert not context["execution_enabled"]
    assert context["qualification"]["scope"]["scope_digest"] == saved["digest"]
    assert context["qualification"]["official_label_access"] == "forbidden"
    body = {
        "purpose": "current_prebid",
        "scope_digest": saved["digest"],
        "method_digest": method.digest(),
        "scale_id": None,
        "budget": "0",
        "reason": "Synthetic formal request must not borrow isolated mechanism eligibility",
    }
    refused = w["client"].post(
        path + "/executions", json=body, headers=headers(w, etag=result.headers["etag"])
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "PACKAGE_TECHNICAL_EXECUTION_BLOCKED"
    details = refused.json()["details"]
    assert details["jobs_created"] == 0 and details["model_requests"] == 0
    codes = {row["code"] for row in details["blockers"]}
    assert {
        "PACKAGE_SCORE_FORMAL_RANGE_AUTHORITY_MISSING",
        "PACKAGE_SCORE_VISUAL_AUTHORITY_MISSING",
        "PACKAGE_SCORE_PROVIDER_NOT_CONFIGURED",
        "THREE_VALID_INDEPENDENT_JUDGMENTS_REQUIRED",
        "ORIGINAL_BYTES_RECHECK_REQUIRED",
    } <= codes
    assert (
        w["client"]
        .post(
            path + "/executions",
            json=body | {"formal_scoring_eligible": True},
            headers=headers(w, etag=result.headers["etag"]),
        )
        .status_code
        == 422
    )
    assert (
        w["client"]
        .post(
            path + "/executions",
            json=body | {"mechanism_test": True},
            headers=headers(w, etag=result.headers["etag"]),
        )
        .status_code
        == 422
    )
    assert (
        w["client"]
        .post(path + "/executions", json=body, headers=headers(w, etag='"stale"'))
        .status_code
        == 412
    )
    assert w["client"].post(path + "/executions", json=body, headers=headers(w)).status_code == 428
    destination = os.environ.get("FUSION_PACKAGE_SCORE_EXECUTION_FIXTURE")
    if destination:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schema": "package-technical-execution-http-fixture/1",
                    "evidence": "Authenticated actual PostgreSQL/ASGI with synthetic materials; no real provider or eligibility",
                    "basePath": path,
                    "scope": saved,
                    "context": context,
                    "etag": result.headers["etag"],
                    "request": body,
                    "refusal": refused.json(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return context


def test_base_only_execution_api_lists_actual_gaps_without_optional_sql_or_calls(exact):
    saved, path = frozen(exact)
    with connection() as c:
        assert (
            c.execute("SELECT to_regclass('score_execution.jobs') AS value").fetchone()["value"]
            is None
        )
    formal_refusal(exact, saved, path, "not_installed")
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.samples WHERE bid_id=%s", (exact["scope"].bid_id,)
            ).fetchone()["n"]
            == 0
        )


def test_complete_material_refusal_is_durable_idempotent_and_csrf_protected(exact):
    from uuid import uuid4

    saved, path = frozen(exact)
    context = exact["client"].get(path + "/material-execution-context")
    assert context.status_code == 200, context.text
    value = context.json()
    body = {
        "version": "package-material-execution-check/1",
        "scope_digest": saved["digest"],
        **{k: v for k, v in value["target"].items() if k != "profile"},
        "input_reference": None,
        "budget_usd": "0",
    }
    h = headers(exact, etag=context.headers["etag"])
    h["Idempotency-Key"] = str(uuid4())
    first = exact["client"].post(path + "/material-execution-checks", json=body, headers=h)
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "blocked" and first.json()["jobs_created"] == 0
    again = exact["client"].post(path + "/material-execution-checks", json=body, headers=h)
    assert again.status_code == 200 and again.json() == first.json()
    assert again.headers["Idempotent-Replayed"] == "true"
    conflict = exact["client"].post(
        path + "/material-execution-checks", json=body | {"budget_usd": "1"}, headers=h
    )
    assert conflict.status_code == 409
    assert exact["client"].post(path + "/material-execution-checks", json=body).status_code == 403
    with connection() as c:
        row = c.execute(
            "SELECT count(*) AS n FROM design.commands WHERE command_kind='check-package-material-execution' AND target_id=%s",
            (saved["manifest"]["id"],),
        ).fetchone()
        assert row["n"] == 1
