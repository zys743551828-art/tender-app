"""比较式锚定：把本项目正文与几份已知官方成绩的历史正文逐项比较，折算成一个百分制位置。

模型判断“哪份更好”远比给绝对分可靠。锚点包（契约 ``anchor-pack/1``，由 ``tools/batch/build_anchor_pack.py`` 生成、
``bidwb-admin register-anchor-pack`` 登记）里每份锚点带官方技术分（占满分的百分比，可能还有逐项得分）与按 ``ai.sections``
切好的章节文字。一次预测：

1. 选锚点：排除与本项目正文字节相同的锚点；优先同工程类型、其次同评标办法；在候选里按官方分的分位（1/(M+1)…M/(M+1)）
   各取最近的一份，让锚点高低分散开。顺序与取舍全部确定，重跑结果相同。
2. 选条款：按分值从大到小，取到累计覆盖 70% 分值或 6 条为止。
3. 逐对比较（温度 0）：本项目条款上下文与锚点里检索到的对应章节各不超过 6000 字；第偶数个锚点本项目放在 A，奇数个放在 B，
   抵消模型对先后位置的偏好，结果再映射回“本项目更好／相当／锚点更好”。
4. 一维 Bradley–Terry 拟合：在 0～100（步长 0.1）上找 s，使 Σ w·log σ(±(s − 锚点分)/τ) 最大；本项目更好取 +，锚点更好取 −，
   相当按两个方向各 0.5 权重计；w = 条款分值占比 × 把握程度。锚点有该条款的逐项得分（条文相近）时用逐项百分比，否则用总分百分比。

结果作为特征 ``anchor_pct``（s）、``anchor_agree``（非“相当”的比较里与 s 方向一致的比例）、``anchor_n``（比较次数）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Connection

from bidwb import retrieval
from bidwb.ai import prompts
from bidwb.ai.grounding import EvidenceText
from bidwb.ai.llm import IncompleteGeneration, LlmClient, Usage, call_validated
from bidwb.storage import ObjectStore
from bidwb.util import canonical_json, sha256_hex

SCHEMA = "anchor-pack/1"
SECTION_TEXT_CHARS = 8000  # 锚点包里每节文字的上限
EXCERPT_CHARS = 6000  # 一次比较里每一方的篇幅上限
ITEM_POINTS_SHARE = 0.7
MAX_ITEMS = 6
ITEM_MATCH_MIN = 0.5  # 锚点逐项得分与本条款条文的相似度下限（字二元组 Jaccard）
GRID_STEP = 0.1

_Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_Pct = Annotated[float, Field(ge=0, le=100)]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AnchorItem(_Contract):
    item: Annotated[str, Field(min_length=1, max_length=500)]
    pct: _Pct


class AnchorSection(_Contract):
    id: Annotated[str, Field(min_length=1, max_length=16)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    text: Annotated[str, Field(max_length=SECTION_TEXT_CHARS)]


class Anchor(_Contract):
    anchor_id: Annotated[str, Field(min_length=1, max_length=100)]
    group_id: Annotated[str, Field(min_length=1, max_length=200)]  # 模板组：同组的样本彼此不作锚点
    project_key: str | None = None  # 招标编号＋标段：同一项目的样本彼此不作锚点
    body_sha256: _Sha
    engineering_type: str | None = None
    region: str | None = None
    scoring_scheme: str | None = None
    technical_pct: _Pct
    items: list[AnchorItem] | None = None
    sections: Annotated[list[AnchorSection], Field(min_length=1)]


class AnchorPack(_Contract):
    schema_: Annotated[Literal["anchor-pack/1"], Field(alias="schema")]
    pack_id: _Sha
    created_at: datetime
    anchors: Annotated[list[Anchor], Field(min_length=1)]


def pack_id_of(raw: dict[str, Any]) -> str:
    """锚点包的标识：去掉 ``pack_id`` 后的规范 JSON（键排序、无空白、UTF-8）的 SHA-256。"""
    return sha256_hex(canonical_json({k: v for k, v in raw.items() if k != "pack_id"}))


class PackError(ValueError):
    """锚点包不符合契约。"""


def parse_pack(raw: Any) -> AnchorPack:
    if not isinstance(raw, dict):
        raise PackError("锚点包必须是 JSON 对象")
    try:
        pack = AnchorPack.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise PackError(f"锚点包不符合 {SCHEMA}：{'.'.join(str(p) for p in first['loc'])} {first['msg']}") from exc
    if pack.pack_id != pack_id_of(raw):
        raise PackError("pack_id 与内容不符（应为去掉 pack_id 后规范 JSON 的 SHA-256）")
    if len({a.anchor_id for a in pack.anchors}) != len(pack.anchors):
        raise PackError("anchor_id 有重复")
    return pack


@dataclass(frozen=True)
class LoadedPack:
    """一次预测可用的锚点：已排除不得使用的（如批量预测时同一模板组的样本）。"""

    pack_id: str
    environment: str
    anchors: tuple[Anchor, ...]
    scoring_scheme: str | None = None  # 本项目的评标办法（已知时用于优先选同办法的锚点）


AnchorSource = Callable[[Connection, ObjectStore, str], LoadedPack | None]  # (连接, 对象存储, 项目 ID)


# ------------------------------------------------------------------ 选锚点、选条款
def _quantile(sorted_values: Sequence[float], q: float) -> float:
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def select_anchors(
    anchors: Sequence[Anchor], m: int, *, body_sha256: str, engineering_type: str | None, scoring_scheme: str | None
) -> list[Anchor]:
    """选出至多 ``m`` 份锚点，按选中顺序返回（该顺序决定本项目在比较里放 A 还是 B）。"""
    if m <= 0:
        return []

    def tier(a: Anchor) -> int:
        same_type = engineering_type is not None and a.engineering_type == engineering_type
        same_scheme = scoring_scheme is not None and a.scoring_scheme == scoring_scheme
        return (0 if same_type else 2) + (0 if same_scheme else 1)

    candidates = sorted((a for a in anchors if a.body_sha256 != body_sha256), key=lambda a: (tier(a), a.technical_pct, a.anchor_id))
    pool: list[Anchor] = []
    for level in range(4):
        if len(pool) >= m:
            break
        pool.extend(a for a in candidates if tier(a) == level)
    if len(pool) <= m:
        return sorted(pool, key=lambda a: (a.technical_pct, a.anchor_id))
    values = sorted(a.technical_pct for a in pool)
    chosen: list[Anchor] = []
    for k in range(1, m + 1):
        target = _quantile(values, k / (m + 1))
        best = min(
            (a for a in pool if a not in chosen),
            key=lambda a: (abs(a.technical_pct - target), tier(a), a.technical_pct, a.anchor_id),
        )
        chosen.append(best)
    return chosen


def select_items(points: Sequence[float]) -> list[int]:
    """参与比较的条款下标：按分值从大到小（同分按原顺序），取到累计覆盖 ``ITEM_POINTS_SHARE`` 或 ``MAX_ITEMS`` 条为止。"""
    total = sum(points)
    order = sorted(range(len(points)), key=lambda i: (-points[i], i))
    chosen: list[int] = []
    covered = 0.0
    for i in order:
        if len(chosen) >= MAX_ITEMS or (total > 0 and covered >= ITEM_POINTS_SHARE * total):
            break
        chosen.append(i)
        covered += points[i]
    return chosen


def _similarity(a: str, b: str) -> float:
    """两段条文的相似度：检索分词（字二元组与西文词）集合的 Jaccard 系数。"""
    x, y = set(retrieval.tokenize(a)), set(retrieval.tokenize(b))
    return len(x & y) / len(x | y) if x | y else 0.0


def anchor_item_pct(anchor: Anchor, statement: str) -> tuple[float, bool]:
    """锚点在这条评分条款上的百分比：逐项得分里条文最相近（相似度不低于 ``ITEM_MATCH_MIN``）的一项，否则用总分百分比。"""
    if anchor.items:
        similarity, best = max(((_similarity(statement, i.item), i) for i in anchor.items), key=lambda s: s[0])
        if similarity >= ITEM_MATCH_MIN:
            return best.pct, True
    return anchor.technical_pct, False


def anchor_excerpt(anchor: Anchor, statement: str) -> str | None:
    """锚点里与本条款对应的内容：按条文对章节（标题＋文字）检索，取最相关的一节，第二节得分不低于第一节一半且放得下时一并带上。"""
    ranked = retrieval.rank(statement, [f"{s.title}\n{s.text}" for s in anchor.sections], 2)
    if not ranked:
        return None
    picked = [ranked[0]] + [r for r in ranked[1:] if r.score >= ranked[0].score / 2]
    parts: list[str] = []
    used = 0
    for r in sorted(picked, key=lambda r: r.index):
        section = anchor.sections[r.index]
        piece = f"【{section.title}】{section.text}"
        if parts and used + len(piece) > EXCERPT_CHARS:
            break
        parts.append(piece)
        used += len(piece)
    return "\n".join(parts)[:EXCERPT_CHARS]


def target_excerpt(context: Sequence[EvidenceText]) -> str:
    parts: list[str] = []
    used = 0
    for block in context:
        if used + len(block.quote) > EXCERPT_CHARS:
            break
        parts.append(block.quote)
        used += len(block.quote)
    return "\n".join(parts) if parts else (context[0].quote[:EXCERPT_CHARS] if context else "")


# ------------------------------------------------------------------ 拟合
Outcome = Literal["target", "similar", "anchor"]


@dataclass(frozen=True)
class Observation:
    anchor_pct: float
    outcome: Outcome
    weight: float


def _log_sigmoid(x: float) -> float:
    return -math.log1p(math.exp(-x)) if x >= 0 else x - math.log1p(math.exp(x))


def log_likelihood(s: float, observations: Sequence[Observation], tau: float) -> float:
    total = 0.0
    for o in observations:
        d = (s - o.anchor_pct) / tau
        if o.outcome == "target":
            total += o.weight * _log_sigmoid(d)
        elif o.outcome == "anchor":
            total += o.weight * _log_sigmoid(-d)
        else:
            total += o.weight * 0.5 * (_log_sigmoid(d) + _log_sigmoid(-d))
    return total


def fit(observations: Sequence[Observation], tau: float) -> float | None:
    """在 0～100 的网格（步长 ``GRID_STEP``）上取似然最大的 s；同为最大时取最小的 s。没有观测返回 ``None``。"""
    if not observations:
        return None
    steps = round(100 / GRID_STEP)
    best_s, best_ll = 0.0, -math.inf
    for k in range(steps + 1):
        s = k * GRID_STEP
        ll = log_likelihood(s, observations, tau)
        if ll > best_ll + 1e-12:
            best_s, best_ll = s, ll
    return round(best_s, 1)


def agreement(s: float, observations: Sequence[Observation]) -> float | None:
    decided = [o for o in observations if o.outcome != "similar"]
    if not decided:
        return None
    agree = sum(1 for o in decided if (o.outcome == "target" and s > o.anchor_pct) or (o.outcome == "anchor" and s < o.anchor_pct))
    return agree / len(decided)


# ------------------------------------------------------------------ 一次预测里的比较
@dataclass(frozen=True)
class ItemForComparison:
    rule_id: str
    statement: str
    max_points: float
    rule_evidence: list[EvidenceText]
    context: list[EvidenceText]


@dataclass
class AnchorResult:
    pack_id: str
    environment: str
    selected: list[dict[str, Any]]
    comparisons: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    pct: float | None = None
    agree: float | None = None
    n: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "environment": self.environment,
            "selected": self.selected,
            "comparisons": self.comparisons,
            "skipped": self.skipped,
            "pct": self.pct,
            "agree": self.agree,
            "n": self.n,
        }


def compare(
    llm: LlmClient,
    pack: LoadedPack,
    items: Sequence[ItemForComparison],
    *,
    m: int,
    tau: float,
    body_sha256: str,
    engineering_type: str | None,
    usage: Usage,
    checkpoint: Callable[[], None],
) -> AnchorResult:
    anchors = select_anchors(
        pack.anchors, m, body_sha256=body_sha256, engineering_type=engineering_type, scoring_scheme=pack.scoring_scheme
    )
    result = AnchorResult(
        pack.pack_id,
        pack.environment,
        [{"anchor_id": a.anchor_id, "technical_pct": a.technical_pct, "engineering_type": a.engineering_type} for a in anchors],
    )
    chosen = [items[i] for i in select_items([i.max_points for i in items])]
    points = sum(i.max_points for i in chosen)
    observations: list[Observation] = []
    for item in chosen:
        mine = target_excerpt(item.context)
        for position, anchor in enumerate(anchors):
            checkpoint()
            theirs = anchor_excerpt(anchor, item.statement)
            if theirs is None or not mine:
                result.skipped.append({"rule_id": item.rule_id, "anchor_id": anchor.anchor_id, "reason": "no_excerpt"})
                continue
            target_first = position % 2 == 0
            first, second = (mine, theirs) if target_first else (theirs, mine)
            try:
                out = call_validated(
                    llm,
                    prompts.Comparison,
                    system=prompts.COMPARISON_SYSTEM,
                    user=prompts.comparison_user(item.statement, item.rule_evidence, first, second),
                    usage=usage,
                )
            except IncompleteGeneration:
                result.skipped.append({"rule_id": item.rule_id, "anchor_id": anchor.anchor_id, "reason": "invalid_output"})
                continue
            outcome = _outcome(out.better, target_first)
            pct, by_item = anchor_item_pct(anchor, item.statement)
            strength = 0.5 if outcome == "similar" else out.strength
            observations.append(Observation(pct, outcome, item.max_points / points * strength))
            result.comparisons.append(
                {
                    "rule_id": item.rule_id,
                    "anchor_id": anchor.anchor_id,
                    "target_position": "A" if target_first else "B",
                    "better": outcome,
                    "strength": strength,
                    "anchor_pct": pct,
                    "anchor_pct_by_item": by_item,
                    "reason": out.reason,
                }
            )
    result.n = len(observations)
    result.pct = fit(observations, tau)
    result.agree = agreement(result.pct, observations) if result.pct is not None else None
    return result


def _outcome(better: Literal["A", "B", "similar"], target_first: bool) -> Outcome:
    if better == "similar":
        return "similar"
    return "target" if (better == "A") == target_first else "anchor"
