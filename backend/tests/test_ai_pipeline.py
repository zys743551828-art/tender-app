"""规则提取 → 人工确认 → 冻结快照 → 诊断 → 审核，端到端（真实 PG、受限 worker 角色、脚本化模型）。"""

from __future__ import annotations

import json

import pytest

from bidwb import db, tasks
from bidwb.ai.handlers import build_handlers
from bidwb.messaging import InMemoryBus
from bidwb.workers.runner import WorkerRunner
from tests.fakes import ScriptedLlm, docs
from tests.pdfs import make_pdf
from tests.test_files_and_parse import _setup, _upload, file_id_of

pytestmark = pytest.mark.integration

TENDER = make_pdf(
    [["第一章 工期要求", "总工期不得超过一百八十日历天，超过的按废标处理。"], ["第二章 质量要求", "工程质量必须达到合格标准。"]]
)
BODY = make_pdf([["第一章 施工进度计划", "本工程计划总工期为二百四十日历天。"]])
RULE_QUOTE = "总工期不得超过一百八十日历天"
BODY_QUOTE = "计划总工期为二百四十日历天"


def _respond(system: str, user: str):  # type: ignore[no-untyped-def]
    items = docs(user)
    if "招标规则抽取员" in system:
        hit = next(((i, t) for i, t in items if RULE_QUOTE in t), None)
        bad = {
            "kind": "mandatory",
            "statement": "必须使用进口设备",
            "evidence_ids": [items[0][0]],
            "quote": "必须使用进口设备",
        }  # 原文中没有
        good = [{"kind": "mandatory", "statement": "总工期不超过180日历天", "evidence_ids": [hit[0]], "quote": RULE_QUOTE}] if hit else []
        return {"rules": [*good, bad]}
    rule_ev, body_ev = items[0], next((i for i in items if BODY_QUOTE in i[1]), None)
    if body_ev is None:
        return {"findings": []}
    return {
        "verdict": "violated",
        "findings": [
            {
                "nature": "fact_conflict",
                "severity": "critical",
                "statement": "进度计划工期超过招标上限",
                "body_evidence_ids": [body_ev[0]],
                "rule_evidence_ids": [rule_ev[0]],
                "body_quote": BODY_QUOTE,
                "rule_quote": RULE_QUOTE,
                "required_facts": [],
            },
            {
                "nature": "fact_conflict",
                "severity": "normal",
                "statement": "编造的冲突",
                "body_evidence_ids": [body_ev[0]],
                "rule_evidence_ids": [rule_ev[0]],
                "body_quote": "正文里并没有这句话",
                "rule_quote": RULE_QUOTE,
                "required_facts": [],
            },
        ],
    }


