from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.api.serializers import arxiv_task_daily_config_read, arxiv_task_job_read, arxiv_task_paper_read, arxiv_task_status_read, arxiv_task_subscription_read, arxiv_task_window_read
from backend.db.repositories import ArxivTaskRepository
from backend.integrations.paper_sources.arxiv import ArxivMetadataEntry
from backend.schemas import (
    ArxivTaskDailyConfigRead,
    ArxivTaskDailyConfigUpdateRequest,
    ArxivTaskHarvestJobRead,
    ArxivTaskHistoryJobCreateRequest,
    ArxivTaskPaperRead,
    ArxivTaskQueryWindowRead,
    ArxivTaskStatusRead,
    ArxivTaskSubscriptionCreateRequest,
    ArxivTaskSubscriptionRead,
    ArxivTaskSubscriptionTestPaperRead,
    ArxivTaskSubscriptionTestRead,
    ArxivTaskSubscriptionTestRequest,
    ArxivTaskSubscriptionUpdateRequest,
)
from backend.services.arxiv_task_scheduler import poke_arxiv_task_scheduler
from backend.services.arxiv_tasks import ArxivTaskService

router = APIRouter(tags=["tasks"])


@router.get("/tasks/arxiv/status", response_model=ArxivTaskStatusRead)
def get_arxiv_task_status(session: Session = Depends(get_db_session)) -> ArxivTaskStatusRead:
    repository = ArxivTaskRepository(session)
    subscriptions = repository.list_subscriptions()
    return arxiv_task_status_read(
        daily_config=repository.daily_config(),
        subscriptions=subscriptions,
        coverage_subscription_ids=repository.successful_subscription_ids_with_papers(),
        active_job=repository.active_job(),
        recent_jobs=repository.list_jobs(limit=20),
        recent_windows=repository.list_windows(limit=100),
        recent_papers=repository.list_papers(limit=20),
        total_papers=repository.count_papers(),
    )


@router.get("/tasks/arxiv/daily-config", response_model=ArxivTaskDailyConfigRead)
def get_arxiv_daily_config(session: Session = Depends(get_db_session)) -> ArxivTaskDailyConfigRead:
    return arxiv_task_daily_config_read(ArxivTaskRepository(session).daily_config())


@router.put("/tasks/arxiv/daily-config", response_model=ArxivTaskDailyConfigRead)
def update_arxiv_daily_config(request: ArxivTaskDailyConfigUpdateRequest, session: Session = Depends(get_db_session)) -> ArxivTaskDailyConfigRead:
    if not _valid_run_time(request.run_time):
        raise HTTPException(status_code=400, detail="run_time must use HH:MM format")
    config = ArxivTaskRepository(session).update_daily_config(enabled=request.enabled, run_time=request.run_time)
    session.commit()
    return arxiv_task_daily_config_read(config)


@router.get("/tasks/arxiv/subscriptions", response_model=list[ArxivTaskSubscriptionRead])
def list_arxiv_task_subscriptions(session: Session = Depends(get_db_session)) -> list[ArxivTaskSubscriptionRead]:
    return [arxiv_task_subscription_read(subscription) for subscription in ArxivTaskRepository(session).list_subscriptions()]


@router.post("/tasks/arxiv/subscriptions/test-query", response_model=ArxivTaskSubscriptionTestRead)
def test_arxiv_task_subscription_query(request: ArxivTaskSubscriptionTestRequest, session: Session = Depends(get_db_session)) -> ArxivTaskSubscriptionTestRead:
    try:
        result = ArxivTaskService(session).test_query(request.query, max_results=request.max_results)
        return ArxivTaskSubscriptionTestRead(
            query=request.query,
            total_results=result.total_results,
            papers=[_test_paper_read(entry) for entry in result.entries],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="arXiv query test timed out after 45 seconds. Refine the query and try again.") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise HTTPException(status_code=429, detail="arXiv rate limit reached. Wait a few seconds and try again.") from exc
        raise HTTPException(status_code=502, detail=str(exc) or type(exc).__name__) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or type(exc).__name__) from exc


@router.post("/tasks/arxiv/subscriptions", response_model=ArxivTaskSubscriptionRead)
def create_arxiv_task_subscription(request: ArxivTaskSubscriptionCreateRequest, session: Session = Depends(get_db_session)) -> ArxivTaskSubscriptionRead:
    try:
        subscription = ArxivTaskService(session).create_subscription(name=request.name, query=request.query, description=request.description, enabled=request.enabled)
        session.commit()
        return arxiv_task_subscription_read(subscription)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Subscription name already exists") from exc


