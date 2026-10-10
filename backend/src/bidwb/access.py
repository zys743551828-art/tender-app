"""身份与访问。

系统只有登录这一道门：登录后的成员可以访问所有项目、执行所有操作，不区分项目岗位。
身份只取自服务端会话得到的 ``Actor``，请求体里的任何“操作者”字段都不被采信；审计记录照常写入操作者。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection

from bidwb import db
from bidwb.errors import NotFound


@dataclass(frozen=True)
class Actor:
    member_id: str
    display_name: str


def require_project(conn: Connection, actor: Actor, project_id: str) -> None:
    """项目必须存在（不存在 → 404）。登录成员对项目没有进一步的权限区分。"""
    del actor  # 访问只要求已登录；保留参数让每个用例都显式经过这一检查
    if db.one(conn, "SELECT 1 AS x FROM projects WHERE id=:p", {"p": project_id}) is None:
        raise NotFound("project_not_found")
