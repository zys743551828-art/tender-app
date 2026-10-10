"""评分预测处理器：上下文组织、落地校验与汇总（纯函数），以及在真实流水线里的重复判断、回退、打分模型与锚点（真实 PG、脚本化模型）。"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from bidwb.ai import anchors, predict, prompts
from bidwb.ai.grounding import EvidenceText
from bidwb.ai.sections import Section
from bidwb.services import anchor_packs, model_registry, scoring_models
from tests.fakes import ScriptedLlm, docs, scoring_bundle
from tests.test_auto_pipeline import (
    BODY,
    TENDER,
    _env,
    _respond,
    judgement_reply,
    settings,  # noqa: F401  自动评审打开的配置夹具（pytest 按名注入）
)
from tests.test_files_and_parse import _upload


def _section(sid: str, ids: list[str]) -> Section:
    return Section(sid, sid, 1, None, tuple(ids), 0, 1, "")


def test_context_keeps_section_heads_then_fills_by_relevance_in_document_order() -> None:
    body = [EvidenceText(f"e{i}", ("关键线路" if i in (7, 18) else "一般内容") + "。" * 998) for i in range(20)]
    position = {b.evidence_id: i for i, b in enumerate(body)}
    small, cut = predict.item_context("关键线路", [_section("S1", ["e0", "e1"])], body, position)
    assert [b.evidence_id for b in small] == ["e0", "e1"] and not cut
    sections = [_section("S1", [f"e{i}" for i in range(10)]), _section("S2", [f"e{i}" for i in range(10, 20)])]
    picked, cut = predict.item_context("关键线路", sections, body, position)
    ids = [b.evidence_id for b in picked]
    # 开头配额 14000×40%÷2 = 2800 字：每节各取前 2 块；余下篇幅按相关度补，关键线路两块先入选；最后按文档顺序
    assert cut and ids[:2] == ["e0", "e1"] and "e10" in ids and "e11" in ids and "e7" in ids and "e18" in ids
    assert ids == sorted(ids, key=lambda e: position[e]) and sum(len(b.quote) for b in picked) <= predict.CONTEXT_CHARS
    fallback, cut = predict.item_context("关键线路", [], body, position)
    assert [b.evidence_id for b in fallback] == ["e7", "e18"] and not cut  # 没有对应章节：全文检索


def _judgement(**overrides: Any) -> prompts.ItemJudgement:
    raw = judgement_reply('<doc id="b1">本工程计划总工期为一百八十日历天</doc>') | overrides
    return prompts.item_judgement(Decimal(8)).model_validate(raw)


def test_grounding_downgrades_points_without_offered_evidence_and_aggregate_unions_grade_intervals() -> None:
    out = _judgement(
        key_points=[
            {"point": "总工期", "status": "covered", "evidence_ids": ["zz"]},
            {"point": "关键线路", "status": "partial", "evidence_ids": ["b1"]},
        ]
    )
    judged = predict.ground(out, {"b1"}, Decimal(8))
    assert [k["status"] for k in judged.key_points] == ["missing", "partial"] and judged.downgraded == 1 and judged.coverage == 0.25
    assert judged.interval == (Decimal(2), Decimal(6)) and judged.grade_position == 0.5
    other = predict.ground(_judgement(grade=0, score="7"), {"b1"}, Decimal(8))
    rule = {"id": "rul_1", "statement": "进度计划", "basis": "unconfirmed"}
    item = predict.aggregate(rule, Decimal(8), [judged, other], mapped=True, sections=["第一章"], rubric="原文")
    assert (item["estimate"], item["low"], item["high"]) == (Decimal("5.5"), Decimal(2), Decimal(8))  # 均值；得分与档次区间的并集
    assert item["grade_position"] == 0.75 and item["repeat_spread"] == 0.375 and item["scores"] == ["4", "7"]
    failed = predict.aggregate(rule, Decimal(8), [], mapped=False, sections=[], rubric="")
    assert failed["failed"] and (failed["estimate"], failed["low"], failed["high"]) == (Decimal(4), Decimal(0), Decimal(8))


def test_judgement_output_must_be_consistent() -> None:
    with pytest.raises(ValueError, match="区间"):
        _judgement(score="7")  # 判为“良”（2～6）却给 7 分
    with pytest.raises(ValueError, match="满分"):
        _judgement(grades=[], grade=None, score="9")
    with pytest.raises(ValueError, match="从高到低"):
        _judgement(grades=[{"label": "差", "low": "0", "high": "2"}, {"label": "优", "low": "6", "high": "8"}], grade=0, score="1")
    assert _judgement(grades=[], grade=None, score=5).score == "5"  # JSON 数字转成十进制字符串


# ------------------------------------------------------------------ 流水线里的预测
def _detail(env) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    with env.engine.connect() as conn:
        key = conn.exec_driver_sql(
            "SELECT a.object_key FROM predictions p JOIN artifacts a ON a.id=p.detail_artifact_id WHERE p.project_id=%s "
            "ORDER BY p.created_at DESC LIMIT 1",
            (env.pid,),
        ).scalar()
    return dict(json.loads(env.store.get(key)))


def _run(api_factory, make_member, store, engine, worker_container, respond):  # type: ignore[no-untyped-def]
    llm = ScriptedLlm(respond)
    env = _env(api_factory, make_member, store, engine, worker_container, llm)
    _upload(env.api, store, env.pid, TENDER)
    _upload(env.api, store, env.pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")
    env.drain()
    return env, llm


@pytest.mark.integration
def test_repeats_use_temperature_and_fallbacks(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    calls = {"judge": 0}

    def respond(system: str, user: str) -> Any:
        if "目录分析员" in system:
            return {"mapping": [{"item": "R9", "sections": ["S1"]}]}  # 不存在的条款编号：重发后仍不合格 → 整体改用检索
        if "评标专家" in system:
            calls["judge"] += 1
            return {"oops": True} if calls["judge"] <= 3 else judgement_reply(user)  # 第 1 次判断连同 2 次重发都不合格
        return _respond(system, user)

    env, llm = _run(api_factory, make_member, store, engine, worker_container, respond)
    detail = _detail(env)
    (item,) = detail["items"]
    assert detail["mapping"]["status"] == "fallback" and not item["mapped"] and item["sections"] == []
    assert item["repeats_valid"] == 2 and not item["failed"] and detail["coverage"]["invalid_outputs"] == 1
    judge_temps = [t for (s, _), t in zip(llm.calls, llm.temperatures, strict=True) if "评标专家" in s]
    assert judge_temps == [0.0, 0.0, 0.0, 0.7, 0.7]  # 第 1 次（含重发）温度 0，其余升温
    judge_prompt = next(u for s, u in llm.calls if "评标专家" in s)
    assert "按关键词检索" in judge_prompt and any("总工期" in t for _, t in docs(judge_prompt))


@pytest.mark.integration
def test_all_judgements_failing_falls_back_to_half_points(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    def respond(system: str, user: str) -> Any:
        return {"oops": True} if "评标专家" in system else _respond(system, user)

    env, _ = _run(api_factory, make_member, store, engine, worker_container, respond)
    prediction = env.get("/report")["prediction"]
    assert (prediction["estimated_value"], prediction["low"], prediction["high"]) == ("4", "0", "8")
    detail = _detail(env)
    assert detail["coverage"]["status"] == "empty" and detail["items"][0]["failed"] and detail["features"]["failed_share"] == 1


def _register(engine, store, registration, environment) -> model_registry.Registered:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        return model_registry.register(conn, store, registration, environment=environment, reviewer_login="lead")


def _bundle_bytes(**overrides: Any) -> bytes:
    return json.dumps(scoring_bundle(**overrides), ensure_ascii=False).encode()


@pytest.mark.integration
def test_business_model_calibrates_and_shadow_is_recorded(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    llm = ScriptedLlm(_respond)
    env = _env(api_factory, make_member, store, engine, worker_container, llm)
    business = _register(engine, store, scoring_models.registration(_bundle_bytes(), b"{}", "business"), "business")
    shadow_bundle = _bundle_bytes(intercept=60.0)
    _register(engine, store, scoring_models.registration(shadow_bundle, b"{}", "shadow"), "shadow")
    _upload(env.api, store, env.pid, TENDER)
    _upload(env.api, store, env.pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")
    env.drain()
    prediction = env.get("/report")["prediction"]
    # raw_pct 50、要点满足度 0.5、锚点缺失取 70：lin = 70 − 4 = 66 → 插值 64%；技术满分 60 → 38.4（80% 区间 59%～69%）
    assert prediction["validation_status"] == "validated_in_scope" and prediction["purpose"] == "business"
    assert (prediction["estimated_value"], prediction["low"], prediction["high"], prediction["maximum"]) == ("38.4", "35.4", "41.4", "60")
    assert prediction["scoring_model"] == {
        "model_id": scoring_bundle()["model_id"],
        "pairs": 280,
        "mae": "3.2",
        "scope": "工程类型：市政道路；地区：合肥",
    }
    assert prediction["reason"].startswith("已用 280 组官方成绩校准")
    detail = _detail(env)
    assert detail["calibrated"]["state"] == "applied" and detail["calibrated"]["bundle_id"] == business.bundle_id
    assert detail["shadow"]["state"] == "applied" and detail["shadow"]["pct"] != detail["calibrated"]["pct"]
    brief = env.api.get("/projects").json()[0]["summary"]["prediction"]
    assert brief["validation_status"] == "validated_in_scope" and brief["estimated_value"] == "38.4"


@pytest.mark.integration
def test_out_of_scope_model_keeps_the_uncalibrated_estimate(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    env = _env(api_factory, make_member, store, engine, worker_container, ScriptedLlm(_respond))
    bundle = _bundle_bytes(scope={"engineering_types": ["市政道路"], "regions": ["安徽省"]})
    _register(engine, store, scoring_models.registration(bundle, b"{}", "business"), "business")
    _upload(env.api, store, env.pid, TENDER)
    _upload(env.api, store, env.pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")
    env.drain()
    prediction = env.get("/report")["prediction"]
    assert prediction["validation_status"] == "out_of_scope" and prediction["purpose"] == "research" and prediction["scoring_model"] is None
    assert (prediction["estimated_value"], prediction["maximum"]) == ("4", "8") and "合肥" in prediction["reason"]
    assert _detail(env)["calibrated"]["state"] == "out_of_scope"


def _pack(*entries: tuple[str, float, str]) -> bytes:
    raw: dict[str, Any] = {
        "schema": "anchor-pack/1",
        "created_at": "2026-10-01T00:00:00+00:00",
        "anchors": [
            {
                "anchor_id": anchor_id,
                "group_id": f"G-{anchor_id}",
                "body_sha256": f"{n:064x}",
                "engineering_type": "市政道路",
                "technical_pct": pct,
                "sections": [{"id": "S1", "title": "第一章 施工进度计划", "text": text}],
            }
            for n, (anchor_id, pct, text) in enumerate(entries, 1)
        ],
    }
    raw["pack_id"] = anchors.pack_id_of(raw)
    return json.dumps(raw, ensure_ascii=False).encode()


@pytest.mark.integration
def test_routed_anchor_pack_feeds_anchor_features(api_factory, make_member, store, engine, worker_container) -> None:  # type: ignore[no-untyped-def]
    def respond(system: str, user: str) -> Any:
        if "正文 A" in user:  # 与锚点比较：本项目工期超限，比 80 分的锚点差、比 50 分的锚点好
            first = user.split('<doc id="A">', 1)[1]
            anchor_first = "锚点" in first.split("</doc>", 1)[0]
            strong = "优秀锚点" in user
            winner_is_anchor = strong
            return {
                "better": ("A" if anchor_first else "B") if winner_is_anchor else ("B" if anchor_first else "A"),
                "strength": 1.0,
                "reason": "比较",
            }
        return _respond(system, user)

    env = _env(api_factory, make_member, store, engine, worker_container, ScriptedLlm(respond))
    pack = _pack(("A1", 50.0, "锚点：施工进度计划粗略"), ("A2", 80.0, "优秀锚点：施工进度计划详尽，关键线路清晰"))
    _register(engine, store, anchor_packs.registration(pack, None), "shadow")
    _upload(env.api, store, env.pid, TENDER)
    _upload(env.api, store, env.pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")
    env.drain()
    detail = _detail(env)
    summary = detail["anchors"]
    assert summary["environment"] == "shadow" and summary["n"] == 2
    assert [c["target_position"] for c in summary["comparisons"]] == ["A", "B"]
    assert {c["anchor_id"]: c["better"] for c in summary["comparisons"]} == {"A1": "target", "A2": "anchor"}
    assert (
        detail["features"]["anchor_pct"] == pytest.approx(65.0)
        and detail["features"]["anchor_agree"] == 1
        and detail["features"]["anchor_n"] == 2
    )
