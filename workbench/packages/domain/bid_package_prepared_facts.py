"""Bounded display previews from the exact prepared snapshot, never current fact heads."""

import json

from packages.domain import bid_package_execution_input_repository as inputs
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, connection, sha
from packages.identity import pagination


def preview(item):
    fact = item["fact"]
    raw = fact["value_jsonb_text"]
    scalar = raw.strip()
    # Only decode JSON strings. Numeric/object previews retain PostgreSQL's exact text.
    display = (
        json.loads(scalar)
        if scalar.startswith('"')
        else {"true": "是", "false": "否", "null": "未填写"}.get(scalar, raw)
    )
    text = {
        "name": fact["name"],
        "subject": fact["subject"],
        "scope": fact["scope"],
        "value_preview": display,
        "unit": fact["unit"],
    }
    return {
        "fact_id": fact["id"],
        "fact_item_digest": digest(item),
        **{key: value[:240] if value is not None else None for key, value in text.items()},
        "preview_truncated": any(value is not None and len(value) > 240 for value in text.values()),
    }


def page(packet, limit=20, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise DomainError("INVALID_REQUEST", "每页事实数量须为1至100", 422)
    cm = packet.snapshot()["context"]["manifest"]
    facts = cm["facts"]
    rows = sorted(facts["items"], key=lambda item: item["fact"]["id"])
    if len({item["fact"]["id"] for item in rows}) != len(rows):
        raise DomainError("PACKAGE_EXECUTION_INPUT_CORRUPT", "准备输入事实身份不唯一", 500)
    scope = sha(
        {
            "directory": "prepared-facts/1",
            "scope": packet.scope,
            "frozen_id": packet.frozen_id,
            "prepared_id": packet.input_id,
            "prepared_digest": packet.digest,
        }
    )
    after = pagination.decode(cursor, scope)
    if after:
        if after[0] != cm["facts_digest"] or str(after[-1]) not in {
            item["fact"]["id"] for item in rows
        }:
            raise DomainError("INVALID_CURSOR", "事实目录游标不属于明确准备输入", 422)
        rows = [item for item in rows if item["fact"]["id"] > str(after[-1])]
    try:
        items = [preview(item) for item in rows[:limit]]
    except (ValueError, TypeError, KeyError) as error:
        raise DomainError(
            "PACKAGE_EXECUTION_INPUT_CORRUPT", "原事实摘要无法按准备快照读取", 500
        ) from error
    more = len(rows) > limit
    return {
        **dict(
            zip(("bid_id", "package_id", "revision_id", "inventory_id"), packet.scope, strict=True)
        ),
        "frozen_input_id": packet.frozen_id,
        "execution_input_id": packet.input_id,
        "execution_input_digest": packet.digest,
        "facts_digest": cm["facts_digest"],
        "fact_set_id": facts["head"]["fact_set_id"],
        "fact_count": len(facts["items"]),
        "items": items,
        "has_more": more,
        "next_cursor": pagination.encode(scope, [cm["facts_digest"], items[-1]["fact_id"]])
        if more
        else None,
    }


def directory(scope, frozen_id, input_id, limit=20, cursor=None):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = inputs.load_packet(c, scope, frozen_id, input_id)
        return page(packet, limit, cursor)
