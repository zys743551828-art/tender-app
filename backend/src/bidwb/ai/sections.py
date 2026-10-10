"""正文结构：把按文档顺序读出的正文证据块组织成章节。

评委给一条评分条款打分时翻的是正文里专门回应它的章节，而不是零散的关键词命中；评分预测先把条款对到章节，
再把章节全文交给模型。产品与比较锚点包（``tools/batch/build_anchor_pack.py``）用同一套切分，保证两边的“章节”是同一回事。

做法：解析时块以标题行开头的，标题单独成第一行（``parsing.chunk_text``）。标题的写法（第X章、一、、（一）、1.、1.1……）
按由外到内排成固定次序，文中实际出现的写法里最外层的定为 1 级、次一层 2 级、再往里都算 3 级；1、2 级标题开新章节，
3 级并入所属章节。只出现一次的写法不参与定级（多半是误识别），按次序归到相邻的层级。目录页（带点线与页码的行）不算标题。
章节过多（超过 ``MAX_SECTIONS``）时只按 1 级分；仍然过多或找不到两个以上的章节时，按约 ``SEGMENT_CHARS`` 字切成“片段”。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from bidwb.checks import Passage
from bidwb.parsing import HEADING

MAX_TITLE_CHARS = 40  # 标题行超过这个长度的视为以编号开头的正文段落
SEGMENT_CHARS = 3000
MAX_SECTIONS = 60
LEAD_CHARS = 60
PREAMBLE_TITLE = "（正文开头）"

_CN = "一二三四五六七八九十百零〇"
# 标题写法，由外到内；同一层可有多种写法（第X条与（1）都在最里层）
_STYLES: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("part", 0, re.compile(rf"第[{_CN}\d]+[篇部]")),
    ("chapter", 1, re.compile(rf"第[{_CN}\d]+章")),
    ("section", 2, re.compile(rf"第[{_CN}\d]+节")),
    ("cn", 3, re.compile(rf"[{_CN}]+[、.．]")),
    ("cn_paren", 4, re.compile(rf"[（(][{_CN}]+[）)]")),
    ("num1", 5, re.compile(r"\d+(?![.．]\d)[\s、.．]")),
    ("num2", 6, re.compile(r"\d+[.．]\d+(?![.．]\d)")),
    ("num3", 7, re.compile(r"\d+(?:[.．]\d+){2,}")),
    ("paren_num", 8, re.compile(r"[（(]\d+[）)]")),
    ("article", 8, re.compile(rf"第[{_CN}\d]+[条款]")),
)
_RANK = {name: rank for name, rank, _ in _STYLES}
_TOC_LINE = re.compile(r"(?:[.．…·•\-_]{3,}|\s{2,})\s*\d{1,4}\s*$")


@dataclass(frozen=True)
class Section:
    id: str  # S1、S2……按文档顺序
    title: str
    level: int  # 1 或 2；按片段切分时为 1
    parent: str | None  # 2 级章节所属 1 级章节的标题
    evidence_ids: tuple[str, ...]
    chars: int
    first_page: int
    lead: str  # 标题之后的开头文字，最多 LEAD_CHARS 字

    @property
    def label(self) -> str:
        return f"{self.parent} › {self.title}" if self.parent else self.title


@dataclass(frozen=True)
class _Heading:
    style: str
    title: str


def heading_of(text: str) -> _Heading | None:
    """块的第一行是标题时返回其写法与标题文字；目录行、过长的行不算。"""
    first = text.split("\n", 1)[0].strip()
    if not first or len(first) > MAX_TITLE_CHARS or _TOC_LINE.search(first) or not HEADING.match(first):
        return None
    for name, _, pattern in _STYLES:
        if pattern.match(first):
            return _Heading(name, first)
    return None


def _levels(counts: Counter[str]) -> dict[str, int]:
    """写法 → 层级。出现两次以上的写法参与定级；只出现一次的按次序落在比它更外的已定级写法之下。"""
    present = sorted({_RANK[s] for s, n in counts.items() if n >= 2} or {_RANK[s] for s in counts})
    return {s: min(3, 1 + sum(1 for r in present if r < _RANK[s])) for s in counts}


def _body_text(passage: Passage) -> str:
    return passage.text.partition("\n")[2] if heading_of(passage.text) is not None else passage.text


def _lead(passages: Sequence[Passage]) -> str:
    for passage in passages:
        text = "".join(_body_text(passage).split())
        if text:
            return text[:LEAD_CHARS]
    return ""


@dataclass
class _Draft:
    title: str
    level: int
    parent: str | None
    passages: list[Passage]


def _group(passages: Sequence[Passage], heads: Sequence[_Heading | None], levels: dict[str, int], max_level: int) -> list[_Draft]:
    drafts: list[_Draft] = []
    parent: str | None = None
    for passage, head in zip(passages, heads, strict=True):
        level = levels[head.style] if head is not None else None
        if head is not None and level is not None and level <= max_level:
            if level == 1:
                parent = head.title
            drafts.append(_Draft(head.title, level, parent if level == 2 else None, [passage]))
        elif drafts:
            drafts[-1].passages.append(passage)
        else:
            drafts.append(_Draft(PREAMBLE_TITLE, 1, None, [passage]))
    return drafts


def _segments(passages: Sequence[Passage]) -> list[_Draft]:
    drafts: list[_Draft] = []
    size = SEGMENT_CHARS
    for passage in passages:
        if not drafts or size >= SEGMENT_CHARS:
            drafts.append(_Draft(f"片段 {len(drafts) + 1}", 1, None, []))
            size = 0
        drafts[-1].passages.append(passage)
        size += len(passage.text)
    return drafts


def build_sections(passages: Sequence[Passage]) -> list[Section]:
    """按文档顺序的正文块 → 章节（S1、S2……）。没有正文时返回空列表。"""
    if not passages:
        return []
    heads = [heading_of(p.text) for p in passages]
    levels = _levels(Counter(h.style for h in heads if h is not None))
    drafts = _group(passages, heads, levels, 2)
    if len(drafts) > MAX_SECTIONS:
        drafts = _group(passages, heads, levels, 1)
    if len([d for d in drafts if d.title != PREAMBLE_TITLE]) < 2 or len(drafts) > MAX_SECTIONS:
        drafts = _segments(passages)
    return [
        Section(
            id=f"S{n}",
            title=d.title,
            level=d.level,
            parent=d.parent,
            evidence_ids=tuple(p.evidence_id for p in d.passages),
            chars=sum(len(p.text) for p in d.passages),
            first_page=d.passages[0].page,
            lead=_lead(d.passages),
        )
        for n, d in enumerate(drafts, 1)
    ]
