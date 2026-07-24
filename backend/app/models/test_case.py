import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_local


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    precondition: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    knowledge_refs: Mapped[str | None] = mapped_column(Text, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    req_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 审核阶段允许人工微调 title/precondition/steps/expected_result；覆盖原文，同时打个标，
    # 用来在统计里区分「AI 直接可用」和「AI+人工微调后可用」，不污染首发通过率。
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)
