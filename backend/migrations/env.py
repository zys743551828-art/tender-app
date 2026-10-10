"""Alembic 环境：只做在线迁移，使用库属主连接串（BIDWB_MIGRATION_DATABASE_URL）。"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def _url() -> str:
    url = os.environ.get("BIDWB_MIGRATION_DATABASE_URL")
    if not url:
        msg = "未设置 BIDWB_MIGRATION_DATABASE_URL（迁移须使用库属主角色，而非 app_api/app_worker）"
        raise RuntimeError(msg)
    return url


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    msg = "不支持离线迁移：触发器与授权需要在真实库上执行并核验"
    raise RuntimeError(msg)
run_migrations_online()
