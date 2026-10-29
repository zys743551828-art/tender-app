"""Read-only frozen-input summaries; no current heads, evidence roots or object IO."""

from datetime import datetime
from typing import Any

from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, clean, sha
from packages.identity import pagination


def directory(
    c: Any, scope: tuple[str, str, str, str], *, limit: int = 20, cursor: str | None = None
):
    if not 1 <= limit <= 100:
        raise DomainError("INVALID_REQUEST", "目录每页数量须为1至100", 422)
    if (
        c.execute(
            """SELECT 1 FROM design.bid_package_requirement_inventories
        WHERE bid_id=%s AND package_id=%s AND target_revision_id=%s AND id=%s""",
            scope,
        ).fetchone()
        is None
    ):
        raise PackageError("PACKAGE_REVIEW_FROZEN_INPUT_NOT_FOUND")
    binding = sha({"directory": "package-review-frozen-inputs/1", "scope": scope})
    after = pagination.decode(cursor, binding)
    at = None
    if after:
        try:
            at = datetime.fromisoformat(after[0].replace("Z", "+00:00"))
            if at.tzinfo is None:
                raise ValueError("timezone_required")
        except (ValueError, OverflowError):
            raise DomainError(
                "INVALID_CURSOR", "冻结输入目录游标无效，请重新读取目录", 422
            ) from None
    rows = c.execute(
        """SELECT id,digest,actor_id,frozen_at,
        manifest->>'input_digest' AS input_digest,manifest->>'context_digest' AS context_digest
        FROM design.bid_package_review_inputs
        WHERE bid_id=%s AND package_id=%s AND revision_id=%s AND inventory_id=%s
        AND (%s::timestamptz IS NULL OR (frozen_at,id)<(%s::timestamptz,%s::uuid))
        ORDER BY frozen_at DESC,id DESC LIMIT %s""",
        (*scope, at, at, after[-1] if after else None, limit + 1),
    ).fetchall()
    items = clean(rows[:limit])
    more = len(rows) > limit
    return {
        **dict(zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)),
        "items": items,
        "has_more": more,
        "next_cursor": pagination.encode(binding, [items[-1]["frozen_at"], items[-1]["id"]])
        if more
        else None,
    }
