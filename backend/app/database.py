from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 本地时区。SQLite 的 func.now() 返回 UTC，会导致时间比真实生成时间早 8 小时，
# 这里统一改用本地时间（naive），存入数据库即为可直接展示的北京时间。
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 轻量迁移：给旧库的 prd_documents 补上飞书来源字段。SQLite 的 ALTER TABLE 加列是幂等安全的，
        # 但重复执行会报错，所以先查 pragma。项目没接 Alembic，先用这种手工方式撑住。
        await conn.run_sync(_migrate_prd_document_source_columns)
        await conn.run_sync(_migrate_test_case_edit_columns)
        await conn.run_sync(_migrate_test_case_priority_column)
        await conn.run_sync(_migrate_test_case_origin_column)


def _migrate_prd_document_source_columns(sync_conn) -> None:
    from sqlalchemy import text

    cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(prd_documents)"))}
    if "source_type" not in cols:
        sync_conn.execute(text("ALTER TABLE prd_documents ADD COLUMN source_type VARCHAR(20) NOT NULL DEFAULT 'upload'"))
    if "source_ref" not in cols:
        sync_conn.execute(text("ALTER TABLE prd_documents ADD COLUMN source_ref VARCHAR(100)"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prd_documents_source_ref ON prd_documents(source_ref)"))
    if "image_tokens" not in cols:
        # SQLite 没有原生 JSON 类型；SQLAlchemy 的 JSON 会退化成 TEXT，读写自动 json.loads/dumps。
        sync_conn.execute(text("ALTER TABLE prd_documents ADD COLUMN image_tokens TEXT"))


def _migrate_test_case_edit_columns(sync_conn) -> None:
    """审核阶段允许人工微调用例文案。老库要补两列，SQLite 加列不能带非常量 default，
    这里给 edited 一个 SQL 层的 0 默认值即可，新写入走 ORM 的 Python 默认（False）。"""
    from sqlalchemy import text

    cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(test_cases)"))}
    if "edited" not in cols:
        sync_conn.execute(text("ALTER TABLE test_cases ADD COLUMN edited BOOLEAN NOT NULL DEFAULT 0"))
    if "edited_at" not in cols:
        sync_conn.execute(text("ALTER TABLE test_cases ADD COLUMN edited_at DATETIME"))


def _migrate_test_case_priority_column(sync_conn) -> None:
    """LLM 生成的 priority 之前一直没入库，导致审核/历史/编辑三处都读不到等级。
    老库补一列 priority（可空），历史用例读到 None 前端兜底展示为 P2 默认档。"""
    from sqlalchemy import text

    cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(test_cases)"))}
    if "priority" not in cols:
        sync_conn.execute(text("ALTER TABLE test_cases ADD COLUMN priority VARCHAR(4)"))


def _migrate_test_case_origin_column(sync_conn) -> None:
    """标记用例的产出阶段（'supplement' = 评审后定向补充），让前端能区分补充用例。
    老库补一列 origin（可空）：那批用例落库时未记录阶段，事后无法可靠反推，统一留 NULL，
    前端对 NULL 不显示标签，不把猜测当事实。"""
    from sqlalchemy import text

    cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(test_cases)"))}
    if "origin" not in cols:
        sync_conn.execute(text("ALTER TABLE test_cases ADD COLUMN origin VARCHAR(20)"))
