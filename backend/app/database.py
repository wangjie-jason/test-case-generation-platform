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


def _migrate_prd_document_source_columns(sync_conn) -> None:
    from sqlalchemy import text

    cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(prd_documents)"))}
    if "source_type" not in cols:
        sync_conn.execute(text("ALTER TABLE prd_documents ADD COLUMN source_type VARCHAR(20) NOT NULL DEFAULT 'upload'"))
    if "source_ref" not in cols:
        sync_conn.execute(text("ALTER TABLE prd_documents ADD COLUMN source_ref VARCHAR(100)"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prd_documents_source_ref ON prd_documents(source_ref)"))
