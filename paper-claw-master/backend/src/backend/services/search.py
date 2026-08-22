from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.db.models import SearchCandidate, SearchSession, Thread
from backend.db.repositories import SearchRepository
from backend.db.types import PaperSource, SearchStatus
from backend.integrations.paper_sources import PaperSourceAdapter, PaperSourceSearchResponse
from backend.schemas import PaperSearchResult
from backend.services.papers import identifiers_from_search_result, normalize_title, search_papers_catalog, upsert_paper_from_search_result


@dataclass(frozen=True)
class PaperSearchExecution:
    search_session: SearchSession
    source: str
    mode: str
    query: str
    query_used: str
    warnings: list[str] = field(default_factory=list)


class PaperSearchService:
    def __init__(self, session: Session, sources: dict[str, PaperSourceAdapter] | None = None) -> None:
        self.session = session
        self.sources = sources or {}

    def search(
        self,
        query: str,
        *,
        source: str = PaperSource.local.value,
        mode: str = "auto",
        thread_id: int | None = None,
        run_id: int | None = None,
        max_results: int = 10,
        offset: int = 0,
    ) -> PaperSearchExecution:
        search_session = SearchRepository(self.session).create_session(
            query,
            thread_id=thread_id,
            run_id=run_id,
            status=SearchStatus.waiting_for_confirmation.value,
            source_preference=f"{source}:{mode}",
        )
        try:
            response = self._search_source(query, source=source, mode=mode, max_results=max_results, offset=offset)
        except Exception as exc:
            search_session.status = SearchStatus.failed.value
            self.session.flush()
            return PaperSearchExecution(
                search_session=search_session,
                source=source,
                mode=mode,
                query=query,
                query_used=f"{source}:{mode}:{query}",
                warnings=[f"{source} search failed: {exc}"],
            )
        for rank, candidate in enumerate(_dedupe_candidates(response.results)[:max_results], start=1):
            self._add_candidate(search_session.id, rank, candidate)
        if not search_session.candidates:
            search_session.status = SearchStatus.failed.value
        self.session.flush()
        return PaperSearchExecution(
            search_session=search_session,
            source=source,
            mode=mode,
            query=query,
            query_used=response.query_used,
            warnings=response.warnings,
        )

    def get_session(self, search_session_id: int) -> SearchSession | None:
        return self.session.get(SearchSession, search_session_id)

    def confirm_candidate(
        self,
        search_session_id: int,
        candidate_id: int,
        *,
        update_thread_focus: bool = True,
    ) -> SearchSession:
        candidate = self.session.get(SearchCandidate, candidate_id)
        if candidate is None or candidate.search_session_id != search_session_id:
            raise ValueError(f"Candidate {candidate_id} does not belong to search session {search_session_id}.")
        paper = candidate.paper or upsert_paper_from_search_result(self.session, _candidate_to_result(candidate))
        candidate.paper_id = paper.id
        search_session = SearchRepository(self.session).confirm_candidate(search_session_id, candidate_id)
        if update_thread_focus and search_session.thread_id is not None:
            thread = self.session.get(Thread, search_session.thread_id)
            if thread is not None:
                thread.current_focus_paper_id = paper.id
        self.session.flush()
        return search_session

    def _search_source(self, query: str, *, source: str, mode: str, max_results: int, offset: int) -> PaperSourceSearchResponse:
        if source == PaperSource.local.value:
            return PaperSourceSearchResponse(results=search_papers_catalog(self.session, query, mode=mode, limit=max_results), query_used=f"local:{mode}:{query}")
        adapter = self.sources.get(source)
        if adapter is None:
            raise ValueError(f"Paper source {source!r} is not configured")
        return adapter.search(query, max_results=max_results, mode=mode, offset=offset)

    def _add_candidate(self, search_session_id: int, rank: int, result: PaperSearchResult) -> SearchCandidate:
        identifiers = identifiers_from_search_result(result)
        paper_id = result.raw.get("paper_id") if result.raw.get("local") else None
        return SearchRepository(self.session).add_candidate(
            search_session_id,
            rank,
            result.source,
            result.title,
            source_record_id=result.source_record_id,
            paper_id=paper_id,
            abstract=result.abstract,
            authors_json=result.authors,
            year=result.year,
            doi=next((item.identifier_value for item in identifiers if item.identifier_type == "doi"), None),
            arxiv_id=next((item.identifier_value for item in identifiers if item.identifier_type == "arxiv"), None),
            openalex_id=next((item.identifier_value for item in identifiers if item.identifier_type == "openalex"), None),
            landing_page_url=result.landing_page_url,
            pdf_url=result.pdf_url,
            score=result.score,
            raw_json={**result.raw, "venue": result.venue},
        )


def _candidate_to_result(candidate: SearchCandidate) -> PaperSearchResult:
    return PaperSearchResult(
        source=candidate.source,
        source_record_id=candidate.source_record_id,
        title=candidate.title,
        abstract=candidate.abstract,
        authors=list(candidate.authors_json or []),
        year=candidate.year,
        venue=(candidate.raw_json or {}).get("venue"),
        doi=candidate.doi,
        arxiv_id=candidate.arxiv_id,
        openalex_id=candidate.openalex_id,
        landing_page_url=candidate.landing_page_url,
        pdf_url=candidate.pdf_url,
        score=candidate.score,
        raw=dict(candidate.raw_json or {}),
    )


def _dedupe_candidates(candidates: list[PaperSearchResult]) -> list[PaperSearchResult]:
    seen: set[tuple[str, str]] = set()
    deduped: list[PaperSearchResult] = []
    for candidate in candidates:
        keys = _candidate_keys(candidate)
        if keys and any(key in seen for key in keys):
            continue
        fallback = ("title", normalize_title(candidate.title))
        if not keys and fallback in seen:
            continue
        seen.update(keys or [fallback])
        deduped.append(candidate)
    return deduped


def _candidate_keys(candidate: PaperSearchResult) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for identifier in identifiers_from_search_result(candidate):
        keys.append((identifier.identifier_type, identifier.identifier_value))
    if candidate.source_record_id:
        keys.append((candidate.source, candidate.source_record_id))
    title = normalize_title(candidate.title)
    if title:
        keys.append(("title", title))
    return keys
