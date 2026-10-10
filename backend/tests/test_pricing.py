"""报价模拟：基准价取法、价格分扣分、风险提示与候选择优。"""

from __future__ import annotations

from bidwb import pricing
from bidwb.schemas import BenchmarkSpec, PriceParams


def _params(**kw: object) -> PriceParams:
    base: dict[str, object] = {
        "full_score": "30",
        "above_deduct_per_pct": "1",
        "below_deduct_per_pct": "0.5",
        "benchmark": {"method": "average", "coefficient": "1"},
    }
    return PriceParams.model_validate({**base, **kw})


def test_average_benchmark_and_score_by_deviation() -> None:
    sim = pricing.simulate(_params(), ["9800", "10000", "10200"], ["10000", "10300", "9700"])
    assert sim.benchmark == "10000"
    by_price = {c.price: c for c in sim.candidates}
    assert by_price["10000"].score == "30" and by_price["10000"].deviation_pct == "0"
    assert by_price["10300"].score == "27" and by_price["10300"].deviation_pct == "3"  # 高于基准 3%，每 1% 扣 1 分
    assert by_price["9700"].score == "28.5"  # 低于基准 3%，每 1% 扣 0.5 分
    assert sim.best is not None and sim.best.price == "10000"
    assert sim.exchange_rate.points_per_pct_above == "1" and sim.exchange_rate.pct_per_point_above == "1"
    assert len(sim.curve) == 41


def test_trimmed_average_drops_extremes_and_coefficient_applies() -> None:
    spec = BenchmarkSpec(method="trimmed_average", trim_pct="20", coefficient="0.98")
    # 5 个报价各去掉 20%（1 个）最高与最低，剩 3 个：平均 100，乘 0.98
    assert pricing.benchmark_price(spec, [*map(pricing.Decimal, ["50", "99", "100", "101", "500"])]) == pricing.Decimal("98")


def test_fixed_benchmark_and_include_own_price() -> None:
    fixed = _params(benchmark={"method": "fixed", "fixed_value": "8000", "coefficient": "1"})
    assert pricing.simulate(fixed, [], ["8000"]).benchmark == "8000"
    own = _params(benchmark={"method": "average", "include_own": True})
    sim = pricing.simulate(own, ["100"], ["200"])  # 己方计入平均：基准 150，己方高于基准 33.33%
    assert sim.candidates[0].deviation_pct == "33.33"


def test_risk_flags_exclude_candidates_from_best() -> None:
    sim = pricing.simulate(_params(max_limit="10500", abnormal_low_pct="10"), ["10000", "10000"], ["10600", "8800", "9900"])
    flags = {c.price: c.flags for c in sim.candidates}
    assert flags["10600"] == ["over_max_limit"] and flags["8800"] == ["abnormal_low"] and flags["9900"] == []
    assert sim.best is not None and sim.best.price == "9900"


def test_score_is_clamped_at_zero() -> None:
    sim = pricing.simulate(_params(above_deduct_per_pct="5"), ["100"], ["200"])
    assert sim.candidates[0].score == "0"


def test_average_without_prices_explains_instead_of_guessing() -> None:
    sim = pricing.simulate(_params(), [], ["100"])
    assert sim.benchmark is None and sim.candidates == [] and any("没有竞争对手报价" in n for n in sim.notes)
