from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool

from backend.db.models import AgentRun, Paper, Thread
from backend.db.repositories import AgentRunRepository
from backend.integrations.paper_sources import paper_source_adapters_from_settings
from backend.services.search import PaperSearchService
from backend.tools.context import current_tool_context, resolve_active_paper_id, tool_session


@tool
def search_papers(
    query: str,
    source: Literal["local", "arxiv", "openalex"],
    mode: Literal["auto", "title", "keyword", "identifier", "doi", "arxiv_id", "openalex_id", "advanced"] = "auto",
    thread_id: int | None = None,
    max_results: int = 10,
    offset: int = 0,
) -> dict:
    """Search exactly one paper source/mode and return an explainable confirmation session."""
    with tool_session() as session:
        context = current_tool_context()
        if context is not None and context.thread_id is not None:
            thread_id = context.thread_id
        if thread_id is not None and session.get(Thread, thread_id) is None:
            raise ValueError(f"Thread {thread_id} not found for paper search context")
        run_id = context.run_id if context is not None else None
        if run_id is not None and session.get(AgentRun, run_id) is None:
            raise ValueError(f"Run {run_id} not found for paper search context")
        execution = PaperSearchService(session, paper_source_adapters_from_settings()).search(
            query,
            source=source,
            mode=mode,
            thread_id=thread_id,
            run_id=run_id,
            max_results=max_results,
            offset=offset,
        )
        search_session = execution.search_session
        candidates = [_candidate_payload(candidate) for candidate in search_session.candidates]
        if run_id is not None:
            _record_search_candidates_event(
                session,
                run_id,
                search_session.id,
                execution.source,
                execution.mode,
                execution.query,
                execution.query_used,
                search_session.status,
                execution.warnings,
                candidates,
            )
        return {
            "search_session_id": search_session.id,
            "source": execution.source,
            "mode": execution.mode,
            "query": execution.query,
            "query_used": execution.query_used,
            "status": search_session.status,
            "warnings": execution.warnings,
            "candidates": candidates,
        }


@tool
def confirm_paper_candidate(search_session_id: int, candidate_id: int, update_thread_focus: bool = True) -> dict:
    """Confirm a search candidate and upsert it into the paper catalog."""
    with tool_session() as session:
        try:
            search_session = PaperSearchService(session).confirm_candidate(search_session_id, candidate_id, update_thread_focus=update_thread_focus)
        except ValueError as exc:
            return {
                "status": "failed",
                "search_session_id": search_session_id,
                "selected_candidate_id": None,
                "paper_id": None,
                "thread_focus_paper_id": None,
                "error": str(exc),
                "action": "run_discovery_again",
            }
        selected = session.get(Paper, search_session.selected_candidate.paper_id) if search_session.selected_candidate and search_session.selected_candidate.paper_id else None
        thread = session.get(Thread, search_session.thread_id) if search_session.thread_id is not None else None
        return {
            "search_session_id": search_session.id,
            "status": search_session.status,
            "selected_candidate_id": search_session.selected_candidate_id,
            "paper_id": selected.id if selected is not None else None,
            "thread_focus_paper_id": thread.current_focus_paper_id if thread is not None else None,
        }


def _record_search_candidates_event(
    session,
    run_id: int,
    search_session_id: int,
    source: str,
    mode: str,
    query: str,
    query_used: str,
    status: str,
    warnings: list[str],
    candidates: list[dict],
) -> None:
    candidate_ids = [candidate["id"] for candidate in candidates]
    AgentRunRepository(session).append_event(
        run_id,
        "search_candidates_found" if candidate_ids else "search_candidates_not_found",
        payload_json={
            "search_session_id": search_session_id,
            "source": source,
            "mode": mode,
            "query": query,
            "query_used": query_used,
            "status": status,
            "candidate_count": len(candidate_ids),
            "candidate_ids": candidate_ids,
            "warnings": warnings,
        },
    )



def _candidate_payload(candidate) -> dict:
    raw = dict(candidate.raw_json or {})
    match_reasons = raw.get("match_reasons") or raw.get("match_reason")
    if isinstance(match_reasons, str):
        match_reasons = [match_reasons]
    return {
        "id": candidate.id,
        "rank": candidate.rank,
        "source": candidate.source,
        "title": candidate.title,
        "paper_id": candidate.paper_id,
        "doi": candidate.doi,
        "arxiv_id": candidate.arxiv_id,
        "openalex_id": candidate.openalex_id,
        "authors": list(candidate.authors_json or []),
        "year": candidate.year,
        "venue": raw.get("venue"),
        "score": candidate.score,
        "landing_page_url": candidate.landing_page_url,
        "pdf_url": candidate.pdf_url,
        "match_reasons": match_reasons or [],
        "confidence_hints": raw.get("confidence_hints") or [],
    }


@tool
def get_paper(paper_id: int | None = None) -> dict:
    """Return paper catalog metadata, defaulting to the active paper."""
    with tool_session() as session:
        if paper_id is not None:
            paper = session.get(Paper, paper_id)
            if paper is None:
                return {"status": "not_found", "paper_id": paper_id, "error": f"Paper {paper_id} not found"}
        else:
            try:
                resolved_paper_id = resolve_active_paper_id(session)
            except ValueError as exc:
                return {"status": "needs_confirmation", "paper_id": None, "error": str(exc)}
            paper = session.get(Paper, resolved_paper_id)
            if paper is None:
                return {"status": "not_found", "paper_id": resolved_paper_id, "error": f"Paper {resolved_paper_id} not found"}
        return {"id": paper.id, "title": paper.title, "abstract": paper.abstract, "year": paper.year, "venue": paper.venue, "authors": paper.authors_json}
