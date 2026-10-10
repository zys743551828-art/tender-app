"""产品逻辑回归：规则确认口径、诊断输入、去重与状态对账、快照新鲜度、上传去重、提交与结果的校验。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import pytest

from bidwb import db
from bidwb.ai.handlers import build_handlers
from bidwb.messaging import InMemoryBus
from bidwb.workers.runner import WorkerRunner
from tests.fakes import ScriptedLlm, docs
from tests.pdfs import make_pdf
from tests.test_ai_pipeline import BODY, BODY_QUOTE, RULE_QUOTE, TENDER, _drain
from tests.test_files_and_parse import _setup, _upload, file_id_of

pytestmark = pytest.mark.integration

QUALITY_QUOTE = "工程质量必须达到合格标准"
RULE_A = "总工期不超过180日历天"
RULE_B = "工程质量必须达到合格标准"
FACT_NAME = "质量保证体系认证"


@dataclass
class Flow:
    api: Any
    pid: str
    engine: Any
    store: Any
    bus: InMemoryBus
    parse_runner: WorkerRunner
    ai_runner: WorkerRunner
    llm: ScriptedLlm
    cfg: dict[str, str]
    tender: str
    body: str
    make_member: Any
    api_factory: Any
    engineer: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    def drain(self) -> None:
        _drain(self.parse_runner, self.bus, self.engine)
        _drain(self.ai_runner, self.bus, self.engine)

    def extract(self) -> dict[str, Any]:
        task = self.api.post(f"/projects/{self.pid}/rules:extract")
        assert task.status_code == 202, task.text
        self.drain()
        return self.api.get(f"/projects/{self.pid}/rules").json()

    def review_rules(self, rules: dict[str, Any], decisions: list[str] | dict[str, str]) -> None:
        """``decisions`` 为列表时按规则顺序（ID 序）对应；为字典时按规则陈述对应。"""
        if isinstance(decisions, dict):
            decisions = [decisions[r["statement"]] for r in rules["rules"]]
        for rule, decision in zip(rules["rules"], decisions, strict=True):
            r = self.api.post(
                f"/rules/{rule['rule_id']}/reviews", {"object_version": str(rules["revision"]), "decision": decision, "reason": "核对原文"}
            )
            assert r.status_code == 200, r.text

    def freeze(self, rules: dict[str, Any], *, fact_set_id: str | None = None, body: str | None = None, versions: list[str] | None = None):  # type: ignore[no-untyped-def]
        body = body or self.body
        return self.api.post(
            f"/projects/{self.pid}/snapshots",
            {
                "body_version_id": body,
                "rule_set_id": rules["rule_set_id"],
                "fact_set_id": fact_set_id,
                "file_version_ids": versions or [self.tender, body],
                "reference_dataset_id": None,
            },
        )

    def diagnose(self, snapshot_id: str) -> list[dict[str, Any]]:
        started = self.api.post(f"/projects/{self.pid}/diagnosis", {"snapshot_id": snapshot_id})
        assert started.status_code == 202, started.text
        self.drain()
        assert self.api.get(f"/tasks/{started.json()['task_id']}").json()["state"] == "succeeded"
        items = self.api.get(f"/projects/{self.pid}/findings?snapshot_id={snapshot_id}&limit=100").json()["items"]
        assert isinstance(items, list)
        return items

    def project_state(self) -> str:
        return str(self.api.get(f"/projects/{self.pid}").json()["state"])

    def add_engineer(self) -> Any:
        self.make_member("eng")
        self.engineer = self.api_factory().login("eng")
        return self.engineer


def _respond(cfg: dict[str, str]):  # type: ignore[no-untyped-def]
    def respond(system: str, user: str) -> Any:  # noqa: PLR0911
        items = docs(user)
        if "抽取员" in system:
            if cfg.get("rules") == "none":
                return {"rules": []}
            out = []
            for stmt, quote in ((RULE_A, RULE_QUOTE), (RULE_B, QUALITY_QUOTE)):
                hit = next((i for i in items if quote in i[1]), None)
                if hit:
                    out.append({"kind": "mandatory", "statement": stmt, "evidence_ids": [hit[0]], "quote": quote})
            return {"rules": out}
        statement = user.split("）：", maxsplit=1)[1].split("\n", maxsplit=1)[0]
        rule_ev = items[0]
        if cfg.get({RULE_A: "a", RULE_B: "b"}[statement]) == "garbage":
            return "这不是 JSON"  # 模型输出多次不符合结构：该条规则整体检查失败
        if statement == RULE_A and cfg.get("a", "conflict") == "conflict":
            body_ev = next((i for i in items if BODY_QUOTE in i[1]), None)
            if body_ev is None:
                return {"findings": []}
            return {
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
                    }
                ]
            }
        if statement == RULE_B and cfg.get("b", "need_fact") == "need_fact":
            return {
                "findings": [
                    {
                        "nature": "needs_confirmation",
                        "severity": "normal",
                        "statement": "正文未说明质量保证体系认证情况",
                        "body_evidence_ids": [],
                        "rule_evidence_ids": [rule_ev[0]],
                        "body_quote": None,
                        "rule_quote": QUALITY_QUOTE,
                        "required_facts": [f"{FACT_NAME}证书"],
                    }
                ]
            }
        return {"findings": []}

    return respond


def _flow(api_factory, make_member, store, engine, worker_container, **cfg: str) -> Flow:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    tender = _upload(api, store, pid, TENDER)[1].json()["version_id"]
    body = _upload(api, store, pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")[1].json()["version_id"]
    state = dict(cfg)
    llm = ScriptedLlm(_respond(state))
    bus = InMemoryBus()
    parse_runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), build_handlers(llm), consumer_name="worker-parse")
    ai_runner = WorkerRunner(worker_container, "ai", bus.consumer(["job.ai"]), build_handlers(llm), consumer_name="worker-ai")
    flow = Flow(api, pid, engine, store, bus, parse_runner, ai_runner, llm, state, tender, body, make_member, api_factory)
    flow.drain()
    return flow


def _ready(flow: Flow, decisions: list[str] | dict[str, str]) -> dict[str, Any]:
    rules = flow.extract()
    assert len(rules["rules"]) == 2, rules
    flow.review_rules(rules, decisions)
    return rules


# ---------------------------------------------------------------- 1、2：规则确认口径
def test_diagnosis_only_uses_rules_whose_latest_review_is_confirm(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, b="none")
    rules = _ready(flow, {RULE_A: "confirm", RULE_B: "reject"})
    snap = flow.freeze(rules)
    assert snap.status_code == 200, snap.text
    flow.diagnose(snap.json()["snapshot_id"])
    diagnosis_calls = [u for s, u in flow.llm.calls if "合规检查员" in s]
    assert len(diagnosis_calls) == 1 and RULE_A in diagnosis_calls[0] and RULE_B not in diagnosis_calls[0]


def test_all_rejected_package_is_not_confirmed_and_empty_extraction_fails(
    api_factory, make_member, store, engine, worker_container
) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["reject", "reject"])
    got = flow.api.get(f"/projects/{flow.pid}/rules").json()
    assert got["status"] == "candidate"
    snap = flow.freeze(rules).json()["snapshot_id"]
    started = flow.api.post(f"/projects/{flow.pid}/diagnosis", {"snapshot_id": snap}).json()
    flow.drain()
    failed = flow.api.get(f"/tasks/{started['task_id']}").json()
    assert failed["state"] == "failed" and failed["error_code"] == "no_rules"  # 规则全被驳回：没有可核对的规则，明确失败
    first = flow.api.post(  # 驳回后可以改决定（包已被引用，改动落在复制出的新规则包上）
        f"/rules/{rules['rules'][0]['rule_id']}/reviews",
        {"object_version": str(rules["revision"]), "decision": "confirm", "reason": "核对原文"},
    )
    assert first.status_code == 200, first.text
    assert flow.api.get(f"/projects/{flow.pid}/rules").json()["status"] == "confirmed"

    # 提取不出任何规则：任务明确失败（带中文原因），不留下空的候选规则包
    flow.cfg["rules"] = "none"
    with engine.connect() as conn:
        before = db.scalar(conn, "SELECT count(*) FROM rule_packages")
    task = flow.api.post(f"/projects/{flow.pid}/rules:extract").json()
    flow.drain()
    got_task = flow.api.get(f"/tasks/{task['task_id']}").json()
    assert got_task["state"] == "failed" and got_task["error_code"] == "no_rules_extracted"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM rule_packages") == before
        message = db.scalar(
            conn, "SELECT details_json->>'message' FROM job_events WHERE job_id=:j AND kind='failed'", {"j": task["task_id"]}
        )
    assert "未能从招标文件中提取出任何可核对的规则" in message


# ---------------------------------------------------------------- 3：事实与 reopen
def test_diagnosis_uses_confirmed_facts_and_skips_covered_confirmation_requests(
    api_factory, make_member, store, engine, worker_container
) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    first = flow.freeze(rules).json()["snapshot_id"]
    findings = flow.diagnose(first)
    assert sorted(f["nature"] for f in findings) == ["fact_conflict", "needs_confirmation"]
    assert {f["rule_id"] for f in findings} == {r["rule_id"] for r in rules["rules"]}

    engineer = flow.add_engineer()
    evidence_id = rules["rules"][1]["evidence"][0]["evidence_id"]
    fact = engineer.post(
        f"/projects/{flow.pid}/facts",
        {
            "name": FACT_NAME,
            "subject": "本公司",
            "scope": "全公司",
            "value_decimal": None,
            "unit": None,
            "statement": "本公司持有 ISO9001 质量管理体系认证",
            "evidence_ids": [evidence_id],
        },
    )
    assert fact.status_code == 200, fact.text
    # 暂缓的问题可以重新打开；非暂缓状态不行
    needs = next(f for f in findings if f["nature"] == "needs_confirmation")
    url = f"/findings/{needs['finding_id']}/reviews"
    assert engineer.post(url, {"object_version": "1", "decision": "reopen", "reason": "无"}).status_code == 409
    assert engineer.post(url, {"object_version": "1", "decision": "request_facts", "reason": "待补充资料"}).status_code == 200
    reopened = engineer.post(url, {"object_version": "2", "decision": "reopen", "reason": "资料已补充"})
    assert reopened.status_code == 200, reopened.text
    assert engineer.get(f"/findings/{needs['finding_id']}").json()["status"] == "candidate"

    second = flow.freeze(rules, fact_set_id=fact.json()["fact_set_id"]).json()["snapshot_id"]
    before = len(flow.llm.calls)
    findings2 = flow.diagnose(second)
    assert [f["nature"] for f in findings2] == ["fact_conflict"]  # 所需事实已被已确认事实覆盖，不再要求确认
    assert any("ISO9001" in u for s, u in flow.llm.calls[before:] if "合规检查员" in s)  # 已确认事实进了提示词
    # 旧一轮的问题只能查看：新一轮冻结后不能再处理
    old = engineer.post(url, {"object_version": "3", "decision": "reopen", "reason": "无"})
    assert old.status_code == 409 and old.json()["code"] == "snapshot_superseded"


# ---------------------------------------------------------------- 4：对账与重跑去重
def test_rerun_does_not_duplicate_and_reconcile_uses_latest_snapshot(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, b="none")
    rules = _ready(flow, ["confirm", "confirm"])
    first = flow.freeze(rules).json()["snapshot_id"]
    findings = flow.diagnose(first)
    assert len(findings) == 1 and flow.project_state() == "issues_open"  # 诊断提交后即对账

    again = flow.diagnose(first)  # 同一快照重跑
    assert [f["finding_id"] for f in again] == [f["finding_id"] for f in findings]
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM findings") == 1 and db.scalar(conn, "SELECT count(*) FROM finding_states") == 1

    flow.cfg["a"] = "none"  # 新快照上没有问题：旧快照遗留的未处理问题不再阻塞项目
    second = flow.freeze(rules).json()["snapshot_id"]
    assert second != first
    assert flow.diagnose(second) == []
    assert flow.project_state() == "ready_to_submit"


# ---------------------------------------------------------------- 11：键集分页
def test_findings_pagination_is_keyset_and_survives_filter_changes(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    flow.diagnose(snap)
    rule_id = rules["rules"][0]["rule_id"]
    with engine.begin() as conn:
        for i, sev in enumerate(["critical", "normal", "improvement", "normal"]):
            db.run(
                conn,
                """INSERT INTO findings(id,project_id,snapshot_id,run_id,rule_id,source,category,rule_basis,dedupe_key,nature,impact,severity,statement,evidence_ids_json,required_facts_json,created_at)
                   VALUES (:i,:p,:s,'job_x',:r,'rule','improvement','confirmed',:k,'suggestion','technical',:sev,'补充的建议类问题',CAST(:ev AS jsonb),'[]'::jsonb,now()+make_interval(secs=>:n))""",
                {
                    "i": f"fnd_extra{i}0000",
                    "p": flow.pid,
                    "s": snap,
                    "r": rule_id,
                    "k": f"extra{i}",
                    "sev": sev,
                    "ev": f'["{rules["rules"][0]["evidence"][0]["evidence_id"]}"]',
                    "n": i,
                },
            )
            db.run(conn, "INSERT INTO finding_states(finding_id,state,revision) VALUES (:f,'candidate',1)", {"f": f"fnd_extra{i}0000"})
    base = f"/projects/{flow.pid}/findings"
    full = [f["finding_id"] for f in flow.api.get(f"{base}?limit=100").json()["items"]]
    assert len(full) == 6

    walked: list[str] = []
    cursor = None
    while True:
        page = flow.api.get(f"{base}?limit=2" + (f"&cursor={cursor}" if cursor else "")).json()
        walked += [f["finding_id"] for f in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert walked == full  # 无重复、无遗漏、顺序稳定

    # 取第一页后，第一页最后一条的状态变化而离开筛选结果；游标依然可用，且不重复、不遗漏
    first = flow.api.get(f"{base}?status=candidate&limit=2").json()
    last = first["items"][-1]
    engineer = flow.add_engineer()
    done = engineer.post(
        f"/findings/{last['finding_id']}/reviews", {"object_version": str(last["revision"]), "decision": "reject", "reason": "不成立"}
    )
    assert done.status_code == 200, done.text
    rest = flow.api.get(f"{base}?status=candidate&limit=100&cursor={first['next_cursor']}")
    assert rest.status_code == 200
    assert [f["finding_id"] for f in rest.json()["items"]] == [f for f in full[2:] if f != last["finding_id"]]
    # 换一个筛选条件继续使用同一游标也不报错
    assert flow.api.get(f"{base}?limit=100&cursor={first['next_cursor']}").status_code == 200
    assert flow.api.get(f"{base}?cursor=not-a-cursor").json()["code"] == "invalid_cursor"


# ---------------------------------------------------------------- 6、7：上传
def test_reupload_of_identical_content_returns_latest_version(api_factory, make_member, store, engine) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    data = make_pdf([["第一章 工程概况", "工期一百八十日历天。"]])
    first = _upload(api, store, pid, data)[1].json()
    second = _upload(api, store, pid, data)[1]  # 同项目、同用途、同原名、字节相同：返回已有版本
    assert second.status_code == 200 and second.json()["version_id"] == first["version_id"]
    assert second.json()["duplicate"] is True and second.json()["new_file"] is False and first["duplicate"] is False
    assert len(api.get(f"/projects/{pid}/files").json()) == 1
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM jobs WHERE kind='parse'") == 1
        assert db.scalar(conn, "SELECT count(*) FROM upload_sessions WHERE state='completed'") == 2
    # 声明为该文件的新版本但字节与最新版本相同：同样返回已有版本
    explicit = _upload(api, store, pid, data, version_of=first["file_id"])[1].json()
    assert explicit["version_id"] == first["version_id"] and explicit["duplicate"] is True
    # 同名不同内容、不声明：另一个逻辑文件
    sibling = _upload(api, store, pid, make_pdf([["第二份 内容充足充足"]]))[1].json()
    assert sibling["file_id"] != first["file_id"] and sibling["supersedes"] is None
    other = _upload(api, store, pid, make_pdf([["第二版 内容充足充足"]]), version_of=first["file_id"])[1].json()
    assert other["supersedes"] == first["version_id"] and other["version_number"] == 2
    # 回到旧内容：与最新版本不同，是新的版本；不声明时同名同内容也命中最新版本之外的旧版本？不命中（只比最新版本）
    again = _upload(api, store, pid, data, version_of=first["file_id"])[1].json()
    assert again["version_id"] not in {first["version_id"], other["version_id"]} and again["supersedes"] == other["version_id"]
    assert again["version_number"] == 3 and again["duplicate"] is False


def test_rules_extraction_uses_latest_version_and_names_unparsed_file(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    _upload(
        flow.api,
        store,
        flow.pid,
        make_pdf([["第一章 工期要求", "总工期不得超过一百七十日历天。"]]),
        version_of=file_id_of(flow.api, flow.pid, flow.tender),
    )  # 招标文件 v2，尚未解析
    refused = flow.api.post(f"/projects/{flow.pid}/rules:extract")
    assert (
        refused.status_code == 409 and refused.json()["code"] == "tender_version_not_parsed" and "招标文件.pdf" in refused.json()["message"]
    )
    flow.drain()
    assert flow.api.post(f"/projects/{flow.pid}/rules:extract").status_code == 202


# ---------------------------------------------------------------- 8、9：快照新鲜度与冻结后的规则
def test_snapshot_requires_latest_confirmed_inputs(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    engineer = flow.add_engineer()
    evidence_id = rules["rules"][1]["evidence"][0]["evidence_id"]
    fact_body = {
        "name": FACT_NAME,
        "subject": "本公司",
        "scope": "全公司",
        "value_decimal": None,
        "unit": None,
        "statement": "本公司持有质量管理体系认证",
        "evidence_ids": [evidence_id],
    }
    old_fact = engineer.post(f"/projects/{flow.pid}/facts", fact_body).json()["fact_set_id"]
    new_fact = engineer.post(f"/projects/{flow.pid}/facts", {**fact_body, "name": "安全生产许可证"}).json()["fact_set_id"]
    stale_fact = flow.freeze(rules, fact_set_id=old_fact)
    assert stale_fact.status_code == 409 and stale_fact.json()["code"] == "stale_inputs"
    assert flow.freeze(rules, fact_set_id=new_fact).status_code == 200

    # 招标文件有了尚未解析的新版本：旧版本过期，新版本未解析
    new_tender = _upload(
        flow.api,
        store,
        flow.pid,
        make_pdf(
            [["第一章 工期要求", "总工期不得超过一百八十日历天，超过的按废标处理。"], ["第二章 质量要求", "工程质量必须达到合格标准。"]]
        ),
        version_of=file_id_of(flow.api, flow.pid, flow.tender),
    )[1].json()["version_id"]
    stale = flow.freeze(rules)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_inputs" and flow.tender in stale.json()["message"]
    unparsed = flow.freeze(rules, versions=[new_tender, flow.body])
    assert unparsed.status_code == 409 and unparsed.json()["code"] == "input_not_parsed" and "招标文件.pdf" in unparsed.json()["message"]
    flow.drain()
    # 规则是从旧招标文件提取的：与快照里的招标文件版本不一致，必须重新提取
    mismatch = flow.freeze(rules, fact_set_id=new_fact, versions=[new_tender, flow.body])
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "rules_source_mismatch" and "重新提取" in mismatch.json()["message"]
    rules2 = flow.extract()
    flow.review_rules(rules2, ["confirm", "confirm"])
    assert flow.freeze(rules2, fact_set_id=new_fact, versions=[new_tender, flow.body]).status_code == 200

    # 重新提取出新的规则包后，旧规则包不能再冻结
    flow.extract()
    old_rules = flow.freeze(rules2, fact_set_id=new_fact, versions=[new_tender, flow.body])
    assert old_rules.status_code == 409 and old_rules.json()["code"] == "stale_inputs"


def test_rule_decision_cannot_change_after_package_is_frozen(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "reject"])
    snap = flow.freeze(rules).json()
    changed = flow.api.post(
        f"/rules/{rules['rules'][1]['rule_id']}/reviews",
        {"object_version": str(rules["revision"]), "decision": "confirm", "reason": "改主意"},
    )
    assert changed.status_code == 200, changed.text  # 改变了参与评审的规则集合：落在复制出的新规则包上
    now = flow.api.get(f"/projects/{flow.pid}/rules").json()
    assert now["rule_set_id"] != rules["rule_set_id"] and now["revision"] == rules["revision"] + 1
    assert {r["confirmation"] for r in now["rules"]} == {"confirmed"}
    assert snap["rule_set_id"] == rules["rule_set_id"]  # 已冻结的输入仍引用原规则包，旧一轮结果可复现
    assert flow.api.get(f"/snapshots/{snap['snapshot_id']}").json()["rule_set_id"] == rules["rule_set_id"]


# ---------------------------------------------------------------- 10：隔离上传的幂等占位
def test_quarantined_upload_leaves_no_idempotency_placeholder(api_factory, make_member, store, engine) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    real = make_pdf([["真实内容 真实内容"]])
    claimed = hashlib.sha256(real).hexdigest()
    init = api.post(
        f"/projects/{pid}/uploads",
        {"original_name": "a.pdf", "role": "tender", "byte_size": len(real), "sha256": claimed, "media_type": "application/pdf"},
    ).json()
    oss_id = next(iter(store._uploads))
    etag = store.put_part(oss_id, 1, bytes([real[0] ^ 1]) + real[1:])
    complete = {"sha256": claimed, "parts": [{"part_number": 1, "etag": etag}]}
    first = api.post(f"/uploads/{init['upload_id']}/complete", complete, key="complete-key-0001")
    assert first.status_code == 422 and first.json()["code"] == "content_mismatch"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM idempotency_keys WHERE response_status=0") == 0
        assert db.scalar(conn, "SELECT status FROM artifacts") == "quarantined"
    replay = api.post(f"/uploads/{init['upload_id']}/complete", complete, key="complete-key-0001")
    assert replay.json()["code"] != "idempotency_in_progress"


# ---------------------------------------------------------------- 12、13：提交与结果
def test_submission_records_lead_confirmation_and_requires_current_body(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, a="none", b="none")
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    flow.diagnose(snap)

    def submit(body: str | None = None, key: str | None = None):  # type: ignore[no-untyped-def]
        return flow.api.post(
            f"/projects/{flow.pid}/submissions",
            {
                "body_version_id": body or flow.body,
                "snapshot_id": snap,
                "submitted_at": "2026-10-01T08:00:00Z",
                "receipt_artifact_id": None,
            },
            key=key,
        )

    mismatch = submit(body=flow.tender)
    assert mismatch.status_code == 422 and mismatch.json()["code"] == "body_version_mismatch"
    ok = submit()
    assert ok.status_code == 200, ok.text
    with engine.connect() as conn:  # 登记本身就是登记人的确认，随提交留存一条确认记录
        row = db.one(
            conn, "SELECT object_kind, object_id, decision, actor_id FROM reviews WHERE id=:r", {"r": ok.json()["confirmation_review_id"]}
        )
        lead = db.scalar(conn, "SELECT owner_id FROM projects WHERE id=:p", {"p": flow.pid})
    assert row is not None and (row["object_kind"], row["object_id"], row["decision"]) == (
        "submission",
        ok.json()["submission_id"],
        "confirm",
    )
    assert row["actor_id"] == lead

    _upload(
        flow.api,
        store,
        flow.pid,
        make_pdf([["第一章 施工进度计划", "本工程计划总工期为一百八十日历天。"]]),
        name="施工组织设计.pdf",
        role="body",
        version_of=file_id_of(flow.api, flow.pid, flow.body),
    )
    stale = submit()
    assert stale.status_code == 409 and stale.json()["code"] == "body_version_stale"


def test_outcome_supersedes_must_be_unsuperseded_record_of_same_submission(
    api_factory, make_member, store, engine, worker_container
) -> None:  # type: ignore[no-untyped-def]
    flow = _flow(api_factory, make_member, store, engine, worker_container, a="none", b="none")
    rules = _ready(flow, ["confirm", "confirm"])
    snap = flow.freeze(rules).json()["snapshot_id"]
    flow.diagnose(snap)
    sub = flow.api.post(
        f"/projects/{flow.pid}/submissions",
        {
            "body_version_id": flow.body,
            "snapshot_id": snap,
            "submitted_at": "2026-10-01T08:00:00Z",
            "receipt_artifact_id": None,
        },
    ).json()["submission_id"]

    def outcome(supersedes: str | None):  # type: ignore[no-untyped-def]
        return flow.api.post(
            f"/projects/{flow.pid}/outcomes",
            {
                "submission_id": sub,
                "source_kind": "user_reported",
                "target": "technical_total",
                "value": "80",
                "maximum": "100",
                "aggregation": None,
                "stage_result": "pending",
                "source_page": None,
                "published_at": None,
                "supersedes": supersedes,
                "source_artifact_id": None,
                "source_description": "口头告知",
            },
        )

    first = outcome(None).json()["outcome_id"]
    second = outcome(first)
    assert second.status_code == 200, second.text
    again = outcome(first)  # first 已被取代
    assert again.status_code == 409 and again.json()["code"] == "outcome_superseded"
    assert outcome(second.json()["outcome_id"]).status_code == 200
    assert outcome("out_missing0000").status_code == 404
