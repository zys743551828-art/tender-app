"""由评分配对集（交接格式 A）生成比较锚点包（契约 ``anchor-pack/1``）。

运行方式（在 backend 目录）::

    python -m tools.batch.build_anchor_pack --pairs <评分配对集.json> --out <pack.json> [--datasets-root …]

只取可用（``eligible``）且有技术分标签（值与满分都在、结果不冲突）的样本；同一正文只取第一次出现的。
每份锚点的正文用产品同样的解析（``bidwb.parsing``）与章节切分（``bidwb.ai.sections``）组织成章节，每节文字不超过 8000 字，
模板组取 ``template_group``（缺省时取样本编号），另记 ``project_key``，批量预测据此排除同源锚点。
标签里带逐项得分（``label.items``：``[{"item", "value", "maximum"}]`` 或 ``[{"item", "pct"}]``）时一并写入。
生成的包可直接给 ``predict_dataset.py --anchor-pack`` 使用，也可用 ``bidwb-admin register-anchor-pack`` 登记进产品。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))

from bidwb import parsing  # noqa: E402
from bidwb.ai import anchors  # noqa: E402
from bidwb.ai.sections import build_sections  # noqa: E402
from bidwb.checks import Passage  # noqa: E402

from tools.batch.predict_dataset import Sample, SampleError, load_dataset  # noqa: E402


def _pct(value: Any, maximum: Any) -> float | None:
    try:
        v, m = float(value), float(maximum)
    except (TypeError, ValueError):
        return None
    return round(min(max(v / m * 100, 0.0), 100.0), 4) if m > 0 else None


def _items(label: dict[str, Any]) -> list[dict[str, Any]] | None:
    out: list[dict[str, Any]] = []
    for raw in label.get("items") or []:
        pct = raw.get("pct") if raw.get("pct") is not None else _pct(raw.get("value"), raw.get("maximum"))
        if raw.get("item") and pct is not None:
            out.append({"item": str(raw["item"])[:500], "pct": round(float(pct), 4)})
    return out or None


def sections_of(pdf: bytes) -> list[dict[str, str]]:
    """正文 → 锚点章节：与产品同样的解析与切分，每节文字截到 ``anchors.SECTION_TEXT_CHARS``。"""
    document = parsing.parse_pdf(pdf)
    passages = [Passage(f"c{i}", c.physical_page, c.quote) for i, c in enumerate(document.chunks)]
    by_id = {p.evidence_id: p.text for p in passages}
    return [
        {"id": s.id, "title": s.label[:200], "text": "\n".join(by_id[e] for e in s.evidence_ids)[: anchors.SECTION_TEXT_CHARS]}
        for s in build_sections(passages)
    ]


def anchor_of(sample: Sample) -> dict[str, Any] | None:
    """一份样本 → 一份锚点；没有可用标签或正文读不出时为 ``None``。"""
    label = sample.raw.get("label") or {}
    if not sample.eligible or sample.body is None or label.get("verification_status") == "conflict":
        return None
    pct = _pct(label.get("value"), label.get("maximum"))
    if pct is None:
        return None
    try:
        sample.resolve_shas()
        sections = sections_of(sample.body.path.read_bytes())
    except (SampleError, parsing.ParseError) as exc:
        print(f"  跳过 {sample.sample_id}：{exc}", file=sys.stderr)
        return None
    if not sections:
        print(f"  跳过 {sample.sample_id}：正文没有可用文字", file=sys.stderr)
        return None
    raw = sample.raw
    return {
        "anchor_id": sample.sample_id,
        "group_id": str(raw.get("template_group") or sample.sample_id),
        "project_key": raw.get("project_key"),
        "body_sha256": sample.body_sha(),
        "engineering_type": raw.get("engineering_type"),
        "region": raw.get("region"),
        "scoring_scheme": raw.get("scoring_scheme"),
        "technical_pct": pct,
        "items": _items(label),
        "sections": sections,
    }


def build(pairs: Path, datasets_root: Path | None = None) -> dict[str, Any]:
    seen: set[str] = set()
    built: list[dict[str, Any]] = []
    for sample in load_dataset(pairs, datasets_root):
        anchor = anchor_of(sample)
        if anchor is None or anchor["body_sha256"] in seen:
            continue
        seen.add(anchor["body_sha256"])
        built.append(anchor)
    pack: dict[str, Any] = {"schema": anchors.SCHEMA, "created_at": datetime.now(UTC).isoformat(), "anchors": built}
    pack["pack_id"] = anchors.pack_id_of(pack)
    anchors.parse_pack(pack)  # 生成即按契约复核
    return pack


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="由评分配对集（格式 A）生成比较锚点包（anchor-pack/1）")
    p.add_argument("--pairs", type=Path, required=True, help="评分配对集.json（交接格式 A）")
    p.add_argument("--out", type=Path, required=True, help="输出的锚点包 JSON")
    p.add_argument("--datasets-root", type=Path, help="覆盖格式 A 里的 datasets_root")
    a = p.parse_args(argv)
    pack = build(a.pairs, a.datasets_root)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(pack, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"锚点 {len(pack['anchors'])} 份，pack_id {pack['pack_id'][:12]}，写入 {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
