from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from backend.db.models import ArxivTaskSubscription
from backend.db.types import ArxivTaskJobKind, ArxivTaskJobStatus, ArxivTaskWindowStatus
from backend.integrations.paper_sources.arxiv import ArxivMetadataEntry, ArxivMetadataQueryResponse
from backend.services.arxiv_tasks import ArxivTaskService


@dataclass
class FakeMetadataClient:
    total_results: int = 1
    arxiv_base_id: str = "2401.00001"
    calls: list[tuple[str, datetime | None, datetime | None, int, int]] | None = None
    on_call: Callable[[], None] | None = None

    def query_metadata(self, search_query: str, *, page_size: int = 5, offset: int = 0):
        return self._response(search_query, None, None, page_size, offset)

    def query_metadata_window(self, search_query: str, start_time: datetime, end_time: datetime, *, page_size: int = 100, offset: int = 0):
        return self._response(search_query, start_time, end_time, page_size, offset)

    def _response(self, search_query: str, start_time: datetime | None, end_time: datetime | None, page_size: int, offset: int):
        if self.calls is None:
            self.calls = []
        self.calls.append((search_query, start_time, end_time, page_size, offset))
        if self.on_call is not None:
            self.on_call()
        published_at = (start_time or datetime(2024, 1, 1, tzinfo=UTC)) + timedelta(minutes=5)
        updated_at = end_time or datetime(2024, 1, 2, tzinfo=UTC)
        entry = ArxivMetadataEntry(
            arxiv_id=f"{self.arxiv_base_id}v1",
            arxiv_base_id=self.arxiv_base_id,
            title="A harvested paper",
            abstract="abstract",
            authors=["Ada Lovelace"],
            primary_category="cs.LG",
            categories=["cs.LG", "cs.AI"],
            published_at=published_at,
            updated_at=updated_at,
            landing_page_url=f"https://arxiv.org/abs/{self.arxiv_base_id}v1",
            pdf_url=f"https://arxiv.org/pdf/{self.arxiv_base_id}v1",
            doi=None,
            journal_ref=None,
            comment=None,
            raw={"id": f"{self.arxiv_base_id}v1"},
        )
        return ArxivMetadataQueryResponse(
            query_used=search_query,
            total_results=self.total_results,
            start=offset,
            page_size=page_size,
            entries=[] if offset else [entry],
        )


def test_harvest_window_upserts_task_metadata_without_curated_papers(session):
    subscription = create_subscription(session)
    client = FakeMetadataClient()
    service = ArxivTaskService(session, arxiv_client=client)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    stats = service.harvest_window(subscription, start, end, job_id=None, kind=ArxivTaskJobKind.history.value)
    second_stats = service.harvest_window(subscription, start, end, job_id=None, kind=ArxivTaskJobKind.history.value)
    session.commit()

    assert stats.inserted_count == 1
    assert second_stats.updated_count == 1
    assert session.execute(text("select count(*) from arxiv_task_papers")).scalar_one() == 1
    assert session.execute(text("select count(*) from arxiv_task_paper_subscriptions")).scalar_one() == 1
    assert session.execute(text("select query_snapshot from arxiv_task_paper_subscriptions")).scalar_one() == "cat:cs.LG"
    assert session.execute(text("select count(*) from papers")).scalar_one() == 0


def test_harvest_window_splits_large_result_windows(session):
    subscription = create_subscription(session)
    client = FakeMetadataClient(total_results=1001)
    service = ArxivTaskService(session, arxiv_client=client)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=2)

    service.harvest_window(subscription, start, end, job_id=None, kind=ArxivTaskJobKind.history.value)
    session.commit()

    windows = session.execute(text("select status from arxiv_task_query_windows order by id")).scalars().all()
    assert windows[0] == ArxivTaskWindowStatus.split.value
    assert windows.count(ArxivTaskWindowStatus.partial.value) == 2


