"""F04 actual API/Worker roles, exact original bytes and atomic human derivations.

All documents, identities and model receipts are synthetic. No provider is called.
"""
# ruff: noqa: F811,F401

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_bid_package_api import world as package_world
from test_bid_package_requirements_api import (
    database as base_database,
)
from test_bid_package_requirements_api import (
    inventory,
    package_extraction_document,
    requirements,
)
from test_stable_lot_identity import api, catalog, headers, post, uid

from packages.contracts.package_rule_corrections_api import valid
from packages.domain import bid_package_rule_correction_repository as repository
from packages.domain import bid_package_rule_corrections as service
from packages.domain import storage
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, connection, enqueue_plan, sha

ADMIN_DSN = os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN")
pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="isolated actual nonowner F04 PG17")
RAW = b"%PDF-1.7\nSynthetic F04 exact original, no business content.\n%%EOF\n"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def database():
    yield_from = base_database.__wrapped__()
    value = next(yield_from)
    try:
        owner = value["owner"]
        if (
            owner.execute(
                "SELECT to_regclass('design.bid_package_rule_corrections') AS name"
            ).fetchone()["name"]
            is None
        ):
            owner.execute(
                (ROOT / "packages/contracts/sql/bid-package-rule-corrections.sql").read_text()
            )
        yield value
    finally:
        try:
            next(yield_from)
        except StopIteration:
            pass


@pytest.fixture
def world(api):
    return package_world.__wrapped__(api, SimpleNamespace(param=RAW))


