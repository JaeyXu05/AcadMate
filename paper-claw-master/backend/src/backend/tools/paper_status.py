from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from langchain_core.tools import tool

from backend.db.models import Artifact, DocumentChunk, Paper, PaperArtifact, ParseJob, ProcessedDocument, Report, Thread
from backend.db.types import ArtifactStatus
from backend.services.papers import search_papers_catalog
from backend.tools.context import current_tool_context, resolve_active_paper_id, tool_session


@tool
def get_active_paper() -> dict:
    """Return the current thread's active paper metadata."""
    with tool_session() as session:
        try:
            paper_id = resolve_active_paper_id(session)
        except ValueError as exc:
            return {"active_paper_id": None, "paper": None, "status": "none", "message": str(exc)}
        paper = session.get(Paper, paper_id)
        return {"active_paper_id": paper_id, "paper": _paper_summary(paper) if paper is not None else None, "status": "found" if paper is not None else "missing"}


@tool
def set_thread_focus(paper_id: int, thread_id: int | None = None) -> dict:
    """Set the current thread focus to a paper."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            context = current_tool_context()
            resolved_thread_id = thread_id if thread_id is not None else context.thread_id if context is not None else None
            if resolved_thread_id is None:
                raise ValueError("No active thread. Specify thread_id to set thread focus.")
            thread = session.get(Thread, resolved_thread_id)
            if thread is None:
                raise ValueError(f"Thread {resolved_thread_id} not found")
            thread.current_focus_paper_id = resolved_paper_id
            session.flush()
            return {"status": "succeeded", "thread_id": thread.id, "current_focus_paper_id": thread.current_focus_paper_id}
    except Exception as exc:
        return {"status": "failed", "paper_id": paper_id, "thread_id": thread_id, "error": str(exc)}


@tool
def search_local_papers(query: str, mode: str = "auto", limit: int = 10) -> dict:
    """Search the local paper catalog by identifier, title, or keyword."""
    try:
        with tool_session() as session:
            candidates = search_papers_catalog(session, query, mode=mode, limit=limit)
            return {
                "status": "succeeded",
                "papers": [
                    {
                        "id": candidate.raw.get("paper_id"),
                        "title": candidate.title,
                        "year": candidate.year,
                        "venue": candidate.venue,
                        "authors": candidate.authors,
                        "match_reason": candidate.raw.get("match_reason"),
                    }
                    for candidate in candidates
                ],
            }
    except Exception as exc:
        return {"status": "failed", "papers": [], "error": str(exc)}


@tool
def get_paper_pipeline_status(paper_id: int | None = None, include_metadata: bool = False) -> dict:
    """Return compact ingestion, processing, embedding, and report status for a paper."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            paper = session.get(Paper, resolved_paper_id)
            if paper is None:
                return {"status": "not_found", "paper_id": resolved_paper_id, "error": f"Paper {resolved_paper_id} not found"}
            processed = _latest_processed_document(session, resolved_paper_id)
            return {
                "status": "succeeded",
                "paper": _paper_metadata(paper) if include_metadata else _paper_summary(paper),
                "artifacts": _artifact_status(session, resolved_paper_id),
                "latest_parse_job": _latest_parse_job_status(session, resolved_paper_id),
                "processed_document": _processed_status(session, processed),
                "embeddings": _embedding_status(session, processed),
                "reports": _report_status(session, resolved_paper_id),
            }
    except Exception as exc:
        return {"status": "failed", "paper_id": paper_id, "error": str(exc)}


