"""初始结构：执行 sql/0001_initial.sql（与 contracts/schema.sql 逐字一致）。

已有部署通过后续增量迁移升级，初始结构不包含后续版本新增的表。

约定：本库的迁移是前进式的。追加保存的表有触发器禁止改写，因此不提供数据级降级；
需要回退时恢复迁移前备份（见 deploy/README.md）。新增表的迁移必须同时写明对 app_api / app_worker 的授权，
因为 worker 使用列级授权，不能依赖 ALTER DEFAULT PRIVILEGES。
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL = Path(__file__).resolve().parent.parent / "sql" / "0001_initial.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    msg = "初始结构不支持降级；请从备份恢复"
    raise RuntimeError(msg)
