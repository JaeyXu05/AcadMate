from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonObject, TimestampMixin
from backend.db.types import EventLevel, RunStatus, WorkflowName

if TYPE_CHECKING:
    from backend.db.models.conversation import Message, Thread
    from backend.db.models.search import SearchSession


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"), index=True)
    workflow: Mapped[str] = mapped_column(String(80), default=WorkflowName.analysis_report.value, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default=RunStatus.pending.value, nullable=False, index=True)
    deepagent_run_id: Mapped[str | None] = mapped_column(String(255), index=True)
    deepagent_thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    input_json: Mapped[JsonDict | None] = mapped_column(JsonObject)
    output_json: Mapped[JsonDict | None] = mapped_column(JsonObject)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    thread: Mapped[Thread | None] = relationship(back_populates="agent_runs")
    events: Mapped[list[AgentRunEvent]] = relationship(back_populates="run", cascade="all, delete-orphan")
    messages: Mapped[list[Message]] = relationship(back_populates="run")
    search_sessions: Mapped[list[SearchSession]] = relationship(back_populates="run")


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_agent_run_events_run_id_sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    level: Mapped[str] = mapped_column(String(40), default=EventLevel.info.value, nullable=False)
    payload_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AgentRun] = relationship(back_populates="events")