@router.put("/tasks/arxiv/subscriptions/{subscription_id}", response_model=ArxivTaskSubscriptionRead)
def update_arxiv_task_subscription(subscription_id: int, request: ArxivTaskSubscriptionUpdateRequest, session: Session = Depends(get_db_session)) -> ArxivTaskSubscriptionRead:
    try:
        subscription = ArxivTaskService(session).update_subscription(subscription_id, name=request.name, query=request.query, description=request.description, enabled=request.enabled)
        session.commit()
        return arxiv_task_subscription_read(subscription)
    except ValueError as exc:
        raise HTTPException(status_code=400 if "not found" not in str(exc).lower() else 404, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Subscription name already exists") from exc


@router.delete("/tasks/arxiv/subscriptions/{subscription_id}")
def delete_arxiv_task_subscription(subscription_id: int, session: Session = Depends(get_db_session)) -> dict[str, bool]:
    try:
        ArxivTaskService(session).delete_subscription(subscription_id)
        session.commit()
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/arxiv/daily/run", response_model=ArxivTaskHarvestJobRead)
def run_arxiv_daily_now(background_tasks: BackgroundTasks, session: Session = Depends(get_db_session)) -> ArxivTaskHarvestJobRead:
    try:
        job = ArxivTaskService(session).enqueue_daily_run()
        session.commit()
        background_tasks.add_task(poke_arxiv_task_scheduler)
        return arxiv_task_job_read(job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/arxiv/history-jobs", response_model=ArxivTaskHarvestJobRead)
def create_arxiv_history_job(request: ArxivTaskHistoryJobCreateRequest, session: Session = Depends(get_db_session)) -> ArxivTaskHarvestJobRead:
    try:
        job = ArxivTaskService(session).create_history_job(request.subscription_ids, request.start_time, request.end_time)
        session.commit()
        return arxiv_task_job_read(job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/arxiv/history-jobs/{job_id}/start", response_model=ArxivTaskHarvestJobRead)
def start_arxiv_history_job(job_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_db_session)) -> ArxivTaskHarvestJobRead:
    try:
        job = ArxivTaskService(session).start_job(job_id)
        session.commit()
        background_tasks.add_task(poke_arxiv_task_scheduler)
        return arxiv_task_job_read(job)
    except ValueError as exc:
        raise HTTPException(status_code=400 if "not found" not in str(exc).lower() else 404, detail=str(exc)) from exc


@router.post("/tasks/arxiv/history-jobs/{job_id}/pause", response_model=ArxivTaskHarvestJobRead)
def pause_arxiv_history_job(job_id: int, session: Session = Depends(get_db_session)) -> ArxivTaskHarvestJobRead:
    try:
        job = ArxivTaskService(session).pause_job(job_id)
        session.commit()
        return arxiv_task_job_read(job)
    except ValueError as exc:
        raise HTTPException(status_code=400 if "not found" not in str(exc).lower() else 404, detail=str(exc)) from exc


@router.post("/tasks/arxiv/history-jobs/{job_id}/stop", response_model=ArxivTaskHarvestJobRead)
def stop_arxiv_history_job(job_id: int, session: Session = Depends(get_db_session)) -> ArxivTaskHarvestJobRead:
    try:
        job = ArxivTaskService(session).stop_job(job_id)
        session.commit()
        return arxiv_task_job_read(job)
    except ValueError as exc:
        raise HTTPException(status_code=400 if "not found" not in str(exc).lower() else 404, detail=str(exc)) from exc


@router.get("/tasks/arxiv/windows", response_model=list[ArxivTaskQueryWindowRead])
def list_arxiv_task_windows(subscription_id: int | None = None, limit: int = Query(default=100, ge=1, le=500), session: Session = Depends(get_db_session)) -> list[ArxivTaskQueryWindowRead]:
    return [arxiv_task_window_read(window) for window in ArxivTaskRepository(session).list_windows(subscription_id=subscription_id, limit=limit)]


@router.get("/tasks/arxiv/papers", response_model=list[ArxivTaskPaperRead])
def list_arxiv_task_papers(subscription_id: int | None = None, published_start: datetime | None = None, published_end: datetime | None = None, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), session: Session = Depends(get_db_session)) -> list[ArxivTaskPaperRead]:
    return [
        arxiv_task_paper_read(paper)
        for paper in ArxivTaskRepository(session).list_papers(
            subscription_id=subscription_id,
            published_start=published_start,
            published_end=published_end,
            limit=limit,
            offset=offset,
        )
    ]


def _test_paper_read(entry: ArxivMetadataEntry) -> ArxivTaskSubscriptionTestPaperRead:
    return ArxivTaskSubscriptionTestPaperRead(
        arxiv_id=entry.arxiv_id,
        title=entry.title,
        abstract=entry.abstract,
        authors=entry.authors,
        primary_category=entry.primary_category,
        categories=entry.categories,
        published_at=entry.published_at,
        updated_at_source=entry.updated_at,
        landing_page_url=entry.landing_page_url,
        pdf_url=entry.pdf_url,
    )


def _valid_run_time(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59 and len(parts[0]) == 2 and len(parts[1]) == 2
