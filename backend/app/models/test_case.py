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
    # LLM 输出的用例等级 P0/P1/P2；老库补列时统一置空，前端读到 None 兜底显示为默认档
    priority: Mapped[str | None] = mapped_column(String(4), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    # 产出阶段：'supplement' = 评审后针对被删/遗漏场景定向补充的用例；生成阶段的留空。
    # 老库补列时统一为 NULL——那批用例落库时没记录阶段，事后无法可靠反推（source 一律
    # 是 'ai'、created_at 只是写库时间），所以不猜，前端对 NULL 不显示任何标签。
    origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
