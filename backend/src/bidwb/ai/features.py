"""评分预测的特征（特征定义 ``pf-1``）：产品与研究共用的唯一定义。

打分模型（``services.scoring_models``）读的就是这里算出的数值；研究侧训练时用系统批量预测输出的同一组特征。
任何一项的含义变化都必须换一个特征定义编号，否则已登记的模型会被喂进含义不同的数。

约定：分值类特征按满分百分制；“均值”一律按条款满分加权（分值大的条款更能决定总分）；
评估失败的条款只计入 raw/low/high（按满分一半、0 到满分全幅）与 failed_share，不参与档次、要点、针对性与重复分差的均值。
没有条件计算的特征为 ``None``（如没有档次的条款、没有技术满分、没有做锚点比较），由模型的缺失值填补处理。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

FEATURE_SPEC = "pf-1"
FEATURES = (
    "raw_pct",
    "low_pct",
    "high_pct",
    "width_pct",
    "grade_mean",
    "coverage_mean",
    "coverage_min",
    "specificity_mean",
    "repeat_spread_pct",
    "failed_share",
    "mapped_share",
    "items_count",
    "max_ratio",
    "body_pages",
    "body_chars_log",
    "qualification_violated",
    "qualification_unclear",
    "findings_consistency",
    "findings_scope",
    "anchor_pct",
    "anchor_agree",
    "anchor_n",
)


@dataclass(frozen=True)
class ItemFacts:
    """一条评分条款的汇总结果（分数为该条款的分值）。"""

    max_points: float
    estimate: float
    low: float
    high: float
    failed: bool
    mapped: bool
    grade_position: float | None = None  # 所定档次在档次表中的相对位置：最高档 1，最低档 0；无档次为 None
    coverage: float | None = None  # 得分要点满足度：covered 1、partial 0.5、missing 0 的均值
    specificity: float | None = None
    repeat_spread: float | None = None  # 重复判断的分差占该条款满分的比例


@dataclass(frozen=True)
class RoundFacts:
    """条款之外、同一轮评审里的事实。"""

    technical_full_score: float | None
    body_pages: int | None
    body_chars: int
    qualification_violated: int
    qualification_unclear: int
    findings_consistency: int
    findings_scope: int
    anchor_pct: float | None = None
    anchor_agree: float | None = None
    anchor_n: int | None = None


Features = dict[str, float | None]


def _weighted(items: Sequence[ItemFacts], value: Callable[[ItemFacts], float | None]) -> float | None:
    pairs = [(i.max_points, v) for i in items if not i.failed and (v := value(i)) is not None]
    weight = sum(w for w, _ in pairs)
    return sum(w * v for w, v in pairs) / weight if weight > 0 else None


def compute(items: Sequence[ItemFacts], facts: RoundFacts) -> Features:
    """全部 ``FEATURES``，键齐全、值为浮点或 ``None``。"""
    total = sum(i.max_points for i in items)

    def pct(key: Callable[[ItemFacts], float]) -> float | None:
        return sum(key(i) for i in items) / total * 100 if total > 0 else None

    def share(selected: Callable[[ItemFacts], bool]) -> float | None:
        return sum(i.max_points for i in items if selected(i)) / total if total > 0 else None

    raw, low, high = pct(lambda i: i.estimate), pct(lambda i: i.low), pct(lambda i: i.high)
    spread = _weighted(items, lambda i: i.repeat_spread)
    coverages = [i.coverage for i in items if not i.failed and i.coverage is not None]
    full = facts.technical_full_score
    out: Features = {
        "raw_pct": raw,
        "low_pct": low,
        "high_pct": high,
        "width_pct": high - low if high is not None and low is not None else None,
        "grade_mean": _weighted(items, lambda i: i.grade_position),
        "coverage_mean": _weighted(items, lambda i: i.coverage),
        "coverage_min": min(coverages) if coverages else None,
        "specificity_mean": _weighted(items, lambda i: i.specificity),
        "repeat_spread_pct": spread * 100 if spread is not None else None,
        "failed_share": share(lambda i: i.failed),
        "mapped_share": share(lambda i: i.mapped),
        "items_count": float(len(items)),
        "max_ratio": total / full if full and total > 0 else None,
        "body_pages": float(facts.body_pages) if facts.body_pages is not None else None,
        "body_chars_log": math.log1p(facts.body_chars),
        "qualification_violated": float(facts.qualification_violated),
        "qualification_unclear": float(facts.qualification_unclear),
        "findings_consistency": float(facts.findings_consistency),
        "findings_scope": float(facts.findings_scope),
        "anchor_pct": facts.anchor_pct,
        "anchor_agree": facts.anchor_agree,
        "anchor_n": float(facts.anchor_n) if facts.anchor_n is not None else None,
    }
    assert tuple(out) == FEATURES
    return {k: (round(v, 6) if v is not None else None) for k, v in out.items()}