def _drain(runner: WorkerRunner, bus: InMemoryBus, engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        tasks.relay_outbox(conn, bus.producer())
    while runner.poll_once():
        pass


def test_rules_to_findings_flow(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    tender = _upload(api, store, pid, TENDER)[1].json()["version_id"]
    body = _upload(api, store, pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")[1].json()["version_id"]
    llm = ScriptedLlm(_respond)
    bus = InMemoryBus()
    parse_runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), build_handlers(llm), consumer_name="worker-parse")
    ai_runner = WorkerRunner(worker_container, "ai", bus.consumer(["job.ai"]), build_handlers(llm), consumer_name="worker-ai")
    _drain(parse_runner, bus, engine)

    task = api.post(f"/projects/{pid}/rules:extract")
    assert task.status_code == 202 and task.json()["kind"] == "rules" and task.json()["snapshot_id"] is None
    _drain(parse_runner, bus, engine)
    rules = api.get(f"/projects/{pid}/rules").json()
    assert rules["status"] == "candidate" and len(rules["rules"]) == 1, rules
    assert rules["rules"][0]["confirmation"] == "pending" and rules["rules"][0]["kind"] == "mandatory"  # 原文里找不到的那条被丢弃
    assert rules["rules"][0]["evidence"][0]["quote"].count("一百八十日历天") == 1
    assert any(b"quote_not_found" in v for k, v in store.objects.items() if k.startswith("artifacts/"))  # 丢弃原因写进产物，可审计

    rule = rules["rules"][0]
    snap_body = {
        "body_version_id": body,
        "rule_set_id": rules["rule_set_id"],
        "fact_set_id": None,
        "file_version_ids": [tender, body],
        "reference_dataset_id": None,
    }
    review = api.post(
        f"/rules/{rule['rule_id']}/reviews",
        {"object_version": str(rules["revision"]), "decision": "confirm", "reason": "与招标文件第一章一致"},
    )
    assert review.status_code == 200, review.text
    snapshot = api.post(f"/projects/{pid}/snapshots", snap_body).json()

    started = api.post(f"/projects/{pid}/diagnosis", {"snapshot_id": snapshot["snapshot_id"]})
    assert started.status_code == 202 and started.json()["bundle_id"] is None
    _drain(ai_runner, bus, engine)
    assert api.get(f"/tasks/{started.json()['task_id']}").json()["state"] == "succeeded"
    page = api.get(f"/projects/{pid}/findings").json()
    assert len(page["items"]) == 1  # 编造的冲突（正文引文不存在）被丢弃
    finding = page["items"][0]
    assert finding["status"] == "candidate" and finding["nature"] == "fact_conflict" and len(finding["evidence"]) == 2
    make_member("eng")
    engineer = api_factory().login("eng")
    done = engineer.post(
        f"/findings/{finding['finding_id']}/reviews",
        {"object_version": str(finding["revision"]), "decision": "confirm", "reason": "确认超期"},
    )
    assert done.status_code == 200 and engineer.get(f"/findings/{finding['finding_id']}").json()["status"] == "confirmed"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action IN ('rules.extract','diagnosis.start')") == 2


def test_rules_job_fails_clearly_without_model(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    _upload(api, store, pid, TENDER)
    bus = InMemoryBus()
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), build_handlers(None), consumer_name="worker-parse")
    _drain(runner, bus, engine)
    task = api.post(f"/projects/{pid}/rules:extract").json()
    _drain(runner, bus, engine)
    got = api.get(f"/tasks/{task['task_id']}").json()
    assert got["state"] == "failed" and got["error_code"] == "llm_not_configured"


def _revise(system: str, user: str):  # type: ignore[no-untyped-def]
    items = docs(user)
    fid = user.split("[")[1].split("]", maxsplit=1)[0]
    ev = next(i for i in items if BODY_QUOTE in i[1])[0]
    base = {"evidence_id": ev, "original": BODY_QUOTE, "finding_id": fid, "facts_used": [], "note": ""}
    return {
        "edits": [
            {**base, "replacement": "计划总工期为一百八十日历天"},  # 数字“一百八十”是汉字，不在数字守卫范围内
            {**base, "replacement": "计划总工期为 175 日历天"},  # 凭空出现的数字
            {**base, "original": "正文里没有的原文片段", "replacement": "任意"},
        ]
    }


