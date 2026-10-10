"""打分模型（契约 ``scoring-model/1``）：研究侧用官方成绩训练、产品侧读取并应用。

模型把一轮评审的特征（``ai.features``，定义 ``pf-1``）映射为技术分占满分的百分比及 80%、90% 区间：

    z = (x − mean) / scale（scale 为 0 视为 1；缺失值先用 impute 填补；名为 ``<特征>__missing`` 的列是缺失指示：原特征缺失为 1，否则 0）
    y = intercept + Σ coef · z（按 ``features`` 的顺序累加）
    有 isotonic 时对 y 做分段线性插值（两端截平），再截到 clip（[0, 100]）
    区间 = y ± interval 半宽，再截到 clip；半宽为 null 表示该把握下给不出区间，取整个 clip 量尺

适用范围：``scope.engineering_types`` 非空时项目的工程类型必须在列；``scope.regions``（训练数据里出现过的完整地区，
如“安徽省合肥市”）非空时，项目地区去掉省、市、县、区等行政区划字后，与其中某项互相包含即适用（“合肥”“安徽省”都算在
“安徽省合肥市”内）；模型用到的特征缺失且没有填补值时不适用。不适用时如实标为 ``out_of_scope``，界面显示未校准的逐项评估。

``model_id`` 是去掉 ``model_id`` 字段后规范 JSON（键排序、无空白、UTF-8）的 SHA-256，登记时复核。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bidwb.ai.features import FEATURE_SPEC, FEATURES, Features
from bidwb.errors import Unprocessable
from bidwb.services.model_registry import TARGET_SCORING, Environment, Registration
from bidwb.util import canonical_json, sha256_hex

SCHEMA = "scoring-model/1"
_DIVISION = re.compile(r"特别行政区|自治区|自治州|地区|省|市|盟|县|区|旗")
SCOPE_REGIONS_SHOWN = 6
MISSING_SUFFIX = "__missing"
_Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


class Standardize(_Contract):
    mean: dict[str, float]
    scale: dict[str, float]


class Isotonic(_Contract):
    x: Annotated[list[float], Field(min_length=2)]
    y: Annotated[list[float], Field(min_length=2)]

    @model_validator(mode="after")
    def _monotone(self) -> Isotonic:
        if len(self.x) != len(self.y):
            raise ValueError("isotonic.x 与 isotonic.y 长度必须相同")
        if any(b <= a for a, b in zip(self.x, self.x[1:], strict=False)):
            raise ValueError("isotonic.x 必须严格递增")
        if any(b < a for a, b in zip(self.y, self.y[1:], strict=False)):
            raise ValueError("isotonic.y 必须单调不减")
        return self


class Scope(_Contract):
    engineering_types: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)


class Evaluation(BaseModel):
    """研究侧的评估摘要。产品只用其中几项（样本数、误差、放行结论），其余原样保留。"""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    n: Annotated[int, Field(ge=1)]
    projects: int | None = None
    mae_pct: Annotated[float, Field(ge=0)]
    verdict: str
    mode: str | None = None


class ScoringModel(_Contract):
    schema_: Annotated[Literal["scoring-model/1"], Field(alias="schema")]
    model_id: _Sha
    target: Literal["technical_total"]
    feature_spec: str
    method: Annotated[str, Field(min_length=1)]
    features: Annotated[list[str], Field(min_length=1)]
    standardize: Standardize
    impute: dict[str, float] = Field(default_factory=dict)
    coefficients: dict[str, float]
    intercept: float
    isotonic: Isotonic | None = None
    output: Literal["technical_percent_of_max"]
    clip: tuple[float, float] = (0.0, 100.0)
    interval: dict[str, Annotated[float, Field(ge=0)] | None]
    scope: Scope = Field(default_factory=Scope)
    evaluation: Evaluation
    data_sha256: str
    code_sha256: str
    created_at: datetime

    @model_validator(mode="after")
    def _coherent(self) -> ScoringModel:
        if self.feature_spec != FEATURE_SPEC:
            raise ValueError(f"feature_spec 必须是本系统的特征定义 {FEATURE_SPEC}")
        if unknown := [f for f in self.features if base_feature(f) not in FEATURES]:
            raise ValueError(f"未定义的特征：{'、'.join(unknown)}")
        if len(set(self.features)) != len(self.features):
            raise ValueError("features 有重复")
        for name, table in (("standardize.mean", self.standardize.mean), ("standardize.scale", self.standardize.scale)):
            if missing := [f for f in self.features if f not in table]:
                raise ValueError(f"{name} 缺少 {'、'.join(missing)}")
        if missing := [f for f in self.features if f not in self.coefficients]:
            raise ValueError(f"coefficients 缺少 {'、'.join(missing)}")
        if extra := sorted(set(self.impute) - {f for f in self.features if not f.endswith(MISSING_SUFFIX)}):
            raise ValueError(f"impute 含未使用的特征 {'、'.join(extra)}")
        if not {"0.8", "0.9"} <= set(self.interval):
            raise ValueError('interval 必须给出 "0.8" 与 "0.9" 的半宽')
        if not 0 <= self.clip[0] < self.clip[1] <= 100:
            raise ValueError("clip 必须在 [0, 100] 内且下限小于上限")
        return self


def base_feature(name: str) -> str:
    return name.removesuffix(MISSING_SUFFIX)


def model_id_of(raw: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({k: v for k, v in raw.items() if k != "model_id"}))


def parse_model(raw: Any) -> ScoringModel:
    """按契约校验并复核 ``model_id``；不合格抛 ``Unprocessable``。"""
    if not isinstance(raw, dict):
        raise Unprocessable("invalid_scoring_model", "打分模型必须是 JSON 对象")
    try:
        model = ScoringModel.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise Unprocessable("invalid_scoring_model", f"打分模型不符合 {SCHEMA}：{'.'.join(map(str, first['loc']))} {first['msg']}") from exc
    if model.model_id != model_id_of(raw):
        raise Unprocessable("model_id_mismatch", "model_id 与内容不符（应为去掉 model_id 后规范 JSON 的 SHA-256）")
    return model


# ------------------------------------------------------------------ 应用
@dataclass(frozen=True)
class Applied:
    """百分制（技术分占满分的百分比）。"""

    pct: float
    low80: float
    high80: float
    low90: float
    high90: float


def _interp(value: float, xs: list[float], ys: list[float]) -> float:
    if value <= xs[0]:
        return ys[0]
    if value >= xs[-1]:
        return ys[-1]
    for (x0, y0), (x1, y1) in zip(zip(xs, ys, strict=True), zip(xs[1:], ys[1:], strict=True), strict=True):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return ys[-1]


def missing_features(model: ScoringModel, features: Features) -> list[str]:
    """模型要用、本轮没有、也没有填补值的特征（缺失指示列不算）。"""
    return [f for f in model.features if not f.endswith(MISSING_SUFFIX) and features.get(f) is None and f not in model.impute]


def _value(model: ScoringModel, features: Features, name: str) -> float:
    if name.endswith(MISSING_SUFFIX):
        return 1.0 if features.get(base_feature(name)) is None else 0.0
    value = features.get(name)
    return model.impute[name] if value is None else value


def apply(model: ScoringModel, features: Features) -> Applied:
    """按模块说明里的公式计算；调用方须先确认 ``missing_features`` 为空。运算顺序与研究侧一致，结果逐位可比。"""
    y = model.intercept
    for name in model.features:
        z = (_value(model, features, name) - model.standardize.mean[name]) / (model.standardize.scale[name] or 1.0)
        y += model.coefficients[name] * z
    if model.isotonic is not None:
        y = _interp(y, model.isotonic.x, model.isotonic.y)
    lo, hi = model.clip

    def clip(v: float) -> float:
        return min(max(v, lo), hi)

    y = clip(y)

    def bounds(level: str) -> tuple[float, float]:
        half = model.interval[level]
        return (lo, hi) if half is None else (clip(y - half), clip(y + half))

    (lo80, hi80), (lo90, hi90) = bounds("0.8"), bounds("0.9")
    return Applied(y, lo80, hi80, lo90, hi90)


def _place(region: str) -> str:
    return _DIVISION.sub("", re.sub(r"\s+", "", region))


def region_in_scope(region: str | None, regions: list[str]) -> bool:
    """项目地区与训练地区按地名互相包含判断（行政区划字不参与比较）。"""
    place = _place(region or "")
    return bool(place) and any(place in other or other in place for other in map(_place, regions) if other)


def _regions_text(regions: list[str]) -> str:
    shown = "、".join(regions[:SCOPE_REGIONS_SHOWN])
    return f"{shown}等 {len(regions)} 处" if len(regions) > SCOPE_REGIONS_SHOWN else shown


def scope_text(model: ScoringModel) -> str:
    types = "、".join(model.scope.engineering_types) or "不限"
    regions = _regions_text(model.scope.regions) or "不限"
    return f"工程类型：{types}；地区：{regions}"


def out_of_scope_reason(model: ScoringModel, features: Features, *, engineering_type: str | None, region: str | None) -> str | None:
    """不适用的原因；适用时为 ``None``。"""
    types, regions = model.scope.engineering_types, model.scope.regions
    if types and engineering_type not in types:
        return f"项目工程类型为“{engineering_type or '未填写'}”，打分模型只适用于{'、'.join(types)}"
    if regions and not region_in_scope(region, regions):
        return f"项目地区为“{region or '未填写'}”，打分模型只适用于{_regions_text(regions)}"
    if missing := missing_features(model, features):
        return f"本轮评审缺少打分模型需要的特征（{'、'.join(missing)}）"
    return None


_MODE_LABELS = {"holdout": "留出验证", "cv": "交叉验证", "cross_validation": "交叉验证", "grouped_cv": "分组交叉验证"}


def calibrated_reason(model: ScoringModel) -> str:
    mae = f"{model.evaluation.mae_pct:.2f}".rstrip("0").rstrip(".")
    mode = _MODE_LABELS.get(model.evaluation.mode or "", "验证")
    return f"已用 {model.evaluation.n} 组官方成绩校准（{mode}平均绝对误差 {mae} 分，满分百分制）；区间约 80% 把握。"


# ------------------------------------------------------------------ 登记
def registration(bundle_bytes: bytes, report_bytes: bytes, environment: Environment) -> Registration:
    """校验模型与评估报告，组装登记内容。业务环境只接受评估结论为 passed 的模型。"""
    try:
        raw = json.loads(bundle_bytes)
        json.loads(report_bytes)
    except ValueError as exc:
        raise Unprocessable("invalid_json", "模型或评估报告不是合法的 JSON") from exc
    model = parse_model(raw)
    if environment == "business" and model.evaluation.verdict != "passed":
        raise Unprocessable("business_gate_not_met", f"业务环境只接受评估结论为 passed 的模型（本模型为 {model.evaluation.verdict}）")
    protocol = model.evaluation.model_extra.get("protocol_sha256") if model.evaluation.model_extra else None
    return Registration(
        target=TARGET_SCORING,
        schema=SCHEMA,
        identity=model.model_id,
        payload=bundle_bytes,
        components=raw,
        report=report_bytes,
        report_contract="scoring-model-report",
        method=model.method,
        code_sha256=model.code_sha256,
        protocol=str(protocol or SCHEMA),
        member_count=model.evaluation.n,
        grouping="project|template|body",
        created_at=model.created_at,
        scope_text=scope_text(model),
    )