@pytest.fixture
def exact(requirements, monkeypatch):
    from packages.domain.bid_package_extraction import (
        freeze_matching_input,
        record_completion,
        validate_frozen_input,
    )
    from packages.domain.bid_package_repository import load_revision
    from packages.domain.human_decisions import append_decision
    from packages.domain.review_data import save_json

    w = requirements
    # All runtime writes below use the API role. Owner only bootstraps shared synthetic fixtures.
    with connection() as c:
        assert (
            c.execute("SELECT current_user AS name").fetchone()["name"]
            == "fusion_package_requirements_service"
        )
        for index in range(2):
            identity = uid()
            c.execute(
                "INSERT INTO design.rule_items(id,bid_id,rule_set_id,kind,statement,conditions,exceptions,evidence_ids,bands) VALUES(%s,%s,%s,'mandatory',%s,'[]','[]',%s,'[]')",
                (
                    identity,
                    w["scope"].bid_id,
                    w["inventory_body"]["rule_set_id"],
                    f"Synthetic original obligation {index}",
                    [w["evidence"]],
                ),
            )
            append_decision(
                c,
                w["scope"].bid_id,
                w["actor"],
                "rule",
                identity,
                {
                    "decision": "confirmed",
                    "reason": "Synthetic original confirmation",
                    "evidence_ids": [w["evidence"]],
                },
            )
    first = inventory(w)
    assert first.status_code == 201, first.text
    objects = {}
    monkeypatch.setattr(storage, "put", lambda key, data, media: objects.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: objects[key])
    monkeypatch.setenv("WORKER_DATABASE_DSN", w["database"]["worker_dsn"])
    with connection() as c:
        authority = load_revision(
            c, w["scope"].bid_id, w["inventory_body"]["authority_revision_id"]
        )
        document = package_extraction_document(c, authority)
        method = {"engine": "synthetic-test-only", "version": "F04-1"}
        method_digest = digest(method)
        slot = uid()
        frozen = freeze_matching_input(
            c, w["scope"].bid_id, slot, [document], method, method_digest
        )
    blob = save_json(
        {"documents": [document], "package_rule_extraction_input": frozen}, worker=True
    )
    operation_digest = digest({"frozen": frozen["digest"]})
    with connection() as c:
        command = uid()
        c.execute(
            "INSERT INTO design.commands(id,actor_id,command_kind,target_id,idempotency_key,request_digest) VALUES(%s,%s,'synthetic-f04-extraction',%s,%s,%s)",
            (command, w["actor"], w["scope"].bid_id, uid(), operation_digest),
        )
        operation = enqueue_plan(
            c,
            w["scope"].bid_id,
            command,
            "prepare-review",
            {"id": blob["id"]},
            stages=[{"key": "extract-rules", "depends_on": []}],
            handler_version="prepare/1",
            topic="tender.task.review.v1",
            input_digest=operation_digest,
        )
    result = {
        "input_digest": frozen["digest"],
        "rule_set_id": w["inventory_body"]["rule_set_id"],
        "authority_revision_id": authority.revision_id,
        "authority_digest": authority.manifest_digest,
        "method_digest": method_digest,
        "range_status": "all_frozen_evidence_submitted",
        "read_evidence_ids_digest": digest(sorted(row["id"] for row in document["blocks"])),
        "extraction_coverage": "partial",
        "quality_status": "not_measured",
    }
    with psycopg.connect(w["database"]["worker_dsn"], row_factory=dict_row) as c:
        c.execute("SET search_path=design,public")
        assert (
            c.execute("SELECT current_user AS name").fetchone()["name"]
            == "fusion_package_requirements_worker"
        )
        validate_frozen_input(c, w["scope"].bid_id, frozen, [document], method, method_digest, slot)
        record_completion(
            c,
            {
                "bid_id": w["scope"].bid_id,
                "operation_id": operation["id"],
                "input_digest": operation_digest,
                "payload_ref": blob["id"],
            },
            frozen,
            w["inventory_body"]["rule_set_id"],
            result,
        )
        c.execute(
            "INSERT INTO design.effect_receipts(operation_id,effect_key,result) VALUES(%s,'extract-rules',%s)",
            (
                operation["id"],
                Jsonb(
                    {
                        "result_ref": w["inventory_body"]["rule_set_id"],
                        "method_digest": method_digest,
                        "extraction_input_digest": frozen["digest"],
                    }
                ),
            ),
        )
        c.execute(
            "UPDATE design.operations SET state='succeeded',finished_at=now() WHERE id=%s",
            (operation["id"],),
        )
    base_response = inventory(w, tag=first.headers["etag"])
    assert base_response.status_code == 201, base_response.text
    base = base_response.json()
    assert base["manifest"]["version"] == "bid-package-requirements/2"
    scope = (
        w["scope"].bid_id,
        w["own"]["manifest"]["package_id"],
        w["own"]["manifest"]["revision_id"],
        base["manifest"]["id"],
    )
    io_state = {"calls": [], "raw": RAW, "callback": None}

    class ObjectClient:
        def get_object(self, *, Bucket, Key):
            if not io_state.get("concurrent_requests"):
                sessions = (
                    w["database"]["owner"]
                    .execute(
                        "SELECT xact_start,(SELECT count(*) FROM pg_locks l WHERE l.pid=a.pid AND l.granted) AS held_locks FROM pg_stat_activity a WHERE datname=current_database() AND usename='fusion_package_requirements_service'"
                    )
                    .fetchall()
                )
                assert all(
                    row["xact_start"] is None and row["held_locks"] == 0 for row in sessions
                ), sessions
            io_state["calls"].append(Key)
            if io_state["callback"]:
                io_state["callback"]()
            return {"Body": io.BytesIO(io_state["raw"])}

    monkeypatch.setattr(storage, "client", lambda: ObjectClient())
    monkeypatch.setattr(storage, "bucket", lambda: "synthetic-f04")
    rule_rows = base["manifest"]["requirements"]
    addition = {
        "kind": "scoring",
        "statement": "Synthetic scored requirement",
        "conditions": ["synthetic page 1"],
        "exceptions": ["synthetic"],
        "scope": {"bid_id": scope[0], "description": "本标段人工评分解释"},
        "maximum": "1",
        "bands": [
            {
                "label": "一分",
                "description": "synthetic page 1",
                "points": "1",
                "evidence_ids": [w["evidence"]],
            }
        ],
        "evidence_quotes": [{"evidence_id": w["evidence"], "quote": "synthetic page 1"}],
    }
    request = {
        "base_inventory_digest": base["digest"],
        "base_rule_set_digest": base["manifest"]["rule_set_digest"],
        "reason": "逐条核对原权威包，补漏、更正并记录不再采用的解释",
        "changes": [
            {"op": "add", "rule": addition},
            {
                "op": "replace",
                "rule_id": rule_rows[0]["rule_id"],
                "rule_digest": rule_rows[0]["rule_digest"],
                "rule": {
                    **addition,
                    "statement": "Synthetic revised obligation",
                    "kind": "mandatory",
                    "maximum": None,
                    "bands": [],
                },
            },
            {
                "op": "withdraw",
                "rule_id": rule_rows[1]["rule_id"],
                "rule_digest": rule_rows[1]["rule_digest"],
                "evidence_quotes": [{"evidence_id": w["evidence"], "quote": "synthetic page 1"}],
            },
        ],
    }
    return w | {
        "inventory": base,
        "inventory_etag": base_response.headers["etag"],
        "correction_scope": scope,
        "correction_url": w["requirement_base"] + "/" + scope[3] + "/rule-corrections",
        "request": request,
        "io": io_state,
        "frozen_extraction": frozen,
    }


