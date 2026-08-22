from __future__ import annotations

from backend.db.models import Paper, SearchCandidate, Thread
from backend.db.types import PaperSource, SearchStatus
from backend.integrations.paper_sources import PaperSourceSearchResponse
from backend.schemas import PaperSearchResult
from backend.services.search import PaperSearchService


class FakeSource:
    def __init__(self, results: list[PaperSearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, str, int]] = []

    def search(self, query: str, max_results: int = 10, *, mode: str = "auto", offset: int = 0) -> PaperSourceSearchResponse:
        self.calls.append((query, max_results, mode, offset))
        return PaperSourceSearchResponse(results=self.results, query_used=f"fake:{mode}:{query}", warnings=["fake-warning"])


class FailingSource:
    def search(self, query: str, max_results: int = 10, *, mode: str = "auto", offset: int = 0) -> PaperSourceSearchResponse:
        raise RuntimeError("HTTP 429")


def test_search_local_source_does_not_call_external_sources(session):
    session.add(Paper(title="Local RAG Paper", abstract="local"))
    session.commit()
    external = FakeSource([PaperSearchResult(source="arxiv", source_record_id="2401.00001", title="External RAG Paper")])

    execution = PaperSearchService(session, {"arxiv": external}).search("RAG Paper", source=PaperSource.local.value, max_results=10)

    assert execution.search_session.status == SearchStatus.waiting_for_confirmation.value
    assert execution.search_session.source_preference == "local:auto"
    assert [candidate.title for candidate in execution.search_session.candidates] == ["Local RAG Paper"]
    assert external.calls == []


def test_search_arxiv_source_does_not_add_local_candidates(session):
    session.add(Paper(title="Local RAG Paper", abstract="local"))
    session.commit()
    external = FakeSource([
        PaperSearchResult(
            source="arxiv",
            source_record_id="2401.00001",
            title="External RAG Paper",
            arxiv_id="2401.00001",
        )
    ])

    execution = PaperSearchService(session, {"arxiv": external}).search("RAG Paper", source="arxiv", mode="title", max_results=10, offset=5)

    assert execution.query_used == "fake:title:RAG Paper"
    assert execution.warnings == ["fake-warning"]
    assert [candidate.title for candidate in execution.search_session.candidates] == ["External RAG Paper"]
    assert external.calls == [("RAG Paper", 10, "title", 5)]


def test_search_openalex_source_dispatches_only_to_openalex(session):
    arxiv = FakeSource([PaperSearchResult(source="arxiv", source_record_id="2401.00001", title="Arxiv")])
    openalex = FakeSource([PaperSearchResult(source="openalex", source_record_id="https://openalex.org/W1", title="OpenAlex", openalex_id="https://openalex.org/W1")])

    execution = PaperSearchService(session, {"arxiv": arxiv, "openalex": openalex}).search("paper", source="openalex", mode="keyword")

    assert [candidate.source for candidate in execution.search_session.candidates] == ["openalex"]
    assert arxiv.calls == []
    assert openalex.calls == [("paper", 10, "keyword", 0)]


def test_search_failed_when_selected_source_has_no_candidates(session):
    execution = PaperSearchService(session, {"arxiv": FakeSource([])}).search("missing", source="arxiv")

    assert execution.search_session.status == SearchStatus.failed.value
    assert execution.search_session.candidates == []



def test_search_external_source_error_returns_failed_execution(session):
    execution = PaperSearchService(session, {"arxiv": FailingSource()}).search("Lightning OPD", source="arxiv", mode="keyword")

    assert execution.search_session.status == SearchStatus.failed.value
    assert execution.search_session.candidates == []
    assert execution.query_used == "arxiv:keyword:Lightning OPD"
    assert execution.warnings == ["arxiv search failed: HTTP 429"]


def test_search_deduplicates_candidates_by_identifier_and_title(session):
    duplicated = PaperSearchResult(
        source="arxiv",
        source_record_id="2401.00001",
        title="Duplicate",
        arxiv_id="2401.00001v1",
    )
    same_title = PaperSearchResult(source="openalex", source_record_id=None, title="Duplicate")
    source = FakeSource([duplicated, duplicated.model_copy(update={"arxiv_id": "2401.00001v2"}), same_title])

    search_session = PaperSearchService(session, {"arxiv": source}).search("duplicate", source="arxiv").search_session

    assert len(search_session.candidates) == 1


def test_confirm_candidate_upserts_paper_and_updates_thread_focus(session):
    thread = Thread(title="Search thread")
    session.add(thread)
    session.commit()
    result = PaperSearchResult(
        source="openalex",
        source_record_id="https://openalex.org/W1",
        title="Confirmed Paper",
        doi="10.1000/confirmed",
        openalex_id="https://openalex.org/W1",
        authors=["A"],
    )
    search_service = PaperSearchService(session, {"openalex": FakeSource([result])})
    search_session = search_service.search("confirmed", source="openalex", thread_id=thread.id).search_session
    candidate = search_session.candidates[0]

    confirmed = search_service.confirm_candidate(search_session.id, candidate.id)

    assert confirmed.status == SearchStatus.confirmed.value
    assert confirmed.selected_candidate_id == candidate.id
    assert candidate.paper_id is not None
    assert session.get(Thread, thread.id).current_focus_paper_id == candidate.paper_id


def test_confirm_candidate_can_skip_thread_focus_update(session):
    thread = Thread(title="Search thread")
    session.add(thread)
    session.commit()
    result = PaperSearchResult(source="arxiv", source_record_id="2401.00001", title="Paper", arxiv_id="2401.00001")
    search_service = PaperSearchService(session, {"arxiv": FakeSource([result])})
    search_session = search_service.search("paper", source="arxiv", thread_id=thread.id).search_session
    candidate = search_session.candidates[0]

    search_service.confirm_candidate(search_session.id, candidate.id, update_thread_focus=False)

    assert session.get(Thread, thread.id).current_focus_paper_id is None


def test_confirm_candidate_rejects_candidate_from_other_session(session):
    service = PaperSearchService(session)
    first = service.search("one", source=PaperSource.local.value).search_session
    second = service.search("two", source=PaperSource.local.value).search_session
    candidate = SearchCandidate(search_session_id=second.id, rank=1, source="local", title="Wrong", created_at=__import__("datetime").datetime.now().astimezone())
    session.add(candidate)
    session.commit()

    try:
        service.confirm_candidate(first.id, candidate.id)
    except ValueError as exc:
        assert "does not belong" in str(exc)
    else:
        raise AssertionError("expected ValueError")
