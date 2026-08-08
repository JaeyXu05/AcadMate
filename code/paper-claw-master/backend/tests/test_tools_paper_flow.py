from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.models import AgentRun, AgentRunEvent, Paper, PaperIdentifier, PaperSourceRecord, Report, SearchCandidate, SearchSession, Thread
from backend.db.repositories import ParsingRepository
from backend.db.types import ProcessedDocumentStatus, RunStatus, SearchStatus, WorkflowName
from backend.schemas import PaperClawContext, ReportGenerationResult, ResolvedProviderConfig
from backend.tools import DISCOVERY_AGENT_TOOLS, EVIDENCE_AGENT_TOOLS, INGESTION_AGENT_TOOLS, MAIN_AGENT_TOOLS, PAPER_CLAW_TOOLS, REPORT_AGENT_TOOLS, update_paper_metadata
from backend.tools.context import set_tool_session_factory, tool_runtime_context
from backend.tools.paper_parsing import ingest_paper_document, parse_paper
from backend.tools.paper_qa import retrieve_paper_evidence
from backend.tools.paper_acquisition import download_arxiv_paper_artifacts
from backend.tools.paper_reports import generate_paper_report
from backend.tools.paper_search import confirm_paper_candidate, get_paper, search_papers
from backend.tools.paper_status import get_paper_pipeline_status, list_paper_artifacts


def test_expected_tool_names_exist():
    assert {tool.name for tool in PAPER_CLAW_TOOLS} == {tool.name for tool in MAIN_AGENT_TOOLS}
    assert {tool.name for tool in MAIN_AGENT_TOOLS} == {
        "get_active_paper",
        "set_thread_focus",
        "get_paper",
        "search_local_papers",
        "get_paper_pipeline_status",
        "list_paper_artifacts",
        "list_paper_reports",
        "confirm_paper_candidate",
        "update_paper_metadata",
    }
    assert {tool.name for tool in DISCOVERY_AGENT_TOOLS} == {"search_papers", "get_paper"}
    assert {tool.name for tool in INGESTION_AGENT_TOOLS} == {
        "get_paper_pipeline_status",
        "list_paper_artifacts",
        "download_arxiv_paper_artifacts",
        "download_paper_pdf_from_url",
        "mark_paper_artifact_upload_required",
        "ingest_paper_document",
    }
    assert {tool.name for tool in EVIDENCE_AGENT_TOOLS} == {"get_paper_pipeline_status", "retrieve_paper_evidence"}
    assert {tool.name for tool in REPORT_AGENT_TOOLS} == {"get_paper_pipeline_status", "list_paper_reports", "generate_paper_report"}


