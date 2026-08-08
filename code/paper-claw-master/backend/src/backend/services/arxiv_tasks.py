from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol

from sqlalchemy.orm import Session

from backend.db.models import ArxivTaskHarvestJob, ArxivTaskSubscription
from backend.db.repositories import ArxivTaskRepository
from backend.db.types import ArxivTaskJobKind, ArxivTaskJobStatus, ArxivTaskWindowStatus
from backend.integrations.paper_sources.arxiv import ArxivClient, ArxivMetadataEntry, ArxivMetadataQueryResponse
from backend.integrations.paper_sources.factory import arxiv_rate_limiter_from_settings, paper_source_adapters_from_settings

PAGE_SIZE = 100
MAX_RESULTS_BEFORE_SPLIT = 1000
MIN_SPLIT_WINDOW = timedelta(hours=1)
MAX_WINDOW = timedelta(days=1)
WINDOW_DRIFT_TOLERANCE = timedelta(seconds=60)
PREVIEW_TIMEOUT_SECONDS = 45.0


class ArxivMetadataClient(Protocol):
    def query_metadata(self, search_query: str, *, page_size: int = 5, offset: int = 0) -> ArxivMetadataQueryResponse: ...
    def query_metadata_window(self, search_query: str, start_time: datetime, end_time: datetime, *, page_size: int = PAGE_SIZE, offset: int = 0) -> ArxivMetadataQueryResponse: ...


@dataclass(frozen=True)
class HarvestStats:
    fetched_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    page_count: int = 0

    def add(self, other: HarvestStats) -> HarvestStats:
        return HarvestStats(
            fetched_count=self.fetched_count + other.fetched_count,
            inserted_count=self.inserted_count + other.inserted_count,
            updated_count=self.updated_count + other.updated_count,
            page_count=self.page_count + other.page_count,
        )


@dataclass(frozen=True)
class WindowTarget:
    subscription: ArxivTaskSubscription
    start: datetime
    end: datetime