def preview(w, request=None):
    response = w["client"].post(
        w["correction_url"] + "/preview", json=request or w["request"], headers=headers(w)
    )
    assert response.status_code == 200, response.text
    assert valid("PackageRuleCorrectionPreviewView", response.json())
    assert not w["io"]["calls"]
    return response.json()


def apply(w, *, body=None, key=None, tag=None):
    if body is None:
        body = {"request": w["request"], "preview_digest": preview(w)["digest"]}
    return w["client"].post(
        w["correction_url"],
        json=body,
        headers=headers(w, key=key) | {"If-Match": tag or w["inventory_etag"]},
    )


def test_exact_apply_native_rows_root_and_original_ack(exact):
    w = exact
    prepared = preview(w)
    body = {"request": w["request"], "preview_digest": prepared["digest"]}
    key = uid()
    response = apply(w, body=body, key=key)
    if response.status_code == 503:
        service.apply(w["correction_scope"], w["actor"], key, body, w["inventory_etag"])
    assert response.status_code == 201, response.text
    value = response.json()
    assert valid("PackageRuleCorrectionAppliedView", value)
    manifest = value["inventory"]["manifest"]
    assert manifest["version"] == "bid-package-requirements/3"
    assert manifest["extraction_basis"]["inventory_id"] == w["inventory"]["manifest"]["id"]
    assert manifest["extraction_basis"]["extraction_coverage"] == "partial"
    assert manifest["inventory_complete"] is False and manifest["review_ready"] is False
    assert len(manifest["requirements"]) == 4
    assert (
        sum(
            row["rule_snapshot"]["provenance_status"] == "superseded"
            for row in manifest["requirements"]
        )
        == 1
    )
    assert len(w["io"]["calls"]) == 1
    assert value["command"]["request"] == body
    assert value["command"]["request_digest"] == repository.command_digest(
        w["correction_scope"], body, w["inventory_etag"]
    )
    replay = apply(w, body=body, key=key)
    assert replay.status_code == 201 and replay.json() == value
    assert len(w["io"]["calls"]) == 1
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.bid_package_requirement_extraction_runs WHERE bid_id=%s",
                (w["scope"].bid_id,),
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.rule_items WHERE rule_set_id=%s",
                (manifest["rule_set_id"],),
            ).fetchone()["n"]
            == 4
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.rule_carryovers WHERE new_rule_id=ANY(%s::uuid[])",
                ([row["rule_id"] for row in manifest["requirements"]],),
            ).fetchone()["n"]
            == 1
        )
    history = w["client"].get(w["correction_url"])
    assert history.status_code == 200, history.text
    assert len(history.json()["items"]) == 1
    detail = w["client"].get(w["correction_url"] + "/" + value["correction"]["manifest"]["id"])
    assert detail.status_code == 200 and detail.json() == value
    evidence_url = w["correction_url"].rsplit("/", 1)[0] + "/rule-correction-evidence"
    evidence_page = w["client"].get(evidence_url)
    assert evidence_page.status_code == 200, evidence_page.text
    evidence_details = []
    for item in evidence_page.json()["items"]:
        item_response = w["client"].get(evidence_url + "/" + item["evidence_id"])
        assert item_response.status_code == 200, item_response.text
        evidence_details.append(item_response.json())
    output = Path("/tmp/tender-completion-runtime/package-rule-corrections-browser")
    output.mkdir(parents=True, exist_ok=True)
    packets = {
        "package": w["own"],
        "inventory": w["inventory"],
        "evidence-page": evidence_page.json(),
        "evidence-details": evidence_details,
        "preview": prepared,
        "applied": value,
        "history": history.json(),
        "headers": {"base_etag": w["inventory_etag"], "applied_etag": response.headers["etag"]},
        "scope": {
            "ids": list(w["correction_scope"]),
            "actor_id": w["actor"],
            "boundary": "Synthetic exact PG service responses; browser transport may replay these fixtures. No provider called; extraction partial and quality unmeasured.",
        },
    }
    for name, packet in packets.items():
        (output / (name + ".json")).write_text(
            json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def counts(w):
    with connection() as c:
        return {
            table: c.execute(
                f"SELECT count(*) AS n FROM design.{table} WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            for table in (
                "bid_package_rule_corrections",
                "rule_sets",
                "rule_items",
                "decisions",
                "rule_carryovers",
                "bid_package_requirement_inventories",
            )
        } | {
            "head": c.execute(
                "SELECT current_rule_set_id::text AS id FROM design.bid_profiles WHERE bid_id=%s",
                (w["scope"].bid_id,),
            ).fetchone()["id"]
        }


def test_reprojection_second_step_and_readonly_worker_receipt(exact):
    from packages.domain import bid_package_inventory_proof as proof_reader
    from packages.domain import bid_package_requirement_repository as inventories
    from packages.domain import package_rule_corrections as policy

    w = exact
    first = apply(w)
    assert first.status_code == 201, first.text
    one = first.json()
    rebased = inventory(
        w,
        tag=first.headers["etag"],
        body={
            "authority_revision_id": w["inventory_body"]["authority_revision_id"],
            "rule_set_id": one["inventory"]["manifest"]["rule_set_id"],
            "mappings": [],
        },
    )
    assert rebased.status_code == 201, rebased.text
    next_inventory = rebased.json()
    assert (
        next_inventory["manifest"]["human_derivation"]
        == one["inventory"]["manifest"]["human_derivation"]
    )
    assert (
        next_inventory["manifest"]["id"] != one["correction"]["manifest"]["result"]["inventory_id"]
    )
    new_request = {
        "base_inventory_digest": next_inventory["digest"],
        "base_rule_set_digest": next_inventory["manifest"]["rule_set_digest"],
        "reason": "第二次明确补漏，原人工撤销仍保留",
        "changes": [
            {
                "op": "add",
                "rule": {
                    **w["request"]["changes"][1]["rule"],
                    "statement": "Synthetic second additional obligation",
                },
            }
        ],
    }
    scope = (*w["correction_scope"][:3], next_inventory["manifest"]["id"])
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        prepared = service.preview(c, scope, new_request)
    saved, replayed = service.apply(
        scope,
        w["actor"],
        uid(),
        {"request": new_request, "preview_digest": prepared["digest"]},
        rebased.headers["etag"],
    )
    assert not replayed
    final = saved["body"]["inventory"]
    assert final["manifest"]["human_derivation"]["length"] == 2
    with psycopg.connect(w["database"]["worker_dsn"], row_factory=dict_row) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        c.execute("SET LOCAL search_path=design,public")
        receipt = proof_reader._receipt(c, scope, final["manifest"])
        assert len(receipt["derivation"]["steps"]) == 2
        assert receipt["run"]["id"] == w["inventory"]["manifest"]["extraction_result_id"]
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.bid_package_rule_corrections','INSERT') AS allowed"
        ).fetchone()["allowed"]
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.commands','SELECT') AS allowed"
        ).fetchone()["allowed"]
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        official = repository.authority(c, scope[0], final)
        chain = repository.read_derivation(c, scope[0], final["manifest"])
        evidence = repository.evidence_rows(c, scope[0], official)
        verified = policy.verify_derivation(final, chain, official, evidence)
        assert verified["counts"]["human_withdrawn"] == 1
        assert inventories.load_inventory(c, *scope[:3], final["manifest"]["id"]) == final
        # The selected descendant scope may read the exact ancestor ACK, never latest.
        descendant = (*scope[:3], final["manifest"]["id"])
        assert service.load(c, descendant, one["correction"]["manifest"]["id"]) == one


