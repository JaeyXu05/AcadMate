from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonList, JsonObject, TimestampMixin
from backend.db.types import PaperStatus

if TYPE_CHECKING:
    from backend.db.models.artifacts import PaperArtifact
    from backend.db.models.parsing import ParseJob, ProcessedDocument


class Paper(TimestampMixin, Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str | None] = mapped_column(String(500))
    authors_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    keywords_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    categories_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    citation_count: Mapped[int | None] = mapped_column(Integer)
    best_pdf_url: Mapped[str | None] = mapped_column(Text)
    landing_page_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default=PaperStatus.metadata_only.value, nullable=False, index=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    identifiers: Mapped[list[PaperIdentifier]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    source_records: Mapped[list[PaperSourceRecord]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    paper_artifacts: Mapped[list[PaperArtifact]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    parse_jobs: Mapped[list[ParseJob]] = relationship(back_populates="paper")
    processed_documents: Mapped[list[ProcessedDocument]] = relationship(back_populates="paper")


class PaperIdentifier(Base):
    __tablename__ = "paper_identifiers"
    __table_args__ = (UniqueConstraint("identifier_type", "identifier_value", name="uq_paper_identifiers_type_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    identifier_type: Mapped[str] = mapped_column(String(80), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(500), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="identifiers")


class PaperSourceRecord(TimestampMixin, Base):
    __tablename__ = "paper_source_records"
    __table_args__ = (
        Index(
            "uq_paper_source_records_source_record_id",
            "source",
            "source_record_id",
            unique=True,
            postgresql_where=text("source_record_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="source_records")
