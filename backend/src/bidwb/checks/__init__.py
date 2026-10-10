"""确定性检测：不调用模型，只读解析出的正文片段，给出带出处的候选问题。

检测结果只是“值得人看一眼”的候选：每条都附正文位置，由人确认；它们和规则核对一样进入问题清单，
并按分类（前后矛盾、范围残留）在报告里归类。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Passage:
    """一段带出处的正文：证据 ID、物理页、文字。"""

    evidence_id: str
    page: int
    text: str


@dataclass(frozen=True)
class Candidate:
    """检测给出的候选问题。``key`` 在同一次评审里唯一，用来去重（重跑不产生重复问题）。"""

    category: Literal["consistency", "scope"]
    nature: Literal["fact_conflict", "needs_confirmation", "suggestion"]
    severity: Literal["critical", "normal", "improvement"]
    statement: str
    evidence_ids: tuple[str, ...]
    required_facts: tuple[str, ...]
    key: str