def test_original_ack_survives_closure_source_withdrawal_and_unavailable_store(exact):
    w = exact
    prepared = preview(w)
    body = {"request": w["request"], "preview_digest": prepared["digest"]}
    key = uid()
    response = apply(w, body=body, key=key)
    assert response.status_code == 201, response.text
    with connection() as c:
        c.execute(
            "UPDATE design.bid_profiles SET phase='terminated' WHERE bid_id=%s",
            (w["scope"].bid_id,),
        )
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (w["sources"][1],),
        )

    def unavailable():
        raise AssertionError("Original ACK or historical read attempted object IO")

    w["io"]["callback"] = unavailable
    saved, replay = service.apply(w["correction_scope"], w["actor"], key, body, w["inventory_etag"])
    assert replay and saved["body"] == response.json()
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        assert (
            service.load(c, w["correction_scope"], response.json()["correction"]["manifest"]["id"])
            == response.json()
        )
        assert len(service.history(c, w["correction_scope"])["items"]) == 1
    different = deepcopy(body)
    different["request"]["reason"] = "Changed original request"
    with pytest.raises(DomainError, match="同一幂等键") as conflict:
        service.apply(w["correction_scope"], w["actor"], key, different, w["inventory_etag"])
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(DomainError) as conflict:
        service.apply(w["correction_scope"], w["actor"], key, body, '"different"')
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "case", ["corrupt_bytes", "source_during_io", "closure_during_io", "decision_during_io"]
)
def test_double_observation_and_no_partial_writes(exact, case):
    from packages.domain.human_decisions import append_decision

    w = exact
    prepared = preview(w)
    before = counts(w)
    if case == "corrupt_bytes":
        w["io"]["raw"] = b"corrupted original"
    else:

        def change():
            w["io"]["callback"] = None
            with connection() as c:
                if case == "source_during_io":
                    c.execute(
                        "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                        (w["sources"][1],),
                    )
                elif case == "closure_during_io":
                    c.execute(
                        "UPDATE design.bid_profiles SET phase='terminated' WHERE bid_id=%s",
                        (w["scope"].bid_id,),
                    )
                else:
                    append_decision(
                        c,
                        w["scope"].bid_id,
                        w["actor"],
                        "rule",
                        w["rule"],
                        {
                            "decision": "confirmed",
                            "reason": "Changed during original IO",
                            "evidence_ids": [w["evidence"]],
                        },
                    )

        w["io"]["callback"] = change
    key = uid()
    with pytest.raises(DomainError) as error:
        service.apply(
            w["correction_scope"],
            w["actor"],
            key,
            {"request": w["request"], "preview_digest": prepared["digest"]},
            w["inventory_etag"],
        )
    expected = {
        "corrupt_bytes": "ORIGINAL_BYTES_CORRUPTED",
        "source_during_io": "PACKAGE_RULE_CORRECTION_SOURCE_CHANGED",
        "closure_during_io": "PROJECT_WORK_CLOSED",
        "decision_during_io": "PACKAGE_RULE_CORRECTION_DECISION_CHANGED",
    }[case]
    assert error.value.code == expected
    after = counts(w)
    if case == "decision_during_io":
        before["decisions"] += 1
    assert after == before
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.commands WHERE command_kind=%s AND idempotency_key=%s",
                (repository.KIND, key),
            ).fetchone()["n"]
            == 0
        )


