from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonList, JsonObject, TimestampMixin
from backend.db.types import SearchStatus

if TYPE_CHECKING:
    from backend.db.models.conversation import Thread
    from backend.db.models.papers import Paper
    from backend.db.models.runtime import AgentRun


class SearchSession(TimestampMixin, Base):
    __tablename__ = "search_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_preference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default=SearchStatus.draft.value, nullable=False, index=True)
    selected_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "search_candidates.id",
            name="fk_search_sessions_selected_candidate_id_search_candidates",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    thread: Mapped[Thread | None] = relationship()
    run: Mapped[AgentRun | None] = relationship(back_populates="search_sessions")
    candidates: Mapped[list[SearchCandidate]] = relationship(
        back_populates="search_session",
        cascade="all, delete-orphan",
        foreign_keys="SearchCandidate.search_session_id",
    )
    selected_candidate: Mapped[SearchCandidate | None] = relationship(foreign_keys=[selected_candidate_id])


class SearchCandidate(Base):
    __tablename__ = "search_candidates"
    __table_args__ = (UniqueConstraint("search_session_id", "rank", name="uq_search_candidates_session_rank"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    search_session_id: Mapped[int] = mapped_column(ForeignKey("search_sessions.id", ondelete="CASCADE"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(500))
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String(500))
    arxiv_id: Mapped[str | None] = mapped_column(String(120))
    openalex_id: Mapped[str | None] = mapped_column(String(120))
    landing_page_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    search_session: Mapped[SearchSession] = relationship(
        back_populates="candidates",
        foreign_keys=[search_session_id],
    )
    paper: Mapped[Paper | None] = relationship()
