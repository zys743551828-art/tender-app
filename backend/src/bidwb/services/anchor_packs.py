"""比较锚点包（契约 ``anchor-pack/1``）的登记与读取。

锚点包可能有几十兆（每份锚点带各章节文字），方法包里只放摘要，全文在产物里；预测时 worker 按路由读出产物。
业务环境优先：业务环境有生效的锚点包就用它，否则用影子环境的（预测明细记下用的是哪一个）。
"""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import Connection

from bidwb.ai.anchors import AnchorPack, LoadedPack, PackError, parse_pack
from bidwb.errors import Unprocessable
from bidwb.services import model_registry
from bidwb.services.model_registry import TARGET_ANCHORS, Environment, Registration
from bidwb.storage import ObjectStore
from bidwb.util import canonical_json

MIN_ANCHORS = 2


def _summary(pack: AnchorPack) -> dict[str, object]:
    return {
        "schema": "anchor-pack/1",
        "pack_id": pack.pack_id,
        "created_at": pack.created_at.isoformat(),
        "anchors": len(pack.anchors),
        "groups": len({a.group_id for a in pack.anchors}),
        "engineering_types": dict(Counter(a.engineering_type or "未填写" for a in pack.anchors)),
        "with_item_scores": sum(1 for a in pack.anchors if a.items),
    }


def registration(pack_bytes: bytes, report_bytes: bytes | None) -> Registration:
    """校验锚点包并组装登记内容。没有给评估报告时，以锚点包摘要作为登记的报告。"""
    try:
        raw = json.loads(pack_bytes)
        pack = parse_pack(raw)
        if report_bytes is not None:
            json.loads(report_bytes)
    except PackError as exc:
        raise Unprocessable("invalid_anchor_pack", str(exc)) from exc
    except ValueError as exc:
        raise Unprocessable("invalid_json", "锚点包或报告不是合法的 JSON") from exc
    if len(pack.anchors) < MIN_ANCHORS:
        raise Unprocessable("too_few_anchors", f"锚点包至少要有 {MIN_ANCHORS} 份锚点")
    summary = _summary(pack)
    types = "、".join(sorted({a.engineering_type or "未填写" for a in pack.anchors}))
    return Registration(
        target=TARGET_ANCHORS,
        schema="anchor-pack/1",
        identity=pack.pack_id,
        payload=pack_bytes,
        components=summary,
        report=report_bytes if report_bytes is not None else canonical_json(summary).encode(),
        report_contract="anchor-pack-summary",
        method="anchored_pairwise",
        code_sha256=pack.pack_id,
        protocol="anchor-pack/1",
        member_count=len(pack.anchors),
        grouping="template_group",
        created_at=pack.created_at,
        scope_text=f"{len(pack.anchors)} 份锚点；工程类型：{types}",
    )


def routed_pack(conn: Connection, store: ObjectStore, _project_id: str) -> LoadedPack | None:
    """当前生效的锚点包：业务环境优先，其次影子环境；都没有时为 ``None``。"""
    environments: tuple[Environment, ...] = ("business", "shadow")
    for environment in environments:
        row = model_registry.routed(conn, TARGET_ANCHORS, environment)
        if row is not None:
            pack = parse_pack(json.loads(store.get(row["artifact_key"])))
            return LoadedPack(pack.pack_id, environment, tuple(pack.anchors))
    return None
