"""成绩身份、未知分值、提交更正和历史保留。"""

import json
from typing import Any

import pytest

from bidwb import db
from tests.test_product_logic import _flow, _ready

pytestmark = pytest.mark.integration


@pytest.fixture
def submitted(api_factory: Any, make_member: Any, store: Any, engine: Any, worker_container: Any) -> tuple[Any, dict[str, Any]]:
    flow = _flow(api_factory, make_member, store, engine, worker_container, a="none", b="none")
    package = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(package).json()["snapshot_id"]
    flow.diagnose(snap)
    request = {"body_version_id": flow.body, "snapshot_id": snap, "submitted_at": "2026-10-01T08:00:00Z", "receipt_artifact_id": None}
    response = flow.api.post(f"/projects/{flow.pid}/submissions", request)
    assert response.status_code == 200, response.text
    return flow, {"submission": response.json(), "request": request}


def payload(submission_id: str, **changes: Any) -> dict[str, Any]:
    return {
        "submission_id": submission_id,
        "source_kind": "user_reported",
        "target": "technical_total",
        "value": None,
        "maximum": "100",
        "score_unknown": True,
        "aggregation": None,
        "stage_result": "pending",
        "source_page": None,
        "published_at": None,
        "supersedes": None,
        "source_artifact_id": None,
        "source_description": "合成验证：分值尚未公布",
        **changes,
    }


def test_unknown_preserves_target_and_null_and_cannot_verify(submitted: Any, engine: Any) -> None:
    flow, info = submitted
    sub = info["submission"]
    assert sub["body_name"] == "施工组织设计.pdf" and len(sub["body_sha256"]) == 64
    assert sub["body_version_id"] == flow.body and sub["superseded"] is False
    path = f"/projects/{flow.pid}"
    revision = flow.api.get(path).json()["revision"]
    request = payload(sub["submission_id"], source_kind="official", expected_project_revision=revision)
    result = flow.api.post(path + "/outcomes", request, key="unknown-score-card")
    assert result.status_code == 200, result.text
    outcome = result.json()
    assert (outcome["target"], outcome["value"], outcome["maximum"], outcome["verification_status"]) == (
        "technical_total",
        None,
        "100",
        "pending",
    )
    assert flow.api.post(path + "/outcomes", request, key="unknown-score-card").json() == outcome
    verified = flow.api.post(
        f"/outcomes/{outcome['outcome_id']}/verify",
        {"source_artifact_id": "art_missing", "source_page": 1, "aggregation": "平均", "reason": "测试"},
    )
    assert verified.status_code == 409 and verified.json()["code"] == "outcome_score_unknown"
    assert flow.api.post(path + "/outcomes", payload(sub["submission_id"], value="0")).status_code == 422
    assert flow.api.post(path + "/outcomes", payload(sub["submission_id"], score_unknown=False)).status_code == 422
    assert flow.api.post(path + "/outcomes", payload(sub["submission_id"], maximum=None)).status_code == 200
    with engine.connect() as conn:
        detail = db.one(
            conn, "SELECT details_json FROM audit_events WHERE action='outcome.record' AND object_id=:o", {"o": outcome["outcome_id"]}
        )
        assert detail and detail["details_json"]["body_version_id"] == flow.body
        assert detail["details_json"]["project_identity"]["revision"] == revision


def test_project_identity_change_rejects_stale_request(submitted: Any) -> None:
    flow, info = submitted
    path = f"/projects/{flow.pid}"
    project = flow.api.get(path).json()
    assert flow.api.patch(path, {"round": project["round"] + 1}, headers={"If-Match": str(project["revision"])}).status_code == 200
    old = flow.api.post(path + "/outcomes", payload(info["submission"]["submission_id"], expected_project_revision=project["revision"]))
    assert old.status_code == 409 and old.json()["code"] == "outcome_identity_stale"
    assert flow.api.get(path + "/outcomes").json() == []
    current = flow.api.get(path).json()
    request = payload(info["submission"]["submission_id"], expected_project_revision=current["revision"])
    conflict = flow.api.post(path + "/outcomes", request)
    assert conflict.status_code == 409 and conflict.json()["code"] == "outcome_identity_conflict"
    assert flow.api.post(path + "/outcomes", {**request, "acknowledge_identity_difference": True}).status_code == 200
    saved = flow.api.get(path + "/submissions").json()[0]
    assert saved["round"] == project["round"] and saved["round"] != current["round"]


def test_corrected_submission_rejects_old_identity_and_preserves_old_result(submitted: Any, engine: Any) -> None:
    flow, info = submitted
    path = f"/projects/{flow.pid}"
    first = flow.api.post(path + "/outcomes", payload(info["submission"]["submission_id"], stage_result="not_awarded")).json()
    second = flow.api.post(path + "/submissions", {**info["request"], "submitted_at": "2026-09-30T08:00:00Z"})
    assert second.status_code == 200, second.text
    assert second.json()["supersedes"] == info["submission"]["submission_id"]
    old = flow.api.post(path + "/outcomes", payload(info["submission"]["submission_id"]))
    assert old.status_code == 409 and old.json()["code"] == "submission_superseded"
    listed = flow.api.get(path + "/submissions").json()
    assert next(s for s in listed if s["submission_id"] == info["submission"]["submission_id"])["superseded"] is True
    assert flow.api.get(path + "/outcomes").json()[0] == first
    third = flow.api.post(path + "/submissions", {**info["request"], "submitted_at": "2026-09-29T08:00:00Z"}).json()
    assert third["supersedes"] == second.json()["submission_id"]
    with engine.connect() as conn:
        from bidwb.services.metrics import _LATEST_OUTCOME

        assert db.all_(conn, _LATEST_OUTCOME, {"ids": [flow.pid]}) == []


def test_submission_maximum_uses_its_frozen_package(submitted: Any, engine: Any) -> None:
    flow, info = submitted
    # 此合成夹具仅核对来源身份；用测试库关闭追加保护构造冻结包中的满分与不同的当前包。
    with engine.begin() as conn:
        db.run(conn, "SET LOCAL session_replication_role=replica")
        package = db.scalar(conn, "SELECT rule_set_id FROM input_snapshots WHERE id=:s", {"s": info["submission"]["snapshot_id"]})
        db.run(
            conn,
            "UPDATE rule_packages SET terms_json=CAST(:t AS jsonb) WHERE id=:k",
            {"k": package, "t": json.dumps({"technical_full_score": {"value": "80", "quote": "技术满分80", "evidence_ids": []}})},
        )
        db.run(
            conn,
            """INSERT INTO rule_packages(id,project_id,revision,status,artifact_id,source_versions_json,terms_json,effectivity_json,created_at)
            SELECT 'pkg_new_current',project_id,revision+1,status,artifact_id,source_versions_json,CAST(:t AS jsonb),effectivity_json,now() FROM rule_packages WHERE id=:k""",
            {"k": package, "t": json.dumps({"technical_full_score": {"value": "120", "quote": "当前满分120", "evidence_ids": []}})},
        )
    entry = next(
        s for s in flow.api.get(f"/projects/{flow.pid}/submissions").json() if s["submission_id"] == info["submission"]["submission_id"]
    )
    assert entry["technical_maximum"] == "80"
