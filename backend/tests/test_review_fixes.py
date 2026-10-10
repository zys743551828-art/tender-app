"""产品逻辑复核后的修正：快照冻结完整性、提交闸门、诊断覆盖度、问题状态流转与对账、事实并发、任务入口白名单等。"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from sqlalchemy import text

from bidwb import db
from tests.pdfs import make_pdf
from tests.test_files_and_parse import _upload
from tests.test_product_logic import FACT_NAME, Flow, _flow, _ready

pytestmark = pytest.mark.integration

SUPPLEMENT = make_pdf([["补遗一 工期说明", "本补遗对工期条款作出补充说明，其余不变。"]])


def _fact_body(evidence_id: str, name: str = FACT_NAME) -> dict[str, Any]:
    return {
        "name": name,
        "subject": "本公司",
        "scope": "全公司",
        "value_decimal": None,
        "unit": None,
        "statement": "本公司持有质量管理体系认证",
        "evidence_ids": [evidence_id],
    }


def _submit(flow: Flow, snap: str, *, at: str = "2026-10-01T08:00:00Z", receipt: str | None = None):  # type: ignore[no-untyped-def]
    return flow.api.post(
        f"/projects/{flow.pid}/submissions",
        {
            "body_version_id": flow.body,
            "snapshot_id": snap,
            "submitted_at": at,
            "receipt_artifact_id": receipt,
        },
    )


# ---------------------------------------------------------------- 1：快照冻结完整性
def test_snapshot_must_cover_current_tender_files_and_matching_rules(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    supplement = _upload(flow.api, store, flow.pid, SUPPLEMENT, name="补遗一.pdf", role="supplement")[1].json()["version_id"]
    flow.drain()
    rules = _ready(flow, ["confirm", "confirm"])  # 规则提取自招标文件 + 补遗
    missing = flow.freeze(rules)  # 只给招标文件，漏了补遗
    assert missing.status_code == 409 and missing.json()["code"] == "tender_inputs_incomplete" and "补遗一.pdf" in missing.json()["message"]
    no_tender = flow.freeze(rules, versions=[supplement, flow.body])
    assert no_tender.status_code == 409 and no_tender.json()["code"] == "tender_missing"
    assert flow.freeze(rules, versions=[flow.tender, supplement, flow.body]).status_code == 200


def test_snapshot_rejects_rules_extracted_from_other_tender_versions(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    # 补遗在规则提取之后才出现：规则与快照里的资料不一致，要求重新提取
    flow2 = _flow(api_factory, make_member, store, engine, worker_container)
    rules2 = _ready(flow2, ["confirm", "confirm"])
    supp2 = _upload(flow2.api, store, flow2.pid, SUPPLEMENT, name="补遗二.pdf", role="supplement", key="supp-upload-0002")[1].json()
    flow2.drain()
    mismatch = flow2.freeze(rules2, versions=[flow2.tender, supp2["version_id"], flow2.body])
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "rules_source_mismatch" and "重新提取" in mismatch.json()["message"]


def test_snapshot_requires_latest_fact_set_when_project_has_facts(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    engineer = flow.add_engineer()
    fact_set = engineer.post(f"/projects/{flow.pid}/facts", _fact_body(rules["rules"][1]["evidence"][0]["evidence_id"])).json()[
        "fact_set_id"
    ]
    omitted = flow.freeze(rules, fact_set_id=None)
    assert omitted.status_code == 409 and omitted.json()["code"] == "fact_set_required"
    assert flow.freeze(rules, fact_set_id=fact_set).status_code == 200


def test_confirm_needs_no_reason_but_other_decisions_do(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = flow.extract()
    first, second = rules["rules"]
    version = str(rules["revision"])
    silent_reject = flow.api.post(f"/rules/{first['rule_id']}/reviews", {"object_version": version, "decision": "reject"})
    assert silent_reject.status_code == 422
    confirmed = flow.api.post(f"/rules/{second['rule_id']}/reviews", {"object_version": version, "decision": "confirm"})
    assert confirmed.status_code == 200, confirmed.text
    rejected = flow.api.post(
        f"/rules/{first['rule_id']}/reviews", {"object_version": version, "decision": "reject", "reason": "与本项目无关"}
    )
    assert rejected.status_code == 200, rejected.text


# ---------------------------------------------------------------- 2：提交闸门
def test_submission_gate(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    assert _submit(flow, snap).json()["code"] == "snapshot_not_diagnosed"

    findings = flow.diagnose(snap)
    blocked = _submit(flow, snap)
    assert blocked.status_code == 409 and blocked.json()["code"] == "critical_findings_open"

    engineer = flow.add_engineer()
    for item in findings:  # 关键问题与强制性要求（响应类）问题都要处理完才能登记提交
        done = engineer.post(
            f"/findings/{item['finding_id']}/reviews",
            {"object_version": str(item["revision"]), "decision": "reject", "reason": "不成立"},
        )
        assert done.status_code == 200, done.text

    naive = _submit(flow, snap, at="2026-10-01T08:00:00")
    assert naive.status_code == 422 and naive.json()["code"] == "submitted_at_naive"
    future = _submit(flow, snap, at="2999-01-01T00:00:00+08:00")
    assert future.status_code == 422 and future.json()["code"] == "submitted_at_in_future"
    with engine.connect() as conn:
        foreign = db.scalar(conn, "SELECT manifest_artifact_id FROM input_snapshots WHERE id=:s", {"s": snap})  # 不是项目上传的文件
        tender_artifact = db.scalar(conn, "SELECT artifact_id FROM file_versions WHERE id=:v", {"v": flow.tender})
    bad_receipt = _submit(flow, snap, receipt=foreign)
    assert bad_receipt.status_code == 422 and bad_receipt.json()["code"] == "receipt_artifact_invalid"
    assert _submit(flow, snap, at="2026-10-01T08:00:00+08:00", receipt=tender_artifact).status_code == 200

    # 之后又冻结了更新的快照：旧快照不再能登记提交
    newer = flow.freeze(rules).json()["snapshot_id"]
    stale = _submit(flow, snap)
    assert stale.status_code == 409 and stale.json()["code"] == "snapshot_not_latest" and stale.json()["details"]["snapshot_id"] == newer


def _diagnosed_and_cleared(flow, engine):  # type: ignore[no-untyped-def]
    """走到“已诊断、严重问题已处理”，返回 (规则集, 快照, 已登录的客户端)。"""
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    engineer = flow.add_engineer()
    for f in flow.diagnose(snap):
        if f["severity"] == "critical":
            engineer.post(
                f"/findings/{f['finding_id']}/reviews",
                {"object_version": str(f["revision"]), "decision": "reject", "reason": "不成立"},
            )
    return rules, snap, engineer


def test_submission_rejects_snapshot_older_than_facts(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules, snap, engineer = _diagnosed_and_cleared(flow, engine)
    engineer.post(f"/projects/{flow.pid}/facts", _fact_body(rules["rules"][1]["evidence"][0]["evidence_id"]))
    blocked = _submit(flow, snap)
    assert blocked.status_code == 409 and blocked.json()["code"] == "snapshot_stale"


def test_submission_rejects_snapshot_older_than_new_materials(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    _, snap, _ = _diagnosed_and_cleared(flow, engine)
    _upload(flow.api, store, flow.pid, SUPPLEMENT, name="补遗一.pdf", role="supplement")
    flow.drain()
    blocked = _submit(flow, snap)
    assert blocked.status_code == 409 and blocked.json()["code"] == "snapshot_stale"


# ---------------------------------------------------------------- 3：诊断覆盖度
def test_partial_diagnosis_exposes_coverage_and_never_reaches_ready_to_submit(
    api_factory, make_member, store, engine, worker_container
) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, a="none", b="garbage")
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    started = flow.api.post(f"/projects/{flow.pid}/diagnosis", {"snapshot_id": snap}).json()
    flow.drain()
    task = flow.api.get(f"/tasks/{started['task_id']}").json()
    assert task["state"] == "succeeded"  # 任务本身成功，但覆盖度如实标注
    assert task["coverage"] == {"status": "partial", "rules_total": 2, "rules_checked": 1, "rules_failed": 1, "candidates_dropped": 0}
    assert "未能完成检查" in task["message"]
    assert flow.project_state() == "issues_open"  # 没有问题也不进入可登记提交
    artifact = json.loads(next(v for k, v in store.objects.items() if task["output_artifact"]["artifact_id"] in k))
    assert artifact["coverage"]["rules_failed"] == 1 and len(artifact["coverage"]["failed_rule_ids"]) == 1
    event = [e for e in flow.api.get(f"/tasks/{started['task_id']}/events").text.split("\n\n") if '"succeeded"' in e][-1]
    assert '"coverage"' in event and "partial" in event
    assert _submit(flow, snap).json()["code"] == "diagnosis_incomplete"

    # 重新诊断且这次全部检查成功：覆盖完整，项目才进入可登记提交
    flow.cfg["b"] = "none"
    assert flow.diagnose(snap) == []
    assert flow.project_state() == "ready_to_submit"
    assert flow.api.get(f"/projects/{flow.pid}/tasks").json()[0]["coverage"]["status"] == "complete"
    assert _submit(flow, snap).status_code == 200


def test_diagnosis_with_no_rule_checked_is_empty_coverage(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, a="garbage", b="garbage")
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    assert flow.diagnose(snap) == []
    task = flow.api.get(f"/projects/{flow.pid}/tasks").json()[0]
    assert task["coverage"]["status"] == "empty" and task["coverage"]["rules_checked"] == 0
    assert flow.project_state() == "issues_open"


# ---------------------------------------------------------------- 4：问题状态流转
def test_finding_reopen_and_manual_resolve(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, b="none")
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    finding = flow.diagnose(snap)[0]
    fid = finding["finding_id"]
    engineer = flow.add_engineer()
    url = f"/findings/{fid}/reviews"

    def act(decision: str, reason: str = "理由") -> Any:
        current = engineer.get(f"/findings/{fid}").json()["revision"]
        return engineer.post(url, {"object_version": str(current), "decision": decision, "reason": reason})

    def status() -> str:
        return str(engineer.get(f"/findings/{fid}").json()["status"])

    assert act("reject").status_code == 200 and status() == "rejected"
    assert act("confirm").status_code == 409  # 驳回后不能直接确认，需先 reopen
    assert act("reopen").status_code == 200 and status() == "candidate"
    assert act("confirm").status_code == 200 and act("resolve").status_code == 200 and status() == "resolved"
    assert act("reopen", "新正文又出现同样问题").status_code == 200 and status() == "candidate"
    assert engineer.post(url, {"object_version": "99", "decision": "reopen", "reason": ""}).status_code == 422  # 理由必填

    # 改稿采纳后（revision_pending）可人工关闭
    with engine.begin() as conn:
        db.run(conn, "UPDATE finding_states SET state='revision_pending', revision=revision+1 WHERE finding_id=:f", {"f": fid})
    assert act("resolve").status_code == 200 and status() == "resolved"


# ---------------------------------------------------------------- 5：对账看最近一个做过诊断的快照
def test_open_findings_on_diagnosed_snapshot_are_not_masked_by_undiagnosed_newer_one(
    api_factory, make_member, store, engine, worker_container
) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, b="none")
    rules = _ready(flow, ["confirm", "confirm"])
    first = flow.freeze(rules).json()["snapshot_id"]
    finding = flow.diagnose(first)[0]
    flow.freeze(rules)  # 更新的快照没诊断
    engineer = flow.add_engineer()
    engineer.post(
        f"/findings/{finding['finding_id']}/reviews", {"object_version": str(finding["revision"]), "decision": "defer", "reason": "待定"}
    )
    assert flow.project_state() == "issues_open"


# ---------------------------------------------------------------- 6：事实录入串行化
def test_add_fact_locks_project_row(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    engineer = flow.add_engineer()
    evidence_id = rules["rules"][1]["evidence"][0]["evidence_id"]
    result: dict[str, Any] = {}

    def add() -> None:
        result["r"] = engineer.post(f"/projects/{flow.pid}/facts", _fact_body(evidence_id))

    with engine.connect() as holder:
        holder.execute(text("SELECT id FROM projects WHERE id=:p FOR UPDATE"), {"p": flow.pid})
        thread = threading.Thread(target=add)
        thread.start()
        thread.join(1.0)
        blocked = thread.is_alive()  # 项目行被别的事务锁住时，录入必须等待
        holder.rollback()
    thread.join(10)
    assert blocked and result["r"].status_code == 200


# ---------------------------------------------------------------- 7：通用任务入口白名单
@pytest.mark.parametrize("kind", ["parse", "rules", "diagnosis", "revision", "recheck", "prediction", "experiment", "export"])
def test_generic_task_endpoint_rejects_every_kind(api_factory, make_member, store, engine, worker_container, kind: str) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    r = flow.api.post(
        f"/projects/{flow.pid}/tasks", {"snapshot_id": "snp_none0001", "kind": kind, "purpose": "business", "bundle_id": "bnd_none0001"}
    )
    assert r.status_code == 422 and r.json()["code"] == "kind_not_creatable_here"


# ---------------------------------------------------------------- 8：原件下载不缓存
def test_original_download_is_not_cacheable(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    r = flow.api.get(f"/files/{flow.tender}/content")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "private, no-store"


# ---------------------------------------------------------------- 9：空建议不能采纳
def test_revision_without_accepted_edits_cannot_be_adopted(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    payload = json.dumps({"edits": [], "dropped": [{"reason": "invented_number"}]}).encode()
    with engine.begin() as conn:
        db.run(
            conn,
            """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
               VALUES ('art_empty0001',:sha,'artifacts/art_empty0001',:n,'application/json','revision-v1',now(),'committed')""",
            {"sha": "0" * 64, "n": len(payload)},
        )
        db.run(
            conn,
            """INSERT INTO revisions(id,project_id,base_version_id,target_version_id,finding_ids_json,allowed_fact_ids_json,diff_artifact_id,created_at)
               VALUES ('rvn_empty0001',:p,:b,NULL,'[]','[]','art_empty0001',now())""",
            {"p": flow.pid, "b": flow.body},
        )
    store.put("artifacts/art_empty0001", payload, "application/json")
    engineer = flow.add_engineer()
    adopt = engineer.post("/revisions/rvn_empty0001/adopt", {"base_version_id": flow.body, "edited_diff_artifact_id": None})
    assert adopt.status_code == 409 and adopt.json()["code"] == "revision_empty"
    reject_body = {"base_version_id": flow.body, "reason": "没有可用修改"}
    rejected = flow.api.post("/revisions/rvn_empty0001/reject", reject_body)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"


# ---------------------------------------------------------------- 10：规则复审
def test_rule_can_be_rereviewed_and_frozen_package_is_cloned(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = flow.extract()
    flow.review_rules(rules, ["defer", "reject"])
    assert flow.api.get(f"/projects/{flow.pid}/rules").json()["status"] == "candidate"
    flow.review_rules(rules, ["confirm", "confirm"])  # 暂缓/驳回 → 确认
    got = flow.api.get(f"/projects/{flow.pid}/rules").json()
    assert got["status"] == "confirmed" and {r["confirmation"] for r in got["rules"]} == {"confirmed"}
    assert flow.freeze(rules).status_code == 200
    frozen = flow.api.post(
        f"/rules/{rules['rules'][0]['rule_id']}/reviews",
        {"object_version": str(rules["revision"]), "decision": "reject", "reason": "改主意"},
    )
    assert frozen.status_code == 200, frozen.text  # 包已被引用：改动落在复制出的新规则包上，旧包不变
    now = flow.api.get(f"/projects/{flow.pid}/rules").json()
    assert now["rule_set_id"] != rules["rule_set_id"] and sorted(r["confirmation"] for r in now["rules"]) == ["confirmed", "rejected"]
