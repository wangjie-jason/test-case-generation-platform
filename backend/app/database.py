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
