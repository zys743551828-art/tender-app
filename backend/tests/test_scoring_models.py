"""打分模型 scoring-model/1：公式（自建参考向量与研究侧参考向量）、契约校验、适用范围。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bidwb.ai.features import FEATURES
from bidwb.errors import Unprocessable
from bidwb.services import scoring_models
from tests.fakes import scoring_bundle

# 手算：lin = 70 + 4·(raw−60)/10 + 2·(cov−0.5)/0.25 + 1·(anchor−70)/1（scale 为 0 视为 1），再按 (50,40)(70,70)(90,80) 插值
GOLDEN = [
    ({"raw_pct": 70.0, "coverage_mean": 0.75, "anchor_pct": 72.0}, (74.0, 69.0, 79.0, 66.0, 82.0)),  # lin 78
    ({"raw_pct": 40.0, "coverage_mean": None, "anchor_pct": None}, (58.0, 53.0, 63.0, 50.0, 66.0)),  # lin 62，缺失取填补值
    ({"raw_pct": 100.0, "coverage_mean": 1.0, "anchor_pct": 100.0}, (80.0, 75.0, 85.0, 72.0, 88.0)),  # lin 120，插值两端截平
]


def _features(**values: float | None) -> dict[str, float | None]:
    return {name: values.get(name) for name in FEATURES}


@pytest.mark.parametrize(("values", "expected"), GOLDEN)
def test_apply_matches_hand_computed_vectors(values: dict[str, float | None], expected: tuple[float, ...]) -> None:
    applied = scoring_models.apply(scoring_models.parse_model(scoring_bundle()), _features(**values))
    assert (applied.pct, applied.low80, applied.high80, applied.low90, applied.high90) == pytest.approx(expected, abs=1e-9)


def _research_golden() -> Path:
    configured = os.environ.get("BIDWB_SCORING_GOLDEN")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "tender-research/protocols/scoring-model-1.golden.json"


@pytest.mark.skipif(
    not _research_golden().is_file(), reason="研究侧参考向量文件不在（设置 BIDWB_SCORING_GOLDEN 或放在 ../tender-research）"
)
def test_apply_matches_research_golden_vectors() -> None:
    golden = json.loads(_research_golden().read_text(encoding="utf-8"))
    model = scoring_models.parse_model(golden["bundle"])  # 同时复核 model_id 的算法与研究侧一致
    for vector in golden["vectors"]:
        applied = scoring_models.apply(model, _features(**vector["features"]))
        got = {"pct": applied.pct, "lo80": applied.low80, "hi80": applied.high80, "lo90": applied.low90, "hi90": applied.high90}
        for key, value in vector["expected"].items():
            assert got[key] == pytest.approx(value, abs=1e-9), (vector["features"], key)


def test_missing_indicator_and_open_interval() -> None:
    bundle = scoring_bundle(
        features=["raw_pct", "raw_pct__missing"],
        standardize={"mean": {"raw_pct": 60.0, "raw_pct__missing": 0.0}, "scale": {"raw_pct": 10.0, "raw_pct__missing": 1.0}},
        impute={"raw_pct": 60.0},
        coefficients={"raw_pct": 5.0, "raw_pct__missing": -3.0},
        isotonic=None,
        interval={"0.8": 4.0, "0.9": None},
    )
    model = scoring_models.parse_model(bundle)
    present = scoring_models.apply(model, _features(raw_pct=70.0))
    absent = scoring_models.apply(model, _features())
    assert present.pct == 75.0 and absent.pct == 67.0  # 缺失：取填补值 60，指示列为 1
    assert (absent.low80, absent.high80, absent.low90, absent.high90) == (63.0, 71.0, 0.0, 100.0)  # 半宽为 null 取整个量尺


def test_contract_is_checked() -> None:
    tampered = {**scoring_bundle(), "intercept": 1.0}
    with pytest.raises(Unprocessable) as wrong_id:
        scoring_models.parse_model(tampered)
    assert wrong_id.value.code == "model_id_mismatch"
    for overrides, fragment in (
        ({"feature_spec": "pf-0"}, "feature_spec"),
        ({"features": ["raw_pct", "no_such_feature"]}, "no_such_feature"),
        ({"coefficients": {"raw_pct": 1.0}}, "coefficients"),
        ({"interval": {"0.8": 1.0}}, "interval"),
        ({"isotonic": {"x": [2.0, 1.0], "y": [1.0, 2.0]}}, "isotonic"),
    ):
        with pytest.raises(Unprocessable) as bad:
            scoring_models.parse_model(scoring_bundle(**overrides))
        assert bad.value.code == "invalid_scoring_model" and fragment in bad.value.message, overrides


def test_scope_and_missing_features() -> None:
    model = scoring_models.parse_model(scoring_bundle(scope={"engineering_types": ["市政道路"], "regions": ["安徽省"]}))
    feats = _features(raw_pct=70.0)
    assert scoring_models.out_of_scope_reason(model, feats, engineering_type="市政道路", region="安徽省合肥市") is None  # 省内的市
    city = scoring_models.parse_model(scoring_bundle(scope={"engineering_types": [], "regions": ["安徽省合肥市", "安徽省宣城市"]}))
    for inside in ("合肥", "合肥市", "安徽省", "安徽 宣城", "宣城市"):
        assert scoring_models.out_of_scope_reason(city, feats, engineering_type=None, region=inside) is None, inside
    for outside in ("芜湖", "江苏省南京市", "", None):
        assert scoring_models.out_of_scope_reason(city, feats, engineering_type=None, region=outside), outside
    assert "房建" in (scoring_models.out_of_scope_reason(model, feats, engineering_type="房建", region="安徽省") or "")
    assert "江苏省" in (scoring_models.out_of_scope_reason(model, feats, engineering_type="市政道路", region="江苏省南京市") or "")
    assert "未填写" in (scoring_models.out_of_scope_reason(model, feats, engineering_type="市政道路", region=None) or "")
    no_impute = scoring_models.parse_model(scoring_bundle(impute={}, scope={}))
    assert "coverage_mean" in (scoring_models.out_of_scope_reason(no_impute, feats, engineering_type=None, region=None) or "")
    assert scoring_models.scope_text(no_impute) == "工程类型：不限；地区：不限"
    assert (
        scoring_models.calibrated_reason(model) == "已用 280 组官方成绩校准（留出验证平均绝对误差 3.2 分，满分百分制）；区间约 80% 把握。"
    )


def test_registration_gate() -> None:
    failed = json.dumps(scoring_bundle(evaluation={"n": 50, "mae_pct": 5.0, "verdict": "failed"})).encode()
    with pytest.raises(Unprocessable) as gate:
        scoring_models.registration(failed, b"{}", "business")
    assert gate.value.code == "business_gate_not_met"
    shadow = scoring_models.registration(failed, b"{}", "shadow")  # 影子环境只做对照，不要求通过
    assert shadow.target == "technical_total" and shadow.member_count == 50
    with pytest.raises(Unprocessable):
        scoring_models.registration(b"not json", b"{}", "shadow")


@pytest.mark.parametrize(
    ("mode", "acceptance"), [("cv", {"status": "passed"}), ("holdout", None), ("holdout", {"status": "not_evaluable"})]
)
def test_complete_chapter_business_model_requires_independent_acceptance(mode: str, acceptance: dict[str, str] | None) -> None:
    evaluation = {**scoring_bundle()["evaluation"], "mode": mode, "acceptance": acceptance}
    raw = scoring_bundle(evaluation=evaluation)
    with pytest.raises(Unprocessable) as rejected:
        scoring_models.registration(json.dumps(raw).encode(), b"{}", "business")
    assert rejected.value.code == "business_gate_not_met"
