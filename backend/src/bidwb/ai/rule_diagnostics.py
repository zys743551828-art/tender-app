"""Safe failure categories; never infer absent rules or relax model validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence


def failed_rules_message(dropped: Sequence[Mapping[str, object]]) -> str:
    counts: Counter[str] = Counter()
    for item in dropped:
        reason = item.get("reason")
        if not isinstance(reason, str):
            counts["other"] += 1
        elif reason.startswith("invalid_item:"):
            counts["schema"] += 1
            field = reason.split(":", 1)[1].split(".", 1)[0]
            if field in {"conditions", "exceptions"}:
                counts[field] += 1
        elif reason in {"unknown_evidence", "quote_not_found", "duplicate", "invalid_output"}:
            counts[reason] += 1
        else:
            counts["other"] += 1
    return (
        f"未能提取出可核对的规则（丢弃记录 {len(dropped)} 条；结构不合规 {counts['schema']}，"
        f"其中 conditions {counts['conditions']}、exceptions {counts['exceptions']}；"
        f"引用不符 {counts['unknown_evidence']}，逐字出处不符 {counts['quote_not_found']}，"
        f"重复 {counts['duplicate']}，整批输出不合规 {counts['invalid_output']}，其他 {counts['other']}）。"
        "请按类别核对模型输出结构、解析片段与原文出处后重试失败的规则任务；失败不表示原文没有规则。"
    )
