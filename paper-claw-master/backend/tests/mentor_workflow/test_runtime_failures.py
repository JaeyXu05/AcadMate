from __future__ import annotations

from time import sleep

import pytest

from backend.mentor_workflow.agents.domain_research import MentorResearchAgent
from backend.mentor_workflow.errors import (
    ModelOutputFormatError,
    PersistenceConflictError,
    ToolTimeoutError,
    parse_structured_output,
)
from backend.mentor_workflow.event_bus import InMemoryEventBus
from backend.mentor_workflow.orchestrator import MentorWorkflowOrchestrator
from backend.mentor_workflow.schemas import (
    AgentMessage,
    IntentPacket,
    MentorGoal,
    MentorResearchResult,
    MentorWorkflowRequest,
    WorkflowErrorKind,
    WorkflowEventType,
    WorkflowStage,
    WorkflowStatus,
    new_workflow_state,
)
from backend.mentor_workflow.state_store import InMemoryStateStore

from .helpers import SequenceResearchTool


def _intent() -> IntentPacket:
    return IntentPacket(
        trace_id="trace-runtime",
        goal=MentorGoal.find_mentors,
        research_topics=["AI"],
        confidence=0.9,
    )


def test_parse_structured_output_rejects_unparseable_model_response():
    with pytest.raises(ModelOutputFormatError):
        parse_structured_output(
            "not json", IntentPacket, stage=WorkflowStage.input_understanding
        )


def test_parse_structured_output_validates_provider_neutral_json():
    output = parse_structured_output(
        '{"trace_id":"trace-runtime","goal":"find_mentors","research_topics":["AI"],"confidence":0.9}',
        IntentPacket,
        stage=WorkflowStage.input_understanding,
    )
    assert output.goal == MentorGoal.find_mentors


def test_event_bus_records_and_dispatches_trace_events():
    bus = InMemoryEventBus()
    seen: list[str] = []
    bus.subscribe(
        WorkflowEventType.intent_ready, lambda message: seen.append(message.message_id)
    )
    message = AgentMessage(
        trace_id="trace-runtime",
        sender="input",
        receiver="planning",
        event_type=WorkflowEventType.intent_ready,
        state_version=1,
    )

    bus.publish(message)

    assert seen == [message.message_id]
    assert bus.list_events("trace-runtime") == [message]
    assert bus.list_events("another-trace") == []


def test_state_store_detects_optimistic_version_conflict():
    store = InMemoryStateStore()
    state = store.create_workflow(
        new_workflow_state(
            MentorWorkflowRequest(message="find AI", research_topics=["AI"])
        )
    )
    store.increment_version(state.trace_id, expected_version=1)

    with pytest.raises(PersistenceConflictError):
        store.increment_version(state.trace_id, expected_version=1)


def test_research_tool_timeout_is_a_typed_error():
    class SlowTool:
        def search_local(self, _intent, _judgements):
            sleep(0.01)
            return MentorResearchResult()

        def search_fallback(self, _intent, _judgements):
            return MentorResearchResult()

    with pytest.raises(ToolTimeoutError):
        MentorResearchAgent(SlowTool(), tool_timeout_seconds=0.001).run(
            _intent(), [], []
        )


def test_agent_timeout_fails_workflow_in_controlled_state():
    store = InMemoryStateStore()
    orchestrator = MentorWorkflowOrchestrator(
        store,
        SequenceResearchTool(),
        agent_timeout_seconds=0.001,
    )
    input_run = orchestrator.input_agent.run

    def slow_input(*args):
        sleep(0.01)
        return input_run(*args)

    orchestrator.input_agent.run = slow_input

    state = orchestrator.create(
        MentorWorkflowRequest(message="find AI mentors", research_topics=["AI"])
    )

    assert state.status == WorkflowStatus.failed
    assert state.errors[-1].kind == WorkflowErrorKind.agent_timeout


def test_invalid_agent_schema_is_recorded_as_schema_validation_error():
    orchestrator = MentorWorkflowOrchestrator(
        InMemoryStateStore(),
        SequenceResearchTool(),
    )
    orchestrator.input_agent.run = lambda *_args: ("invalid-intent", None)

    state = orchestrator.create(
        MentorWorkflowRequest(message="find AI mentors", research_topics=["AI"])
    )

    assert state.status == WorkflowStatus.failed
    assert state.errors[-1].kind == WorkflowErrorKind.schema_validation


def test_empty_research_completes_as_auditable_no_match_without_retry_loop():
    tool = SequenceResearchTool()
    orchestrator = MentorWorkflowOrchestrator(
        InMemoryStateStore(),
        tool,
        max_total_retries=2,
    )

    state = orchestrator.create(
        MentorWorkflowRequest(message="find AI mentors", research_topics=["AI"])
    )

    assert state.status == WorkflowStatus.completed
    assert state.review_decision is not None
    assert state.review_decision.status.value == "PASS"
    assert state.candidates == []
    assert state.final_result is not None
    assert state.final_result.mentors == []
    assert len(state.retries) == 0
    assert tool.local_calls == 1
