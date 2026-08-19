from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 本地时区。SQLite 的 func.now() 返回 UTC，会导致时间比真实生成时间早 8 小时，
# 这里统一改用本地时间（naive），存入数据库即为可直接展示的北京时间。
# 数据库结构由 Alembic 管理；应用进程不再在启动时隐式建表或 ALTER TABLE。
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


def run_migrations() -> None:
    """启动时自动执行 Alembic 迁移，与 init_db 时代一样：起服务即建表/补列，无需手工命令。

    幂等：已在 head 时是 no-op，每次启动都可以放心调。
    老库自动识别：改造前由 init_db 建的库没有 alembic_version 表却有业务表，直接 upgrade
    会让 0001 对已存在的表执行 CREATE TABLE 而报错；检测到这种库就先 stamp 0001
    （声明「建表那步早已完成」），再 upgrade 只跑 0002 补列。新库则正常从 0001 建起。

    注意：多 worker 并发 upgrade 会撞 alembic_version 表，本项目单 uvicorn 进程，无此顾虑。
    alembic 在此函数内延迟 import——CI 只装 pytest（不装 requirements.txt），而本模块被
    generator_service 等间接 import，顶部 import alembic 会让轻量测试直接 ModuleNotFoundError。
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)

    sync_engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        inspector = inspect(sync_engine)
        if not inspector.has_table("alembic_version") and inspector.has_table("test_cases"):
            command.stamp(cfg, "0001_initial_schema")
        command.upgrade(cfg, "head")
    finally:
        sync_engine.dispose()
