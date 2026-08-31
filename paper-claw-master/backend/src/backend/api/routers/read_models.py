from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.agents.runner import mark_stale_running_run_failed
from backend.api.deps import get_db_session
from backend.api.serializers import memory_read, paper_detail, paper_summary, report_read, report_summary, run_read, search_session_read, thread_detail, thread_summary
from backend.db.models import AgentRun, Paper, PaperArtifact, Report, SearchSession, Thread
from backend.db.repositories import MemoryRepository, ThreadRepository
from backend.db.types import PaperSource
from backend.integrations.paper_sources import paper_source_adapters_from_settings
from backend.services.search import PaperSearchService
from backend.schemas import MemoryRead, PaperDetail, PaperSummary, ReportRead, ReportSummary, RunRead, RuntimeSettingsRead, SearchSessionRead, ThreadDetail, ThreadSummary
from backend.settings import get_settings

router = APIRouter(tags=["read-models"])


@router.get("/threads", response_model=list[ThreadSummary])
def list_threads(
    include_archived: bool = Query(False),
    owner: str | None = Header(default=None, alias="X-PaperClaw-Owner"),
    session: Session = Depends(get_db_session),
) -> list[ThreadSummary]:
    threads = ThreadRepository(session).list(include_archived=include_archived)
    if owner:
        threads = [thread for thread in threads if _thread_owned_by(thread, owner)]
    return [thread_summary(thread) for thread in threads]


@router.post("/threads/{thread_id}/archive", response_model=ThreadSummary)
def archive_thread(
    thread_id: int,
    owner: str | None = Header(default=None, alias="X-PaperClaw-Owner"),
    session: Session = Depends(get_db_session),
) -> ThreadSummary:
    repository = ThreadRepository(session)
    current = repository.get(thread_id)
    if current is None or (owner and not _thread_owned_by(current, owner)):
        raise HTTPException(status_code=404, detail="Thread not found")
    thread = repository.archive(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    session.commit()
    return thread_summary(thread)


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_thread(
    thread_id: int,
    owner: str | None = Header(default=None, alias="X-PaperClaw-Owner"),
    session: Session = Depends(get_db_session),
) -> ThreadDetail:
    thread = session.scalar(
        select(Thread)
        .where(Thread.id == thread_id)
        .options(selectinload(Thread.messages), selectinload(Thread.agent_runs).selectinload(AgentRun.events))
    )
    if thread is None or (owner and not _thread_owned_by(thread, owner)):
        raise HTTPException(status_code=404, detail="Thread not found")
    for run in thread.agent_runs:
        mark_stale_running_run_failed(session, run)
    return thread_detail(thread)


def _thread_owned_by(thread: Thread, owner: str) -> bool:
    metadata = thread.metadata_json or {}
    return str(metadata.get("owner_key") or "") == owner.strip()


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: int, session: Session = Depends(get_db_session)) -> RunRead:
    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).options(selectinload(AgentRun.events)))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    mark_stale_running_run_failed(session, run)
    return run_read(run)


@router.get("/memories", response_model=list[MemoryRead])
def list_memories(session: Session = Depends(get_db_session)) -> list[MemoryRead]:
    memories = MemoryRepository(session).list(limit=1000)
    return [memory_read(memory) for memory in memories]


@router.get("/settings/runtime", response_model=RuntimeSettingsRead)
def get_runtime_settings() -> RuntimeSettingsRead:
    settings = get_settings()
    return RuntimeSettingsRead(
        environment=settings.environment,
        data_dir=str(settings.data_dir),
        storage_root=str(settings.storage_root) if settings.storage_root is not None else None,
        database_configured=bool(settings.database_url),
        chat={
            "model": settings.chat_model,
            "base_url_configured": settings.chat_base_url is not None,
            "api_key_configured": settings.chat_api_key is not None,
            "temperature": settings.chat_temperature,
            "max_tokens": settings.chat_max_tokens,
            "timeout_seconds": settings.chat_timeout_seconds,
            "max_retries": settings.chat_max_retries,
            "rate_limiter_requests_per_second": settings.chat_rate_limiter_requests_per_second,
            "rate_limiter_check_every_n_seconds": settings.chat_rate_limiter_check_every_n_seconds,
            "rate_limiter_max_bucket_size": settings.chat_rate_limiter_max_bucket_size,
        },
        embedding={
            "model": settings.embedding_model,
            "dimension": settings.embedding_dimension,
            "base_url_configured": settings.embedding_base_url is not None,
            "api_key_configured": settings.embedding_api_key is not None,
            "timeout_seconds": settings.embedding_timeout_seconds,
            "max_retries": settings.embedding_max_retries,
        },
        arxiv={
            "min_interval_seconds": settings.arxiv_min_interval_seconds,
            "max_retries": settings.arxiv_max_retries,
            "backoff_base_seconds": settings.arxiv_backoff_base_seconds,
            "backoff_max_seconds": settings.arxiv_backoff_max_seconds,
            "timeout_seconds": settings.arxiv_timeout_seconds,
        },
        openalex={
            "email_configured": settings.openalex_email is not None,
            "api_key_configured": settings.openalex_api_key is not None,
            "timeout_seconds": settings.openalex_timeout_seconds,
        },
        parsing={
            "local_ocr_base_url_configured": settings.local_ocr_base_url is not None,
            "local_ocr_api_key_configured": settings.local_ocr_api_key not in {"", "EMPTY"},
            "local_ocr_model": settings.local_ocr_model,
            "local_ocr_timeout_seconds": settings.local_ocr_timeout_seconds,
            "llama_parse_api_key_configured": settings.llama_parse_api_key is not None,
            "llama_parse_tier": settings.llama_parse_tier,
        },
    )


