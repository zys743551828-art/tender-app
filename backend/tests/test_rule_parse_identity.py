"""提取前后解析变化、旧任务拒绝及规则包来源继承的真实库回归。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bidwb import db, tasks
from bidwb.ai.handlers import make_rules_handler
from bidwb.services import action_context, parse_identity, snapshots
from bidwb.util import new_id
from tests.fakes import ScriptedLlm
from tests.test_product_logic import _flow, _ready, _respond
from tests.test_snapshot_parse_identity import _replace_parse

pytestmark = pytest.mark.integration


def _copy_parse(engine: Any, pid: str, version: str) -> str:
    identity = new_id("prs")
    with engine.begin() as conn:
        original = db.one(
            conn,
            "SELECT * FROM parses WHERE file_version_id=:v AND project_id=:p ORDER BY created_at DESC,id DESC LIMIT 1",
            {"v": version, "p": pid},
        )
        db.run(
            conn,
            """INSERT INTO parses(id,project_id,file_version_id,parser_version,page_count,coverage,gaps_json,artifact_id,created_at)
           VALUES (:i,:p,:v,'same-text-new-parse',:n,:c,CAST(:g AS jsonb),:a,now()+interval '1 second')""",
            {
                "i": identity,
                "p": pid,
                "v": version,
                "n": original["page_count"],
                "c": original["coverage"],
                "g": json.dumps(original["gaps_json"]),
                "a": original["artifact_id"],
            },
        )
        for evidence in db.all_(conn, "SELECT * FROM evidence WHERE parse_id=:r", {"r": original["id"]}):
            db.run(
                conn,
                """INSERT INTO evidence(id,project_id,file_version_id,parse_id,physical_page,printed_page,quote,kind,seq,bbox_json,semantic_review)
               VALUES (:i,:p,:v,:r,:page,:printed,:quote,:kind,:seq,CAST(:bbox AS jsonb),:review)""",
                {
                    "i": new_id("evd"),
                    "p": pid,
                    "v": version,
                    "r": identity,
                    "page": evidence["physical_page"],
                    "printed": evidence["printed_page"],
                    "quote": evidence["quote"],
                    "kind": evidence["kind"],
                    "seq": evidence["seq"],
                    "bbox": json.dumps(evidence["bbox_json"]),
                    "review": evidence["semantic_review"],
                },
            )
    return identity


def test_rules_job_identity_and_idempotency_change_with_parse(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    with engine.begin() as conn:
        first, created = tasks.enqueue_rules(conn, flow.pid, [flow.tender], "same-logical-key")
        duplicate, duplicated = tasks.enqueue_rules(conn, flow.pid, [flow.tender], "same-logical-key")
        original = db.one(conn, "SELECT input_json,input_sha256 FROM jobs WHERE id=:i", {"i": first})
        token = action_context.fingerprint(conn, flow.pid)
    assert created and not duplicated and first == duplicate
    _replace_parse(engine, flow.pid, flow.tender)
    flow.drain()
    task = flow.api.get(f"/tasks/{first}").json()
    assert task["state"] == "failed" and task["error_code"] == "rules_inputs_stale"
    assert flow.llm.calls == []
    with engine.begin() as conn:
        assert db.one(conn, "SELECT input_json,input_sha256 FROM jobs WHERE id=:i", {"i": first}) == original
        assert action_context.fingerprint(conn, flow.pid) != token
        fresh, created = tasks.enqueue_rules(conn, flow.pid, [flow.tender], "same-logical-key")
        assert created and fresh != first
        assert db.scalar(conn, "SELECT input_sha256 FROM jobs WHERE id=:i", {"i": fresh}) != original["input_sha256"]


def test_source_change_during_model_call_keeps_artifact_without_current_package(
    api_factory, make_member, store, engine, worker_container
) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    changed = False
    base = _respond(flow.cfg)

    def respond(system: str, user: str) -> Any:
        nonlocal changed
        if not changed:
            changed = True
            _replace_parse(engine, flow.pid, flow.tender)
        return base(system, user)

    flow.parse_runner.handlers["rules"] = make_rules_handler(ScriptedLlm(respond))
    started = flow.api.post(f"/projects/{flow.pid}/rules:extract").json()
    flow.drain()
    assert changed
    assert flow.api.get(f"/tasks/{started['task_id']}").json()["state"] == "succeeded"
    assert flow.api.get(f"/projects/{flow.pid}/rules").status_code == 404
    with engine.connect() as conn:
        job = db.one(conn, "SELECT input_json,output_artifact_id FROM jobs WHERE id=:i", {"i": started["task_id"]})
        key = db.scalar(conn, "SELECT object_key FROM artifacts WHERE id=:i", {"i": job["output_artifact_id"]})
        result = json.loads(store.get(key))
        assert result["parse_inputs"] == job["input_json"]["parse_inputs"]
        assert result["parse_inputs"] != parse_identity.capture(conn, flow.pid, [flow.tender])[0]


def test_unfrozen_legacy_rules_job_does_not_call_model(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    with engine.begin() as conn:
        identity, _ = tasks.enqueue(
            conn,
            project_id=flow.pid,
            kind="rules",
            purpose="business",
            input_json={"file_version_ids": [flow.tender]},
            idempotency_key="legacy-rules-job",
        )
    flow.drain()
    task = flow.api.get(f"/tasks/{identity}").json()
    assert task["state"] == "failed" and task["error_code"] == "rules_parse_identity_unknown"
    assert flow.llm.calls == []


def test_legacy_rule_package_remains_readable_but_requires_fresh_extraction(
    api_factory, make_member, store, engine, worker_container
) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    original = _ready(flow, ["confirm", "confirm"])
    legacy = new_id("rpk")
    with engine.begin() as conn:
        db.run(
            conn,
            """INSERT INTO rule_packages(id,project_id,revision,status,artifact_id,source_versions_json,terms_json,effectivity_json,created_at)
            SELECT :i,project_id,revision+1,status,artifact_id,source_versions_json,terms_json,effectivity_json,now()
            FROM rule_packages WHERE id=:old""",
            {"i": legacy, "old": original["rule_set_id"]},
        )
    historical = flow.api.get(f"/projects/{flow.pid}/rules").json()
    assert historical["rule_set_id"] == legacy and historical["source_parse_state"] == "legacy_unfrozen"
    status = flow.api.get(f"/projects/{flow.pid}/pipeline").json()
    assert status["stage"] == "waiting_start" and not status["input_verification_required"]
    response = flow.freeze(historical)
    assert response.status_code == 409 and response.json()["code"] == "rule_parse_identity_unknown"
    fresh = flow.extract()
    assert fresh["source_parse_state"] == "current" and fresh["rule_set_id"] != legacy
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT parse_inputs_json IS NULL FROM rule_packages WHERE id=:i", {"i": legacy})


def test_same_file_reparse_requires_new_rules_and_does_not_carry_reviews(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    original = _ready(flow, ["confirm", "confirm"])
    old_snapshot = flow.freeze(original).json()
    with engine.connect() as conn:
        manifest = snapshots.manifest_json(store, conn, old_snapshot["snapshot_id"])
    new_parse = _copy_parse(engine, flow.pid, flow.tender)
    stale = flow.api.get(f"/projects/{flow.pid}/rules").json()
    assert stale["source_parse_state"] == "stale"
    status = flow.api.get(f"/projects/{flow.pid}/pipeline").json()
    assert status["stage"] == "waiting_start" and not status["input_verification_required"]
    rejected = flow.api.post(
        f"/projects/{flow.pid}/rules:confirm",
        {"object_version": str(original["revision"]), "rule_ids": [original["rules"][0]["rule_id"]]},
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "rules_parse_stale"
    assert flow.freeze(original).json()["code"] == "rules_parse_stale"
    fresh = flow.extract()
    assert fresh["source_parse_state"] == "current" and fresh["rule_set_id"] != original["rule_set_id"]
    assert all(rule["confirmation"] == "pending" and rule["carried_from_rule_id"] is None for rule in fresh["rules"])
    assert flow.freeze(fresh).status_code == 200
    # 冻结后的人工驳回创建副本，副本继承实际来源身份。
    reviewed = flow.api.post(
        f"/rules/{fresh['rules'][0]['rule_id']}/reviews",
        {"object_version": str(fresh["revision"]), "decision": "reject", "reason": "本条不适用"},
    )
    assert reviewed.status_code == 200
    with engine.connect() as conn:
        package = db.one(
            conn, "SELECT parse_inputs_json FROM rule_packages WHERE project_id=:p ORDER BY revision DESC LIMIT 1", {"p": flow.pid}
        )
        assert package["parse_inputs_json"][flow.tender]["parse_id"] == new_parse
        assert snapshots.manifest_json(store, conn, old_snapshot["snapshot_id"]) == manifest
        assert (
            db.scalar(conn, "SELECT count(*) FROM reviews WHERE object_kind='rule' AND object_version=:v", {"v": str(original["revision"])})
            == 2
        )
