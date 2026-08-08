from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.schemas import (
    AgentMessage,
    CandidateMentor,
    EvidenceRecord,
    IntentPacket,
    MentorGoal,
    MentorWorkflowRequest,
    ReviewDecision,
    ReviewStatus,
    WorkflowEventType,
    new_workflow_state,
)
from backend.mentor_workflow.state_store import InMemoryStateStore


def test_intent_packet_validates_complete_payload():
    intent = IntentPacket(
        trace_id="trace-1",
        goal=MentorGoal.find_mentors,
        research_topics=["multi-agent systems"],
        confidence=0.8,
    )

    assert intent.goal == MentorGoal.find_mentors
    assert intent.research_topics == ["multi-agent systems"]


def test_intent_packet_rejects_missing_required_trace_id():
    with pytest.raises(ValidationError):
        IntentPacket.model_validate(
            {"goal": "find_mentors", "research_topics": ["AI"], "confidence": 0.8}
        )


def test_agent_message_validates_event_enum():
    message = AgentMessage(
        trace_id="trace-1",
        sender="a",
        receiver="b",
        event_type=WorkflowEventType.intent_ready,
        state_version=1,
    )

    assert message.event_type.value == "INTENT_READY"
    with pytest.raises(ValidationError):
        AgentMessage.model_validate(
            {
                "trace_id": "trace-1",
                "sender": "a",
                "receiver": "b",
                "event_type": "NOT_AN_EVENT",
                "state_version": 1,
            }
        )


def test_evidence_record_requires_locator_and_fact():
    with pytest.raises(ValidationError):
        EvidenceRecord(
            source_type="local",
            source_uri="paper:1",
            title="Paper",
            extracted_fact="",
            locator="",
            confidence=0.9,
        )


def test_review_decision_validates_status_enum():
    decision = ReviewDecision(status=ReviewStatus.pass_, reviewer_summary="ok")
    assert decision.status.value == "PASS"
    with pytest.raises(ValidationError):
        ReviewDecision.model_validate({"status": "OK", "reviewer_summary": "bad"})


def test_workflow_state_initializes_and_version_increments():
    store = InMemoryStateStore()
    state = store.create_workflow(
        new_workflow_state(MentorWorkflowRequest(message="帮我找 AI 导师"))
    )

    updated = store.increment_version(state.trace_id, expected_version=1)

    assert state.state_version == 1
    assert updated.state_version == 2


def test_evidence_ledger_rejects_unknown_or_wrong_candidate_refs():
    record = EvidenceRecord(
        evidence_id="ev-1",
        candidate_id="mentor-1",
        source_type="local",
        source_uri="paper:1",
        title="Paper",
        extracted_fact="Mentor 1 authored Paper.",
        locator="authors",
        confidence=0.9,
    )
    ledger = EvidenceLedger([record])

    unknown = CandidateMentor(
        candidate_id="mentor-1",
        mentor_name="Mentor 1",
        evidence_refs=["ev-missing"],
    )
    wrong = CandidateMentor(
        candidate_id="mentor-2",
        mentor_name="Mentor 2",
        evidence_refs=["ev-1"],
    )

    assert ledger.validate_candidate(unknown) == ["ev-missing"]
    assert ledger.validate_candidate(wrong) == ["ev-1"]


def test_evidence_ledger_deduplicates_same_source_fact():
    first = EvidenceRecord(
        evidence_id="ev-1",
        candidate_id="mentor-1",
        source_type="local",
        source_uri="paper:1",
        title="Paper",
        extracted_fact="Mentor authored Paper.",
        locator="authors",
        confidence=0.9,
    )
    duplicate = first.model_copy(update={"evidence_id": "ev-2"})
    ledger = EvidenceLedger([first])

    stored = ledger.add(duplicate)

    assert stored.evidence_id == "ev-1"
    assert len(ledger.list()) == 1
