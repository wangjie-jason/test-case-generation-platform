from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.database import Base
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# SQLite 不支持大多数 ALTER TABLE，batch 模式会自动改用「建新表 → 拷数据 → 换名」，
# 后续要改列类型/加约束时才不会卡住（纯 ADD COLUMN 不受影响）。
_RENDER_AS_BATCH = settings.SYNC_DATABASE_URL.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=_RENDER_AS_BATCH)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 直接用 URL 建引擎，不走 engine_from_config(get_section(...))：程序内启动时
    # （database.run_migrations 构造的 Config 没有 ini 文件，get_section 拿到空 dict，
    # engine_from_config 会因缺 sqlalchemy.url 报错）。URL 已由 set_main_option 统一为
    # settings.SYNC_DATABASE_URL，CLI 与程序内两条路径一致。
    connectable = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=_RENDER_AS_BATCH)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
