"""服务器可恢复的构建历史；刷新发现不依赖浏览器记住构建ID。"""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from apps.api.auth import auth
from packages.authoring.build_views import build_view
from packages.domain.runtime import connection, decode_cursor, encode_cursor, fetch

router = APIRouter(prefix="/api/v1", tags=["history"])


@router.get("/bids/{bid_id}/builds")
def list_builds(
    bid_id: UUID,
    r: Request,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    draft_id: UUID | None = None,
):
    auth(r)
    scope = f"builds:{bid_id}:1" if draft_id is None else f"builds:{bid_id}:draft:{draft_id}:1"
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        fetch(c, "SELECT id FROM bids WHERE id=%s", (bid_id,))
        if draft_id is not None:
            fetch(c, "SELECT id FROM drafts WHERE bid_id=%s AND id=%s", (bid_id, draft_id))
        if cursor:
            at, identity = decode_cursor(cursor, scope=scope)
            rows = c.execute(
                """SELECT b.id,o.created_at FROM builds b
                JOIN operations o ON o.id=b.operation_id AND o.bid_id=b.bid_id
                JOIN build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
                JOIN draft_snapshots s ON s.id=i.draft_snapshot_id AND s.bid_id=b.bid_id
                WHERE b.bid_id=%s AND (%s::uuid IS NULL OR s.draft_id=%s)
                AND(o.created_at,b.id)<(%s,%s)
                ORDER BY o.created_at DESC,b.id DESC LIMIT %s""",
                (bid_id, draft_id, draft_id, at, identity, limit + 1),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT b.id,o.created_at FROM builds b
                JOIN operations o ON o.id=b.operation_id AND o.bid_id=b.bid_id
                JOIN build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
                JOIN draft_snapshots s ON s.id=i.draft_snapshot_id AND s.bid_id=b.bid_id
                WHERE b.bid_id=%s AND (%s::uuid IS NULL OR s.draft_id=%s)
                ORDER BY o.created_at DESC,b.id DESC LIMIT %s""",
                (bid_id, draft_id, draft_id, limit + 1),
            ).fetchall()
        more = len(rows) > limit
        items = rows[:limit]
        return {
            "items": [build_view(c, row["id"]) for row in items],
            "has_more": more,
            "next_cursor": encode_cursor(items[-1], scope=scope) if more else None,
        }
