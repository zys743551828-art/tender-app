"""可选本地向量检索的派生索引；纯 PostgreSQL 也可迁移，扩展另由管理员安装。"""

from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    path = Path(__file__).resolve().parent.parent / "sql/0002_evidence_embeddings.sql"
    op.get_bind().exec_driver_sql(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("前进式迁移；回退请恢复迁移前备份")
