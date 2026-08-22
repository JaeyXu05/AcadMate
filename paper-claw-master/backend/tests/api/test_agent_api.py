from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from backend.db.models import AgentRun, Message, Thread
from backend.db.repositories import AgentRunRepository
from backend.db.types import MessageRole, RunStatus, WorkflowName
from backend.settings import clear_settings_cache


class FakeAgent:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def stream(self, payload, *, context, config=None, stream_mode=None, subgraphs=None, version=None):
        self.calls.append((payload, context, config, stream_mode, subgraphs, version))
        if isinstance(self.chunks, Exception):
            raise self.chunks
        if callable(self.chunks):
            yield from self.chunks(context)
            return
        yield from self.chunks


def message_chunk(content: str):
    return {"type": "messages", "ns": (), "data": (AIMessage(content=content), {"langgraph_node": "model"})}


def test_post_agent_message_creates_thread_messages_run_and_events(client, session, monkeypatch):
    fake_agent = FakeAgent([message_chunk("assistant answer")])
    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: fake_agent)

    response = client.post("/api/agent/messages", json={"message": "Explain this paper", "model": "test-model", "api_key": "secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == RunStatus.running.value
    assert payload["message"] is None
    run = session.get(AgentRun, payload["run_id"])
    thread = session.get(Thread, payload["thread_id"])
    assert thread.deepagent_thread_id is not None
    assert run.deepagent_thread_id == thread.deepagent_thread_id
    assert run.status == RunStatus.running.value
    assert run.input_json["has_api_key"] is True
    assert "api_key" not in run.input_json
    messages = session.query(Message).filter(Message.thread_id == payload["thread_id"]).order_by(Message.created_at).all()
    assert [message.role for message in messages] == [MessageRole.user.value]
    assert [event.event_type for event in run.events] == ["agent_message_received"]


def test_post_agent_message_stream_returns_ndjson_events(client, session, monkeypatch):
    fake_agent = FakeAgent([message_chunk("streamed answer")])
    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: fake_agent)

    with client.stream("POST", "/api/agent/messages/stream", json={"message": "Stream this", "model": "test-model"}) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]

    payloads = [json.loads(line) for line in events]
    assert [payload["type"] for payload in payloads] == ["run_started", "agent_chunk", "run_completed"]
    assert payloads[-1]["message"] == "streamed answer"
    run = session.get(AgentRun, payloads[-1]["run_id"])
    thread = session.get(Thread, payloads[-1]["thread_id"])
    assert run.status == RunStatus.succeeded.value
    assert fake_agent.calls[0][0]["messages"][0]["content"] == "Stream this"
    assert fake_agent.calls[0][1].thread_id == thread.id
    assert fake_agent.calls[0][1].run_id == run.id
    assert fake_agent.calls[0][1].model == "test-model"
    assert fake_agent.calls[0][2]["configurable"]["thread_id"] == thread.deepagent_thread_id
    assert fake_agent.calls[0][2]["metadata"]["paper_claw_run_id"] == run.id
    assert fake_agent.calls[0][3] == ["messages", "updates"]
    assert fake_agent.calls[0][4] is True
    assert fake_agent.calls[0][5] == "v2"
    messages = session.query(Message).filter(Message.thread_id == payloads[-1]["thread_id"]).order_by(Message.created_at).all()
    assert [message.role for message in messages] == [MessageRole.user.value, MessageRole.assistant.value]


def test_post_agent_message_stream_stops_persisting_after_cancel(client, session, monkeypatch):
    def chunks(context):
        yield message_chunk("partial answer")
        run = session.get(AgentRun, context.run_id)
        run.status = RunStatus.cancelled.value
        AgentRunRepository(session).append_event(run.id, "agent_run_cancelled")
        session.commit()
        yield message_chunk(" should not persist")

    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: FakeAgent(chunks))

    with client.stream("POST", "/api/agent/messages/stream", json={"message": "Cancel this", "model": "test-model"}) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]

    payloads = [json.loads(line) for line in events]
    assert [payload["type"] for payload in payloads] == ["run_started", "agent_chunk", "run_cancelled"]
    run = session.get(AgentRun, payloads[-1]["run_id"])
    assert run.status == RunStatus.cancelled.value
    messages = session.query(Message).filter(Message.thread_id == payloads[-1]["thread_id"]).order_by(Message.created_at).all()
    assert [message.role for message in messages] == [MessageRole.user.value]
    event_types = [event.event_type for event in run.events]
    assert "agent_run_cancelled" in event_types
    assert "agent_message_completed" not in event_types


