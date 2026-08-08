from __future__ import annotations

from backend.db.models import AgentRun, AgentRunEvent, ArxivTaskDailyConfig, ArxivTaskHarvestJob, ArxivTaskPaper, ArxivTaskQueryWindow, ArxivTaskSubscription, Artifact, Memory, Message, Paper, Report, SearchCandidate, SearchSession, Thread
from backend.schemas import (
    ArxivTaskDailyConfigRead,
    ArxivTaskHarvestJobRead,
    ArxivTaskPaperRead,
    ArxivTaskQueryWindowRead,
    ArxivTaskStatusRead,
    ArxivTaskSubscriptionRead,
    ArtifactRead,
    MemoryRead,
    MessageRead,
    PaperDetail,
    PaperSummary,
    ReportRead,
    ReportSummary,
    RunEventRead,
    RunRead,
    SearchCandidateRead,
    SearchSessionRead,
    ThreadDetail,
    ThreadSummary,
)


def message_read(message: Message) -> MessageRead:
    return MessageRead(
        id=message.id,
        thread_id=message.thread_id,
        role=message.role,
        content_text=message.content_text,
        content_json=message.content_json,
        source=message.source,
        run_id=message.run_id,
        created_at=message.created_at,
    )


def run_event_read(event: AgentRunEvent) -> RunEventRead:
    return RunEventRead(
        id=event.id,
        run_id=event.run_id,
        sequence=event.sequence,
        event_type=event.event_type,
        level=event.level,
        payload=event.payload_json or {},
        created_at=event.created_at,
    )


