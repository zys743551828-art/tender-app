"""比较式锚定：选锚点、选条款、位置偏差的映射、Bradley–Terry 拟合、无锚点包时跳过、锚点包契约。"""

from __future__ import annotations

from typing import Any

import pytest

from bidwb.ai import anchors, prompts
from bidwb.ai.anchors import Anchor, ItemForComparison, LoadedPack, Observation
from bidwb.ai.grounding import EvidenceText
from bidwb.ai.llm import Usage
from tests.fakes import ScriptedLlm


def anchor(n: int, pct: float, *, kind: str = "市政道路", scheme: str | None = "综合评估法", group: str | None = None, **kw: Any) -> Anchor:
    return Anchor(
        anchor_id=f"A{n:02d}",
        group_id=group or f"G{n}",
        body_sha256=f"{n:064x}",
        engineering_type=kind,
        scoring_scheme=scheme,
        technical_pct=pct,
        sections=[{"id": "S1", "title": "第一章 施工进度计划", "text": "总工期安排与关键线路说明，劳动力计划。"}],
        **kw,
    )


def test_selection_prefers_same_type_then_scheme_and_spreads_over_quantiles() -> None:
    pool = [anchor(i, 50 + i * 5) for i in range(1, 9)]  # 55…90，同类型同办法
    pool += [anchor(20, 99, kind="房建"), anchor(21, 52, scheme="经评审的最低价法")]
    chosen = anchors.select_anchors(pool, 3, body_sha256="f" * 64, engineering_type="市政道路", scoring_scheme="综合评估法")
    # 分位 1/4、2/4、3/4 → 63.75、72.5、81.25 → 最近的 65、70（与 75 等距时取较低）、80
    assert [a.technical_pct for a in chosen] == [65, 70, 80]
    again = anchors.select_anchors(list(reversed(pool)), 3, body_sha256="f" * 64, engineering_type="市政道路", scoring_scheme="综合评估法")
    assert [a.anchor_id for a in again] == [a.anchor_id for a in chosen]  # 与输入顺序无关
    # 同类型同办法不够时依次放宽；与本项目正文相同的锚点永远不选
    few = anchors.select_anchors(pool, 9, body_sha256=f"{1:064x}", engineering_type="市政道路", scoring_scheme="综合评估法")
    assert "A01" not in {a.anchor_id for a in few} and len(few) == 9 and {a.anchor_id for a in few} >= {"A21"}
    assert anchors.select_anchors(pool, 0, body_sha256="", engineering_type=None, scoring_scheme=None) == []


def test_items_cover_seventy_percent_of_points_at_most_six() -> None:
    assert anchors.select_items([10, 30, 5, 20, 35]) == [4, 1, 3]  # 35+30=65 < 70，再加 20
    assert len(anchors.select_items([1.0] * 10)) == 6


def test_bradley_terry_fit_finds_the_known_optimum() -> None:
    tau = 6.0
    symmetric = [Observation(60, "target", 1.0), Observation(80, "anchor", 1.0)]
    assert anchors.fit(symmetric, tau) == pytest.approx(70.0)
    assert anchors.agreement(70.0, symmetric) == 1.0
    similar = [Observation(64.3, "similar", 0.5)]
    assert anchors.fit(similar, tau) == pytest.approx(64.3)
    lopsided = [Observation(60, "target", 1.0), Observation(80, "anchor", 0.25)]
    s = anchors.fit(lopsided, tau)
    assert s is not None and s > 70  # 赢得更有把握，估计偏向更高
    grid = [anchors.log_likelihood(x / 10, lopsided, tau) for x in range(1001)]
    assert grid.index(max(grid)) / 10 == s
    assert anchors.fit([], tau) is None


def test_position_alternates_and_maps_back() -> None:
    seen: list[str] = []

    def respond(system: str, user: str) -> Any:
        seen.append(user)
        target_is_a = "本项目正文" in user.split('<doc id="A">', 1)[1].split("</doc>", 1)[0]
        return {"better": "A" if target_is_a else "B", "strength": 1.0, "reason": "本项目要点更全"}  # 模型总认为本项目更好

    pack = LoadedPack("p" * 64, "business", (anchor(1, 60), anchor(2, 70), anchor(3, 80)))
    item = ItemForComparison(
        "rul_1", "施工进度计划合理可行", 8.0, [EvidenceText("t1", "进度计划合理的得8分")], [EvidenceText("b1", "本项目正文：总工期安排")]
    )
    result = anchors.compare(
        ScriptedLlm(respond),
        pack,
        [item],
        m=3,
        tau=6.0,
        body_sha256="f" * 64,
        engineering_type="市政道路",
        usage=Usage(),
        checkpoint=lambda: None,
    )
    assert [c["target_position"] for c in result.comparisons] == ["A", "B", "A"]
    assert {c["better"] for c in result.comparisons} == {"target"} and result.n == 3
    assert result.pct == 100.0 and result.agree == 1.0  # 全胜：估计落在量尺上端
    assert all(prompts.COMPARISON_SYSTEM for _ in seen) and len(seen) == 3


def test_item_scores_are_used_when_the_rubric_matches() -> None:
    a = anchor(1, 60, items=[{"item": "施工进度计划合理可行", "pct": 90}, {"item": "质量保证措施", "pct": 40}])
    assert anchors.anchor_item_pct(a, "施工进度计划合理可行，关键线路清晰") == (90, True)
    assert anchors.anchor_item_pct(a, "安全文明施工措施") == (60, False)


def test_pack_contract() -> None:
    raw = {"schema": "anchor-pack/1", "created_at": "2026-10-01T00:00:00+00:00", "anchors": [anchor(1, 60).model_dump(mode="json")]}
    raw["pack_id"] = anchors.pack_id_of(raw)
    assert anchors.parse_pack(raw).anchors[0].anchor_id == "A01"
    with pytest.raises(anchors.PackError, match="pack_id"):
        anchors.parse_pack({**raw, "created_at": "2026-10-02T00:00:00+00:00"})
    with pytest.raises(anchors.PackError, match="anchor_id"):
        dup = {**raw, "anchors": raw["anchors"] * 2}
        anchors.parse_pack({**dup, "pack_id": anchors.pack_id_of(dup)})
