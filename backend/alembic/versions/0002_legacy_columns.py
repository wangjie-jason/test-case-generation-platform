"""move legacy startup migrations into Alembic.

只对**改造前就存在的老库**有实际作用：那些库由旧 init_db 的 _migrate_* 逐个补列，
补到哪一步取决于它最后一次启动的版本，故这里逐列判断存在性再补。

新库不会走到任何一条分支——0001 已把这些列写进建表语句。留着它是为了让老库有一条
可走的升级路径，不是冗余。

老库首次接入 Alembic 需要先打标记，否则 0001 会去 CREATE TABLE 已存在的表而报错
（0001 改成显式建表后不再有 create_all 那种「表已存在就整表跳过」的静默行为）：
    alembic stamp 0001_initial_schema   # 声明「建表那步老库早就做过了」
    alembic upgrade head                # 只跑 0002 补列
新库直接 `alembic upgrade head` 即可。
"""
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
