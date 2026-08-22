from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from backend.integrations.paper_sources.factory import paper_source_adapters_from_settings
from backend.services.acquisition import AcquisitionService
from backend.services.storage import ArtifactStorageService
from backend.tools.context import current_tool_context, resolve_active_paper_id, tool_session


@tool
def acquire_paper_artifacts(paper_id: int | None = None, thread_id: int | None = None, run_id: int | None = None) -> dict:
    """Plan paper artifact acquisition using existing source/PDF artifacts or upload requirements."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            job = AcquisitionService(session).plan_acquisition(resolved_paper_id, thread_id=thread_id, run_id=run_id)
            return _job_payload(job)
    except Exception as exc:
        return _error_payload("acquire_paper_artifacts", exc, paper_id)


@tool
def download_arxiv_paper_artifacts(arxiv_id: str, paper_id: int | None = None) -> dict:
    """Download arXiv TeX source and PDF artifacts for a paper."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            context = current_tool_context()
            client = paper_source_adapters_from_settings().get("arxiv")
            if client is None:
                raise ValueError("arXiv paper source is not configured")
            job = AcquisitionService(session).download_arxiv_artifacts(
                resolved_paper_id,
                arxiv_id,
                client,
                thread_id=context.thread_id if context else None,
                run_id=context.run_id if context else None,
            )
            return _job_payload(job)
    except Exception as exc:
        return _error_payload("download_arxiv_paper_artifacts", exc, paper_id, action="ask_user_upload")


@tool
def download_paper_pdf_from_url(pdf_url: str, paper_id: int | None = None) -> dict:
    """Download a safe public PDF URL and register it as a paper artifact."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            context = current_tool_context()
            job = AcquisitionService(session).download_pdf_from_url(
                resolved_paper_id,
                pdf_url,
                thread_id=context.thread_id if context else None,
                run_id=context.run_id if context else None,
            )
            return _job_payload(job)
    except Exception as exc:
        return _error_payload("download_paper_pdf_from_url", exc, paper_id, action="ask_user_upload")


@tool
def mark_paper_artifact_upload_required(reason: str, paper_id: int | None = None) -> dict:
    """Record that the user must upload a PDF or TeX source artifact for this paper."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            context = current_tool_context()
            job = AcquisitionService(session).mark_waiting_for_upload(
                resolved_paper_id,
                reason,
                thread_id=context.thread_id if context else None,
                run_id=context.run_id if context else None,
            )
            return _job_payload(job)
    except Exception as exc:
        return _error_payload("mark_paper_artifact_upload_required", exc, paper_id)


@tool
def register_local_paper_pdf(path: str, paper_id: int | None = None) -> dict:
    """Register a local PDF file as a paper artifact."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            artifact = ArtifactStorageService(session).register_local_pdf(resolved_paper_id, Path(path))
            return {"status": "available", "artifact_id": artifact.id, "kind": artifact.kind, "storage_uri": artifact.storage_uri}
    except Exception as exc:
        return _error_payload("register_local_paper_pdf", exc, paper_id)


@tool
def register_local_paper_source(path: str, paper_id: int | None = None) -> dict:
    """Register a local TeX source file/archive as a paper artifact."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            artifact = ArtifactStorageService(session).register_source_artifact(resolved_paper_id, Path(path))
            return {"status": "available", "artifact_id": artifact.id, "kind": artifact.kind, "storage_uri": artifact.storage_uri}
    except Exception as exc:
        return _error_payload("register_local_paper_source", exc, paper_id)


def _job_payload(job) -> dict:
    return {
        "acquisition_job_id": job.id,
        "status": job.status,
        "requested_source": job.requested_source,
        "input": job.input_json,
        "result": job.result_json,
        "error": job.error_message,
    }


def _error_payload(tool_name: str, exc: Exception, paper_id: int | None, *, action: str | None = None) -> dict:
    payload = {"status": "failed", "tool": tool_name, "paper_id": paper_id, "error": str(exc)}
    if action is not None:
        payload["action"] = action
    return payload
