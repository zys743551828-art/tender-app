"""规则包保存条款级补遗效力依据，历史包默认没有效力更正。"""

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    path = Path(__file__).resolve().parent.parent / "sql/0003_rule_effectivity.sql"
    op.get_bind().exec_driver_sql(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("前进式迁移；回退请恢复迁移前备份")