@router.get("/papers", response_model=list[PaperSummary])
def list_papers(session: Session = Depends(get_db_session)) -> list[PaperSummary]:
    papers = session.scalars(select(Paper).order_by(Paper.updated_at.desc())).all()
    return [paper_summary(paper) for paper in papers]


@router.get("/papers/search")
def search_paper_catalog(
    query: str = Query(..., min_length=1, max_length=500),
    source: str = Query(PaperSource.local.value),
    mode: str = Query("auto"),
    limit: int = Query(8, ge=1, le=20),
    session: Session = Depends(get_db_session),
) -> dict:
    """Small read-model facade for the Research workspace.

    The agent remains the orchestrator for conversational paper work.  This
    endpoint only exposes the existing, explainable search-session contract so
    the UI can show candidates and require an explicit selection.
    """
    if source not in {PaperSource.local.value, PaperSource.arxiv.value, PaperSource.openalex.value}:
        raise HTTPException(status_code=400, detail="Unsupported paper source")
    execution = PaperSearchService(session, paper_source_adapters_from_settings()).search(
        query.strip(), source=source, mode=mode, max_results=limit,
    )
    candidates = []
    for candidate in execution.search_session.candidates:
        raw = dict(candidate.raw_json or {})
        candidates.append({
            "id": candidate.id,
            "rank": candidate.rank,
            "source": candidate.source,
            "paper_id": candidate.paper_id,
            "title": candidate.title,
            "abstract": candidate.abstract,
            "authors": list(candidate.authors_json or []),
            "year": candidate.year,
            "venue": raw.get("venue"),
            "doi": candidate.doi,
            "arxiv_id": candidate.arxiv_id,
            "openalex_id": candidate.openalex_id,
            "landing_page_url": candidate.landing_page_url,
            "pdf_url": candidate.pdf_url,
            "score": candidate.score,
            "match_reasons": raw.get("match_reasons") or raw.get("match_reason") or [],
        })
    return {
        "search_session_id": execution.search_session.id,
        "source": execution.source,
        "mode": execution.mode,
        "query": execution.query,
        "query_used": execution.query_used,
        "status": execution.search_session.status,
        "warnings": execution.warnings,
        "candidates": candidates,
    }


@router.post("/papers/search/{search_session_id}/confirm")
def confirm_paper_catalog_candidate(
    search_session_id: int,
    candidate_id: int = Query(..., gt=0),
    session: Session = Depends(get_db_session),
) -> dict:
    try:
        search_session = PaperSearchService(session).confirm_candidate(
            search_session_id, candidate_id, update_thread_focus=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    selected = session.get(Paper, search_session.selected_candidate.paper_id) if search_session.selected_candidate and search_session.selected_candidate.paper_id else None
    return {
        "search_session_id": search_session.id,
        "status": search_session.status,
        "selected_candidate_id": search_session.selected_candidate_id,
        "paper_id": selected.id if selected is not None else None,
        "title": selected.title if selected is not None else None,
    }


@router.get("/papers/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: int, session: Session = Depends(get_db_session)) -> PaperDetail:
    paper = session.scalar(
        select(Paper)
        .where(Paper.id == paper_id)
        .options(
            selectinload(Paper.identifiers),
            selectinload(Paper.source_records),
            selectinload(Paper.paper_artifacts).selectinload(PaperArtifact.artifact),
            selectinload(Paper.parse_jobs),
            selectinload(Paper.processed_documents),
        )
    )
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    detail = paper_detail(paper)
    reports = session.scalars(select(Report).where(Report.paper_id == paper.id).order_by(Report.updated_at.desc())).all()
    detail.reports = [{"id": report.id, "title": report.title, "status": report.status, "report_type": report.report_type} for report in reports]
    return detail


@router.get("/search-sessions/{search_session_id}", response_model=SearchSessionRead)
def get_search_session(search_session_id: int, session: Session = Depends(get_db_session)) -> SearchSessionRead:
    search_session = session.scalar(select(SearchSession).where(SearchSession.id == search_session_id).options(selectinload(SearchSession.candidates)))
    if search_session is None:
        raise HTTPException(status_code=404, detail="Search session not found")
    return search_session_read(search_session)


@router.get("/reports", response_model=list[ReportSummary])
def list_reports(session: Session = Depends(get_db_session)) -> list[ReportSummary]:
    reports = session.scalars(select(Report).order_by(Report.updated_at.desc())).all()
    return [report_summary(report) for report in reports]


@router.get("/reports/{report_id}", response_model=ReportRead)
def get_report(report_id: int, session: Session = Depends(get_db_session)) -> ReportRead:
    report = session.scalar(select(Report).where(Report.id == report_id).options(selectinload(Report.evidence), selectinload(Report.paper)))
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_read(report)


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: int, session: Session = Depends(get_db_session)) -> None:
    report = session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    session.delete(report)
    session.commit()
