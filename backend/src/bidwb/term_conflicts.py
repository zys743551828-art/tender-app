"""投标条件候选及冲突；不根据模型输出顺序或文件上传时间判定生效。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from bidwb.util import canonical_json, sha256_hex

TermMap = dict[str, dict[str, Any]]
KEYS = ("technical_full_score", "price_rule")


def values(candidate: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in candidate.items() if key not in {"evidence_ids", "quote"}}


def _signature(candidate: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in values(candidate).items():
        try:
            normalized[key] = str(Decimal(value).normalize())
        except InvalidOperation:
            normalized[key] = value
    return normalized


def option_id(candidate: dict[str, Any]) -> str:
    return "trm_" + sha256_hex(canonical_json(candidate))[:24]


def add_candidate(terms: TermMap, key: str, candidate: dict[str, Any]) -> None:
    alternatives = terms.setdefault("_alternatives", {}).setdefault(key, [])
    if not alternatives and key in terms:
        alternatives.append(terms[key])
    if not any(_signature(existing) == _signature(candidate) for existing in alternatives):
        alternatives.append(candidate)
    terms.setdefault(key, candidate)


def pending(terms: TermMap) -> dict[str, list[dict[str, Any]]]:
    alternatives = terms.get("_alternatives", {})
    resolved = terms.get("_resolved", {})
    return {key: alternatives[key] for key in KEYS if len(alternatives.get(key, [])) > 1 and key not in resolved}


def effective(terms: TermMap) -> TermMap:
    return {key: value for key, value in terms.items() if key in KEYS and key not in pending(terms)}
