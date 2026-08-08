from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonObject, TimestampMixin
from backend.db.types import MessageRole, MessageSource, ThreadStatus, ThreadSurface

if TYPE_CHECKING:
    from backend.db.models.runtime import AgentRun


class Thread(TimestampMixin, Base):
    __tablename__ = "threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    surface: Mapped[str] = mapped_column(String(40), default=ThreadSurface.web.value, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=ThreadStatus.active.value, nullable=False, index=True)
    current_focus_paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id", ondelete="SET NULL"))
    summary: Mapped[str | None] = mapped_column(Text)
    deepagent_thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    messages: Mapped[list[Message]] = relationship(back_populates="thread", cascade="all, delete-orphan")
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="thread", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_thread_id_created_at", "thread_id", "created_at"),
        Index("ix_messages_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(40), default=MessageRole.user.value, nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[JsonDict | None] = mapped_column(JsonObject)
    source: Mapped[str] = mapped_column(String(40), default=MessageSource.human.value, nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    token_input: Mapped[int | None] = mapped_column(Integer)
    token_output: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    thread: Mapped[Thread] = relationship(back_populates="messages")
    run: Mapped[AgentRun | None] = relationship(back_populates="messages")
