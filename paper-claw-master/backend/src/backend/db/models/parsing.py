from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonList, JsonObject, TimestampMixin
from backend.db.types import ParseJobStatus, ParseQualityStatus, ParseStrategy, ProcessedDocumentStatus, SectionRole

if TYPE_CHECKING:
    from backend.db.models.artifacts import Artifact
    from backend.db.models.papers import Paper
    from backend.db.models.runtime import AgentRun


class ParseJob(TimestampMixin, Base):
    __tablename__ = "parse_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    input_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    strategy: Mapped[str] = mapped_column(String(80), default=ParseStrategy.pdf_text.value, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=ParseJobStatus.pending.value, nullable=False, index=True)
    parser_version: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    settings_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)
    metrics_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="parse_jobs")
    run: Mapped[AgentRun | None] = relationship()
    input_artifact: Mapped[Artifact | None] = relationship()
    events: Mapped[list[ParserEvent]] = relationship(back_populates="parse_job", cascade="all, delete-orphan")
    parsed_document: Mapped[ParsedDocument | None] = relationship(back_populates="parse_job", cascade="all, delete-orphan")


class ParserEvent(Base):
    __tablename__ = "parser_events"
    __table_args__ = (UniqueConstraint("parse_job_id", "sequence", name="uq_parser_events_parse_job_sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parse_job_id: Mapped[int] = mapped_column(ForeignKey("parse_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    level: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    parse_job: Mapped[ParseJob] = relationship(back_populates="events")
    paper: Mapped[Paper] = relationship()


class ParsedDocument(TimestampMixin, Base):
    __tablename__ = "parsed_documents"
    __table_args__ = (UniqueConstraint("parse_job_id", name="uq_parsed_documents_parse_job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    parse_job_id: Mapped[int] = mapped_column(ForeignKey("parse_jobs.id", ondelete="CASCADE"), nullable=False)
    source_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    parser_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    plain_text: Mapped[str | None] = mapped_column(Text)
    markdown_content: Mapped[str | None] = mapped_column(Text)
    json_content: Mapped[JsonDict | None] = mapped_column(JsonObject)
    quality_status: Mapped[str] = mapped_column(String(40), default=ParseQualityStatus.unknown.value, nullable=False)
    quality_summary: Mapped[str | None] = mapped_column(Text)

    paper: Mapped[Paper] = relationship()
    parse_job: Mapped[ParseJob] = relationship(back_populates="parsed_document")
    source_artifact: Mapped[Artifact | None] = relationship()
    processed_documents: Mapped[list[ProcessedDocument]] = relationship(back_populates="parsed_document", cascade="all, delete-orphan")


class ProcessedDocument(TimestampMixin, Base):
    __tablename__ = "processed_documents"
    __table_args__ = (UniqueConstraint("paper_id", "version", name="uq_processed_documents_paper_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    parsed_document_id: Mapped[int] = mapped_column(ForeignKey("parsed_documents.id", ondelete="CASCADE"), nullable=False)
    parse_job_id: Mapped[int] = mapped_column(ForeignKey("parse_jobs.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=ProcessedDocumentStatus.processing.value, nullable=False)
    content_markdown: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    quality_status: Mapped[str] = mapped_column(String(40), default=ParseQualityStatus.unknown.value, nullable=False)
    quality_summary: Mapped[str | None] = mapped_column(Text)
    processing_profile: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="processed_documents")
    parsed_document: Mapped[ParsedDocument] = relationship(back_populates="processed_documents")
    parse_job: Mapped[ParseJob] = relationship()
    sections: Mapped[list[DocumentSection]] = relationship(back_populates="processed_document", cascade="all, delete-orphan")
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="processed_document", cascade="all, delete-orphan")
    references: Mapped[list[PaperReference]] = relationship(back_populates="processed_document", cascade="all, delete-orphan")


class DocumentSection(TimestampMixin, Base):
    __tablename__ = "document_sections"
    __table_args__ = (UniqueConstraint("processed_document_id", "section_index", name="uq_document_sections_doc_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    processed_document_id: Mapped[int] = mapped_column(ForeignKey("processed_documents.id", ondelete="CASCADE"), nullable=False)
    section_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(40), default=SectionRole.unknown.value, nullable=False)
    heading_path_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(Text)
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    quality_flags_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    processed_document: Mapped[ProcessedDocument] = relationship(back_populates="sections")


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("processed_document_id", "chunk_key", name="uq_document_chunks_doc_key"),
        UniqueConstraint("processed_document_id", "chunk_index", name="uq_document_chunks_doc_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    processed_document_id: Mapped[int] = mapped_column(ForeignKey("processed_documents.id", ondelete="CASCADE"), nullable=False)
    chunk_key: Mapped[str] = mapped_column(String(120), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(40), default=SectionRole.body.value, nullable=False)
    heading_path_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    source_section_ids_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector)
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    processed_document: Mapped[ProcessedDocument] = relationship(back_populates="chunks")


class PaperReference(TimestampMixin, Base):
    __tablename__ = "paper_references"
    __table_args__ = (UniqueConstraint("processed_document_id", "reference_index", name="uq_paper_references_doc_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    processed_document_id: Mapped[int] = mapped_column(ForeignKey("processed_documents.id", ondelete="CASCADE"), nullable=False)
    reference_index: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(1000))
    authors_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String(500))
    arxiv_id: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(Text)
    resolved_paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id", ondelete="SET NULL"))
    confidence: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    processed_document: Mapped[ProcessedDocument] = relationship(back_populates="references")
    resolved_paper: Mapped[Paper | None] = relationship()
