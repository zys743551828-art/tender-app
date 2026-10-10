"""证据落地校验：模型给出的每条引用都必须能在提供给它的证据中逐字找到。

不做“差不多就行”的模糊匹配——匹配只忽略空白差异；找不到的候选直接丢弃并计入原因，
由调用方写进产物的 ``dropped`` 列表，保证“少而准”优于“多而虚”。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def squash(text: str) -> str:
    return _WS.sub("", text)


@dataclass(frozen=True)
class EvidenceText:
    evidence_id: str
    quote: str


def quote_supported(quote: str, evidence: dict[str, EvidenceText], evidence_ids: list[str]) -> bool:
    """``quote`` 必须是所引证据之一原文的连续子串（忽略空白）。"""
    needle = squash(quote)
    if len(needle) < 4:
        return False
    return any(eid in evidence and needle in squash(evidence[eid].quote) for eid in evidence_ids)


def unknown_ids(evidence_ids: list[str], evidence: dict[str, EvidenceText]) -> list[str]:
    return [e for e in evidence_ids if e not in evidence]


def numeric_tokens(text: str) -> set[str]:
    return set(_NUM.findall(text))


def invented_numbers(generated: str, *sources: str) -> set[str]:
    """生成文本里出现、但所有来源（原文、允许使用的事实）里都没有的数字。"""
    allowed: set[str] = set()
    for source in sources:
        allowed |= numeric_tokens(source)
    return numeric_tokens(generated) - allowed
