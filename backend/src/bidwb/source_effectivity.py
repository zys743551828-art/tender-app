"""条款效力身份：原文证据或具体要求变化后，不沿用旧的终止决定。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal

from bidwb.util import canonical_json, sha256_hex

LOCAL_SCOPE_MARKERS = (
    "其他条款不变",
    "其余条款不变",
    "其他要求不变",
    "其余要求不变",
    "其他内容不变",
    "其余内容不变",
    "仅替换",
    "仅修改",
    "局部替代",
)


def rule_key(rule: Mapping[Any, Any]) -> str:
    maximum = rule.get("max_points")
    return sha256_hex(
        canonical_json(
            {
                "kind": rule["kind"],
                "statement": rule["statement"],
                "conditions": rule.get("conditions_json", rule.get("conditions", [])),
                "exceptions": rule.get("exceptions_json", rule.get("exceptions", [])),
                "max_points": str(Decimal(str(maximum)).normalize()) if maximum is not None else None,
                "evidence_ids": sorted(rule.get("evidence_ids_json", rule.get("evidence_ids", []))),
            }
        )
    )


def state(effectivity: Mapping[str, Any], rule: Mapping[Any, Any]) -> Literal["active", "superseded", "needs_confirmation"]:
    key = rule_key(rule)
    if key in effectivity.get("pending", {}):
        return "needs_confirmation"
    if key in effectivity.get("ended", {}):
        return "superseded"
    return "active"


def pending_count(effectivity: Mapping[str, Any], rules: Sequence[Mapping[Any, Any]]) -> int:
    return sum(state(effectivity, rule) == "needs_confirmation" for rule in rules)
