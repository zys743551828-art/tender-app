"""补遗效力必须是有据的追加决定，不能整页删掉原要求或改变旧快照。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import Engine

from bidwb import db, source_effectivity
from bidwb.ai.handlers import build_handlers
from bidwb.messaging import InMemoryBus
from bidwb.services import rules
from bidwb.workers.runner import WorkerRunner
from tests.fakes import ScriptedLlm, docs
from tests.pdfs import make_pdf
from tests.test_ai_pipeline import _drain
from tests.test_files_and_parse import _setup, _upload

pytestmark = pytest.mark.integration

OLD_QUOTE = "总工期不得超过180日历天。"
QUALITY = "工程质量必须达到合格标准。"
LOCAL = "本补遗仅修改总工期为120日历天，其余要求不变。"
WHOLE = "本补遗整份替代原招标要求，总工期为120日历天。"


def _respond(system: str, user: str) -> dict[str, Any]:
    assert "招标规则抽取员" in system
    extracted = []
    for identity, quote in docs(user):
        for required in (OLD_QUOTE, QUALITY, LOCAL, WHOLE):
            if required in quote:
                extracted.append({"kind": "mandatory", "statement": required, "quote": required, "evidence_ids": [identity]})
    return {"rules": extracted}


@pytest.fixture
def materials(
    api_factory: Any, make_member: Any, store: Any, engine: Engine, worker_container: Any, request: pytest.FixtureRequest
) -> tuple[Any, str, dict[str, Any]]:
    api, pid = _setup(api_factory, make_member)
    tender = _upload(api, store, pid, make_pdf([["第一章 工期与质量", OLD_QUOTE, QUALITY]]))[1].json()["version_id"]
    source_quote = getattr(request, "param", LOCAL)
    supplement = _upload(api, store, pid, make_pdf([[source_quote]]), role="supplement")[1].json()["version_id"]
    body = _upload(
        api, store, pid, make_pdf([["第一章 施工工期", "总工期计划180日历天。"], ["第二章 质量控制", "本工程质量保证合格。"]]), role="body"
    )[1].json()["version_id"]
    bus = InMemoryBus()
    runner = WorkerRunner(
        worker_container, "parse", bus.consumer(["job.parse"]), build_handlers(ScriptedLlm(_respond)), consumer_name="effectivity-parse"
    )
    _drain(runner, bus, engine)
    assert api.post(f"/projects/{pid}/rules:extract").status_code == 202
    _drain(runner, bus, engine)
    package = api.get(f"/projects/{pid}/rules").json()
    target = next(item for item in package["rules"] if item["statement"] == OLD_QUOTE)
    basis = next(item for item in package["rules"] if item["statement"] == source_quote)["evidence"][0]
    request = {
        "object_version": str(package["revision"]),
        "old_version_id": tender,
        "new_version_id": supplement,
        "action": "partial_replace",
        "rule_ids": [target["rule_id"]],
        "scope_basis": [{"evidence_id": basis["evidence_id"], "quote": source_quote}],
        "reason": "已核对补遗，仅替代工期条款，质量要求继续有效",
    }
    snapshot = {
        "body_version_id": body,
        "rule_set_id": package["rule_set_id"],
        "file_version_ids": [tender, supplement, body],
        "fact_set_id": None,
        "reference_dataset_id": None,
    }
    return api, pid, {"package": package, "request": request, "snapshot": snapshot, "body": body, "runner": runner, "bus": bus}


def test_partial_replacement_preserves_other_rules_originals_and_frozen_history(materials: Any, engine: Engine) -> None:
    api, pid, data = materials
    old_package = data["package"]["rule_set_id"]
    assert api.post(f"/projects/{pid}/snapshots", data["snapshot"]).status_code == 200
    preview = api.post(
        f"/projects/{pid}/rules/effectivity:preview",
        {key: value for key, value in data["request"].items() if key not in {"reason", "scope_basis"}},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_rule_ids"] == data["request"]["rule_ids"]
    assert preview.json()["gaps"] and any("工期" in section["title"] for section in preview.json()["related_sections"])
    assert all(ref["version_id"] == data["body"] for section in preview.json()["related_sections"] for ref in section["evidence"])
    result = api.post(f"/projects/{pid}/rules/effectivity:decide", data["request"], key="effectivity-once")
    assert result.status_code == 200, result.text
    current = result.json()
    states = {item["statement"]: item["source_status"] for item in current["rules"]}
    assert states == {OLD_QUOTE: "superseded", QUALITY: "active", LOCAL: "active"}
    assert current["rule_set_id"] != old_package
    found = api.post(f"/projects/{pid}/search", {"query": "180", "mode": "keyword", "top_k": 10}).json()
    old_hit = next(item for item in found["hits"] if item["evidence"]["version_id"] == data["request"]["old_version_id"])
    assert any("已被补遗替代" in note and "同页其他要求不因此失效" in note for note in old_hit["evidence"]["effectivity_notes"])
    page = api.get(f"/evidence/{old_hit['evidence']['evidence_id']}").json()
    assert page["effectivity_notes"] == old_hit["evidence"]["effectivity_notes"]
    replay = api.post(f"/projects/{pid}/rules/effectivity:decide", data["request"], key="effectivity-once")
    assert replay.json() == current
    assert api.post(f"/projects/{pid}/rules/effectivity:decide", data["request"]).status_code == 412
    with engine.connect() as conn:
        assert len(rules.effective_rules(conn, pid, old_package)) == 3
        assert len(rules.effective_rules(conn, pid, current["rule_set_id"])) == 2
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='source.effectivity_decided'") == 1
    ended = next(item for item in current["rules"] if item["statement"] == OLD_QUOTE)
    assert (
        api.post(
            f"/rules/{ended['rule_id']}/reviews",
            {"object_version": str(current["revision"]), "decision": "confirm", "reason": "不能绕过效力"},
        ).status_code
        == 409
    )
    assert api.post(f"/projects/{pid}/snapshots", {**data["snapshot"], "rule_set_id": current["rule_set_id"]}).status_code == 200


def test_local_scope_cannot_be_confirmed_as_whole_replacement(materials: Any, engine: Engine) -> None:
    api, pid, data = materials
    result = api.post(f"/projects/{pid}/rules/effectivity:decide", {**data["request"], "action": "whole_replace", "rule_ids": []})
    assert result.status_code == 422 and result.json()["code"] == "effectivity_local_scope"
    narrowed = {
        **data["request"],
        "action": "whole_replace",
        "rule_ids": [],
        "scope_basis": [{**data["request"]["scope_basis"][0], "quote": "总工期为120日历天"}],
    }
    assert api.post(f"/projects/{pid}/rules/effectivity:decide", narrowed).json()["code"] == "effectivity_local_scope"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM rule_packages") == 1


def test_defer_blocks_new_snapshot_and_retain_releases_it(materials: Any) -> None:
    api, pid, data = materials
    result = api.post(f"/projects/{pid}/rules/effectivity:decide", {**data["request"], "action": "defer", "scope_basis": []})
    assert result.status_code == 200, result.text
    current = result.json()
    assert current["status"] == "conflict"
    assert api.get(f"/projects/{pid}/pipeline").json()["input_verification_required"] is True
    overview = next(item for item in api.get("/projects").json() if item["project_id"] == pid)
    assert overview["summary"]["next_action"]["key"] == "verify_sources"
    blocked = api.post(f"/projects/{pid}/snapshots", {**data["snapshot"], "rule_set_id": current["rule_set_id"]})
    assert blocked.status_code == 409 and blocked.json()["code"] == "source_effectivity_pending"
    target = next(item for item in current["rules"] if item["statement"] == OLD_QUOTE)
    kept = api.post(
        f"/projects/{pid}/rules/effectivity:decide",
        {
            **data["request"],
            "object_version": str(current["revision"]),
            "action": "retain",
            "rule_ids": [target["rule_id"]],
            "reason": "核实后本条继续适用，此处演示保留动作",
        },
    )
    assert kept.status_code == 200, kept.text
    assert all(item["source_status"] == "active" for item in kept.json()["rules"])
    assert api.post(f"/projects/{pid}/snapshots", {**data["snapshot"], "rule_set_id": kept.json()["rule_set_id"]}).status_code == 200


@pytest.mark.parametrize("invalid", ["quote", "source", "rule", "missing_basis"])
def test_scope_and_basis_reject_foreign_or_invented_inputs(materials: Any, invalid: str) -> None:
    api, pid, data = materials
    request = dict(data["request"])
    if invalid == "quote":
        request["scope_basis"] = [{"evidence_id": request["scope_basis"][0]["evidence_id"], "quote": "原文中不存在的整份替代说明"}]
    elif invalid == "source":
        request["new_version_id"] = request["old_version_id"]
    elif invalid == "rule":
        request["rule_ids"] = [next(item["rule_id"] for item in data["package"]["rules"] if item["statement"] == LOCAL)]
    else:
        request["scope_basis"] = []
    assert api.post(f"/projects/{pid}/rules/effectivity:decide", request).status_code == 422


def test_original_bytes_are_checked_before_any_rule_change(materials: Any, engine: Engine, store: Any) -> None:
    api, pid, data = materials
    with engine.connect() as conn:
        key = db.scalar(
            conn,
            "SELECT a.object_key FROM file_versions fv JOIN artifacts a ON a.id=fv.artifact_id WHERE fv.id=:v",
            {"v": data["request"]["new_version_id"]},
        )
    store.objects[key] = b"wrong-source-bytes"
    result = api.post(f"/projects/{pid}/rules/effectivity:decide", data["request"])
    assert result.status_code == 409 and result.json()["code"] == "effectivity_original_mismatch"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM rule_packages") == 1
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='source.effectivity_decided'") == 0


def test_source_scope_fingerprint_changes_with_requirements_and_evidence() -> None:
    rule = {
        "kind": "mandatory",
        "statement": OLD_QUOTE,
        "conditions": [],
        "exceptions": [],
        "max_points": None,
        "evidence_ids": ["evd_original"],
    }
    key = source_effectivity.rule_key(rule)
    effectivity = {"ended": {key: "sfx_decision"}}
    assert source_effectivity.state(effectivity, rule) == "superseded"
    assert source_effectivity.state(effectivity, {**rule, "statement": LOCAL}) == "active"
    assert source_effectivity.state(effectivity, {**rule, "evidence_ids": ["evd_new_parse"]}) == "active"


def test_reextraction_inherits_only_exact_source_and_requirement_decisions(materials: Any, engine: Engine) -> None:
    api, pid, data = materials
    assert api.post(f"/projects/{pid}/rules/effectivity:decide", data["request"]).status_code == 200
    assert api.post(f"/projects/{pid}/rules:extract").status_code == 202
    _drain(data["runner"], data["bus"], engine)
    latest = api.get(f"/projects/{pid}/rules").json()
    assert next(item for item in latest["rules"] if item["statement"] == OLD_QUOTE)["source_status"] == "superseded"
    assert next(item for item in latest["rules"] if item["statement"] == QUALITY)["source_status"] == "active"


@pytest.mark.parametrize("materials", [WHOLE], indirect=True)
def test_whole_replacement_preserves_mixed_source_rules_for_review(materials: Any, engine: Engine) -> None:
    api, pid, data = materials
    package = data["package"]
    old = next(item for item in package["rules"] if item["statement"] == OLD_QUOTE)
    supplement = next(item for item in package["rules"] if item["statement"] == WHOLE)
    refs = [old["evidence"][0]["evidence_id"], supplement["evidence"][0]["evidence_id"]]
    with engine.begin() as conn:
        db.run(
            conn,
            """INSERT INTO rule_items(id,project_id,package_id,kind,statement,conditions_json,exceptions_json,evidence_ids_json)
                       VALUES ('rul_mixed_sources',:p,:k,'mandatory','同时引用两份原件的要求','[]','[]',CAST(:e AS jsonb))""",
            {"p": pid, "k": package["rule_set_id"], "e": json.dumps(refs)},
        )
    result = api.post(f"/projects/{pid}/rules/effectivity:decide", {**data["request"], "action": "whole_replace", "rule_ids": []})
    assert result.status_code == 200, result.text
    states = {item["statement"]: item["source_status"] for item in result.json()["rules"]}
    assert states[OLD_QUOTE] == states[QUALITY] == "superseded"
    assert states[WHOLE] == "active" and states["同时引用两份原件的要求"] == "needs_confirmation"
    frozen = api.post(f"/projects/{pid}/snapshots", {**data["snapshot"], "rule_set_id": result.json()["rule_set_id"]})
    assert frozen.status_code == 409 and frozen.json()["code"] == "source_effectivity_pending"
