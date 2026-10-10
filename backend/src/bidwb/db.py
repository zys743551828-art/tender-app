"""数据库访问基础。

业务库的唯一事实来源是 ``contracts/schema.sql``（含触发器与授权），Alembic 迁移直接执行它；
代码里用显式 SQL（SQLAlchemy ``text``）读写，不维护第二份 ORM 模型，避免两份定义漂移。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import RowMapping

from bidwb.errors import DomainError

Row = RowMapping
Params = Mapping[str, Any]


def make_engine(url: str, *, pool_size: int = 10, pool_timeout: float = 10.0, application_name: str = "bidwb") -> Engine:
    return create_engine(
        url,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"application_name": application_name, "options": "-c timezone=UTC"},
    )


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """一个业务用例一个事务：正常返回提交，抛出异常回滚。

    例外：``commit_on_error`` 为真的领域错误（如上传内容校验失败后的隔离记录）先提交再向外抛出。
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        except DomainError as exc:
            if exc.commit_on_error:
                trans.commit()
            else:
                trans.rollback()
            raise
        except BaseException:
            trans.rollback()
            raise
        else:
            trans.commit()


def one(conn: Connection, sql: str, params: Params | None = None) -> Row | None:
    return conn.execute(text(sql), params or {}).mappings().first()


def all_(conn: Connection, sql: str, params: Params | None = None) -> list[Row]:
    return list(conn.execute(text(sql), params or {}).mappings().all())


def run(conn: Connection, sql: str, params: Params | None = None) -> int:
    """执行写语句，返回受影响行数。"""
    return conn.execute(text(sql), params or {}).rowcount


def scalar(conn: Connection, sql: str, params: Params | None = None) -> Any:
    return conn.execute(text(sql), params or {}).scalar()
