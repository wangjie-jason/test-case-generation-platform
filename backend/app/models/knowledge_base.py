import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_local


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    # 重名规则按可见性区分（name 列不再全局 unique）：
    #   团队库在团队范围内不重名；个人库只要求在「同一拥有者」下不重名——
    #   不同人的个人库可以同名。用 SQLite partial unique index 表达。
    # 注意 sqlite_where 是 SQLite 方言参数，将来迁 PostgreSQL 时要换成 postgresql_where。
    __table_args__ = (
        Index("uq_kb_team_name", "name", unique=True, sqlite_where=text("visibility = 'team'")),
        Index(
            "uq_kb_personal_owner_name",
            "owner_id", "name",
            unique=True, sqlite_where=text("visibility = 'personal'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # 归属者 users.id（裸字符串列不加 FK：用户只停用不删除，无需级联）。
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 可见性：'team' = 全员可查看/引用（改删限创建者与管理员）；'personal' = 仅本人可见。
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, default="team")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)