def test_post_agent_message_stream_preserves_failed_run_from_tool_middleware(client, session, monkeypatch):
    def chunks(context):
        run = session.get(AgentRun, context.run_id)
        run.status = RunStatus.failed.value
        run.error_message = "subagent task failed"
        AgentRunRepository(session).append_event(
            run.id,
            "agent_message_failed",
            level="error",
            payload_json={"error": "subagent task failed", "status": RunStatus.failed.value},
        )
        session.commit()
        return
        yield

    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: FakeAgent(chunks))

    with client.stream("POST", "/api/agent/messages/stream", json={"message": "fail inside task", "model": "test-model"}) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line]

    payloads = [json.loads(line) for line in events]
    assert [payload["type"] for payload in payloads] == ["run_started", "run_failed"]
    run = session.get(AgentRun, payloads[-1]["run_id"])
    assert run.status == RunStatus.failed.value
    assert run.error_message == "subagent task failed"
    assert "agent_message_completed" not in [event.event_type for event in run.events]



def test_post_agent_message_reuses_existing_thread(client, session, monkeypatch):
    thread = Thread(title="Existing thread")
    session.add(thread)
    session.commit()
    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: FakeAgent([message_chunk("ok")]))

    response = client.post("/api/agent/messages", json={"thread_id": thread.id, "message": "Continue", "model": "test-model"})

    assert response.status_code == 200
    assert response.json()["thread_id"] == thread.id
    session.refresh(thread)
    assert thread.deepagent_thread_id is not None


def test_post_agent_message_uses_settings_chat_provider(client, monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "openai:gpt-4o-mini")
    monkeypatch.setenv("PAPER_CLAW_CHAT_API_KEY", "secret-value")
    monkeypatch.setenv("PAPER_CLAW_CHAT_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("PAPER_CLAW_CHAT_TEMPERATURE", "0.4")
    monkeypatch.setenv("PAPER_CLAW_CHAT_TIMEOUT_SECONDS", "33")
    monkeypatch.setenv("PAPER_CLAW_CHAT_MAX_RETRIES", "3")
    clear_settings_cache()
    fake_agent = FakeAgent([message_chunk("ok")])
    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: fake_agent)

    try:
        response = client.post("/api/agent/messages", json={"message": "Use settings"})
    finally:
        clear_settings_cache()

    assert response.status_code == 200
    context = fake_agent.calls[0][1]
    assert context.model == "openai:gpt-4o-mini"
    assert context.api_key == "secret-value"
    assert context.base_url == "https://example.invalid/v1"
    assert context.temperature == 0.4
    assert context.timeout == 33
    assert context.max_retries == 3


def test_post_agent_message_reports_missing_chat_model(client, monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", " ")
    clear_settings_cache()
    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: FakeAgent([message_chunk("ok")]))

    try:
        response = client.post("/api/agent/messages", json={"message": "Use settings"})
    finally:
        clear_settings_cache()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == RunStatus.running.value
    run_response = client.get(f"/api/runs/{payload['run_id']}")
    assert run_response.status_code == 200
    assert run_response.json()["status"] == RunStatus.running.value


def test_post_agent_message_failure_marks_run_failed(client, session, monkeypatch):
    monkeypatch.setattr("backend.agents.runner.create_paper_claw_agent", lambda: FakeAgent(RuntimeError("model failed")))

    response = client.post("/api/agent/messages", json={"message": "fail", "model": "test-model"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == RunStatus.running.value
    assert payload["error"] is None
    run = session.get(AgentRun, payload["run_id"])
    assert run.status == RunStatus.running.value
    assert run.error_message is None
    assert run.events[-1].event_type == "agent_message_received"


def test_run_events_endpoint_filters_after_sequence(client, session):
    run = AgentRunRepository(session).create(WorkflowName.paper_qa.value, status=RunStatus.running.value)
    repo = AgentRunRepository(session)
    repo.append_event(run.id, "first")
    repo.append_event(run.id, "second")
    session.commit()

    response = client.get(f"/api/agent/runs/{run.id}/events", params={"after_sequence": 1})

    assert response.status_code == 200
    payload = response.json()
    assert [event["event_type"] for event in payload] == ["second"]


def test_cancel_run_marks_running_run_cancelled(client, session):
    run = AgentRunRepository(session).create(WorkflowName.paper_qa.value, status=RunStatus.running.value)
    session.commit()

    response = client.post(f"/api/agent/runs/{run.id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == RunStatus.cancelled.value
    assert run.events[-1].event_type == "agent_run_cancelled"


def test_route_list_does_not_expose_direct_orchestration_endpoints(client):
    paths = {route.path for route in client.app.routes}

    assert "/api/parse" not in paths
    assert "/api/acquire" not in paths
    assert "/api/reports/generate" not in paths
    assert "/api/search/run" not in paths
