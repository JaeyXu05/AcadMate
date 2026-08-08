from __future__ import annotations

import pytest

from backend.mentor_workflow.agents.composer import ResultComposerAgent
from backend.mentor_workflow.agents.evaluation import MatchingAgent
from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.schemas import (
    IntentPacket,
    MentorGoal,
    MentorWorkflowRequest,
    ReviewDecision,
    ReviewStatus,
    UserProfile,
    new_workflow_state,
)


def _approved_state(research_result_factory, *, goal=MentorGoal.find_mentors):
    result = research_result_factory()
    request = MentorWorkflowRequest(
        message="workflow",
        goal=goal,
        research_topics=["multi-agent reinforcement learning"],
        user_profile=UserProfile(
            name="Student S",
            education_level="undergraduate",
            background=["mathematics"],
        ),
    )
    state = new_workflow_state(request, trace_id="trace-composer")
    state.intent = IntentPacket(
        trace_id=state.trace_id,
        goal=goal,
        research_topics=request.research_topics,
        user_profile=request.user_profile,
        confidence=0.9,
    )
    state.candidates = result.candidates
    state.evidence_ledger = result.evidence
    state.match_results = MatchingAgent().run(
        state.intent, state.candidates, EvidenceLedger(state.evidence_ledger)
    )
    state.review_decision = ReviewDecision(
        status=ReviewStatus.pass_,
        reviewed_candidate_ids=[state.candidates[0].candidate_id],
        reviewer_summary="approved",
    )
    return state


def test_composer_generates_only_after_pass(research_result_factory):
    state = _approved_state(research_result_factory)
    state.review_decision = ReviewDecision(
        status=ReviewStatus.revise, reviewer_summary="revise"
    )

    with pytest.raises(ValueError, match="PASS"):
        ResultComposerAgent().run(state)


def test_composer_preserves_candidates_scores_evidence_and_uncertainty(
    research_result_factory,
):
    state = _approved_state(research_result_factory)
    original_candidate = state.candidates[0].model_copy(deep=True)
    original_match = state.match_results[0].model_copy(deep=True)

    result = ResultComposerAgent().run(state)

    assert len(result.mentors) == 1
    assert result.mentors[0].candidate == original_candidate
    assert result.mentors[0].match == original_match
    assert result.evidence_refs == original_candidate.evidence_refs
    assert result.uncertainty == original_match.uncertainty


def test_composer_rejects_invalid_evidence_reference(research_result_factory):
    state = _approved_state(research_result_factory)
    state.candidates[0].evidence_refs = ["unknown"]

    with pytest.raises(ValueError, match="invalid evidence"):
        ResultComposerAgent().run(state)


def test_contact_email_uses_only_approved_facts_and_does_not_send(
    research_result_factory,
):
    state = _approved_state(
        research_result_factory, goal=MentorGoal.generate_contact_email
    )

    result = ResultComposerAgent().run(state)

    assert result.contact_email_draft is not None
    assert "Professor A" in result.contact_email_draft
    assert "Verified MARL Paper" in result.contact_email_draft
    assert "未假设您的招生状态" in result.contact_email_draft
    assert not hasattr(result, "send")