def test_run_history_step_honors_stop_after_current_window(session):
    subscription = create_subscription(session)
    service = ArxivTaskService(session, arxiv_client=FakeMetadataClient(total_results=0))
    job = service.create_history_job([subscription.id], datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
    service.start_job(job.id)

    def stop_during_window() -> None:
        session.execute(text("update arxiv_task_harvest_jobs set status = 'stopping' where id = :job_id"), {"job_id": job.id})
        session.commit()

    service.arxiv_client.on_call = stop_during_window
    service.run_job_step(job.id)
    session.commit()

    assert job.status == ArxivTaskJobStatus.stopped.value


def test_daily_queue_uses_latest_successful_coverage(session):
    create_subscription(session, enabled=True)
    client = FakeMetadataClient(total_results=0)
    service = ArxivTaskService(session, arxiv_client=client)

    job = service.enqueue_daily_run()
    service.run_next_queue_step()
    service.run_next_queue_step()
    session.commit()

    assert job.status == ArxivTaskJobStatus.succeeded.value
    assert client.calls is not None
    window_calls = [(start, end) for _, start, end, _, _ in client.calls if start is not None and end is not None]
    assert window_calls
    assert all(end - start <= timedelta(days=1) for start, end in window_calls)


def test_list_papers_filters_subscription_papers_by_published_window(session):
    subscription = create_subscription(session)
    client = FakeMetadataClient(arxiv_base_id="2401.00001")
    service = ArxivTaskService(session, arxiv_client=client)
    first_start = datetime(2024, 1, 1, tzinfo=UTC)
    second_start = datetime(2024, 1, 2, tzinfo=UTC)

    service.harvest_window(subscription, first_start, first_start + timedelta(hours=1), job_id=None, kind=ArxivTaskJobKind.history.value)
    client.arxiv_base_id = "2401.00002"
    service.harvest_window(subscription, second_start, second_start + timedelta(hours=1), job_id=None, kind=ArxivTaskJobKind.history.value)
    session.commit()

    papers = service.repository.list_papers(
        subscription_id=subscription.id,
        published_start=second_start,
        published_end=second_start + timedelta(hours=1),
        limit=20,
        offset=0,
    )

    assert [paper.arxiv_base_id for paper in papers] == ["2401.00002"]
    assert papers[0].published_at == second_start + timedelta(minutes=5)


def test_daily_queue_allows_seconds_level_drift_without_tiny_remainder(session):
    subscription = create_subscription(session, enabled=True)
    client = FakeMetadataClient(total_results=0)
    service = ArxivTaskService(session, arxiv_client=client)
    start = datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)
    requested_end = start + timedelta(days=1, seconds=7, microseconds=123456)
    service.repository.create_window(
        subscription.id,
        subscription.query,
        start - timedelta(days=1),
        start,
        kind=ArxivTaskJobKind.daily.value,
        status=ArxivTaskWindowStatus.succeeded.value,
    )
    job = service.repository.create_job(
        ArxivTaskJobKind.daily.value,
        [subscription.id],
        status=ArxivTaskJobStatus.running.value,
        requested_end=requested_end,
        stats_json={},
    )

    service.run_job_step(job.id)
    service.run_job_step(job.id)
    session.commit()

    window_calls = [(start_time, end_time) for _, start_time, end_time, _, _ in client.calls or [] if start_time is not None and end_time is not None]
    assert window_calls == [(start, requested_end.replace(microsecond=0))]
    assert job.status == ArxivTaskJobStatus.succeeded.value


def test_daily_queue_still_splits_beyond_drift_tolerance(session):
    subscription = create_subscription(session, enabled=True)
    client = FakeMetadataClient(total_results=0)
    service = ArxivTaskService(session, arxiv_client=client)
    start = datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)
    requested_end = start + timedelta(days=1, seconds=90)
    service.repository.create_window(
        subscription.id,
        subscription.query,
        start - timedelta(days=1),
        start,
        kind=ArxivTaskJobKind.daily.value,
        status=ArxivTaskWindowStatus.succeeded.value,
    )
    job = service.repository.create_job(
        ArxivTaskJobKind.daily.value,
        [subscription.id],
        status=ArxivTaskJobStatus.running.value,
        requested_end=requested_end,
        stats_json={},
    )

    service.run_job_step(job.id)
    service.run_job_step(job.id)
    service.run_job_step(job.id)
    session.commit()

    window_calls = [(start_time, end_time) for _, start_time, end_time, _, _ in client.calls or [] if start_time is not None and end_time is not None]
    assert window_calls == [
        (start, start + timedelta(days=1)),
        (start + timedelta(days=1), requested_end),
    ]
    assert job.status == ArxivTaskJobStatus.succeeded.value


def test_subscription_query_is_preserved_verbatim(session):
    service = ArxivTaskService(session, arxiv_client=FakeMetadataClient())
    subscription = service.create_subscription(name="Verbatim", query="  cat:cs.AI AND ti:agent  ", enabled=True)
    session.commit()

    assert subscription.query == "  cat:cs.AI AND ti:agent  "


def test_query_preview_uses_fast_dedicated_arxiv_client(session, monkeypatch):
    from backend.services import arxiv_tasks

    arxiv_tasks._arxiv_preview_client.cache_clear()
    created: dict[str, object] = {}

    class RecordingClient:
        def __init__(self, *, limiter, max_retries: int, backoff_base_seconds: float, backoff_max_seconds: float, timeout_seconds: float) -> None:
            created["limiter"] = limiter
            created["max_retries"] = max_retries
            created["backoff_base_seconds"] = backoff_base_seconds
            created["backoff_max_seconds"] = backoff_max_seconds
            created["timeout_seconds"] = timeout_seconds

        def query_metadata(self, search_query: str, *, page_size: int = 5, offset: int = 0):
            return ArxivMetadataQueryResponse(query_used=search_query, total_results=0, start=offset, page_size=page_size, entries=[])

    monkeypatch.setattr("backend.services.arxiv_tasks.paper_source_adapters_from_settings", lambda: (_ for _ in ()).throw(AssertionError("default harvester client should not be used for preview")))
    monkeypatch.setattr("backend.services.arxiv_tasks.arxiv_rate_limiter_from_settings", lambda: "shared-limiter")
    monkeypatch.setattr("backend.services.arxiv_tasks.ArxivClient", RecordingClient)

    response = ArxivTaskService(session).test_query("cat:cs.AI")

    assert response.total_results == 0
    assert created["limiter"] == "shared-limiter"
    assert created["max_retries"] == 1
    assert created["backoff_base_seconds"] == 5.0
    assert created["backoff_max_seconds"] == 5.0
    assert created["timeout_seconds"] == 45.0


def create_subscription(session, *, enabled: bool = True) -> ArxivTaskSubscription:
    subscription = ArxivTaskSubscription(name="Machine learning", query="cat:cs.LG", enabled=enabled)
    session.add(subscription)
    session.commit()
    return subscription