def test_quote_exact_authority_and_preview_cas(exact):
    w = exact
    original_counts = counts(w)
    for evidence_id, quote in (
        (w["body_evidence"], "synthetic page 1"),
        (w["evidence"], "synthetic page fabricated"),
    ):
        body = deepcopy(w["request"])
        body["changes"] = body["changes"][:1]
        body["changes"][0]["rule"]["evidence_quotes"] = [
            {"evidence_id": evidence_id, "quote": quote}
        ]
        result = w["client"].post(w["correction_url"] + "/preview", json=body, headers=headers(w))
        assert result.status_code == 422, result.text
    prepared = preview(w)
    with pytest.raises(DomainError) as changed:
        service.apply(
            w["correction_scope"],
            w["actor"],
            uid(),
            {"request": w["request"], "preview_digest": "0" * 64},
            w["inventory_etag"],
        )
    assert changed.value.code == "PACKAGE_RULE_CORRECTION_PREVIEW_CHANGED"
    wrong = apply(
        w, body={"request": w["request"], "preview_digest": prepared["digest"]}, tag='"stale"'
    )
    assert wrong.status_code == 412
    assert counts(w) == original_counts
    assert w["io"]["calls"] == []


def test_declared_long_text_bounds_are_not_old_200_character_limit(exact):
    w = exact
    request = deepcopy(w["request"])
    request["reason"] = "逐字核对后的人工说明。" * 100
    request["changes"] = request["changes"][:1]
    request["changes"][0]["rule"]["statement"] = "完整记录适用条款的人工解释。" * 300
    request["changes"][0]["rule"]["scope"]["description"] = "该条款适用于当前明确标段。" * 80
    prepared = preview(w, request)
    response = apply(w, body={"request": request, "preview_digest": prepared["digest"]})
    assert response.status_code == 201, response.text
    added = next(
        row["rule_snapshot"]
        for row in response.json()["inventory"]["manifest"]["requirements"]
        if row["rule_snapshot"]["origin_kind"] == "human_added"
    )
    assert added["statement"] == request["changes"][0]["rule"]["statement"]


