"""冻结规则提取的解析来源；历史规则包保持未知。"""

from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    path = Path(__file__).resolve().parent.parent / "sql/0006_rule_parse_identity.sql"
    op.get_bind().exec_driver_sql(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("前进式迁移；回退请恢复迁移前备份")
