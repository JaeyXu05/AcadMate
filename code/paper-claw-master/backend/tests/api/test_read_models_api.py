from __future__ import annotations

from datetime import datetime, timedelta

from backend.db.models import Artifact, Memory, Paper, Report, ReportEvidence
from backend.db.repositories import AgentRunRepository, ParsingRepository, ThreadRepository
from backend.db.types import ArtifactKind, EventLevel, EvidenceType, PaperArtifactRole, ReportType, RunStatus, ThreadStatus, WorkflowName
from backend.services.storage import ArtifactStorageService
from backend.integrations.storage import LocalStorage


def test_threads_read_model(client, session):
    threads = ThreadRepository(session)
    runs = AgentRunRepository(session)
    thread = threads.create("API thread")
    run = runs.create(WorkflowName.paper_qa.value, thread_id=thread.id)
    event = runs.append_event(run.id, "agent_message_received")
    threads.add_message(thread.id, "user", "hello", run_id=run.id)
    session.commit()

    list_response = client.get("/api/threads")
    detail_response = client.get(f"/api/threads/{thread.id}")

    assert list_response.status_code == 200
    assert list_response.json()[0]["title"] == "API thread"
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["messages"][0]["content_text"] == "hello"
    assert payload["runs"][0]["events"][0]["id"] == event.id


def test_run_read_model_marks_stale_running_run_failed(client, session):
    runs = AgentRunRepository(session)
    thread = ThreadRepository(session).create("Stale run thread")
    run = runs.create(WorkflowName.paper_qa.value, thread_id=thread.id, status=RunStatus.running.value)
    run.started_at = datetime.now().astimezone() - timedelta(minutes=30)
    event = runs.append_event(run.id, "agent_stream_update", payload_json={"data": {"model": None}})
    event.created_at = datetime.now().astimezone() - timedelta(minutes=30)
    session.commit()

    response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == RunStatus.failed.value
    assert payload["error_message"] == "Agent run stopped before completion. Please retry the request."
    assert payload["events"][-1]["event_type"] == "agent_message_failed"
    assert payload["events"][-1]["level"] == EventLevel.error.value


def test_archive_thread_hides_it_from_default_list(client, session):
    thread = ThreadRepository(session).create("Archived thread")
    session.commit()

    archive_response = client.post(f"/api/threads/{thread.id}/archive")
    list_response = client.get("/api/threads")
    archived_list_response = client.get("/api/threads", params={"include_archived": True})

    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == ThreadStatus.archived.value
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == []
    assert archived_list_response.status_code == 200
    assert archived_list_response.json()[0]["id"] == thread.id


def test_archive_missing_thread_returns_404(client):
    response = client.post("/api/threads/999/archive")

    assert response.status_code == 404


def test_memories_read_model(client, session):
    memory = Memory(path="/memories/user/preferences.md", title="Preferences", content_text="Use Chinese.")
    session.add(memory)
    session.commit()

    response = client.get("/api/memories")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["path"] == memory.path
    assert payload[0]["content_text"] == "Use Chinese."


def test_runtime_settings_read_model_redacts_secrets(client, monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_CHAT_API_KEY", "secret-value")
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "openai:gpt-test")
    from backend.settings import clear_settings_cache

    clear_settings_cache()
    try:
        response = client.get("/api/settings/runtime")
    finally:
        clear_settings_cache()

    assert response.status_code == 200
    payload = response.json()
    assert payload["chat"]["api_key_configured"] is True
    assert "secret-value" not in str(payload)


def test_paper_detail_includes_aggregate_state(client, session, tmp_path):
    paper = Paper(title="API paper", authors_json=["A"])
    session.add(paper)
    session.flush()
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    ArtifactStorageService(session, LocalStorage(tmp_path / "files")).register_local_pdf(paper.id, source)
    repo = ParsingRepository(session)
    job = repo.create_parse_job(paper.id, status="succeeded", strategy="fixture")
    parsed = repo.create_parsed_document(paper.id, job.id, "fixture")
    repo.create_processed_document(paper.id, parsed.id, job.id, status="ready")
    report = Report(title="API report", paper_id=paper.id, report_type=ReportType.paper_summary.value, markdown_content="report")
    session.add(report)
    session.commit()

    response = client.get(f"/api/papers/{paper.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "API paper"
    assert payload["artifacts"][0]["kind"] == ArtifactKind.pdf.value
    assert payload["parse_jobs"][0]["status"] == "succeeded"
    assert payload["processed_documents"][0]["status"] == "ready"
    assert payload["reports"][0]["title"] == "API report"


def test_delete_report_removes_report_and_evidence(client, session):
    paper = Paper(title="Delete report paper")
    session.add(paper)
    session.flush()
    report = Report(title="Delete report", paper_id=paper.id, report_type=ReportType.paper_summary.value, markdown_content="report")
    session.add(report)
    session.flush()
    evidence = ReportEvidence(report_id=report.id, evidence_type=EvidenceType.paper.value, paper_id=paper.id, quote_text="quote")
    session.add(evidence)
    session.commit()

    response = client.delete(f"/api/reports/{report.id}")

    assert response.status_code == 204
    assert session.get(Report, report.id) is None
    assert session.get(ReportEvidence, evidence.id) is None


def test_delete_missing_report_returns_404(client):
    response = client.delete("/api/reports/999")

    assert response.status_code == 404


def test_report_detail_includes_evidence(client, session):
    paper = Paper(title="Evidence paper")
    session.add(paper)
    session.flush()
    report = Report(title="Evidence report", paper_id=paper.id, report_type=ReportType.paper_summary.value, markdown_content="report")
    session.add(report)
    session.flush()
    session.add(ReportEvidence(report_id=report.id, evidence_type=EvidenceType.paper.value, paper_id=paper.id, quote_text="quote"))
    session.commit()

    response = client.get(f"/api/reports/{report.id}")

    assert response.status_code == 200
    assert response.json()["paper_title"] == "Evidence paper"
    assert response.json()["evidence"][0]["quote_text"] == "quote"
