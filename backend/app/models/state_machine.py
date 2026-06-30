import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_local


class StateMachine(Base):
    __tablename__ = "state_machines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    entity: Mapped[str] = mapped_column(String(200), nullable=False)
    from_state: Mapped[str] = mapped_column(String(200), nullable=False)
    to_state: Mapped[str] = mapped_column(String(200), nullable=False)
    condition: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
