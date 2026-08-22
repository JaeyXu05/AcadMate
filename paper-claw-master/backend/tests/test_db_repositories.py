from __future__ import annotations

from sqlalchemy import text

from backend.db.repositories import (
    AgentRunRepository,
    ArtifactRepository,
    PaperRepository,
    ParsingRepository,
    ReportRepository,
    SearchRepository,
    ThreadRepository,
)
from backend.db.seed import seed_minimal_database
from backend.db.types import ArtifactKind, EvidenceType, IdentifierType, PaperArtifactRole, PaperSource, ThreadStatus, WorkflowName


def test_repositories_basic_flow(session):
    threads = ThreadRepository(session)
    runs = AgentRunRepository(session)
    papers = PaperRepository(session)
    searches = SearchRepository(session)
    artifacts = ArtifactRepository(session)
    parsing = ParsingRepository(session)
    reports = ReportRepository(session)

    thread = threads.create("Repo thread")
    run = runs.create(WorkflowName.search_confirmation.value, thread_id=thread.id)
    runs.append_event(run.id, "run_started")
    threads.add_message(thread.id, "user", "find papers", run_id=run.id)

    paper = papers.create("Repo Paper")
    papers.upsert_identifier(paper.id, IdentifierType.manual.value, "fixture:repo-paper")
    papers.upsert_source_record(paper.id, PaperSource.manual_upload.value, "fixture:repo-paper")

    search = searches.create_session("repo", thread_id=thread.id, run_id=run.id)
    candidate = searches.add_candidate(search.id, 1, PaperSource.manual_upload.value, "Repo Paper", paper_id=paper.id)
    searches.confirm_candidate(search.id, candidate.id)

    artifact = artifacts.create_artifact(ArtifactKind.pdf.value, storage_uri="local://repo.pdf")
    artifacts.link_paper_artifact(paper.id, artifact.id, PaperArtifactRole.pdf.value)

    parse_job = parsing.create_parse_job(paper.id, run_id=run.id)
    parsed = parsing.create_parsed_document(paper.id, parse_job.id, "fixture")
    processed = parsing.create_processed_document(paper.id, parsed.id, parse_job.id)
    chunk = parsing.add_chunk(processed.id, "chunk-1", 1, "chunk text")

    report = reports.create("Repo Report", thread_id=thread.id, run_id=run.id, paper_id=paper.id)
    reports.add_evidence(report.id, EvidenceType.chunk.value, chunk_id=chunk.id)
    session.commit()

    assert run.events[0].sequence == 1
    assert search.selected_candidate_id == candidate.id
    assert report.evidence[0].chunk_id == chunk.id


def test_thread_repository_archive_hides_default_list(session):
    threads = ThreadRepository(session)
    active = threads.create("Active thread")
    archived = threads.create("Archived thread")
    threads.archive(archived.id)
    session.commit()

    assert [thread.id for thread in threads.list()] == [active.id]
    assert {thread.id for thread in threads.list(include_archived=True)} == {active.id, archived.id}
    assert archived.status == ThreadStatus.archived.value


def test_seed_minimal_database(session):
    seed_minimal_database(session)
    session.commit()
    assert session.execute(text("select count(*) from papers")).scalar_one() == 3