def test_same_key_concurrent_receipt_and_different_key_cas(exact):
    w = exact
    prepared = preview(w)
    body = {"request": w["request"], "preview_digest": prepared["digest"]}
    key = uid()
    w["io"]["concurrent_requests"] = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                service.apply, w["correction_scope"], w["actor"], key, body, w["inventory_etag"]
            )
            for _ in range(2)
        ]
        results = [f.result(timeout=20) for f in futures]
    assert sorted(replay for _, replay in results) == [False, True]
    assert results[0][0] == results[1][0]
    before = counts(w)
    with pytest.raises(DomainError) as conflict:
        service.apply(w["correction_scope"], w["actor"], uid(), body, w["inventory_etag"])
    assert conflict.value.status == 412
    assert counts(w) == before


def prepare_review_inputs(w, inv):
    from packages.domain import bid_package_execution_inputs as inputs
    from packages.domain import bid_package_original_verification as originals
    from packages.domain import bid_package_review_eligibility as eligibility
    from packages.domain import bid_package_review_freezing as freezing
    from packages.domain import bid_package_review_preview as preview_service

    scope = (*w["correction_scope"][:3], inv["manifest"]["id"])
    body = {
        "package_digest": inv["manifest"]["package_digest"],
        "inventory_digest": inv["digest"],
        "coverage_attempt_id": None,
        "coverage_digest": None,
    }
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        checked = preview_service.preview(c, *scope, body)
    body["input_digest"] = checked["digest"]
    captured = originals.read_input(*scope, body)
    frozen, _ = freezing.freeze(
        w["actor"],
        scope,
        uid(),
        body | {"context_digest": captured.execution_context["semantic_digest"]},
    )
    frozen = frozen["body"]
    observed = eligibility.inspect(scope, frozen["manifest"]["id"], frozen["digest"])
    prepared, _ = inputs.save(
        w["actor"],
        scope,
        frozen["manifest"]["id"],
        uid(),
        {
            "frozen_digest": frozen["digest"],
            "context_digest": observed["current_context"]["semantic_digest"],
            "rerun": None,
        },
    )
    return scope, frozen, prepared["body"]


