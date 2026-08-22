from __future__ import annotations

from backend.agents.runner import _active_paper_system_info, _agent_context, _resume_decisions, prepare_agent_message_run
from backend.agents.runner import PreparedAgentRun
from backend.db.models import Paper, Thread
from backend.settings import clear_settings_cache
from backend.schemas import AgentMessageRequest, ApprovalRequest


def test_prepare_agent_message_run_persists_request_active_paper(session):
    paper = Paper(title="Focused Paper", year=2024, authors_json=["Alice", "Bob"])
    thread = Thread(title="Thread")
    session.add_all([paper, thread])
    session.commit()

    prepared = prepare_agent_message_run(session, AgentMessageRequest(thread_id=thread.id, message="Summarize this paper", active_paper_id=paper.id))

    assert prepared.active_paper_id == paper.id
    assert session.get(Thread, thread.id).current_focus_paper_id == paper.id
    assert prepared.active_paper_system_info is not None
    assert f"Active paper is #{paper.id}: Focused Paper" in prepared.active_paper_system_info


def test_prepare_agent_message_run_rejects_unknown_active_paper(session):
    thread = Thread(title="Thread")
    session.add(thread)
    session.commit()

    try:
        prepare_agent_message_run(session, AgentMessageRequest(thread_id=thread.id, message="Summarize", active_paper_id=999))
    except ValueError as exc:
        assert "Paper 999 not found" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_prepare_agent_message_run_falls_back_to_thread_focus(session):
    paper = Paper(title="Existing Focus")
    thread = Thread(title="Thread", current_focus_paper_id=None)
    session.add_all([paper, thread])
    session.flush()
    thread.current_focus_paper_id = paper.id
    session.commit()

    prepared = prepare_agent_message_run(session, AgentMessageRequest(thread_id=thread.id, message="Continue"))

    assert prepared.active_paper_id == paper.id
    assert session.get(Thread, thread.id).current_focus_paper_id == paper.id
    assert prepared.active_paper_system_info is not None
    assert f"Active paper is #{paper.id}: Existing Focus" in prepared.active_paper_system_info


def test_resume_decisions_preserves_edit_payload_shape():
    decisions = _resume_decisions(
        ApprovalRequest(
            decisions=[
                {
                    "type": "edit",
                    "edited_action": {"name": "update_paper_metadata", "args": {"paper_id": 15, "metadata": {"venue": "EMNLP 2024"}}},
                }
            ]
        )
    )

    assert decisions == [
        {
            "type": "edit",
            "edited_action": {"name": "update_paper_metadata", "args": {"paper_id": 15, "metadata": {"venue": "EMNLP 2024"}}},
        }
    ]


def test_resume_decisions_preserves_reject_message():
    decisions = _resume_decisions(ApprovalRequest(decisions=[{"type": "reject", "message": "not this change"}]))

    assert decisions == [{"type": "reject", "message": "not this change"}]


def test_agent_context_request_model_falls_back_to_settings_provider(monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_CHAT_API_KEY", "settings-key")
    monkeypatch.setenv("PAPER_CLAW_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "settings-model")
    monkeypatch.setenv("PAPER_CLAW_CHAT_TEMPERATURE", "0.4")
    monkeypatch.setenv("PAPER_CLAW_CHAT_MAX_TOKENS", "1234")
    monkeypatch.setenv("PAPER_CLAW_CHAT_EXTRA_BODY", '{"thinking": {"type": "disabled"}}')
    clear_settings_cache()
    try:
        context = _agent_context(
            PreparedAgentRun(thread_id=1, run_id=2, deepagent_thread_id="thread-1", active_paper_id=None, active_paper_system_info=None),
            AgentMessageRequest(message="hello", model="request-model"),
        )
    finally:
        clear_settings_cache()

    assert context.model == "request-model"
    assert context.api_key == "settings-key"
    assert context.base_url == "https://chat.example/v1"
    assert context.temperature == 0.4
    assert context.max_tokens == 1234
    assert context.extra_body["thinking"] == {"type": "disabled"}


def test_agent_context_request_provider_overrides_settings(monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_CHAT_API_KEY", "settings-key")
    monkeypatch.setenv("PAPER_CLAW_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "settings-model")
    clear_settings_cache()
    try:
        context = _agent_context(
            PreparedAgentRun(thread_id=1, run_id=2, deepagent_thread_id="thread-1", active_paper_id=None, active_paper_system_info=None),
            AgentMessageRequest(message="hello", model="request-model", api_key="request-key", base_url="https://request.example/v1"),
        )
    finally:
        clear_settings_cache()

    assert context.model == "request-model"
    assert context.api_key == "request-key"
    assert context.base_url == "https://request.example/v1"


def test_active_paper_system_info_includes_catalog_metadata(session):
    paper = Paper(title="Metadata Paper", year=2025, authors_json=["A", "B", "C", "D", "E", "F"])
    session.add(paper)
    session.commit()

    info = _active_paper_system_info(session, paper.id)

    assert info is not None
    assert f"Active paper is #{paper.id}: Metadata Paper" in info
    assert "Year: 2025." in info
    assert "Authors: A, B, C, D, E." in info
    assert "this paper" in info
