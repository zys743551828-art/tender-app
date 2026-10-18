"""冻结解析、证据集合与覆盖缺口，旧快照身份保留未知。"""

from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    path = Path(__file__).resolve().parent.parent / "sql/0005_snapshot_parse_identity.sql"
    op.get_bind().exec_driver_sql(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("前进式迁移；回退请恢复迁移前备份")
