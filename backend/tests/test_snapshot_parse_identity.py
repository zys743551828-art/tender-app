"""真实 PostgreSQL：新解析、同解析追加及历史未冻结身份不能改变快照输入。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from bidwb import db, tasks
from bidwb.ai.handlers import _load_diagnosis_inputs, _load_evidence
from bidwb.ai.predict import _load as prediction_inputs
from bidwb.errors import Conflict
from bidwb.services import parse_identity, snapshots
from bidwb.services.outcomes import _require_snapshot_inputs_current
from bidwb.services.pipeline import _inspect
from bidwb.services.score_pairs import _VERSION_SQL
from bidwb.util import canonical_json, new_id, sha256_hex
from tests.test_files_and_parse import PROJECT
from tests.test_product_logic import _flow, _ready

pytestmark = pytest.mark.integration


def _replace_parse(engine: Any, pid: str, version: str) -> tuple[str, str]:
    parse, evidence = new_id("prs"), new_id("evd")
    with engine.begin() as conn:
        db.run(
            conn,
            """INSERT INTO parses(id,project_id,file_version_id,parser_version,page_count,coverage,gaps_json,created_at)
            VALUES (:i,:p,:v,'human-test',99,'partial','["new_gap"]',now()+interval '1 second')""",
            {"i": parse, "p": pid, "v": version},
        )
        db.run(
            conn,
            """INSERT INTO evidence(id,project_id,file_version_id,parse_id,physical_page,quote,kind,seq,semantic_review)
            VALUES (:i,:p,:v,:r,1,'后来核验的工期为100天','table',0,'supported')""",
            {"i": evidence, "p": pid, "v": version, "r": parse},
        )
    return parse, evidence


def test_snapshot_keeps_exact_inputs_after_new_parse(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    original = flow.freeze(rules).json()
    identity = original["snapshot_id"]
    assert original["contract_version"] == "input-v2" and original["parse_identity"] == "frozen"
    with engine.connect() as conn:
        manifest = snapshots.manifest_json(store, conn, identity)
        before = _load_diagnosis_inputs(conn, flow.pid, identity)
        prediction_before = prediction_inputs(conn, flow.pid, identity)
        exported_before = db.one(conn, _VERSION_SQL + "WHERE fv.id=:v", {"s": identity, "v": flow.body})
        assert parse_identity.is_current(conn, flow.pid, identity)
    parse, evidence = _replace_parse(engine, flow.pid, flow.body)
    assert flow.api.get(f"/snapshots/{identity}").json() == original
    with engine.connect() as conn:
        assert snapshots.manifest_json(store, conn, identity) == manifest
        assert _load_diagnosis_inputs(conn, flow.pid, identity) == before
        assert prediction_inputs(conn, flow.pid, identity) == prediction_before
        assert db.one(conn, _VERSION_SQL + "WHERE fv.id=:v", {"s": identity, "v": flow.body}) == exported_before
        assert not parse_identity.is_current(conn, flow.pid, identity)
        assert _inspect(conn, flow.pid).snapshot_id is None
        with pytest.raises(Conflict, match="snapshot_parse_stale"):
            _require_snapshot_inputs_current(conn, flow.pid, identity)
        assert [e.evidence_id for e in _load_evidence(conn, flow.pid, [flow.body])] == [evidence]
    historical = flow.api.post(
        f"/projects/{flow.pid}/search", {"snapshot_id": identity, "query": "工期", "top_k": 20, "mode": "keyword"}
    ).json()
    current = flow.api.post(f"/projects/{flow.pid}/search", {"query": "工期", "top_k": 20, "mode": "keyword"}).json()
    assert evidence not in {hit["evidence"]["evidence_id"] for hit in historical["hits"]}
    assert evidence in {hit["evidence"]["evidence_id"] for hit in current["hits"]}
    fresh = flow.freeze(rules).json()
    assert fresh["parse_ids"][flow.body] == parse and fresh["sha256"] != original["sha256"]
    assert f"{flow.body}:new_gap" in fresh["coverage_gaps"]
    rejected = flow.api.post(
        f"/projects/{flow.pid}/submissions",
        {
            "body_version_id": flow.body,
            "snapshot_id": fresh["snapshot_id"],
            "submitted_at": "2026-10-01T08:00:00Z",
            "receipt_artifact_id": None,
        },
    )
    assert rejected.status_code == 409  # 新输入必须完成诊断


def test_evidence_appended_to_same_parse_is_not_added_to_frozen_input(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()
    identity = new_id("evd")
    with engine.begin() as conn:
        before = _load_evidence(conn, flow.pid, [flow.body], snap["snapshot_id"])
        db.run(
            conn,
            """INSERT INTO evidence(id,project_id,file_version_id,parse_id,physical_page,quote,kind,seq,semantic_review)
            VALUES (:i,:p,:v,:r,1,'追加的工期200天','text',999,'pending')""",
            {"i": identity, "p": flow.pid, "v": flow.body, "r": snap["parse_ids"][flow.body]},
        )
        assert _load_evidence(conn, flow.pid, [flow.body], snap["snapshot_id"]) == before
        assert identity in {e.evidence_id for e in _load_evidence(conn, flow.pid, [flow.body])}
        assert not parse_identity.is_current(conn, flow.pid, snap["snapshot_id"])
    fresh = flow.freeze(rules).json()
    assert fresh["parse_ids"] == snap["parse_ids"] and fresh["sha256"] != snap["sha256"]
    with engine.begin() as conn:
        nested = conn.begin_nested()
        with pytest.raises(DBAPIError) as error:
            db.run(conn, "UPDATE input_snapshots SET parse_inputs_json='{}' WHERE id=:i", {"i": snap["snapshot_id"]})
        assert getattr(error.value.orig, "sqlstate", None) == "23000"
        nested.rollback()


def test_legacy_identity_stays_unknown_and_manifest_unchanged(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    current = flow.freeze(rules).json()
    identity, artifact = new_id("snp"), new_id("art")
    payload = canonical_json({"snapshot_id": identity, "contract_version": "input-v1", "coverage_gaps": ["old_gap"]}).encode()
    key = f"artifacts/{artifact}"
    store.put(key, payload, "application/json")
    with engine.begin() as conn:
        db.run(
            conn,
            """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
            VALUES (:i,:sha,:key,:size,'application/json','artifact-v1',now(),'committed')""",
            {"i": artifact, "sha": sha256_hex(payload), "key": key, "size": len(payload)},
        )
        db.run(
            conn,
            """INSERT INTO input_snapshots(id,project_id,body_version_id,rule_set_id,as_of,contract_version,sha256,manifest_artifact_id)
            VALUES (:i,:p,:b,:r,now(),'input-v1',:sha,:a)""",
            {"i": identity, "p": flow.pid, "b": flow.body, "r": rules["rule_set_id"], "sha": sha256_hex(payload), "a": artifact},
        )
        for version in (flow.tender, flow.body):
            db.run(
                conn,
                "INSERT INTO snapshot_files(snapshot_id,project_id,file_version_id) VALUES (:s,:p,:v)",
                {"s": identity, "p": flow.pid, "v": version},
            )
        # 模拟旧版本已完成的评审，仍可查询原报告；不是一次新的业务执行。
        job, _ = tasks.enqueue(
            conn,
            project_id=flow.pid,
            kind="diagnosis",
            purpose="business",
            snapshot_id=identity,
            input_sha256=sha256_hex(payload),
            input_json={},
            idempotency_key="legacy-done",
        )
        db.run(
            conn,
            "UPDATE jobs SET state='succeeded',coverage_json=CAST(:c AS jsonb) WHERE id=:i",
            {
                "i": job,
                "c": json.dumps({"status": "complete", "rules_total": 2, "rules_checked": 2, "rules_failed": 0, "candidates_dropped": 0}),
            },
        )
    _replace_parse(engine, flow.pid, flow.body)
    legacy = flow.api.get(f"/snapshots/{identity}")
    assert legacy.status_code == 200 and legacy.json()["contract_version"] == "input-v1"
    assert legacy.json()["parse_identity"] == "legacy_unfrozen" and legacy.json()["parse_ids"] == {}
    assert legacy.json()["coverage_gaps"] == ["old_gap", "legacy_parse_identity_unfrozen"]
    assert flow.api.get(f"/projects/{flow.pid}/report").status_code == 200
    for path, body in (
        ("diagnosis", {"snapshot_id": identity}),
        ("search", {"snapshot_id": identity, "query": "工期", "top_k": 5, "mode": "keyword"}),
    ):
        response = flow.api.post(f"/projects/{flow.pid}/{path}", body)
        assert response.status_code == 409 and response.json()["code"] == "snapshot_parse_identity_unknown"
    with engine.connect() as conn:
        with pytest.raises(Conflict, match="snapshot_parse_identity_unknown"):
            _load_diagnosis_inputs(conn, flow.pid, identity)
        assert json.loads(store.get(key)) == snapshots.manifest_json(store, conn, identity)
        assert sha256_hex(store.get(key)) == legacy.json()["sha256"]
        assert parse_identity.is_current(conn, flow.pid, current["snapshot_id"]) is False
    fresh = flow.freeze(rules).json()
    assert fresh["parse_identity"] == "frozen"
    assert api_factory().get(f"/snapshots/{fresh['snapshot_id']}").status_code == 401
    other = flow.api.post("/projects", {**PROJECT, "title": "另一个项目"}).json()["project_id"]
    isolated = flow.api.post(
        f"/projects/{other}/search", {"snapshot_id": fresh["snapshot_id"], "query": "工期", "top_k": 5, "mode": "keyword"}
    )
    assert isolated.status_code == 404
