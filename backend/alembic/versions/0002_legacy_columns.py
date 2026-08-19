"""move legacy startup migrations into Alembic."""

from alembic import op
from sqlalchemy import inspect, text

revision = "0002_legacy_columns"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    prd_columns = _columns("prd_documents")
    if "source_type" not in prd_columns:
        op.execute(text("ALTER TABLE prd_documents ADD COLUMN source_type VARCHAR(20) NOT NULL DEFAULT 'upload'"))
    if "source_ref" not in prd_columns:
        op.execute(text("ALTER TABLE prd_documents ADD COLUMN source_ref VARCHAR(100)"))
        op.execute(text("CREATE INDEX IF NOT EXISTS ix_prd_documents_source_ref ON prd_documents(source_ref)"))
    if "image_tokens" not in prd_columns:
        op.execute(text("ALTER TABLE prd_documents ADD COLUMN image_tokens TEXT"))

    case_columns = _columns("test_cases")
    if "edited" not in case_columns:
        op.execute(text("ALTER TABLE test_cases ADD COLUMN edited BOOLEAN NOT NULL DEFAULT 0"))
    if "edited_at" not in case_columns:
        op.execute(text("ALTER TABLE test_cases ADD COLUMN edited_at DATETIME"))
    if "priority" not in case_columns:
        op.execute(text("ALTER TABLE test_cases ADD COLUMN priority VARCHAR(4)"))
    if "origin" not in case_columns:
        op.execute(text("ALTER TABLE test_cases ADD COLUMN origin VARCHAR(20)"))


def downgrade() -> None:
    # 兼容 SQLite 旧版本，补列不做不可移植的回滚。
    pass
