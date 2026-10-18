"""保存 Word 转换、实际 PDF 关系及采用决定。"""

from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    path = Path(__file__).resolve().parent.parent / "sql/0004_word_materials.sql"
    op.get_bind().exec_driver_sql(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("前进式迁移；回退请恢复迁移前备份")