def test_get_paper_pipeline_status_can_include_full_metadata(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Metadata Paper", best_pdf_url="https://example.com/paper.pdf", landing_page_url="https://arxiv.org/abs/2401.00001", metadata_json={"source": "arxiv"})
    session.add(paper)
    session.flush()
    session.add_all(
        [
            PaperIdentifier(paper_id=paper.id, identifier_type="arxiv", identifier_value="2401.00001", is_primary=True, created_at=datetime.now().astimezone()),
            PaperSourceRecord(paper_id=paper.id, source="arxiv", source_record_id="2401.00001v1", source_url="https://arxiv.org/abs/2401.00001v1", is_primary=True, raw_json={"primary_category": "cs.AI"}),
        ]
    )
    session.commit()
    set_tool_session_factory(factory)
    try:
        compact = get_paper_pipeline_status.invoke({"paper_id": paper.id})
        full = get_paper_pipeline_status.invoke({"paper_id": paper.id, "include_metadata": True})
    finally:
        set_tool_session_factory(None)

    assert "identifiers" not in compact["paper"]
    assert full["paper"]["best_pdf_url"] == "https://example.com/paper.pdf"
    assert full["paper"]["identifiers"] == [{"type": "arxiv", "value": "2401.00001", "is_primary": True}]
    assert full["paper"]["source_records"][0]["raw"] == {"primary_category": "cs.AI"}



def test_search_papers_returns_rich_local_candidate_payload(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Recursive Multi-Agent Systems", venue="arXiv", year=2024, authors_json=["A"])
    session.add(paper)
    session.commit()
    set_tool_session_factory(factory)
    try:
        result = search_papers.invoke({"query": "Recursive Multi-Agent Systems", "source": "local", "mode": "title"})
    finally:
        set_tool_session_factory(None)

    assert result["source"] == "local"
    assert "candidate_ref" not in result["candidates"][0]
    assert result["candidates"][0]["title"] == "Recursive Multi-Agent Systems"
    assert result["candidates"][0]["venue"] == "arXiv"



def test_update_paper_metadata_tool_updates_explicit_paper(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Metadata Tool Paper")
    session.add(paper)
    session.commit()
    set_tool_session_factory(factory)
    try:
        result = update_paper_metadata.invoke(
            {
                "paper_id": paper.id,
                "metadata": {"venue": "arXiv", "best_pdf_url": "https://arxiv.org/pdf/2406.17328v3"},
                "identifiers": [{"identifier_type": "arxiv", "identifier_value": "https://arxiv.org/abs/2406.17328v3"}],
                "source_records": [{"source": "arxiv", "source_record_id": "2406.17328v3", "source_url": "https://arxiv.org/abs/2406.17328v3"}],
                "reason": "arXiv metadata discovered after initial confirmation",
            }
        )
    finally:
        set_tool_session_factory(None)

    session.refresh(paper)
    assert result["status"] == "updated"
    assert paper.venue == "arXiv"
    assert paper.best_pdf_url == "https://arxiv.org/pdf/2406.17328v3"
    assert session.query(PaperIdentifier).filter_by(paper_id=paper.id, identifier_type="arxiv", identifier_value="2406.17328").one()
    assert session.query(PaperSourceRecord).filter_by(paper_id=paper.id, source="arxiv", source_record_id="2406.17328v3").one()



def test_update_paper_metadata_tool_uses_active_paper(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Active Metadata Paper")
    session.add(paper)
    session.commit()
    set_tool_session_factory(factory)
    try:
        with tool_runtime_context(PaperClawContext(active_paper_id=paper.id)):
            result = update_paper_metadata.invoke({"metadata": {"year": 2026}, "reason": "year discovered"})
    finally:
        set_tool_session_factory(None)

    session.refresh(paper)
    assert result["status"] == "updated"
    assert result["paper_id"] == paper.id
    assert paper.year == 2026



def test_update_paper_metadata_tool_returns_structured_error_without_active_paper(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    set_tool_session_factory(factory)
    try:
        result = update_paper_metadata.invoke({"metadata": {"year": 2026}})
    finally:
        set_tool_session_factory(None)

    assert result["status"] == "failed"
    assert "No active paper" in result["error"]



def test_get_paper_returns_not_found_for_missing_explicit_id(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    set_tool_session_factory(factory)
    try:
        result = get_paper.invoke({"paper_id": 999999})
    finally:
        set_tool_session_factory(None)

    assert result == {"status": "not_found", "paper_id": 999999, "error": "Paper 999999 not found"}



def test_get_paper_returns_needs_confirmation_without_active_paper(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    set_tool_session_factory(factory)
    try:
        result = get_paper.invoke({})
    finally:
        set_tool_session_factory(None)

    assert result == {
        "status": "needs_confirmation",
        "paper_id": None,
        "error": "No active paper. Ask the user to select or confirm a paper first.",
    }


def test_search_papers_records_candidate_found_event(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    thread = Thread(title="Search thread")
    paper = Paper(title="Recursive Multi-Agent Systems", venue="arXiv", year=2024, authors_json=["A"])
    session.add_all([thread, paper])
    session.flush()
    run = AgentRun(workflow=WorkflowName.paper_qa.value, thread_id=thread.id, status=RunStatus.running.value)
    session.add(run)
    session.commit()
    set_tool_session_factory(factory)
    try:
        with tool_runtime_context(PaperClawContext(thread_id=thread.id, run_id=run.id)):
            result = search_papers.invoke({"query": "Recursive Multi-Agent Systems", "source": "local", "mode": "title"})
    finally:
        set_tool_session_factory(None)

    event = session.query(AgentRunEvent).filter_by(run_id=run.id, event_type="search_candidates_found").one()
    assert event.payload_json["search_session_id"] == result["search_session_id"]
    assert event.payload_json["candidate_count"] == 1
    assert event.payload_json["candidate_ids"] == [result["candidates"][0]["id"]]



def test_search_papers_runtime_thread_overrides_model_thread_argument(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    thread = Thread(title="Search thread")
    paper = Paper(title="Recursive Multi-Agent Systems", venue="arXiv", year=2024, authors_json=["A"])
    session.add_all([thread, paper])
    session.flush()
    run = AgentRun(workflow=WorkflowName.paper_qa.value, thread_id=thread.id, status=RunStatus.running.value)
    session.add(run)
    session.commit()
    set_tool_session_factory(factory)
    try:
        with tool_runtime_context(PaperClawContext(thread_id=thread.id, run_id=run.id)):
            result = search_papers.invoke({"query": "Recursive Multi-Agent Systems", "source": "local", "mode": "title", "thread_id": 999999})
    finally:
        set_tool_session_factory(None)

    assert result["candidates"][0]["title"] == "Recursive Multi-Agent Systems"
    event = session.query(AgentRunEvent).filter_by(run_id=run.id, event_type="search_candidates_found").one()
    assert event.payload_json["search_session_id"] == result["search_session_id"]



def test_search_papers_records_candidate_not_found_event(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    thread = Thread(title="Search thread")
    session.add(thread)
    session.flush()
    run = AgentRun(workflow=WorkflowName.paper_qa.value, thread_id=thread.id, status=RunStatus.running.value)
    session.add(run)
    session.commit()
    set_tool_session_factory(factory)
    try:
        with tool_runtime_context(PaperClawContext(thread_id=thread.id, run_id=run.id)):
            result = search_papers.invoke({"query": "Missing Paper", "source": "local", "mode": "title"})
    finally:
        set_tool_session_factory(None)

    event = session.query(AgentRunEvent).filter_by(run_id=run.id, event_type="search_candidates_not_found").one()
    assert event.payload_json["search_session_id"] == result["search_session_id"]
    assert event.payload_json["candidate_count"] == 0
    assert event.payload_json["candidate_ids"] == []



def test_confirm_paper_candidate_returns_structured_error_for_mismatched_candidate(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    first_session = SearchSession(query_text="First query", status=SearchStatus.waiting_for_confirmation.value)
    session.add(first_session)
    other_session = SearchSession(query_text="Second query", status=SearchStatus.waiting_for_confirmation.value)
    session.add(other_session)
    session.flush()
    candidate = SearchCandidate(search_session_id=other_session.id, rank=1, source="arxiv", title="Other Paper", created_at=datetime.now().astimezone())
    session.add(candidate)
    session.commit()
    set_tool_session_factory(factory)
    try:
        result = confirm_paper_candidate.invoke({"search_session_id": first_session.id, "candidate_id": candidate.id})
    finally:
        set_tool_session_factory(None)

    assert result == {
        "status": "failed",
        "search_session_id": first_session.id,
        "selected_candidate_id": None,
        "paper_id": None,
        "thread_focus_paper_id": None,
        "error": f"Candidate {candidate.id} does not belong to search session {first_session.id}.",
        "action": "run_discovery_again",
    }



def test_parse_paper_returns_structured_error_when_parse_chain_raises(session, engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Exploding Parser Paper")
    session.add(paper)
    session.commit()

    def fail_parse(_service, paper_id, run_id=None):
        raise RuntimeError("parser service unavailable")

    monkeypatch.setattr("backend.tools.paper_parsing.ParseChainService.run_parse_chain", fail_parse)
    set_tool_session_factory(factory)
    try:
        result = parse_paper.invoke({"paper_id": paper.id})
    finally:
        set_tool_session_factory(None)

    assert result == {"paper_id": paper.id, "status": "parse_failed", "error": "parser service unavailable"}



def test_ingest_paper_document_returns_parse_failed_when_parse_chain_raises(session, engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Exploding Ingest Paper")
    session.add(paper)
    session.commit()

    def fail_parse(_service, paper_id, run_id=None):
        raise RuntimeError("parser service unavailable")

    monkeypatch.setattr("backend.tools.paper_parsing.ParseChainService.run_parse_chain", fail_parse)
    set_tool_session_factory(factory)
    try:
        result = ingest_paper_document.invoke({"paper_id": paper.id})
    finally:
        set_tool_session_factory(None)

    assert result == {"paper_id": paper.id, "status": "parse_failed", "error": "parser service unavailable"}



def test_retrieve_paper_evidence_returns_structured_error(session, engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Retrieval Failure Paper")
    session.add(paper)
    session.commit()

    def fail_retrieve(_service, paper_id, query, limit=5):
        raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr("backend.tools.paper_qa.RetrievalService.retrieve", fail_retrieve)
    set_tool_session_factory(factory)
    try:
        result = retrieve_paper_evidence.invoke({"paper_id": paper.id, "query": "methods"})
    finally:
        set_tool_session_factory(None)

    assert result == {"paper_id": paper.id, "status": "failed", "chunks": [], "error": "embedding provider unavailable"}



def test_download_arxiv_paper_artifacts_returns_structured_error(session, engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Download Failure Paper")
    session.add(paper)
    session.commit()

    monkeypatch.setattr("backend.tools.paper_acquisition.paper_source_adapters_from_settings", lambda: {})
    set_tool_session_factory(factory)
    try:
        result = download_arxiv_paper_artifacts.invoke({"paper_id": paper.id, "arxiv_id": "2401.00001"})
    finally:
        set_tool_session_factory(None)

    assert result == {
        "status": "failed",
        "tool": "download_arxiv_paper_artifacts",
        "paper_id": paper.id,
        "error": "arXiv paper source is not configured",
        "action": "ask_user_upload",
    }



def test_list_paper_artifacts_returns_structured_error_without_active_paper(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    set_tool_session_factory(factory)
    try:
        result = list_paper_artifacts.invoke({})
    finally:
        set_tool_session_factory(None)

    assert result == {
        "status": "failed",
        "paper_id": None,
        "artifacts": [],
        "error": "No active paper. Ask the user to select or confirm a paper first.",
    }



def test_ingest_paper_document_returns_parse_failed_without_processing(session, engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Unparseable Paper")
    session.add(paper)
    session.commit()

    def fake_run_parse_chain(_service, paper_id, run_id=None):
        return SimpleNamespace(id=10, status="failed", strategy="unavailable", error_message="No parseable artifact.")

    def fail_process(_service, _paper_id):
        raise AssertionError("process should not run after parse failure")

    monkeypatch.setattr("backend.tools.paper_parsing.ParseChainService.run_parse_chain", fake_run_parse_chain)
    monkeypatch.setattr("backend.tools.paper_parsing.DocumentProcessingService.process_latest_parsed_document", fail_process)
    set_tool_session_factory(factory)
    try:
        result = ingest_paper_document.invoke({"paper_id": paper.id})
    finally:
        set_tool_session_factory(None)

    assert result == {
        "paper_id": paper.id,
        "status": "parse_failed",
        "parse_job_id": 10,
        "strategy": "unavailable",
        "error": "No parseable artifact.",
    }



def test_ingest_paper_document_processes_after_successful_parse(session, engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    paper = Paper(title="Parseable Paper")
    session.add(paper)
    session.commit()

    def fake_run_parse_chain(_service, paper_id, run_id=None):
        return SimpleNamespace(id=11, status="succeeded", strategy="tex", error_message=None)

    def fake_process(_service, paper_id):
        return SimpleNamespace(id=12, paper_id=paper_id, status="ready", version=1)

    monkeypatch.setattr("backend.tools.paper_parsing.ParseChainService.run_parse_chain", fake_run_parse_chain)
    monkeypatch.setattr("backend.tools.paper_parsing.DocumentProcessingService.process_latest_parsed_document", fake_process)
    set_tool_session_factory(factory)
    try:
        result = ingest_paper_document.invoke({"paper_id": paper.id})
    finally:
        set_tool_session_factory(None)

    assert result == {
        "paper_id": paper.id,
        "status": "ready",
        "parse_job_id": 11,
        "strategy": "tex",
        "processed_document_id": 12,
        "processed_status": "ready",
        "version": 1,
    }



def test_generate_paper_report_returns_error_message_on_failure(session, engine, monkeypatch):
    class FailingReportService:
        def __init__(self, *args, **kwargs):
            pass

        def generate_reading_report(self, paper_id, **kwargs):
            report = Report(paper_id=paper_id, title="Failed report", status="failed", report_type="paper_summary", source_scope="full_document", error_message="Request timed out.")
            session.add(report)
            session.flush()
            return ReportGenerationResult(report_id=report.id, status="failed", json_content={"error": "Request timed out."}, error_message="Request timed out.")

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    thread = Thread(title="Report thread")
    paper = Paper(title="Timeout Paper")
    session.add_all([thread, paper])
    session.flush()
    run = AgentRun(workflow=WorkflowName.paper_qa.value, thread_id=thread.id, status=RunStatus.running.value)
    session.add(run)
    session.commit()
    monkeypatch.setattr("backend.tools.paper_reports.ReportGenerationService", FailingReportService)
    set_tool_session_factory(factory)
    try:
        with tool_runtime_context(PaperClawContext(thread_id=thread.id, run_id=run.id)):
            with pytest.raises(RuntimeError, match="Request timed out"):
                generate_paper_report.invoke({"paper_id": paper.id, "orchestrator_instruction": "Language: English", "output_language": "English"})
    finally:
        set_tool_session_factory(None)

    events = session.query(AgentRunEvent).filter_by(run_id=run.id).order_by(AgentRunEvent.sequence).all()
    assert [event.event_type for event in events] == ["report_generation_started", "report_generation_failed"]
    assert events[-1].level == "error"
    assert events[-1].payload_json["error_message"] == "Request timed out."


def test_tools_can_be_invoked_directly(session, engine, monkeypatch):
    monkeypatch.setattr(
        "backend.services.embeddings.embedding_provider_from_settings",
        lambda: ResolvedProviderConfig(id=0, name="fixture-embedding", kind="embedding", provider="fixture", model="fixture-embedding-v1"),
    )
    monkeypatch.setattr(
        "backend.services.reports.chat_provider_from_settings",
        lambda: ResolvedProviderConfig(id=0, name="fixture-chat", kind="chat", provider="fixture", model="fixture", settings={"title": "Tool Report"}),
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    thread = Thread(title="Tool thread")
    paper = Paper(title="Tool Paper")
    session.add_all([thread, paper])
    session.flush()
    run = AgentRun(workflow=WorkflowName.paper_qa.value, thread_id=thread.id, status=RunStatus.running.value)
    session.add(run)
    session.flush()
    repo = ParsingRepository(session)
    job = repo.create_parse_job(paper.id, status="succeeded", strategy="fixture")
    parsed = repo.create_parsed_document(paper.id, job.id, "fixture", plain_text="retrieval evidence", markdown_content="retrieval evidence")
    processed = repo.create_processed_document(paper.id, parsed.id, job.id, status=ProcessedDocumentStatus.ready.value, content_text="retrieval evidence", content_markdown="retrieval evidence")
    repo.add_chunk(processed.id, "c1", 1, "retrieval evidence")
    session.commit()
    set_tool_session_factory(factory)
    try:
        paper_result = get_paper.invoke({"paper_id": paper.id})
        retrieval_result = retrieve_paper_evidence.invoke({"paper_id": paper.id, "query": "retrieval"})
        with tool_runtime_context(PaperClawContext(thread_id=thread.id, run_id=run.id)):
            report_result = generate_paper_report.invoke({"paper_id": paper.id, "orchestrator_instruction": "Language: English. Focus on retrieval.", "output_language": "English"})
    finally:
        set_tool_session_factory(None)

    assert paper_result["title"] == "Tool Paper"
    assert retrieval_result["chunks"][0]["content"] == "retrieval evidence"
    assert report_result["status"] == "succeeded"
    assert report_result["json_content"]["context_strategy"] == "full_body"
    assert report_result["json_content"]["validation_passed"] is True
    events = session.query(AgentRunEvent).filter_by(run_id=run.id).order_by(AgentRunEvent.sequence).all()
    assert [event.event_type for event in events] == ["report_generation_started", "report_generation_succeeded"]
    assert events[-1].payload_json["report_id"] == report_result["report_id"]
