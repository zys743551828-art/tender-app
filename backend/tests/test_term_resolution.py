"""不同文件条件冲突：逐文件抽取、冻结阻断、人工核实、旧版本保存和并发保护。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import Engine

from bidwb import db
from bidwb.ai.handlers import build_handlers
from bidwb.messaging import InMemoryBus
from bidwb.workers.runner import WorkerRunner
from tests.fakes import ScriptedLlm, docs
from tests.pdfs import make_pdf
from tests.test_ai_pipeline import _drain
from tests.test_files_and_parse import _setup, _upload

pytestmark = pytest.mark.integration


def _respond(system: str, user: str) -> dict[str, Any]:
    assert "招标规则抽取员" in system
    evidence = docs(user)
    # 同一批不混入两份文件，所以两份条件会分别保留。
    values = [value for value in ("60", "80") if any(value in quote for _, quote in evidence)]
    assert len(values) == 1
    value = values[0]
    ev_id, _ = next(item for item in evidence if value in item[1])
    quote = f"技术标满分{value}分"
    return {
        "rules": [{"kind": "scoring", "statement": quote, "quote": quote, "evidence_ids": [ev_id], "max_points": value}],
        "technical_full_score": {"value": value, "quote": quote, "evidence_ids": [ev_id]},
    }


@pytest.fixture
def conflicted(api_factory: Any, make_member: Any, store: Any, engine: Engine, worker_container: Any) -> tuple[Any, str, dict[str, Any]]:
    api, pid = _setup(api_factory, make_member)
    tender = _upload(api, store, pid, make_pdf([["技术标满分60分"]]))[1].json()["version_id"]
    supplement = _upload(api, store, pid, make_pdf([["技术标满分80分"]]), role="supplement")[1].json()["version_id"]
    body = _upload(api, store, pid, make_pdf([["本工程施工组织设计正文"]]), role="body")[1].json()["version_id"]
    bus = InMemoryBus()
    runner = WorkerRunner(
        worker_container, "parse", bus.consumer(["job.parse"]), build_handlers(ScriptedLlm(_respond)), consumer_name="terms-parse"
    )
    _drain(runner, bus, engine)
    assert api.post(f"/projects/{pid}/rules:extract").status_code == 202
    _drain(runner, bus, engine)
    package = api.get(f"/projects/{pid}/rules").json()
    assert package["status"] == "conflict" and package["terms"]["technical_full_score"] is None
    assert {item["values"]["value"] for item in package["terms"]["conflicts"][0]["alternatives"]} == {"60", "80"}
    assert {item["evidence"][0]["file_role"] for item in package["terms"]["conflicts"][0]["alternatives"]} == {"tender", "supplement"}
    snapshot = {
        "body_version_id": body,
        "rule_set_id": package["rule_set_id"],
        "fact_set_id": None,
        "file_version_ids": [tender, supplement, body],
        "reference_dataset_id": None,
    }
    return api, pid, {"package": package, "snapshot": snapshot}


def test_unresolved_condition_blocks_snapshot_and_requires_reason(conflicted: Any) -> None:
    api, pid, data = conflicted
    response = api.post(f"/projects/{pid}/snapshots", data["snapshot"])
    assert response.status_code == 409 and response.json()["code"] == "rule_terms_conflict"
    package = data["package"]
    choice = package["terms"]["conflicts"][0]["alternatives"][0]
    request = {"object_version": str(package["revision"]), "term": "technical_full_score", "option_id": choice["option_id"], "reason": " "}
    assert api.post(f"/projects/{pid}/rules/terms:resolve", request).status_code == 422


def test_resolution_creates_new_package_and_rejects_stale_or_foreign_choices(conflicted: Any, engine: Engine) -> None:
    api, pid, data = conflicted
    package = data["package"]
    choice = next(item for item in package["terms"]["conflicts"][0]["alternatives"] if item["values"]["value"] == "80")
    request = {
        "object_version": str(package["revision"]),
        "term": "technical_full_score",
        "option_id": choice["option_id"],
        "reason": "已核对补遗适用范围，采用补遗满分",
    }
    assert api.post(f"/projects/{pid}/rules/terms:resolve", {**request, "option_id": "trm_foreign"}).status_code == 422
    resolved = api.post(f"/projects/{pid}/rules/terms:resolve", request, key="resolve-this-term-once")
    assert resolved.status_code == 200, resolved.text
    current = resolved.json()
    assert current["rule_set_id"] != package["rule_set_id"] and current["revision"] == package["revision"] + 1
    assert current["terms"]["technical_full_score"]["value"] == "80" and current["terms"]["conflicts"] == []
    replay = api.post(f"/projects/{pid}/rules/terms:resolve", request, key="resolve-this-term-once")
    assert replay.json() == current
    assert api.post(f"/projects/{pid}/rules/terms:resolve", request).status_code == 412
    assert api.post(f"/projects/{pid}/snapshots", {**data["snapshot"], "rule_set_id": current["rule_set_id"]}).status_code == 200
    with engine.connect() as conn:
        original = db.one(conn, "SELECT terms_json FROM rule_packages WHERE id=:i", {"i": package["rule_set_id"]})
        assert "_resolved" not in original["terms_json"]
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='rule_term.resolve'") == 1
        event = db.scalar(conn, "SELECT details_json FROM audit_events WHERE action='rule_term.resolve'")
        assert request["reason"] in json.dumps(event, ensure_ascii=False)


def test_upload_after_candidates_rejects_obsolete_resolution(conflicted: Any, store: Any) -> None:
    api, pid, data = conflicted
    package = data["package"]
    _upload(api, store, pid, make_pdf([["新的补遗内容与生效日期"]]), role="supplement")
    choice = package["terms"]["conflicts"][0]["alternatives"][0]
    result = api.post(
        f"/projects/{pid}/rules/terms:resolve",
        {
            "object_version": str(package["revision"]),
            "term": "technical_full_score",
            "option_id": choice["option_id"],
            "reason": "试图采用旧资料",
        },
    )
    assert result.status_code == 412 and result.json()["code"] == "stale_inputs"
