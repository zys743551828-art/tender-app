"""追加审计。审计行与业务写入在同一事务，业务回滚时审计一并回滚（拒绝类事件另走日志）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection

from bidwb import db
from bidwb.util import new_id, utcnow


def record(
    conn: Connection,
    *,
    actor_id: str | None,
    project_id: str | None,
    action: str,
    object_kind: str,
    object_id: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.run(
        conn,
        """INSERT INTO audit_events(id,project_id,actor_id,action,object_kind,object_id,request_id,details_json,created_at)
           VALUES (:id,:project_id,:actor_id,:action,:kind,:oid,:rid,CAST(:details AS jsonb),:now)""",
        {
            "id": new_id("aud"),
            "project_id": project_id,
            "actor_id": actor_id,
            "action": action,
            "kind": object_kind,
            "oid": object_id,
            "rid": request_id,
            "details": json.dumps(details or {}, ensure_ascii=False),
            "now": utcnow(),
        },
    )