def run_read(run: AgentRun, *, include_events: bool = True) -> RunRead:
    events = sorted(run.events, key=lambda event: event.sequence) if include_events else []
    return RunRead(
        id=run.id,
        thread_id=run.thread_id,
        workflow=run.workflow,
        status=run.status,
        error_message=run.error_message,
        input_json=run.input_json,
        output_json=run.output_json,
        events=[run_event_read(event) for event in events],
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def thread_summary(thread: Thread) -> ThreadSummary:
    return ThreadSummary(
        id=thread.id,
        title=thread.title,
        surface=thread.surface,
        status=thread.status,
        current_focus_paper_id=thread.current_focus_paper_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


def thread_detail(thread: Thread) -> ThreadDetail:
    summary = thread_summary(thread)
    return ThreadDetail(
        **summary.model_dump(),
        messages=[message_read(message) for message in sorted(thread.messages, key=lambda item: item.created_at)],
        runs=[run_read(run, include_events=True) for run in sorted(thread.agent_runs, key=lambda item: item.created_at, reverse=True)],
    )


def memory_read(memory: Memory) -> MemoryRead:
    return MemoryRead(
        id=memory.id,
        path=memory.path,
        title=memory.title,
        memory_type=memory.memory_type,
        scope_type=memory.scope_type,
        scope_id=memory.scope_id,
        paper_id=memory.paper_id,
        content_text=memory.content_text,
        content_json=memory.content_json,
        source=memory.source,
        status=memory.status,
        source_thread_id=memory.source_thread_id,
        source_paper_id=memory.source_paper_id,
        last_accessed_at=memory.last_accessed_at,
        metadata=memory.metadata_json or {},
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def artifact_read(artifact: Artifact) -> ArtifactRead:
    return ArtifactRead(
        id=artifact.id,
        kind=artifact.kind,
        status=artifact.status,
        storage_backend=artifact.storage_backend,
        storage_uri=artifact.storage_uri,
        original_filename=artifact.original_filename,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        checksum_sha256=artifact.checksum_sha256,
    )


def paper_summary(paper: Paper) -> PaperSummary:
    return PaperSummary(
        id=paper.id,
        title=paper.title,
        abstract=paper.abstract,
        year=paper.year,
        venue=paper.venue,
        status=paper.status,
        current_pdf_url=paper.best_pdf_url,
    )


def paper_detail(paper: Paper) -> PaperDetail:
    summary = paper_summary(paper)
    return PaperDetail(
        **summary.model_dump(),
        authors=list(paper.authors_json or []),
        identifiers=[
            {"id": item.id, "type": item.identifier_type, "value": item.identifier_value, "is_primary": item.is_primary}
            for item in paper.identifiers
        ],
        source_records=[
            {"id": item.id, "source": item.source, "source_record_id": item.source_record_id, "source_url": item.source_url, "is_primary": item.is_primary}
            for item in paper.source_records
        ],
        artifacts=[
            {"id": link.artifact.id, "role": link.role, "is_primary": link.is_primary, "kind": link.artifact.kind, "status": link.artifact.status, "storage_uri": link.artifact.storage_uri}
            for link in paper.paper_artifacts
        ],
        parse_jobs=[{"id": job.id, "strategy": job.strategy, "status": job.status, "error_message": job.error_message} for job in paper.parse_jobs],
        processed_documents=[
            {
                "id": doc.id,
                "version": doc.version,
                "status": doc.status,
                "quality_status": doc.quality_status,
                "quality_summary": doc.quality_summary,
                "processing_profile": doc.processing_profile,
                "metadata": doc.metadata_json or {},
                "content_markdown": doc.content_markdown,
                "chunks": [
                    {
                        "id": chunk.id,
                        "chunk_key": chunk.chunk_key,
                        "chunk_index": chunk.chunk_index,
                        "role": chunk.role,
                        "heading_path": chunk.heading_path_json,
                        "source_section_ids": chunk.source_section_ids_json,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "token_estimate": chunk.token_estimate,
                        "metadata": chunk.metadata_json or {},
                        "content_text": chunk.content_text,
                    }
                    for chunk in sorted(doc.chunks, key=lambda item: item.chunk_index)
                ],
            }
            for doc in paper.processed_documents
        ],
        reports=[{"id": report.id, "title": report.title, "status": report.status, "report_type": report.report_type} for report in []],
    )


def search_candidate_read(candidate: SearchCandidate) -> SearchCandidateRead:
    return SearchCandidateRead(
        id=candidate.id,
        rank=candidate.rank,
        source=candidate.source,
        source_record_id=candidate.source_record_id,
        paper_id=candidate.paper_id,
        title=candidate.title,
        abstract=candidate.abstract,
        authors=list(candidate.authors_json or []),
        year=candidate.year,
        doi=candidate.doi,
        arxiv_id=candidate.arxiv_id,
        openalex_id=candidate.openalex_id,
        landing_page_url=candidate.landing_page_url,
        pdf_url=candidate.pdf_url,
        score=candidate.score,
    )


def search_session_read(search_session: SearchSession) -> SearchSessionRead:
    return SearchSessionRead(
        id=search_session.id,
        thread_id=search_session.thread_id,
        run_id=search_session.run_id,
        query_text=search_session.query_text,
        status=search_session.status,
        selected_candidate_id=search_session.selected_candidate_id,
        candidates=[search_candidate_read(candidate) for candidate in sorted(search_session.candidates, key=lambda item: item.rank)],
    )


def report_summary(report: Report) -> ReportSummary:
    return ReportSummary(
        id=report.id,
        title=report.title,
        paper_id=report.paper_id,
        processed_document_id=report.processed_document_id,
        report_type=report.report_type,
        status=report.status,
        source_scope=report.source_scope,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def arxiv_task_daily_config_read(config: ArxivTaskDailyConfig) -> ArxivTaskDailyConfigRead:
    return ArxivTaskDailyConfigRead(
        id=config.id,
        enabled=config.status == "enabled",
        run_time=config.run_time,
        last_started_at=config.last_started_at,
        last_finished_at=config.last_finished_at,
        metadata=config.metadata_json or {},
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def arxiv_task_subscription_read(subscription: ArxivTaskSubscription) -> ArxivTaskSubscriptionRead:
    return ArxivTaskSubscriptionRead(
        id=subscription.id,
        name=subscription.name,
        query=subscription.query,
        description=subscription.description,
        enabled=subscription.enabled,
        last_refreshed_at=subscription.last_refreshed_at,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


def arxiv_task_paper_read(paper: ArxivTaskPaper) -> ArxivTaskPaperRead:
    return ArxivTaskPaperRead(
        id=paper.id,
        arxiv_id=paper.arxiv_id,
        arxiv_base_id=paper.arxiv_base_id,
        title=paper.title,
        abstract=paper.abstract,
        authors=list(paper.authors_json or []),
        primary_category=paper.primary_category,
        categories=list(paper.categories_json or []),
        published_at=paper.published_at,
        updated_at_source=paper.updated_at_source,
        landing_page_url=paper.landing_page_url,
        pdf_url=paper.pdf_url,
        comment=paper.comment,
        journal_ref=paper.journal_ref,
        doi=paper.doi,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


def arxiv_task_window_read(window: ArxivTaskQueryWindow) -> ArxivTaskQueryWindowRead:
    return ArxivTaskQueryWindowRead(
        id=window.id,
        subscription_id=window.subscription_id,
        query_snapshot=window.query_snapshot,
        job_id=window.job_id,
        kind=window.kind,
        window_start=window.window_start,
        window_end=window.window_end,
        status=window.status,
        total_results=window.total_results,
        fetched_count=window.fetched_count,
        inserted_count=window.inserted_count,
        updated_count=window.updated_count,
        page_size=window.page_size,
        page_count=window.page_count,
        error_message=window.error_message,
        warning_code=window.warning_code,
        parent_window_id=window.parent_window_id,
        started_at=window.started_at,
        finished_at=window.finished_at,
        created_at=window.created_at,
        updated_at=window.updated_at,
    )


def arxiv_task_job_read(job: ArxivTaskHarvestJob) -> ArxivTaskHarvestJobRead:
    return ArxivTaskHarvestJobRead(
        id=job.id,
        kind=job.kind,
        status=job.status,
        subscription_ids=[int(subscription_id) for subscription_id in job.subscription_ids_json or []],
        requested_start=job.requested_start,
        requested_end=job.requested_end,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        stats=job.stats_json or {},
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def arxiv_task_status_read(*, daily_config: ArxivTaskDailyConfig, subscriptions: list[ArxivTaskSubscription], coverage_subscription_ids: list[int], active_job: ArxivTaskHarvestJob | None, recent_jobs: list[ArxivTaskHarvestJob], recent_windows: list[ArxivTaskQueryWindow], recent_papers: list[ArxivTaskPaper], total_papers: int) -> ArxivTaskStatusRead:
    return ArxivTaskStatusRead(
        daily_config=arxiv_task_daily_config_read(daily_config),
        subscriptions=[arxiv_task_subscription_read(subscription) for subscription in subscriptions],
        enabled_subscription_ids=[subscription.id for subscription in subscriptions if subscription.enabled],
        coverage_subscription_ids=coverage_subscription_ids,
        active_job=arxiv_task_job_read(active_job) if active_job is not None else None,
        recent_jobs=[arxiv_task_job_read(job) for job in recent_jobs],
        recent_windows=[arxiv_task_window_read(window) for window in recent_windows],
        recent_papers=[arxiv_task_paper_read(paper) for paper in recent_papers],
        total_papers=total_papers,
    )


def report_read(report: Report) -> ReportRead:
    summary = report_summary(report)
    return ReportRead(
        **summary.model_dump(),
        paper_title=report.paper.title if report.paper is not None else None,
        markdown_content=report.markdown_content,
        json_content=report.json_content,
        source_refs=list(report.source_refs_json or []),
        evidence=[
            {
                "id": evidence.id,
                "evidence_type": evidence.evidence_type,
                "chunk_id": evidence.chunk_id,
                "reference_id": evidence.reference_id,
                "paper_id": evidence.paper_id,
                "quote_text": evidence.quote_text,
                "note": evidence.note,
            }
            for evidence in report.evidence
        ],
    )