@tool
def list_paper_artifacts(paper_id: int | None = None) -> dict:
    """List compact artifact metadata for a paper."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            artifacts = list(
                session.scalars(
                    select(Artifact)
                    .join(PaperArtifact)
                    .options(selectinload(Artifact.paper_artifacts))
                    .where(PaperArtifact.paper_id == resolved_paper_id)
                    .order_by(Artifact.created_at.desc(), Artifact.id.desc())
                )
            )
            return {
                "status": "succeeded",
                "paper_id": resolved_paper_id,
                "artifacts": [
                    {
                        "id": artifact.id,
                        "kind": artifact.kind,
                        "status": artifact.status,
                        "storage_uri": artifact.storage_uri,
                        "original_filename": artifact.original_filename,
                        "roles": [link.role for link in artifact.paper_artifacts if link.paper_id == resolved_paper_id],
                    }
                    for artifact in artifacts
                ],
            }
    except Exception as exc:
        return {"status": "failed", "paper_id": paper_id, "artifacts": [], "error": str(exc)}


@tool
def list_paper_reports(paper_id: int | None = None, limit: int = 10) -> dict:
    """List recent reports for a paper."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            reports = list(
                session.scalars(
                    select(Report)
                    .where(Report.paper_id == resolved_paper_id)
                    .order_by(Report.created_at.desc(), Report.id.desc())
                    .limit(limit)
                )
            )
            return {
                "status": "succeeded",
                "paper_id": resolved_paper_id,
                "reports": [
                    {
                        "id": report.id,
                        "title": report.title,
                        "status": report.status,
                        "report_type": report.report_type,
                        "source_scope": report.source_scope,
                        "created_at": report.created_at.isoformat(),
                    }
                    for report in reports
                ],
            }
    except Exception as exc:
        return {"status": "failed", "paper_id": paper_id, "reports": [], "error": str(exc)}


def _paper_summary(paper: Paper) -> dict:
    return {"id": paper.id, "title": paper.title, "year": paper.year, "venue": paper.venue, "authors": list(paper.authors_json or [])}


def _paper_metadata(paper: Paper) -> dict:
    return {
        **_paper_summary(paper),
        "abstract": paper.abstract,
        "best_pdf_url": paper.best_pdf_url,
        "landing_page_url": paper.landing_page_url,
        "metadata": dict(paper.metadata_json or {}),
        "identifiers": [
            {
                "type": identifier.identifier_type,
                "value": identifier.identifier_value,
                "is_primary": identifier.is_primary,
            }
            for identifier in paper.identifiers
        ],
        "source_records": [
            {
                "source": record.source,
                "source_record_id": record.source_record_id,
                "source_url": record.source_url,
                "is_primary": record.is_primary,
                "raw": dict(record.raw_json or {}),
            }
            for record in paper.source_records
        ],
    }


def _artifact_status(session, paper_id: int) -> dict:
    rows = list(
        session.execute(
            select(PaperArtifact.role, Artifact.status, func.count(Artifact.id))
            .join(Artifact, Artifact.id == PaperArtifact.artifact_id)
            .where(PaperArtifact.paper_id == paper_id)
            .group_by(PaperArtifact.role, Artifact.status)
        )
    )
    available_roles = sorted({role for role, status, _ in rows if status == ArtifactStatus.available.value})
    return {"available_roles": available_roles, "counts": [{"role": role, "status": status, "count": count} for role, status, count in rows]}


def _latest_parse_job_status(session, paper_id: int) -> dict | None:
    job = session.scalar(select(ParseJob).where(ParseJob.paper_id == paper_id).order_by(ParseJob.created_at.desc(), ParseJob.id.desc()))
    if job is None:
        return None
    return {"id": job.id, "status": job.status, "strategy": job.strategy, "error": job.error_message}


def _latest_processed_document(session, paper_id: int) -> ProcessedDocument | None:
    return session.scalar(select(ProcessedDocument).where(ProcessedDocument.paper_id == paper_id).order_by(ProcessedDocument.version.desc(), ProcessedDocument.id.desc()))


def _processed_status(session, processed: ProcessedDocument | None) -> dict | None:
    if processed is None:
        return None
    chunk_count = session.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.processed_document_id == processed.id)) or 0
    return {"id": processed.id, "status": processed.status, "version": processed.version, "chunk_count": chunk_count, "metadata": processed.metadata_json}


def _embedding_status(session, processed: ProcessedDocument | None) -> dict | None:
    if processed is None:
        return None
    total = session.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.processed_document_id == processed.id)) or 0
    embedded = session.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.processed_document_id == processed.id, DocumentChunk.embedding.is_not(None))) or 0
    return {"embedded_chunks": embedded, "missing_chunks": total - embedded, "total_chunks": total}


def _report_status(session, paper_id: int) -> list[dict]:
    reports = list(session.scalars(select(Report).where(Report.paper_id == paper_id).order_by(Report.created_at.desc(), Report.id.desc()).limit(5)))
    return [{"id": report.id, "title": report.title, "status": report.status, "report_type": report.report_type} for report in reports]
