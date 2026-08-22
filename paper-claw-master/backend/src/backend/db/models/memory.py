from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonObject, TimestampMixin
from backend.db.types import MemoryScope, MemorySource, MemoryStatus, MemoryType

if TYPE_CHECKING:
    from backend.db.models.conversation import Thread
    from backend.db.models.papers import Paper


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (UniqueConstraint("path", name="uq_memories_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    memory_type: Mapped[str] = mapped_column(String(40), default=MemoryType.research_note.value, nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(40), default=MemoryScope.global_.value, nullable=False, index=True)
    scope_id: Mapped[str | None] = mapped_column(String(255), index=True)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id", ondelete="SET NULL"), index=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[JsonDict | None] = mapped_column(JsonObject)
    source: Mapped[str] = mapped_column(String(40), default=MemorySource.agent.value, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default=MemoryStatus.active.value, nullable=False, index=True)
    source_thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"))
    source_paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id", ondelete="SET NULL"))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    source_thread: Mapped[Thread | None] = relationship(foreign_keys=[source_thread_id])
    source_paper: Mapped[Paper | None] = relationship(foreign_keys=[source_paper_id])
    paper: Mapped[Paper | None] = relationship(foreign_keys=[paper_id])