def test_v3_frozen_consume_proof_dependency_plan_and_sql_state_guard(exact):
    from packages.domain import bid_package_dependency_plan_repository as plan_repository
    from packages.domain import bid_package_dependency_plans as plans
    from packages.domain import bid_package_input_dependencies as dependencies
    from packages.domain import bid_package_inventory_proof as proof
    from packages.domain.runtime import Command, audit

    w = exact
    response = apply(w)
    assert response.status_code == 201, response.text
    inv = response.json()["inventory"]
    scope, frozen, prepared = prepare_review_inputs(w, inv)
    args = (scope, frozen["manifest"]["id"], prepared["manifest"]["id"])
    proven = proof.observe(*args, prepared["digest"]).view()
    assert proven["manifest"]["version"] == "package-inventory-proof/2"
    assert proven["manifest"]["human_derivation"]["state"] == "verified"
    assert proven["manifest"]["human_derivation"]["counts"]["human_withdrawn"] == 1
    selected = {
        "execution_input_digest": prepared["digest"],
        "purpose": "prebid_compliance",
        "fact_ids": [],
        "dependencies": [],
    }
    checked = dependencies.check(*args, selected)
    assert checked["manifest"]["version"] == "package-input-dependencies/2"
    assert checked["manifest"]["rule_state_counts"] == {
        "total": 4,
        "active": 3,
        "inactive": 1,
        "needs_revalidation": 0,
    }
    body = selected | {
        "assessment_digest": checked["digest"],
        "reason": "明确保存仍有未知依赖的人工检查计划",
    }
    saved, _ = plans.save(w["actor"], *args, uid(), body)
    assert saved["body"]["manifest"]["assessment"] == checked
    assert plans.read(*args, saved["body"]["manifest"]["id"]) == saved["body"]
    assert saved["body"]["manifest"]["review_ready"] is False
    # Exact real /2 row projection is checked even when bypassing Python construction.
    with pytest.raises(psycopg.errors.CheckViolation, match="dependency_plan_rule_state_binding"):
        with connection() as c:
            command = Command(c, w["actor"], plan_repository.KIND, args[2], uid(), body)
            forged = deepcopy(saved["body"])
            forged["manifest"].update(id=uid(), command_id=str(command.id))
            assessment = forged["manifest"]["assessment"]
            target = next(
                item
                for item in assessment["manifest"]["requirements"]
                if item["rule_status"] == "inactive"
            )
            target["rule_status"] = "active"
            assessment["manifest"]["rule_state_counts"].update(active=4, inactive=0)
            assessment["digest"] = digest(assessment["manifest"])
            forged["digest"] = digest(forged["manifest"])
            plan_repository.append(c, forged)
            audit(
                c,
                w["actor"],
                scope[0],
                plan_repository.EVENT,
                plan_repository.audit_payload(forged),
                command.id,
            )
            command.finish(forged, 201)


