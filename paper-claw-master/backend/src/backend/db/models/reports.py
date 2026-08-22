from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonList, JsonObject, TimestampMixin, utcnow
from backend.db.types import EvidenceType, ReportSourceScope, ReportStatus, ReportType

if TYPE_CHECKING:
    from backend.db.models.conversation import Thread
    from backend.db.models.papers import Paper
    from backend.db.models.parsing import DocumentChunk, PaperReference, ProcessedDocument
    from backend.db.models.runtime import AgentRun


class Report(TimestampMixin, Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id", ondelete="SET NULL"), index=True)
    processed_document_id: Mapped[int | None] = mapped_column(ForeignKey("processed_documents.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    report_type: Mapped[str] = mapped_column(String(80), default=ReportType.paper_summary.value, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=ReportStatus.draft.value, nullable=False, index=True)
    instructions: Mapped[str | None] = mapped_column(Text)
    markdown_content: Mapped[str | None] = mapped_column(Text)
    json_content: Mapped[JsonDict | None] = mapped_column(JsonObject)
    source_scope: Mapped[str] = mapped_column(String(80), default=ReportSourceScope.mixed.value, nullable=False)
    source_refs_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    thread: Mapped[Thread | None] = relationship()
    run: Mapped[AgentRun | None] = relationship()
    paper: Mapped[Paper | None] = relationship()
    processed_document: Mapped[ProcessedDocument | None] = relationship()
    evidence: Mapped[list[ReportEvidence]] = relationship(back_populates="report", cascade="all, delete-orphan")


class ReportEvidence(Base):
    __tablename__ = "report_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), default=EvidenceType.chunk.value, nullable=False)
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("document_chunks.id", ondelete="SET NULL"))
    reference_id: Mapped[int | None] = mapped_column(ForeignKey("paper_references.id", ondelete="SET NULL"))
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id", ondelete="SET NULL"))
    quote_text: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    report: Mapped[Report] = relationship(back_populates="evidence")
    chunk: Mapped[DocumentChunk | None] = relationship()
    reference: Mapped[PaperReference | None] = relationship()
    paper: Mapped[Paper | None] = relationship()
