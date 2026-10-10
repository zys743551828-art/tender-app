"""特征定义 pf-1：手算对照。"""

from __future__ import annotations

import math

import pytest

from bidwb.ai.features import FEATURES, ItemFacts, RoundFacts, compute

FACTS = RoundFacts(
    technical_full_score=60,
    body_pages=120,
    body_chars=50000,
    qualification_violated=1,
    qualification_unclear=2,
    findings_consistency=3,
    findings_scope=0,
)


def test_features_by_hand() -> None:
    items = [
        # 10 分：判为三档里的中档（位置 0.5），要点满足度 0.75，针对性 0.8，重复分差 1 分
        ItemFacts(10, 6, 5, 8, False, True, grade_position=0.5, coverage=0.75, specificity=0.8, repeat_spread=0.1),
        # 5 分：单档（位置 1），要点满足度 0.5，针对性 0.2，重复无分差
        ItemFacts(5, 4, 4, 5, False, False, grade_position=1.0, coverage=0.5, specificity=0.2, repeat_spread=0.0),
        # 5 分：评估失败，按满分一半、0 到满分计入
        ItemFacts(5, 2.5, 0, 5, True, True),
    ]
    f = compute(items, FACTS)
    assert tuple(f) == FEATURES
    assert f["raw_pct"] == pytest.approx((6 + 4 + 2.5) / 20 * 100)
    assert f["low_pct"] == pytest.approx(9 / 20 * 100) and f["high_pct"] == pytest.approx(18 / 20 * 100)
    assert f["width_pct"] == pytest.approx(45.0)
    assert f["grade_mean"] == pytest.approx((10 * 0.5 + 5 * 1.0) / 15, abs=1e-6)  # 失败条款不参与
    assert f["coverage_mean"] == pytest.approx((10 * 0.75 + 5 * 0.5) / 15, abs=1e-6) and f["coverage_min"] == 0.5
    assert f["specificity_mean"] == pytest.approx((10 * 0.8 + 5 * 0.2) / 15, abs=1e-6)
    assert f["repeat_spread_pct"] == pytest.approx((10 * 0.1 + 0) / 15 * 100, abs=1e-4)
    assert f["failed_share"] == 0.25 and f["mapped_share"] == 0.75 and f["items_count"] == 3
    assert f["max_ratio"] == pytest.approx(20 / 60, abs=1e-6) and f["body_pages"] == 120
    assert f["body_chars_log"] == pytest.approx(math.log(1 + 50000), abs=1e-6)
    assert (f["qualification_violated"], f["qualification_unclear"], f["findings_consistency"], f["findings_scope"]) == (1, 2, 3, 0)
    assert f["anchor_pct"] is None and f["anchor_agree"] is None and f["anchor_n"] is None


def test_unknowns_are_explicit_nulls() -> None:
    f = compute([], RoundFacts(None, None, 0, 0, 0, 0, 0, anchor_pct=55.5, anchor_agree=0.75, anchor_n=8))
    assert tuple(f) == FEATURES
    for key in ("raw_pct", "low_pct", "high_pct", "width_pct", "grade_mean", "coverage_mean", "coverage_min", "max_ratio", "body_pages"):
        assert f[key] is None, key
    assert f["items_count"] == 0 and f["body_chars_log"] == 0 and (f["anchor_pct"], f["anchor_agree"], f["anchor_n"]) == (55.5, 0.75, 8)
    no_grades = compute([ItemFacts(8, 4, 2, 6, False, True, coverage=1.0)], FACTS)
    assert no_grades["grade_mean"] is None and no_grades["coverage_mean"] == 1.0