def test_authority_original_ancestor_is_read_and_rechecked(exact):
    w = exact
    ancestor, version = uid(), uid()
    with connection() as c:
        c.execute(
            "INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) SELECT %s,bid_id,blob_id,'synthetic-ancestor.pdf',obtained_at,'source_original',created_by FROM design.document_versions WHERE id=%s",
            (version, w["member"].document_version_id),
        )
        c.execute(
            "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,'document','prebid_content',now()-interval '1 minute',%s)",
            (ancestor, version, sha(RAW)),
        )
        c.execute(
            "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',now()-interval '1 minute')",
            (ancestor,),
        )
        c.execute(
            "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
            (w["sources"][1], ancestor),
        )
    # Capture the now-explicit ancestor in a fresh v2 projection; no old snapshot is rewritten.
    projected = inventory(w, tag=w["inventory_etag"])
    assert projected.status_code == 201, projected.text
    inv = projected.json()
    scope = (*w["correction_scope"][:3], inv["manifest"]["id"])
    request = deepcopy(w["request"])
    request["base_inventory_digest"] = inv["digest"]
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        observed = service._observe(c, scope, request)
        assert {r["document_version_id"] for r in observed["originals"]} == {
            version,
            observed["authority"]["manifest"]["members"][0]["document_version_id"],
        }

    def withdraw():
        w["io"]["callback"] = None
        with connection() as c:
            c.execute(
                "UPDATE retrieval.source_heads SET revision=2,status='withdrawn' WHERE source_id=%s",
                (ancestor,),
            )

    w["io"]["callback"] = withdraw
    before = counts(w)
    with pytest.raises(DomainError) as error:
        service.apply(
            scope,
            w["actor"],
            uid(),
            {"request": request, "preview_digest": observed["preview"]["digest"]},
            projected.headers["etag"],
        )
    assert error.value.code == "PACKAGE_RULE_CORRECTION_SOURCE_CHANGED"
    assert len(w["io"]["calls"]) == 2
    assert counts(w) == before


@pytest.mark.parametrize("tamper", ["missing_map", "wrong_decision", "wrong_ack"])
def test_direct_sql_defense_rolls_back_all_native_rows(exact, monkeypatch, tamper):
    from packages.domain import bid_package_requirement_repository as inventories
    from packages.domain.runtime import Command

    w = exact
    prepared = preview(w)
    body = {"request": w["request"], "preview_digest": prepared["digest"]}
    before = counts(w)
    actual_load = inventories.load_inventory
    base_id = w["correction_scope"][3]

    def unvalidated_result(c, bid, package, revision, identity):
        if identity == base_id:
            return actual_load(c, bid, package, revision, identity)
        return repository.raw_inventory(c, bid, identity)

    monkeypatch.setattr(inventories, "load_inventory", unvalidated_result)
    # Deliberately bypass final Python verification to exercise deferred SQL itself.
    if tamper == "wrong_ack":
        original = Command.finish

        def altered(self, value, status=200, headers=None):
            return original(self, value, 200, headers)

        monkeypatch.setattr(Command, "finish", altered)
    else:
        original = repository.insert

        def altered(c, value):
            if tamper == "missing_map":
                value["manifest"]["mappings"].pop()
            else:
                value["manifest"]["decision_bindings"][0]["decision_digest"] = "0" * 64
            value["digest"] = digest(value["manifest"])
            original(c, value)

        monkeypatch.setattr(repository, "insert", altered)
    with pytest.raises(psycopg.errors.CheckViolation, match="package_rule_correction_"):
        service.apply(w["correction_scope"], w["actor"], uid(), body, w["inventory_etag"])
    assert counts(w) == before