def test_revision_propose_adopt_and_stale(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    tender = _upload(api, store, pid, TENDER)[1].json()["version_id"]
    body = _upload(api, store, pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")[1].json()["version_id"]
    bus = InMemoryBus()
    llm = ScriptedLlm(lambda s, u: _respond(s, u) if "合规检查员" in s or "抽取员" in s else _revise(s, u))
    parse_runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), build_handlers(llm), consumer_name="worker-parse")
    ai_runner = WorkerRunner(worker_container, "ai", bus.consumer(["job.ai"]), build_handlers(llm), consumer_name="worker-ai")
    _drain(parse_runner, bus, engine)
    api.post(f"/projects/{pid}/rules:extract")
    _drain(parse_runner, bus, engine)
    rules = api.get(f"/projects/{pid}/rules").json()
    api.post(
        f"/rules/{rules['rules'][0]['rule_id']}/reviews",
        {"object_version": str(rules["revision"]), "decision": "confirm", "reason": "一致"},
    )
    snapshot = api.post(
        f"/projects/{pid}/snapshots",
        {
            "body_version_id": body,
            "rule_set_id": rules["rule_set_id"],
            "fact_set_id": None,
            "file_version_ids": [tender, body],
            "reference_dataset_id": None,
        },
    ).json()
    api.post(f"/projects/{pid}/diagnosis", {"snapshot_id": snapshot["snapshot_id"]})
    _drain(ai_runner, bus, engine)
    finding = api.get(f"/projects/{pid}/findings").json()["items"][0]
    make_member("eng")
    engineer = api_factory().login("eng")
    make_member("comp")
    compiler = api_factory().login("comp")
    request = {
        "base_version_id": body,
        "snapshot_id": snapshot["snapshot_id"],
        "finding_ids": [finding["finding_id"]],
        "allowed_fact_ids": [],
        "scope": "进度计划",
    }

    # 未确认的问题不能生成建议
    assert api.post(f"/projects/{pid}/revisions", request).json()["code"] == "finding_not_confirmed"
    engineer.post(
        f"/findings/{finding['finding_id']}/reviews", {"object_version": str(finding["revision"]), "decision": "confirm", "reason": "超期"}
    )

    task = api.post(f"/projects/{pid}/revisions", request)
    assert task.status_code == 202 and task.json()["kind"] == "revision"
    _drain(ai_runner, bus, engine)
    revisions = api.get(f"/projects/{pid}/revisions").json()
    assert len(revisions) == 1 and revisions[0]["status"] == "proposed"
    stored = next(v for k, v in store.objects.items() if revisions[0]["diff_artifact"]["artifact_id"] in k)
    payload = json.loads(stored)
    assert [e["replacement"] for e in payload["edits"]] == ["计划总工期为一百八十日历天"]  # 凭空数字与非原文引用的两条被丢弃
    assert {d["reason"] for d in payload["dropped"]} == {"invented_number", "original_not_verbatim"}

    revision_id = revisions[0]["revision_id"]
    diff = api.get(f"/revisions/{revision_id}/diff").json()
    assert [e["replacement"] for e in diff["edits"]] == ["计划总工期为一百八十日历天"]
    assert api_factory().get(f"/revisions/{revision_id}/diff").status_code == 401
    assert [s["snapshot_id"] for s in api.get(f"/projects/{pid}/snapshots").json()] == [snapshot["snapshot_id"]]
    adopt = {"base_version_id": body, "edited_diff_artifact_id": None}
    assert (
        engineer.post(f"/revisions/{revision_id}/adopt", {**adopt, "edited_diff_artifact_id": "art_xxx"}).json()["code"]
        == "edited_diff_unsupported"
    )
    done = compiler.post(f"/revisions/{revision_id}/adopt", adopt)  # 任何登录成员都可以采纳
    assert done.status_code == 200 and done.json()["status"] == "adopted" and len(done.json()["review_ids"]) == 1
    assert engineer.get(f"/findings/{finding['finding_id']}").json()["status"] == "revision_pending"
    assert engineer.post(f"/revisions/{revision_id}/adopt", {**adopt}, key="another-key-0002").json()["code"] == "revision_already_reviewed"


def test_stale_revision_cannot_be_adopted(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    """正文上传了新版本后，基于旧版本的建议显示为过期，且不能再采纳。"""
    api, pid = _setup(api_factory, make_member)
    old = _upload(api, store, pid, BODY, name="施工组织设计.pdf", role="body")[1].json()["version_id"]
    with engine.begin() as conn:  # 直接植入一条建议，聚焦过期判定本身
        art = db.one(conn, "SELECT artifact_id FROM file_versions WHERE id=:v", {"v": old})["artifact_id"]
        db.run(
            conn,
            """INSERT INTO revisions(id,project_id,base_version_id,target_version_id,finding_ids_json,allowed_fact_ids_json,diff_artifact_id,created_at)
                        VALUES ('rvn_stale0001',:p,:b,NULL,'["fnd_none0001"]','[]',:a,now())""",
            {"p": pid, "b": old, "a": art},
        )
    assert api.get(f"/projects/{pid}/revisions").json()[0]["status"] == "proposed"
    _upload(
        api,
        store,
        pid,
        make_pdf([["第一章 施工进度计划", "本工程计划总工期为一百八十日历天。"]]),
        name="施工组织设计.pdf",
        role="body",
        key="body-upload-0002",
        version_of=file_id_of(api, pid, old),
    )
    assert api.get(f"/projects/{pid}/revisions").json()[0]["status"] == "stale"
