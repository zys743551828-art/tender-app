"""中文关键词检索（BM25，字二元组 + 西文词）。

这是检索的基线与回退通道（TECH-001 §3.3）：不依赖外部服务、结果可解释。Milvus 混合检索只有在评测显示它
确实优于本基线时才启用，因此这里的实现要足够正确，而不是“先凑合”。

分词：连续汉字按相邻两字切分（“施工组织”→ 施工/工组/组织），单个孤立汉字保留为一元；字母数字串整体小写后作为词。
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
_WORD = re.compile(r"[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*")

K1 = 1.5
B = 0.75

# 不把 15.12、15.120、115.12 或 15.12‰ 当作同一事实。标点只在编号内部保留。
_EXACT = re.compile(r"[A-Za-z0-9]+(?:[.\-/][A-Za-z0-9]+)*(?:[%‰])?")


def exact_terms(text: str) -> set[str]:
    """提取含数字的完整编号／数值；全角字符规范化，但保留单位符号和小数精度。"""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return {term for term in _EXACT.findall(normalized) if any(char.isdigit() for char in term)}


def rank_exact(query: str, documents: Sequence[str], top_k: int) -> list[Scored]:
    """按查询中完整编号／数值的覆盖率排序；纯中文查询不启用此通道。"""
    terms = exact_terms(query)
    if not terms or top_k <= 0:
        return []
    scored = [Scored(i, len(terms & exact_terms(doc)) / len(terms)) for i, doc in enumerate(documents)]
    return sorted((item for item in scored if item.score > 0), key=lambda item: (-item.score, item.index))[:top_k]


def reciprocal_rank_fusion(channels: Sequence[Sequence[Scored]], top_k: int, *, offset: int = 60) -> list[Scored]:
    """融合通道名次，不混用 BM25 与余弦分数；每个通道的重复项只计首次出现。"""
    if offset < 1:
        raise ValueError("RRF offset 必须大于零")
    if top_k <= 0:
        return []
    scores: dict[int, float] = {}
    for channel in channels:
        seen: set[int] = set()
        for item in channel:
            if item.index in seen:
                continue
            seen.add(item.index)
            scores[item.index] = scores.get(item.index, 0.0) + 1.0 / (offset + len(seen))
    return [Scored(index, score) for index, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _CJK.finditer(text):
        run = match.group()
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    tokens.extend(word.lower() for word in _WORD.findall(text))
    return tokens


@dataclass(frozen=True)
class Scored:
    index: int
    score: float


def rank(query: str, documents: Sequence[str], top_k: int) -> list[Scored]:
    """对 ``documents`` 做 BM25 排序，只返回得分大于 0 的前 ``top_k`` 条；同分按原顺序（页码顺序）稳定排列。"""
    if top_k <= 0:
        return []
    query_terms = Counter(tokenize(query))
    if not query_terms or not documents:
        return []
    doc_tokens = [Counter(tokenize(d)) for d in documents]
    lengths = [sum(c.values()) for c in doc_tokens]
    avg = (sum(lengths) / len(lengths)) or 1.0
    n = len(documents)
    df = {t: sum(1 for c in doc_tokens if t in c) for t in query_terms}
    scored: list[Scored] = []
    for i, counts in enumerate(doc_tokens):
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if tf == 0:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * lengths[i] / avg))
        if score > 0:
            scored.append(Scored(i, score))
    scored.sort(key=lambda s: (-s.score, s.index))
    return scored[:top_k]
