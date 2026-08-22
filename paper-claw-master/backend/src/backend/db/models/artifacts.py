from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonObject, TimestampMixin
from backend.db.types import AcquisitionSource, ArtifactKind, ArtifactStatus, RunStatus, StorageBackend

if TYPE_CHECKING:
    from backend.db.models.conversation import Thread
    from backend.db.models.papers import Paper, PaperSourceRecord
    from backend.db.models.runtime import AgentRun


class Artifact(TimestampMixin, Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), default=ArtifactKind.other.value, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default=ArtifactStatus.pending.value, nullable=False, index=True)
    storage_backend: Mapped[str] = mapped_column(String(80), default=StorageBackend.local.value, nullable=False)
    storage_uri: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    remote_url: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    paper_artifacts: Mapped[list[PaperArtifact]] = relationship(back_populates="artifact", cascade="all, delete-orphan")


class PaperArtifact(Base):
    __tablename__ = "paper_artifacts"
    __table_args__ = (UniqueConstraint("paper_id", "artifact_id", name="uq_paper_artifacts_paper_artifact"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("paper_source_records.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="paper_artifacts")
    artifact: Mapped[Artifact] = relationship(back_populates="paper_artifacts")
    source_record: Mapped[PaperSourceRecord | None] = relationship()


class AcquisitionJob(TimestampMixin, Base):
    __tablename__ = "acquisition_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("threads.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_source: Mapped[str] = mapped_column(String(80), default=AcquisitionSource.url.value, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=RunStatus.pending.value, nullable=False, index=True)
    input_json: Mapped[JsonDict | None] = mapped_column(JsonObject)
    result_json: Mapped[JsonDict | None] = mapped_column(JsonObject)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    thread: Mapped[Thread | None] = relationship()
    run: Mapped[AgentRun | None] = relationship()
    paper: Mapped[Paper] = relationship()