class ArxivTaskService:
    def __init__(self, session: Session, *, arxiv_client: ArxivMetadataClient | None = None) -> None:
        self.session = session
        self.repository = ArxivTaskRepository(session)
        self._arxiv_client = arxiv_client

    @property
    def arxiv_client(self) -> ArxivMetadataClient:
        if self._arxiv_client is None:
            self._arxiv_client = _arxiv_client_from_settings()
        return self._arxiv_client

    @arxiv_client.setter
    def arxiv_client(self, value: ArxivMetadataClient) -> None:
        self._arxiv_client = value

    def create_subscription(self, *, name: str, query: str, description: str | None = None, enabled: bool = True) -> ArxivTaskSubscription:
        name = _validate_name(name)
        query = _validate_query(query)
        return self.repository.create_subscription(name=name, query=query, description=_clean_optional(description), enabled=enabled)

    def update_subscription(self, subscription_id: int, *, name: str, query: str, description: str | None = None, enabled: bool = True) -> ArxivTaskSubscription:
        subscription = self.repository.get_subscription(subscription_id)
        if subscription is None:
            raise ValueError("arXiv task subscription not found")
        name = _validate_name(name)
        query = _validate_query(query)
        return self.repository.update_subscription(subscription, name=name, query=query, description=_clean_optional(description), enabled=enabled)

    def delete_subscription(self, subscription_id: int) -> None:
        if not self.repository.delete_subscription(subscription_id):
            raise ValueError("arXiv task subscription not found")

    def test_query(self, query: str, *, max_results: int = 5) -> ArxivMetadataQueryResponse:
        client = self._arxiv_client or _arxiv_preview_client()
        return client.query_metadata(_validate_query(query), page_size=max_results)

    def enqueue_daily_run(self) -> ArxivTaskHarvestJob:
        subscriptions = self.repository.enabled_subscriptions()
        now = _now()
        config = self.repository.daily_config()
        config.last_started_at = now
        return self.repository.create_job(
            ArxivTaskJobKind.daily.value,
            [subscription.id for subscription in subscriptions],
            status=ArxivTaskJobStatus.pending.value,
            requested_end=now,
            stats_json={},
        )

    def create_history_job(self, subscription_ids: list[int], start_time: datetime, end_time: datetime) -> ArxivTaskHarvestJob:
        self._validate_subscription_ids(subscription_ids)
        start_time = _as_utc(start_time)
        end_time = _as_utc(end_time)
        if end_time <= start_time:
            raise ValueError("History job end_time must be after start_time")
        return self.repository.create_job(
            ArxivTaskJobKind.history.value,
            subscription_ids,
            requested_start=start_time,
            requested_end=end_time,
            status=ArxivTaskJobStatus.paused.value,
            stats_json={},
        )

    def start_job(self, job_id: int) -> ArxivTaskHarvestJob:
        job = self.session.get(ArxivTaskHarvestJob, job_id)
        if job is None:
            raise ValueError("History job not found")
        if job.kind != ArxivTaskJobKind.history.value:
            raise ValueError("Only history jobs can be manually started")
        if job.status in {ArxivTaskJobStatus.succeeded.value, ArxivTaskJobStatus.stopped.value}:
            raise ValueError("History job cannot be started from its current status")
        now = _now()
        job.status = ArxivTaskJobStatus.running.value
        job.started_at = job.started_at or now
        job.finished_at = None
        job.error_message = None
        self.session.flush()
        return job

    def pause_job(self, job_id: int) -> ArxivTaskHarvestJob:
        job = self.session.get(ArxivTaskHarvestJob, job_id)
        if job is None:
            raise ValueError("History job not found")
        if job.kind != ArxivTaskJobKind.history.value:
            raise ValueError("Only history jobs can be paused")
        if job.status == ArxivTaskJobStatus.running.value:
            job.status = ArxivTaskJobStatus.paused.value
            self.session.flush()
        return job

    def stop_job(self, job_id: int) -> ArxivTaskHarvestJob:
        job = self.session.get(ArxivTaskHarvestJob, job_id)
        if job is None:
            raise ValueError("History job not found")
        if job.kind != ArxivTaskJobKind.history.value:
            raise ValueError("Only history jobs can be stopped")
        if job.status in {ArxivTaskJobStatus.running.value, ArxivTaskJobStatus.pending.value}:
            job.status = ArxivTaskJobStatus.stopping.value
        else:
            job.status = ArxivTaskJobStatus.stopped.value
            job.finished_at = _now()
        self.session.flush()
        return job

    def run_next_queue_step(self) -> ArxivTaskHarvestJob | None:
        job = self.repository.running_job()
        if job is None:
            job = self.repository.next_pending_job()
            if job is None:
                return None
            job.status = ArxivTaskJobStatus.running.value
            job.started_at = job.started_at or _now()
            job.finished_at = None
            job.error_message = None
            self.session.flush()
        return self.run_job_step(job.id)

    def run_job_step(self, job_id: int) -> ArxivTaskHarvestJob:
        job = self.session.get(ArxivTaskHarvestJob, job_id)
        if job is None:
            raise ValueError("Harvest job not found")
        if job.status == ArxivTaskJobStatus.stopping.value:
            job.status = ArxivTaskJobStatus.stopped.value
            job.finished_at = _now()
            self.session.flush()
            return job
        if job.status != ArxivTaskJobStatus.running.value:
            return job
        target = self._next_window(job)
        if target is None:
            job.status = ArxivTaskJobStatus.succeeded.value
            job.finished_at = _now()
            if job.kind == ArxivTaskJobKind.daily.value:
                config = self.repository.daily_config()
                config.last_finished_at = job.finished_at
            self.session.flush()
            return job
        try:
            stats = self.harvest_window(target.subscription, target.start, target.end, job_id=job.id, kind=job.kind)
            self.session.refresh(job)
            job.stats_json = _merge_stats(job.stats_json or {}, stats)
        except Exception as exc:
            job.status = ArxivTaskJobStatus.failed.value
            job.error_message = str(exc) or type(exc).__name__
            job.finished_at = _now()
            if job.kind == ArxivTaskJobKind.daily.value:
                config = self.repository.daily_config()
                config.last_finished_at = job.finished_at
            self.session.flush()
            return job
        finally:
            if job.status == ArxivTaskJobStatus.stopping.value:
                job.status = ArxivTaskJobStatus.stopped.value
                job.finished_at = _now()
            self.session.flush()
        return job

    def harvest_window(self, subscription: ArxivTaskSubscription, start_time: datetime, end_time: datetime, *, job_id: int | None, kind: str, parent_window_id: int | None = None) -> HarvestStats:
        start_time = _as_utc(start_time)
        end_time = _as_utc(end_time)
        if end_time <= start_time:
            raise ValueError("arXiv window end_time must be after start_time")
        if end_time - start_time > MAX_WINDOW + WINDOW_DRIFT_TOLERANCE:
            raise ValueError("arXiv window cannot exceed one day plus scheduler drift tolerance")
        query_snapshot = subscription.query
        window = self.repository.create_window(
            subscription.id,
            query_snapshot,
            start_time,
            end_time,
            job_id=job_id,
            kind=kind,
            parent_window_id=parent_window_id,
            status=ArxivTaskWindowStatus.running.value,
            started_at=_now(),
            page_size=PAGE_SIZE,
        )
        try:
            first_page = self.arxiv_client.query_metadata_window(query_snapshot, start_time, end_time, page_size=PAGE_SIZE, offset=0)
            window.total_results = first_page.total_results
            if first_page.total_results > MAX_RESULTS_BEFORE_SPLIT and end_time - start_time > MIN_SPLIT_WINDOW:
                middle = start_time + (end_time - start_time) / 2
                window.status = ArxivTaskWindowStatus.split.value
                window.finished_at = _now()
                self.session.flush()
                left = self.harvest_window(subscription, start_time, middle, job_id=job_id, kind=kind, parent_window_id=window.id)
                right = self.harvest_window(subscription, middle, end_time, job_id=job_id, kind=kind, parent_window_id=window.id)
                return left.add(right)
            stats = self._persist_pages(subscription.id, query_snapshot, first_page.entries, first_page.total_results, start_time, end_time)
            window.fetched_count = stats.fetched_count
            window.inserted_count = stats.inserted_count
            window.updated_count = stats.updated_count
            window.page_count = stats.page_count
            window.status = ArxivTaskWindowStatus.partial.value if first_page.total_results > MAX_RESULTS_BEFORE_SPLIT else ArxivTaskWindowStatus.succeeded.value
            if window.status == ArxivTaskWindowStatus.partial.value:
                window.warning_code = "too_many_results_min_window"
            window.finished_at = _now()
            subscription.last_refreshed_at = window.finished_at
            self.session.flush()
            return stats
        except Exception as exc:
            window.status = ArxivTaskWindowStatus.failed.value
            window.error_message = str(exc) or type(exc).__name__
            window.finished_at = _now()
            self.session.flush()
            raise

    def _persist_pages(self, subscription_id: int, query_snapshot: str, first_entries: list[ArxivMetadataEntry], total_results: int, start_time: datetime, end_time: datetime) -> HarvestStats:
        total = self._persist_entries(subscription_id, query_snapshot, first_entries)
        page_count = 1
        offset = PAGE_SIZE
        while offset < total_results:
            page = self.arxiv_client.query_metadata_window(query_snapshot, start_time, end_time, page_size=PAGE_SIZE, offset=offset)
            total = total.add(self._persist_entries(subscription_id, query_snapshot, page.entries))
            page_count += 1
            offset += PAGE_SIZE
        return HarvestStats(total.fetched_count, total.inserted_count, total.updated_count, page_count)

    def _persist_entries(self, subscription_id: int, query_snapshot: str, entries: list[ArxivMetadataEntry]) -> HarvestStats:
        now = _now()
        inserted = 0
        updated = 0
        for entry in entries:
            values = {
                "arxiv_id": entry.arxiv_id,
                "title": entry.title,
                "abstract": entry.abstract,
                "authors_json": entry.authors,
                "primary_category": entry.primary_category,
                "categories_json": entry.categories,
                "published_at": entry.published_at,
                "updated_at_source": entry.updated_at,
                "landing_page_url": entry.landing_page_url,
                "pdf_url": entry.pdf_url,
                "comment": entry.comment,
                "journal_ref": entry.journal_ref,
                "doi": entry.doi,
                "raw_json": entry.raw,
            }
            paper, was_inserted = self.repository.upsert_paper(arxiv_base_id=entry.arxiv_base_id, values=values, now=now)
            inserted += 1 if was_inserted else 0
            updated += 0 if was_inserted else 1
            self.repository.upsert_paper_subscription(paper.id, subscription_id, query_snapshot=query_snapshot)
        return HarvestStats(fetched_count=len(entries), inserted_count=inserted, updated_count=updated, page_count=0)

    def _next_window(self, job: ArxivTaskHarvestJob) -> WindowTarget | None:
        if job.kind == ArxivTaskJobKind.history.value:
            return self._next_history_window(job)
        if job.kind == ArxivTaskJobKind.daily.value:
            return self._next_daily_window(job)
        return self._next_daily_window(job)

    def _next_daily_window(self, job: ArxivTaskHarvestJob) -> WindowTarget | None:
        requested_end = _as_utc(job.requested_end or _now())
        for subscription_id in _subscription_ids(job):
            subscription = self.repository.get_subscription(subscription_id)
            if subscription is None:
                continue
            start = self.repository.latest_successful_window_end(subscription.id) or requested_end - MAX_WINDOW
            start = _as_utc(start)
            if start < requested_end:
                remaining = requested_end - start
                end = requested_end if remaining <= MAX_WINDOW + WINDOW_DRIFT_TOLERANCE else start + MAX_WINDOW
                return WindowTarget(subscription=subscription, start=start, end=end)
        return None

    def _next_history_window(self, job: ArxivTaskHarvestJob) -> WindowTarget | None:
        if job.requested_start is None or job.requested_end is None:
            return None
        existing = {(window.subscription_id, _as_utc(window.window_start), _as_utc(window.window_end)) for window in job.windows if window.status in {ArxivTaskWindowStatus.succeeded.value, ArxivTaskWindowStatus.partial.value, ArxivTaskWindowStatus.split.value}}
        for subscription_id in _subscription_ids(job):
            subscription = self.repository.get_subscription(subscription_id)
            if subscription is None:
                continue
            cursor = _as_utc(job.requested_start)
            requested_end = _as_utc(job.requested_end)
            while cursor < requested_end:
                end = min(cursor + MAX_WINDOW, requested_end)
                key = (subscription.id, cursor, end)
                if key not in existing:
                    return WindowTarget(subscription=subscription, start=cursor, end=end)
                cursor = end
        return None

    def _validate_subscription_ids(self, subscription_ids: list[int]) -> None:
        if not subscription_ids:
            raise ValueError("At least one arXiv task subscription is required")
        known = {subscription.id for subscription in self.repository.list_subscriptions()}
        unknown = sorted(set(subscription_ids) - known)
        if unknown:
            raise ValueError(f"Unknown arXiv task subscriptions: {', '.join(str(value) for value in unknown)}")


