import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_local


class User(Base):
    """登录用户。账号由管理员创建，不开放注册；停用（is_active=0）而非硬删除。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # bcrypt 哈希固定 60 字符，留少量余量。
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)


class UserLlmConfig(Base):
    """用户个人的大模型凭据（与 users 1:1）。

    api_key 只以 Fernet 密文落库，接口回显走 api_key_masked，任何接口都不返回明文。
    未配置该行的用户走全局兜底模型（settings.LLM_API_KEY）。
    """

    __tablename__ = "user_llm_configs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # 落库时算好的脱敏串（如 sk-...ab12），列表/回显直接用，避免每次解密。
    api_key_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)
