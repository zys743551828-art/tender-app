"""报价模拟：按招标文件的评标价规则，计算不同报价下的价格分。

纯函数，不读库、不调模型。金额与分数一律用 ``Decimal``，对外输出去掉多余小数零的字符串。
评标价得分规则按行业通行写法建模：以评标基准价为准，报价每高于基准价 1% 扣若干分，每低于 1% 扣若干分，
扣到 0 分为止；基准价可以是固定值，也可以是各投标人报价的平均值（可去掉最高、最低各一定比例）乘以系数。
本模块不涉及任何成本口径：投标人的内部成本不属于本系统的管理范围。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext

from bidwb.schemas import BenchmarkSpec, ExchangeRate, PriceParams, PricePoint, PriceSimulation
from bidwb.util import decimal_text

_HUNDRED = Decimal(100)
_SCORE_PLACES = Decimal("0.0001")
_PCT_PLACES = Decimal("0.01")
_CURVE_POINTS = 41


def benchmark_price(spec: BenchmarkSpec, competitors: Sequence[Decimal], own: Decimal | None = None) -> Decimal | None:
    """评标基准价。平均值法没有任何可用报价时返回 None；``include_own`` 时己方报价计入平均。"""
    coefficient = Decimal(spec.coefficient)
    if spec.method == "fixed":
        assert spec.fixed_value is not None
        return Decimal(spec.fixed_value) * coefficient
    prices = sorted([*competitors, *([own] if spec.include_own and own is not None else [])])
    if not prices:
        return None
    if spec.method == "trimmed_average":
        drop = int(len(prices) * Decimal(spec.trim_pct) / _HUNDRED)  # 各去掉 trim_pct% 的最高与最低报价，至少保留一个
        drop = min(drop, (len(prices) - 1) // 2)
        prices = prices[drop : len(prices) - drop]
    return sum(prices, Decimal(0)) / len(prices) * coefficient


def price_score(price: Decimal, benchmark: Decimal, params: PriceParams) -> Decimal:
    deviation = (price - benchmark) / benchmark * _HUNDRED
    rate = Decimal(params.above_deduct_per_pct) if deviation > 0 else Decimal(params.below_deduct_per_pct)
    score = Decimal(params.full_score) - abs(deviation) * rate
    return max(Decimal(0), min(Decimal(params.full_score), score))


def _point(price: Decimal, params: PriceParams, competitors: Sequence[Decimal]) -> PricePoint | None:
    bench = benchmark_price(params.benchmark, competitors, price)
    if bench is None:
        return None
    deviation = (price - bench) / bench * _HUNDRED
    flags: list[str] = []
    if params.max_limit is not None and price > Decimal(params.max_limit):
        flags.append("over_max_limit")
    if params.abnormal_low_pct is not None and deviation < -Decimal(params.abnormal_low_pct):
        flags.append("abnormal_low")
    return PricePoint(
        price=decimal_text(price) or "0",
        deviation_pct=decimal_text(deviation.quantize(_PCT_PLACES, ROUND_HALF_UP)) or "0",
        score=decimal_text(price_score(price, bench, params).quantize(_SCORE_PLACES, ROUND_HALF_UP)) or "0",
        flags=flags,
    )


def _curve_prices(candidates: Sequence[Decimal], competitors: Sequence[Decimal], bench: Decimal | None) -> list[Decimal]:
    known = [*candidates, *competitors, *([bench] if bench is not None else [])]
    low, high = min(known) * Decimal("0.9"), max(known) * Decimal("1.1")
    step = (high - low) / (_CURVE_POINTS - 1)
    return [low + step * i for i in range(_CURVE_POINTS)]


def simulate(params: PriceParams, competitor_prices: Sequence[str], candidate_prices: Sequence[str]) -> PriceSimulation:
    with localcontext() as ctx:
        ctx.prec = 80  # 输入至多 24 个字符（见 schemas），偏差百分比与分数在此精度下量化不会溢出
        return _simulate(params, competitor_prices, candidate_prices)


def _simulate(params: PriceParams, competitor_prices: Sequence[str], candidate_prices: Sequence[str]) -> PriceSimulation:
    competitors = [Decimal(p) for p in competitor_prices]
    candidates = [Decimal(p) for p in candidate_prices]
    bench = benchmark_price(params.benchmark.model_copy(update={"include_own": False}), competitors)
    above = Decimal(params.above_deduct_per_pct)
    rate = ExchangeRate(
        points_per_pct_above=decimal_text(above) or "0",
        pct_per_point_above=decimal_text((Decimal(1) / above).quantize(_SCORE_PLACES, ROUND_HALF_UP)) if above > 0 else None,
    )
    notes: list[str] = []
    if params.benchmark.method != "fixed":
        notes.append("平均值法的基准价取决于其他投标人的报价，竞争对手报价只是估计，实际基准价以开标为准。")
    if params.benchmark.method != "fixed" and not competitors and not params.benchmark.include_own:
        notes.append("没有竞争对手报价，无法计算基准价；请先填写竞争对手报价的估计。")
    points = [p for p in (_point(c, params, competitors) for c in candidates) if p is not None]
    has_range = bool(candidates or competitors or bench is not None)
    curve = (
        [p for p in (_point(c, params, competitors) for c in _curve_prices(candidates, competitors, bench)) if p is not None]
        if has_range
        else []
    )
    eligible = [p for p in points if not p.flags]
    best = max(eligible, key=lambda p: Decimal(p.score)) if eligible else None
    if points and not eligible:
        notes.append("所有候选报价都触发了风险提示（超过最高限价或低于异常低价线）。")
    return PriceSimulation(benchmark=decimal_text(bench), exchange_rate=rate, candidates=points, curve=curve, best=best, notes=notes)
