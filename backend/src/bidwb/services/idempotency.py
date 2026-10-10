"""写接口幂等。

绑定“成员 + 幂等键 + 操作”：同键同请求返回首次的响应（不再产生副作用）；同键不同请求返回 409
``idempotency_conflict``。响应与业务写入在同一事务内保存，因此“执行了但没记住”不会发生。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection

from bidwb import db
from bidwb.errors import Conflict, DomainError, Unprocessable
from bidwb.util import canonical_json, sha256_hex

IDEMPOTENCY_MIN, IDEMPOTENCY_MAX = 8, 128


def run_idempotent(
    conn: Connection,
    *,
    member_id: str,
    key: str,
    operation: str,
    request: Any,
    handler: Callable[[], tuple[int, dict[str, Any]]],
) -> tuple[int, dict[str, Any]]:
    """首次执行 ``handler`` 并保存其 ``(状态码, JSON 响应)``；重放时直接返回保存的结果。"""
    if not IDEMPOTENCY_MIN <= len(key) <= IDEMPOTENCY_MAX:
        raise Unprocessable("invalid_idempotency_key", "Idempotency-Key 长度应为 8–128 个字符")
    request_hash = sha256_hex(canonical_json(request))
    # 先占位再执行，使并发的同键请求在主键上串行，后到者等待先到者提交后读取其结果。
    inserted = db.one(
        conn,
        """INSERT INTO idempotency_keys(member_id,idem_key,operation,request_hash,response_status,response_json)
           VALUES (:m,:k,:op,:h,0,'{}'::jsonb) ON CONFLICT DO NOTHING RETURNING 1 AS ok""",
        {"m": member_id, "k": key, "op": operation, "h": request_hash},
    )
    if inserted is None:
        row = db.one(
            conn,
            "SELECT request_hash,response_status,response_json FROM idempotency_keys WHERE member_id=:m AND idem_key=:k AND operation=:op",
            {"m": member_id, "k": key, "op": operation},
        )
        if row is None or row["request_hash"] != request_hash:
            raise Conflict("idempotency_conflict", "同一个幂等键已用于不同的请求")
        if row["response_status"] == 0:  # 理论上不可达：占位与响应在同一事务
            raise Conflict("idempotency_in_progress", "相同请求仍在处理，请稍后重试")
        return int(row["response_status"]), dict(row["response_json"])
    try:
        status, body = handler()
    except DomainError as exc:
        if exc.commit_on_error:
            # 这类错误会连同占位一起提交（例如上传隔离记录要保留）；占位必须撤掉，否则同键重放会卡在“处理中”
            db.run(
                conn,
                "DELETE FROM idempotency_keys WHERE member_id=:m AND idem_key=:k AND operation=:op",
                {"m": member_id, "k": key, "op": operation},
            )
        raise
    db.run(
        conn,
        """UPDATE idempotency_keys SET response_status=:s, response_json=CAST(:b AS jsonb)
           WHERE member_id=:m AND idem_key=:k AND operation=:op""",
        {"s": status, "b": json.dumps(body, ensure_ascii=False, default=str), "m": member_id, "k": key, "op": operation},
    )
    return status, body