def _arxiv_client_from_settings() -> ArxivClient:
    return paper_source_adapters_from_settings()["arxiv"]  # type: ignore[return-value]


@lru_cache(maxsize=1)
def _arxiv_preview_client() -> ArxivClient:
    return ArxivClient(
        limiter=arxiv_rate_limiter_from_settings(),
        max_retries=1,
        backoff_base_seconds=5.0,
        backoff_max_seconds=5.0,
        timeout_seconds=PREVIEW_TIMEOUT_SECONDS,
    )


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC, microsecond=0)
    return value.astimezone(UTC).replace(microsecond=0)


def _validate_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Subscription name is required")
    if len(name) > 255:
        raise ValueError("Subscription name is too long")
    return name


def _validate_query(value: str) -> str:
    if not value.strip():
        raise ValueError("arXiv query is required")
    if len(value) > 2000:
        raise ValueError("arXiv query is too long")
    return value


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _subscription_ids(job: ArxivTaskHarvestJob) -> list[int]:
    return [int(subscription_id) for subscription_id in job.subscription_ids_json or []]


def _stats_json(stats: HarvestStats) -> dict[str, int]:
    return {
        "fetched_count": stats.fetched_count,
        "inserted_count": stats.inserted_count,
        "updated_count": stats.updated_count,
        "page_count": stats.page_count,
    }


def _merge_stats(existing: dict[str, object], stats: HarvestStats) -> dict[str, int]:
    merged = dict(existing)
    for key, value in _stats_json(stats).items():
        merged[key] = int(merged.get(key, 0) or 0) + value
    return {key: int(value) for key, value in merged.items() if isinstance(value, int)}
