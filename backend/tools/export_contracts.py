"""由代码生成 contracts/openapi.json，并把项目、规则、评审、预测、报价与度量相关的数据结构写入 contracts/domain.schema.json。

用法：python tools/export_contracts.py        （重写两个文件）
      python tools/export_contracts.py --check （只比对，不一致时以非零状态退出）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bidwb import schemas
from bidwb.api.app import create_app
from bidwb.config import Settings

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "contracts/openapi.json"
DOMAIN = ROOT / "contracts/domain.schema.json"

# 由代码生成的领域结构；其余结构（平台侧的数据集、实验、放行等）在 domain.schema.json 中手工维护
GENERATED = (
    "AnalysisRequest",
    "AssistantRequest",
    "AssistantReply",
    "AssistantCard",
    "UploadRequest",
    "UploadResult",
    "FileVersion",
    "InputSnapshot",
    "WordStatus",
    "WordAdoptRequest",
    "WordRetryRequest",
    "ProjectSettings",
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectOverview",
    "RuleSet",
    "ConfirmRulesRequest",
    "ConfirmRulesResult",
    "Finding",
    "Prediction",
    "Calibration",
    "ScoringModelRef",
    "PredictionTopic",
    "RuleVerdict",
    "VerdictCounts",
    "Compliance",
    "BenchmarkSpec",
    "PriceParams",
    "PricePlanRequest",
    "PricePlan",
    "PricePoint",
    "ExchangeRate",
    "PriceSimulation",
    "PricePlanWithSimulation",
    "PipelineStep",
    "PipelineStatus",
    "CategoryCount",
    "NextAction",
    "ReportBasis",
    "PriceSummary",
    "Report",
    "OutcomeMetrics",
    "QualificationMetrics",
    "RoundPoint",
    "RoundTrend",
    "Metrics",
)


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title" or isinstance(v, dict)}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def build_openapi() -> dict[str, Any]:
    return create_app(Settings(environment="test")).openapi()


def build_domain(current: dict[str, Any]) -> dict[str, Any]:
    defs: dict[str, Any] = dict(current["$defs"])
    for name in GENERATED:
        schema = getattr(schemas, name).model_json_schema(ref_template="#/$defs/{model}", mode="serialization")
        for nested_name, nested in schema.pop("$defs", {}).items():
            if nested_name not in GENERATED:
                defs[nested_name] = _strip_titles(nested)
        defs[name] = _strip_titles(schema)
    return {**current, "$defs": dict(sorted(defs.items(), key=lambda kv: (kv[0] in GENERATED, kv[0])))}


def dump(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = {OPENAPI: dump(build_openapi()), DOMAIN: dump(build_domain(json.loads(DOMAIN.read_text(encoding="utf-8"))))}
    stale = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    if args.check:
        for p in stale:
            print(f"与代码不一致：{p.relative_to(ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    for p in stale:
        p.write_text(outputs[p], encoding="utf-8")
        print(f"已更新 {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
