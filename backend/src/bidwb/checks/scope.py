"""超范围残留：正文里反复出现、招标文件及补遗里却完全没有的工程对象（泵站、沉井、调度平台等）。

这是套用其他项目模板最常见的失分点。检测只给候选：用一份与项目无关的“工程对象”词表在正文里找词，
再看招标文件和补遗是否出现过同一对象；没出现过的列出出处，由人确认它是否确实不属于本项目的招标范围。
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from bidwb.checks import Candidate, Passage

FACILITIES = (
    "一体化预制泵站",
    "泵站",
    "泵房",
    "沉井",
    "调蓄池",
    "沉淀池",
    "污水处理厂",
    "污水厂",
    "净水厂",
    "水厂",
    "变电站",
    "配电柜",
    "控制箱",
    "监控系统",
    "调度平台",
    "智能化",
    "隧道",
    "下穿段",
    "立交",
    "高架",
    "盾构",
    "顶管",
    "管廊",
    "码头",
    "涵洞",
    "挡土墙",
    "堤防",
    "闸门",
    "水库",
    "边坡支护",
    "钻孔灌注桩",
    "预应力",
)
_FACILITY_RE = re.compile("|".join(sorted((re.escape(f) for f in FACILITIES), key=len, reverse=True)))
_PLACE_RE = re.compile(r"[一-鿿]{2,4}(?:大道|路|街)(?:[一-鿿]{0,3}段)?|[一-鿿]{2,4}区(?=[一-鿿]{2,}(?:厂|平台|站))")
_MAX_FINDINGS = 8
_MAX_EVIDENCE = 4


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def residual_scope(body: Sequence[Passage], tender: Sequence[Passage]) -> list[Candidate]:
    """正文出现、招标文件及补遗没有的工程对象。出现次数多的排前面，至多 8 条。"""
    if not tender:
        return []  # 没有招标文本就没有比较基准，不猜
    tender_text = _squash("".join(p.text for p in tender))
    found: dict[str, list[Passage]] = defaultdict(list)
    for p in body:
        for m in _FACILITY_RE.finditer(p.text):
            term = m.group(0)
            if term not in tender_text and p not in found[term]:
                found[term].append(p)
        for m in _PLACE_RE.finditer(p.text):
            term = m.group(0)
            if term not in tender_text and p not in found[term]:
                found[term].append(p)
    for term in [t for t in found if any(t != other and t in other and set(found[t]) <= set(found[other]) for other in found)]:
        del found[term]  # “下穿段”已包含在“建设路下穿段”里，只报更完整的那个
    ranked = sorted(found.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:_MAX_FINDINGS]
    out: list[Candidate] = []
    for term, passages in ranked:
        pages = sorted({p.page for p in passages})
        shown = "、".join(str(n) for n in pages[:6]) + ("等" if len(pages) > 6 else "")
        place = _PLACE_RE.fullmatch(term) is not None
        out.append(
            Candidate(
                category="scope",
                nature="needs_confirmation",
                severity="improvement" if place or len(passages) == 1 else "normal",
                statement=f"正文在第 {shown} 页提到“{term}”，招标文件及补遗中没有出现，可能是其他项目的模板残留，或超出本项目招标范围。",
                evidence_ids=tuple(p.evidence_id for p in passages[:_MAX_EVIDENCE]),
                required_facts=(f"确认“{term}”是否属于本项目的招标范围",),
                key=f"scope|{term}",
            )
        )
    return out
