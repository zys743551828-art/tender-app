"""评分配对集导出（bidwb-admin export-score-pairs）：提交＋官方技术分 → 格式 A 与格式 B，可直接给批量工具读（真实 PG）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from tools.batch import predict_dataset as batch

from bidwb import admin
from bidwb.ai import features
from bidwb.config import Settings
from bidwb.runtime import Container
from tests.fakes import ScriptedLlm
from tests.test_auto_pipeline import (
    BODY_V2,
    TENDER,
    _env,
    _respond,
    settings,  # noqa: F401  自动评审打开的配置夹具（pytest 按名注入）
)
from tests.test_files_and_parse import _upload

pytestmark = pytest.mark.integration


def _submit_with_outcome(env, body_version: str, value: str) -> str:  # type: ignore[no-untyped-def]
    report = env.get("/report")
    rules = env.get("/rules")
    for rule in rules["rules"]:
        if rule["kind"] in ("disqualification", "mandatory"):
            env.api.post(
                f"/rules/{rule['rule_id']}/reviews", {"object_version": str(rules["revision"]), "decision": "confirm", "reason": "核对"}
            )
    env.make_member("eng")
    reviewer = env.api_factory().login("eng")
    for finding in env.get("/findings?limit=100")["items"]:
        reviewer.post(
            f"/findings/{finding['finding_id']}/reviews",
            {"object_version": str(finding["revision"]), "decision": "reject", "reason": "不成立"},
        )
    submit = env.api.post(
        f"/projects/{env.pid}/submissions",
        {
            "snapshot_id": report["snapshot_id"],
            "body_version_id": body_version,
            "submitted_at": "2026-10-01T08:00:00+08:00",
            "receipt_artifact_id": None,
        },
    )
    assert submit.status_code == 200, submit.text
    outcome = {
        "submission_id": submit.json()["submission_id"],
        "source_kind": "user_reported",
        "target": "technical_total",
        "value": value,
        "maximum": "8",
        "aggregation": None,
        "stage_result": "technical_shortlisted",
        "source_page": None,
        "published_at": None,
        "supersedes": None,
        "source_artifact_id": None,
        "source_description": "开标现场公布",
    }
    assert env.api.post(f"/projects/{env.pid}/outcomes", outcome).status_code == 200
    return str(submit.json()["submission_id"])


def test_export_writes_format_a_and_b(api_factory, make_member, store, engine, worker_container, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    env = _env(api_factory, make_member, store, engine, worker_container, ScriptedLlm(_respond))
    _upload(env.api, store, env.pid, TENDER)
    body = _upload(env.api, store, env.pid, BODY_V2, name="施工组织设计.pdf", role="body", key="body-upload-0001")[1].json()["version_id"]
    env.drain()
    submission = _submit_with_outcome(env, body, "5")
    out = tmp_path / "export"
    assert (
        admin.main(["export-score-pairs", "--out", str(out)], container=lambda: Container(Settings(environment="test"), engine, store)) == 0
    )

    (sample,) = batch.load_dataset(out / "评分配对集.json")  # 批量工具能直接读
    sample.resolve_shas()
    assert sample.sample_id == submission and sample.eligible and sample.body_sha() == hashlib.sha256(BODY_V2).hexdigest()
    assert sample.tender_shas() == [hashlib.sha256(TENDER).hexdigest()]
    raw = json.loads((out / "评分配对集.json").read_text("utf-8"))
    label = raw["samples"][0]["label"]
    assert raw["schema"] == "score-pairs/1" and label == {
        "target": "technical_total",
        "value": 5.0,
        "maximum": 8.0,
        "verification_status": "pending",
    }
    assert raw["samples"][0]["template_group"] == env.pid and raw["samples"][0]["body_file"]["text_layer"] is True

    record = json.loads((out / "predictions" / f"{submission}.json").read_text("utf-8"))
    assert record["schema"] == "system-prediction/1" and record["status"] == "succeeded" and record["error"] is None
    assert record["prediction"] == {"status": "candidate", "estimate": "4", "low": "2", "high": "6", "maximum": "8"}
    assert set(record["artifact_extra"]["features"]) == set(features.FEATURES) and record["artifact_extra"]["feature_spec"] == "pf-1"
    (item,) = record["items"]
    assert {*batch.ITEM_KEYS, "item_id", "rubric"} <= set(item) and item["evidence_count"] == 1
    assert record["rules"]["total"] == 3 and record["compliance"]["violated"] == 0 and record["technical_full_score"] == "60"
    assert record["body"]["pages"] == 2 and record["inputs"]["body_sha256"] == sample.body_sha()
