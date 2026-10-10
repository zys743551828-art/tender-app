"""正文内部的前后矛盾：同一个量在不同位置取值不同，以及大段重复。

数值矛盾只比较“同一个量”：量的名称取数值前面的名词短语，再用名称的末尾属性（如“最大开挖深度”）加上
前面的型号限定（如 DN300、SP-Ⅲ）作为键；单位必须相同。型号不同的同类量（DN300 与 DN500 的管长）键不同，不会互相比较。
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from bidwb.checks import Candidate, Passage

_UNITS = r"mm|cm|km|m³|m3|m²|m2|㎡|m|kg|t|MPa|kPa|日历天|天|人|台|套|座|%|℃|°"
_CONNECTORS = r"(?:不小于|不少于|不超过|不大于|不低于|大于|小于|为|是|约|达|共|计|取|[:：=≥≤<>])"
_NUMBER = re.compile(
    rf"(?P<label>[一-鿿A-Za-z0-9Ⅰ-Ⅻ\-·（）()]{{2,24}}?)(?P<conn>{_CONNECTORS})\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>{_UNITS})"
)
_TRADE = re.compile(r"(?P<label>[一-鿿]{1,5}(?:工|员))\s*(?P<num>\d+)\s*(?P<unit>人|名)")
_QUALIFIER = re.compile(r"[A-Za-z]+[\-]?[Ⅰ-ⅫA-Za-z0-9]*\d*[Ⅰ-Ⅻ]*|\d+")
_CJK_TAIL = re.compile(r"[一-鿿]{2,}$")
_STOP_PREFIX = ("本", "该", "其", "各", "此")
_MAX_VALUES = 4
_MIN_DUPLICATE_CHARS = 120
_DUPLICATE_RATIO = 0.8


@dataclass(frozen=True)
class _Mention:
    key: str
    label: str
    value: str
    unit: str
    passage: Passage


def _key(label: str) -> tuple[str, str] | None:
    """量的名称 → （键, 展示名）；取不出有意义的属性时返回 None。"""
    tail = _CJK_TAIL.search(label)
    if tail is None:
        return None
    attribute = tail.group(0)[-6:]
    while attribute and attribute.startswith(_STOP_PREFIX):
        attribute = attribute[1:]
    if len(attribute) < 3:
        return None
    qualifier = ""
    before = label[: tail.start()]
    match = _QUALIFIER.search(before[-8:])
    if match is not None and match.end() == len(before[-8:].rstrip("（(·-")):
        qualifier = match.group(0)
    return f"{qualifier}|{attribute}", f"{qualifier}{attribute}"


def _mentions(passages: Sequence[Passage]) -> list[_Mention]:
    found: list[_Mention] = []
    for p in passages:
        for m in _NUMBER.finditer(p.text):
            parsed = _key(m.group("label"))
            if parsed is not None:
                found.append(_Mention(parsed[0], parsed[1], m.group("num"), m.group("unit"), p))
        for m in _TRADE.finditer(p.text):
            found.append(_Mention(f"|{m.group('label')}", m.group("label"), m.group("num"), "人", p))
    return found


def numeric_conflicts(passages: Sequence[Passage]) -> list[Candidate]:
    """同一个量（键与单位相同）在不同位置有不同取值。每个量只报一条，列出至多 4 个取值及其页码。"""
    groups: dict[tuple[str, str], list[_Mention]] = defaultdict(list)
    for mention in _mentions(passages):
        groups[(mention.key, mention.unit)].append(mention)
    out: list[Candidate] = []
    for (key, unit), items in sorted(groups.items()):
        values: dict[str, _Mention] = {}
        for item in items:
            values.setdefault(str(float(item.value)), item)  # 5.0 与 5 视为同一个值
        if len(values) < 2:
            continue
        shown = sorted(values.values(), key=lambda i: (i.passage.page, i.value))[:_MAX_VALUES]
        label = shown[0].label
        parts = "、".join(f"{i.value}{unit}（第 {i.passage.page} 页）" for i in shown)
        out.append(
            Candidate(
                category="consistency",
                nature="fact_conflict",
                severity="normal",
                statement=f"“{label}”在正文中有不同取值：{parts}。请核对哪一个是准确的，并统一全文。",
                evidence_ids=tuple(dict.fromkeys(i.passage.evidence_id for i in shown)),
                required_facts=(),
                key=f"numeric|{key}|{unit}",
            )
        )
    return out


def _normalize(text: str) -> str:
    return re.sub(r"[\s　，。、；：！？,.;:!?（）()“”\"'‘’\-—·]", "", text)


def duplicate_passages(passages: Sequence[Passage]) -> list[Candidate]:
    """不同页的两段文字高度重复（共享的 24 字片段占较短一段的 80% 以上）。每对只报一条，至多 10 条。"""
    shingle = 24
    normalized = [(p, _normalize(p.text)) for p in passages]
    sets: list[set[str]] = []
    index: dict[str, list[int]] = defaultdict(list)
    eligible: list[int] = []
    for i, (_, text) in enumerate(normalized):
        if len(text) < _MIN_DUPLICATE_CHARS:
            sets.append(set())
            continue
        grams = {text[j : j + shingle] for j in range(0, len(text) - shingle + 1)}
        sets.append(grams)
        eligible.append(i)
        for g in grams:
            index[g].append(i)
    seen: set[tuple[int, int]] = set()
    out: list[Candidate] = []
    for i in eligible:
        hits: dict[int, int] = defaultdict(int)
        for g in sets[i]:
            for j in index[g]:
                if j > i:
                    hits[j] += 1
        for j, shared in sorted(hits.items()):
            a, b = normalized[i][0], normalized[j][0]
            if a.page == b.page or (i, j) in seen:
                continue
            ratio = shared / min(len(sets[i]), len(sets[j]))
            if ratio >= _DUPLICATE_RATIO:
                seen.add((i, j))
                out.append(
                    Candidate(
                        category="consistency",
                        nature="suggestion",
                        severity="improvement",
                        statement=f"第 {a.page} 页与第 {b.page} 页的内容高度重复（约 {int(ratio * 100)}%）。重复段落会降低方案的针对性和精练度，建议合并或改写。",
                        evidence_ids=(a.evidence_id, b.evidence_id),
                        required_facts=(),
                        key=f"duplicate|{a.evidence_id}|{b.evidence_id}",
                    )
                )
                if len(out) >= 10:
                    return out
    return out


def check(passages: Sequence[Passage]) -> list[Candidate]:
    return [*numeric_conflicts(passages), *duplicate_passages(passages)]
