from __future__ import annotations

from backend.mentor_workflow.event_bus import InMemoryEventBus
from backend.mentor_workflow.orchestrator import MentorWorkflowOrchestrator
from backend.mentor_workflow.schemas import (
    EvidenceFreshness,
    MentorGoal,
    MentorWorkflowRequest,
    MentorWorkflowSupplement,
    ReviewStatus,
    WorkflowEventType,
    WorkflowStatus,
)
from backend.mentor_workflow.state_store import InMemoryStateStore

from .helpers import SequenceResearchTool


def _orchestrator(tool):
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    return MentorWorkflowOrchestrator(store, tool, event_bus=bus), store, bus


def test_flow_a_normal_mentor_search_completes(research_result_factory):
    tool = SequenceResearchTool(local_results=[research_result_factory()])
    orchestrator, store, bus = _orchestrator(tool)

    state = orchestrator.create(
        MentorWorkflowRequest(
            message="帮我找做多智能体强化学习的导师",
            research_topics=["multi-agent reinforcement learning"],
            methods=["reinforcement learning"],
        )
    )

    assert state.status == WorkflowStatus.completed
    assert state.review_decision.status == ReviewStatus.pass_
    assert state.final_result is not None
    assert len(state.final_result.mentors) == 1
    event_types = [event.event_type for event in bus.list_events(state.trace_id)]
    assert event_types[0] == WorkflowEventType.workflow_created
    assert WorkflowEventType.review_passed in event_types
    assert event_types[-1] == WorkflowEventType.workflow_completed
    assert store.get_workflow(state.trace_id).state_version == state.state_version


def test_flow_b_stale_evidence_triggers_local_research_retry(research_result_factory):
    stale = research_result_factory(
        freshness=EvidenceFreshness.stale, evidence_id="ev-stale"
    )
    fresh = research_result_factory(
        freshness=EvidenceFreshness.current, evidence_id="ev-current"
    )
    tool = SequenceResearchTool(local_results=[stale, fresh])
    orchestrator, _, bus = _orchestrator(tool)

    state = orchestrator.create(
        MentorWorkflowRequest(
            message="find MARL mentors",
            research_topics=["multi-agent reinforcement learning"],
        )
    )

    assert state.status == WorkflowStatus.completed
    assert state.review_decision.status == ReviewStatus.pass_
    assert tool.local_calls == 2
    assert len(state.retries) == 1
    assert state.retries[0].retry_target.value == "mentor_research"
    event_types = [event.event_type for event in bus.list_events(state.trace_id)]
    assert event_types.count(WorkflowEventType.domain_analysis_started) == 1
    assert event_types.count(WorkflowEventType.research_started) == 2
    assert WorkflowEventType.task_retry in event_types


def test_flow_c_insufficient_input_requests_clarification_without_candidates():
    tool = SequenceResearchTool()
    orchestrator, _, bus = _orchestrator(tool)

    state = orchestrator.create(MentorWorkflowRequest(message="帮我找导师"))

    assert state.status == WorkflowStatus.clarification_required
    assert state.clarification_request.missing_fields == ["research_topics"]
    assert state.candidates == []
    assert state.final_result is None
    assert tool.local_calls == 0
    assert (
        bus.list_events(state.trace_id)[-1].event_type
        == WorkflowEventType.clarification_required
    )


def test_flow_d_contact_email_reuses_approved_result_without_new_research(
    research_result_factory,
):
    tool = SequenceResearchTool(local_results=[research_result_factory()])
    orchestrator, _, _ = _orchestrator(tool)
    approved = orchestrator.create(
        MentorWorkflowRequest(
            message="find MARL mentors",
            research_topics=["multi-agent reinforcement learning"],
        )
    )
    calls_before_email = tool.local_calls

    emailed = orchestrator.supplement(
        approved.trace_id,
        MentorWorkflowSupplement(
            message="generate a contact email",
            goal=MentorGoal.generate_contact_email,
        ),
    )

    assert emailed.status == WorkflowStatus.completed
    assert emailed.final_result.goal == MentorGoal.generate_contact_email
    assert emailed.final_result.contact_email_draft is not None
    assert emailed.final_result.evidence_refs
    assert tool.local_calls == calls_before_email
