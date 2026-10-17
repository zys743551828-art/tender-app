"""测试用模型：按提示词内容返回预设 JSON，并记录每次调用。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from bidwb.ai.llm import LlmResult, Usage

DOC = re.compile(r'<doc id="([^"]+)">(.*?)</doc>', re.S)


def docs(prompt: str) -> list[tuple[str, str]]:
    return DOC.findall(prompt)


class ScriptedLlm:
    model = "scripted-test"

    def __init__(self, respond: Callable[[str, str], Any]) -> None:
        self._respond = respond
        self.calls: list[tuple[str, str]] = []
        self.temperatures: list[float] = []

    def complete(self, *, system: str, user: str, max_tokens: int = 4096, temperature: float = 0.0) -> LlmResult:
        self.calls.append((system, user))
        self.temperatures.append(temperature)
        reply = self._respond(system, user)
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return LlmResult(text, Usage(10, 5, 1))


def scoring_bundle(**overrides: Any) -> dict[str, Any]:
    """一份合乎契约 scoring-model/1 的打分模型（model_id 按内容算出）；``overrides`` 覆盖顶层键。"""
    from bidwb.services.scoring_models import model_id_of

    bundle: dict[str, Any] = {
        "schema": "scoring-model/1",
        "target": "technical_total",
        "feature_spec": "pf-1",
        "input_method": "complete-chapters-1",
        "method": "ridge+isotonic",
        "features": ["raw_pct", "coverage_mean", "anchor_pct"],
        "standardize": {
            "mean": {"raw_pct": 60.0, "coverage_mean": 0.5, "anchor_pct": 70.0},
            "scale": {"raw_pct": 10.0, "coverage_mean": 0.25, "anchor_pct": 0.0},
        },
        "impute": {"coverage_mean": 0.5, "anchor_pct": 70.0},
        "coefficients": {"raw_pct": 4.0, "coverage_mean": 2.0, "anchor_pct": 1.0},
        "intercept": 70.0,
        "isotonic": {"x": [50.0, 70.0, 90.0], "y": [40.0, 70.0, 80.0]},
        "output": "technical_percent_of_max",
        "clip": [0.0, 100.0],
        "interval": {"0.8": 5.0, "0.9": 8.0},
        "scope": {"engineering_types": ["市政道路"], "regions": ["合肥"]},
        "evaluation": {
            "n": 280,
            "projects": 120,
            "mae_pct": 3.2,
            "verdict": "passed",
            "acceptance": {"status": "passed"},
            "mode": "holdout",
            "coverage_0.8": 0.81,
        },
        "data_sha256": "1" * 64,
        "code_sha256": "2" * 64,
        "created_at": "2026-10-01T00:00:00+00:00",
        **overrides,
    }
    bundle.pop("model_id", None)
    bundle["model_id"] = model_id_of(bundle)
    return bundle
