"""确认卡所见项目状态；正式操作在项目锁内重新比对，不采用刷新后的输入替换旧卡。"""

from __future__ import annotations

import json

from sqlalchemy import Connection

from bidwb import db
from bidwb.errors import Conflict
from bidwb.util import sha256_hex


def fingerprint(conn: Connection, project_id: str) -> str:
    parts: list[object] = [db.scalar(conn, "SELECT revision FROM projects WHERE id=:p", {"p": project_id})]
    for query in (
        "SELECT id FROM file_versions WHERE project_id=:p ORDER BY id",
        "SELECT id FROM rule_packages WHERE project_id=:p ORDER BY id",
        "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY id",
        "SELECT id FROM input_snapshots WHERE project_id=:p ORDER BY id",
        "SELECT id,state,attempt FROM jobs WHERE project_id=:p ORDER BY id",
        "SELECT id FROM reviews WHERE project_id=:p ORDER BY id",
        "SELECT id FROM word_pdf_adoptions WHERE project_id=:p ORDER BY id",
        "SELECT id FROM submissions WHERE project_id=:p ORDER BY id",
        "SELECT id FROM outcomes WHERE project_id=:p ORDER BY id",
    ):
        parts.append([dict(r) for r in db.all_(conn, query, {"p": project_id})])
    return sha256_hex(json.dumps(parts, sort_keys=True, default=str).encode())


def require_current(conn: Connection, project_id: str, expected: str | None) -> None:
    if expected is not None and fingerprint(conn, project_id) != expected:
        raise Conflict("assistant_card_stale", "项目资料或处理状态已有变化，请重新提问生成确认卡")
