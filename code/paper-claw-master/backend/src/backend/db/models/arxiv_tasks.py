from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, JsonDict, JsonList, JsonObject, TimestampMixin
from backend.db.types import ArxivTaskDailyStatus, ArxivTaskJobKind, ArxivTaskJobStatus, ArxivTaskWindowStatus

if TYPE_CHECKING:
    pass


class ArxivTaskDailyConfig(TimestampMixin, Base):
    __tablename__ = "arxiv_task_daily_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(40), default=ArxivTaskDailyStatus.enabled.value, nullable=False, index=True)
    run_time: Mapped[str] = mapped_column(String(5), default="08:00", nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)


class ArxivTaskSubscription(TimestampMixin, Base):
    __tablename__ = "arxiv_task_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paper_links: Mapped[list[ArxivTaskPaperSubscription]] = relationship(back_populates="subscription", cascade="all, delete-orphan")
    windows: Mapped[list[ArxivTaskQueryWindow]] = relationship(back_populates="subscription")


class ArxivTaskPaper(TimestampMixin, Base):
    __tablename__ = "arxiv_task_papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    arxiv_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    arxiv_base_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    primary_category: Mapped[str | None] = mapped_column(String(40), index=True)
    categories_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    landing_page_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    journal_ref: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(500), index=True)
    raw_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    subscription_links: Mapped[list[ArxivTaskPaperSubscription]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class ArxivTaskPaperSubscription(Base):
    __tablename__ = "arxiv_task_paper_subscriptions"
    __table_args__ = (UniqueConstraint("paper_id", "subscription_id", name="uq_arxiv_task_paper_subscriptions_paper_subscription"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("arxiv_task_papers.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("arxiv_task_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    query_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    paper: Mapped[ArxivTaskPaper] = relationship(back_populates="subscription_links")
    subscription: Mapped[ArxivTaskSubscription] = relationship(back_populates="paper_links")


class ArxivTaskHarvestJob(TimestampMixin, Base):
    __tablename__ = "arxiv_task_harvest_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), default=ArxivTaskJobKind.history.value, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default=ArxivTaskJobStatus.paused.value, nullable=False, index=True)
    subscription_ids_json: Mapped[JsonList] = mapped_column(JsonObject, default=list, nullable=False)
    requested_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    requested_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    stats_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)

    windows: Mapped[list[ArxivTaskQueryWindow]] = relationship(back_populates="job")


class ArxivTaskQueryWindow(TimestampMixin, Base):
    __tablename__ = "arxiv_task_query_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("arxiv_task_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    query_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("arxiv_task_harvest_jobs.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default=ArxivTaskJobKind.history.value, nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default=ArxivTaskWindowStatus.pending.value, nullable=False, index=True)
    total_results: Mapped[int | None] = mapped_column(Integer)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_size: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    warning_code: Mapped[str | None] = mapped_column(String(120))
    parent_window_id: Mapped[int | None] = mapped_column(ForeignKey("arxiv_task_query_windows.id", ondelete="SET NULL"), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[ArxivTaskHarvestJob | None] = relationship(back_populates="windows")
    subscription: Mapped[ArxivTaskSubscription] = relationship(back_populates="windows")
    parent_window: Mapped[ArxivTaskQueryWindow | None] = relationship(remote_side=[id])
