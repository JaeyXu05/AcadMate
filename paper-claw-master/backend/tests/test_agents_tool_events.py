from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from backend.agents.context import PaperClawContext
from backend.agents.tool_events import record_tool_event_call
from backend.db.models import AgentRun
from backend.db.types import RunStatus, WorkflowName


class FakeTool:
    name = "fake_tool"


class FakeRequest:
    def __init__(self, run_id: int):
        self.runtime = SimpleNamespace(context=PaperClawContext(run_id=run_id))
        self.tool = FakeTool()
        self.tool_call = {"id": "call-1", "name": "fake_tool", "args": {"query": "x", "api_key": "secret"}}


def test_tool_event_middleware_records_started_and_completed(session):
    run = AgentRun(workflow=WorkflowName.paper_qa.value, status=RunStatus.running.value)
    session.add(run)
    session.commit()

    def handler(_request):
        return ToolMessage(content="tool result", tool_call_id="call-1")

    result = record_tool_event_call(FakeRequest(run.id), handler)

    assert result.content == "tool result"
    session.refresh(run)
    assert [event.event_type for event in run.events] == ["agent_tool_call_started", "agent_tool_call_completed"]
    assert run.events[0].payload_json["args"]["api_key"] == "[REDACTED]"
    assert run.events[1].payload_json["result_preview"] == "tool result"


def test_tool_event_middleware_records_failure(session):
    run = AgentRun(workflow=WorkflowName.paper_qa.value, status=RunStatus.running.value)
    session.add(run)
    session.commit()

    def handler(_request):
        raise RuntimeError("boom")

    try:
        record_tool_event_call(FakeRequest(run.id), handler)
    except RuntimeError:
        pass

    session.refresh(run)
    assert [event.event_type for event in run.events] == ["agent_tool_call_started", "agent_tool_call_failed"]
    assert run.events[-1].payload_json["error"] == "boom"
