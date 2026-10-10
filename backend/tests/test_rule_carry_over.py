"""重新提取规则时，沿用上一版规则包中同一条款的人工决定。"""

from __future__ import annotations

import pytest

from bidwb import db
from bidwb.ai.handlers import build_handlers
from bidwb.messaging import InMemoryBus
from bidwb.workers.runner import WorkerRunner
from tests.fakes import ScriptedLlm, docs
from tests.pdfs import make_pdf
from tests.test_ai_pipeline import _drain
from tests.test_files_and_parse import _setup, _upload

pytestmark = pytest.mark.integration

TENDER = make_pdf(
    [
        ["第一章 工期要求", "总工期不得超过一百八十日历天，超过的按废标处理。"],
        ["第二章 质量要求", "工程质量必须达到合格标准。"],
        ["第三章 安全要求", "项目经理必须常驻现场。"],
    ]
)
QUOTES = {"工期": "总工期不得超过一百八十日历天", "质量": "工程质量必须达到合格标准", "安全": "项目经理必须常驻现场"}
PREFIX = "沿用自上一版规则集："


def _rules_script(statements: dict[str, tuple[str, str]]):  # type: ignore[no-untyped-def]
    """statements: 主题 -> (kind, 条文)；按主题在证据里找到原文引文。"""

    def respond(system: str, user: str):  # type: ignore[no-untyped-def]
        items = docs(user)
        out = []
        for topic, (kind, statement) in statements.items():
            hit = next(((i, t) for i, t in items if QUOTES[topic] in t), None)
            if hit:
                out.append({"kind": kind, "statement": statement, "evidence_ids": [hit[0]], "quote": QUOTES[topic]})
        return {"rules": out}

    return respond


def _extract(api, pid, runner, bus, engine) -> dict:  # type: ignore[no-untyped-def]
    assert api.post(f"/projects/{pid}/rules:extract").status_code == 202
    _drain(runner, bus, engine)
    return api.get(f"/projects/{pid}/rules").json()


def _review(api, rules, topic_statement: str, decision: str, reason: str) -> None:  # type: ignore[no-untyped-def]
    rule = next(r for r in rules["rules"] if r["statement"] == topic_statement)
    res = api.post(f"/rules/{rule['rule_id']}/reviews", {"object_version": str(rules["revision"]), "decision": decision, "reason": reason})
    assert res.status_code == 200, res.text


def test_reextraction_carries_decisions(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    _upload(api, store, pid, TENDER)
    script = {
        "current": _rules_script(
            {
                "工期": ("mandatory", "总工期不超过180日历天"),
                "质量": ("mandatory", "工程质量合格"),
                "安全": ("mandatory", "项目经理常驻现场"),
            }
        )
    }
    llm = ScriptedLlm(lambda s, u: script["current"](s, u))  # noqa: PLW0108 - 每次取最新脚本
    bus = InMemoryBus()
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), build_handlers(llm), consumer_name="worker-parse")
    _drain(runner, bus, engine)

    first = _extract(api, pid, runner, bus, engine)
    assert len(first["rules"]) == 3 and all(r["carried_from_rule_id"] is None for r in first["rules"])
    _review(api, first, "总工期不超过180日历天", "confirm", "与招标一致")
    _review(api, first, "工程质量合格", "reject", "重复条款")
    _review(api, first, "项目经理常驻现场", "defer", "待澄清")
    old_ids = {r["statement"]: r["rule_id"] for r in first["rules"]}

    # 第二次：工期条文仅空白不同（沿用）；质量条文改了（待定）；安全条文换了性质（待定）
    script["current"] = _rules_script(
        {
            "工期": ("mandatory", "总工期 不超过 180 日历天"),
            "质量": ("mandatory", "工程质量必须合格且验收一次通过"),
            "安全": ("recommendation", "项目经理常驻现场"),
        }
    )
    second = _extract(api, pid, runner, bus, engine)
    assert second["revision"] == first["revision"] + 1 and second["status"] == "candidate"
    by = {r["statement"]: r for r in second["rules"]}
    carried = by["总工期 不超过 180 日历天"]
    assert carried["confirmation"] == "confirmed" and carried["carried_from_rule_id"] == old_ids["总工期不超过180日历天"]
    assert (
        by["工程质量必须合格且验收一次通过"]["confirmation"] == "pending"
        and by["工程质量必须合格且验收一次通过"]["carried_from_rule_id"] is None
    )
    assert by["项目经理常驻现场"]["confirmation"] == "pending" and by["项目经理常驻现场"]["carried_from_rule_id"] is None
    with engine.connect() as conn:
        row = db.one(
            conn,
            "SELECT decision,reason,actor_id,object_version FROM reviews WHERE object_id=:o ORDER BY reviewed_at DESC, id DESC LIMIT 1",
            {"o": carried["rule_id"]},
        )
        orig = db.one(conn, "SELECT actor_id FROM reviews WHERE object_id=:o", {"o": old_ids["总工期不超过180日历天"]})
    assert row is not None and orig is not None
    assert row["decision"] == "confirm" and row["reason"] == PREFIX + "与招标一致" and row["actor_id"] == orig["actor_id"]
    assert row["object_version"] == str(second["revision"])

    # 剩余待定的规则可以正常审核，包整体随之确认（沿用的决定计入）
    _review(api, second, "工程质量必须合格且验收一次通过", "reject", "不适用")
    assert api.get(f"/projects/{pid}/rules").json()["status"] == "candidate"
    _review(api, second, "项目经理常驻现场", "confirm", "确认")
    assert api.get(f"/projects/{pid}/rules").json()["status"] == "confirmed"

    # 第三次：条文全部不变，决定一路沿用（原因前缀不叠加），规则包一出生即已确认
    third = _extract(api, pid, runner, bus, engine)
    assert third["status"] == "confirmed" and all(r["confirmation"] != "pending" for r in third["rules"])
    with engine.connect() as conn:
        reasons = db.all_(
            conn,
            "SELECT reason FROM reviews WHERE object_id = ANY(:ids)",
            {"ids": [r["rule_id"] for r in third["rules"]]},
        )
    assert reasons and all(r["reason"].startswith(PREFIX) and not r["reason"].startswith(PREFIX + PREFIX) for r in reasons)
