from __future__ import annotations

import pytest

from backend.mentor_workflow.agents.domain_research import (
    DynamicDomainExpertAgent,
    MentorResearchAgent,
)
from backend.mentor_workflow.agents.evaluation import (
    EvidenceReviewAgent,
    MatchingAgent,
    RetryController,
)
from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    EvidenceFreshness,
    IntentPacket,
    MentorGoal,
    MentorResearchResult,
    MentorWorkflowRequest,
    RetryPolicy,
    RetryRecord,
    RetryTarget,
    ReviewDecision,
    ReviewStatus,
    WorkflowState,
    new_workflow_state,
)

from .helpers import SequenceResearchTool


def _intent(**updates) -> IntentPacket:
    payload = {
        "trace_id": "trace-1",
        "goal": MentorGoal.find_mentors,
        "research_topics": ["multi-agent reinforcement learning"],
        "methods": ["reinforcement learning"],
        "application_domains": [],
        "confidence": 0.9,
    }
    payload.update(updates)
    return IntentPacket.model_validate(payload)


def _state(intent: IntentPacket | None = None) -> WorkflowState:
    state = new_workflow_state(
        MentorWorkflowRequest(
            message="find mentors",
            research_topics=["multi-agent reinforcement learning"],
        ),
        trace_id="trace-1",
    )
    state.intent = intent or _intent()
    return state


def test_domain_expert_loads_multiple_configs_and_preserves_disagreement():
    judgements = DynamicDomainExpertAgent().run(
        _intent(research_topics=["多智能体强化学习", "博弈论"])
    )

    assert {item.domain for item in judgements} == {
        "artificial_intelligence",
        "mathematics_statistics",
    }
    assert all(item.conflicts for item in judgements)
    assert any(
        "multi-agent reinforcement learning" in item.search_concepts
        for item in judgements
    )


def test_research_uses_local_result_and_binds_evidence(research_result_factory):
    result = research_result_factory()
    tool = SequenceResearchTool(local_results=[result])

    output = MentorResearchAgent(tool).run(_intent(), [], [])

    assert tool.local_calls == 1
    assert tool.fallback_calls == 0
    assert output.candidates[0].evidence_refs == [output.evidence[0].evidence_id]


def test_research_calls_fallback_when_local_has_no_results(research_result_factory):
    fallback = research_result_factory(
        candidate_id="mentor-2", mentor_name="Professor B"
    )
    tool = SequenceResearchTool(
        local_results=[MentorResearchResult()], fallback_result=fallback
    )

    output = MentorResearchAgent(tool).run(_intent(), [], [])

    assert tool.local_calls == 1
    assert tool.fallback_calls == 1
    assert output.used_fallback
    assert output.candidates[0].candidate_id == "mentor-2"


def test_research_deduplicates_existing_evidence(research_result_factory):
    result = research_result_factory(evidence_id="ev-same")
    duplicate = result.evidence[0].model_copy(update={"evidence_id": "ev-duplicate"})
    result.evidence = [duplicate]
    result.candidates[0].evidence_refs = [duplicate.evidence_id]
    tool = SequenceResearchTool(local_results=[result])

    output = MentorResearchAgent(tool).run(
        _intent(), [], [research_result_factory(evidence_id="ev-same").evidence[0]]
    )

    assert output.candidates[0].evidence_refs == ["ev-same"]
    assert output.evidence[0].evidence_id == "ev-same"


def test_research_degrades_after_tool_error(research_result_factory):
    fallback = research_result_factory(candidate_id="mentor-fallback")
    tool = SequenceResearchTool(
        local_error=RuntimeError("temporary"), fallback_result=fallback
    )

    output = MentorResearchAgent(tool).run(_intent(), [], [])

    assert output.candidates[0].candidate_id == "mentor-fallback"
    assert output.warnings


def test_matching_scores_multiple_dimensions_and_ranks(research_result_factory):
    strong = research_result_factory(candidate_id="strong")
    weak = research_result_factory(
        candidate_id="weak",
        mentor_name="Professor Weak",
        topics=["computer vision"],
        missing_fields=[
            "affiliation",
            "department",
            "projects",
            "homepage",
            "recruitment_status",
        ],
    )
    all_evidence = [*strong.evidence, *weak.evidence]

    matches = MatchingAgent().run(
        _intent(), [*strong.candidates, *weak.candidates], EvidenceLedger(all_evidence)
    )

    assert matches[0].candidate_id == "strong"
    assert matches[0].ranking_position == 1
    assert matches[0].dimension_scores.research_topic_match == 100
    assert (
        matches[1].dimension_scores.evidence_completeness
        < matches[0].dimension_scores.evidence_completeness
    )
    assert matches[0].risks == [
        "Recruitment status is not verified and must not be assumed."
    ]


def test_matching_rejects_unknown_evidence_reference(research_result_factory):
    result = research_result_factory()
    result.candidates[0].evidence_refs = ["missing"]

    with pytest.raises(ValueError, match="unknown or mismatched evidence"):
        MatchingAgent().run(
            _intent(), result.candidates, EvidenceLedger(result.evidence)
        )


def test_matching_rejects_candidate_without_evidence():
    candidate = CandidateMentor(candidate_id="mentor-1", mentor_name="Professor A")

    with pytest.raises(ValueError, match="has no evidence"):
        MatchingAgent().run(_intent(), [candidate], EvidenceLedger())


def _review_state(
    research_result_factory, freshness=EvidenceFreshness.current
) -> WorkflowState:
    result = research_result_factory(freshness=freshness)
    state = _state()
    state.candidates = result.candidates
    state.evidence_ledger = result.evidence
    state.match_results = MatchingAgent().run(
        state.intent, state.candidates, EvidenceLedger(state.evidence_ledger)
    )
    return state


def test_review_passes_consistent_evidence(research_result_factory):
    decision = EvidenceReviewAgent().run(_review_state(research_result_factory))
    assert decision.status == ReviewStatus.pass_


def test_review_requests_research_for_stale_evidence(research_result_factory):
    decision = EvidenceReviewAgent().run(
        _review_state(research_result_factory, EvidenceFreshness.stale)
    )
    assert decision.status == ReviewStatus.research_again
    assert decision.revision_target == RetryTarget.mentor_research


def test_review_requests_research_for_invalid_reference(research_result_factory):
    state = _review_state(research_result_factory)
    state.candidates[0].evidence_refs = ["missing"]

    decision = EvidenceReviewAgent().run(state)

    assert decision.status == ReviewStatus.research_again
    assert "missing" in decision.missing_evidence_refs


def test_review_requests_research_when_mentor_identity_is_not_verified(
    research_result_factory,
):
    state = _review_state(research_result_factory)
    state.evidence_ledger[0].metadata["identity_verified"] = False

    decision = EvidenceReviewAgent().run(state)

    assert decision.status == ReviewStatus.research_again
    assert decision.revision_target == RetryTarget.mentor_research
    assert decision.failed_checks == ["evidence_fact_support"]
    assert decision.missing_evidence_refs == ["candidate:mentor_1:mentor_identity"]


def test_review_rejects_faculty_record_without_verified_mentor_role(
    research_result_factory,
):
    state = _review_state(research_result_factory)
    state.evidence_ledger[0].metadata["identity_verified"] = True
    state.evidence_ledger[0].metadata["mentor_role_verified"] = False

    decision = EvidenceReviewAgent().run(state)

    assert decision.status == ReviewStatus.research_again
    assert decision.revision_target == RetryTarget.mentor_research
    assert decision.missing_evidence_refs == ["candidate:mentor_1:mentor_identity"]


def test_review_requires_evidence_backed_research_direction(
    research_result_factory,
):
    state = _review_state(research_result_factory)
    state.candidates[0].research_topics = []
    state.candidates[0].methods = []
    state.candidates[0].missing_fields = ["research_topics", "methods"]

    decision = EvidenceReviewAgent().run(state)

    assert decision.status == ReviewStatus.research_again
    assert decision.revision_target == RetryTarget.mentor_research
    assert decision.failed_checks == ["candidate_research_direction_presence"]


def test_review_requests_matching_revision_for_score_mismatch(research_result_factory):
    state = _review_state(research_result_factory)
    state.match_results[0].total_score = 1

    decision = EvidenceReviewAgent().run(state)

    assert decision.status == ReviewStatus.revise
    assert decision.revision_target == RetryTarget.matching


def test_review_needs_more_input_for_incomplete_intent():
    state = _state(_intent(missing_fields=["research_topics"]))
    decision = EvidenceReviewAgent().run(state)
    assert decision.status == ReviewStatus.need_more_input
    assert decision.revision_target == RetryTarget.input_understanding


@pytest.mark.parametrize(
    ("failed_check", "target"),
    [
        ("evidence_reference_integrity", RetryTarget.mentor_research),
        ("domain_direction", RetryTarget.domain_expert),
        ("score_consistency", RetryTarget.matching),
        ("input_completeness", RetryTarget.input_understanding),
        ("output_format", RetryTarget.result_composer),
    ],
)
def test_retry_controller_routes_precisely(failed_check, target):
    state = _state()
    decision = ReviewDecision(
        status=ReviewStatus.revise,
        failed_checks=[failed_check],
        reviewer_summary="retry",
    )

    instruction = RetryController().decide(decision, state, RetryPolicy())

    assert instruction.target == target
    assert not instruction.exhausted


def test_retry_controller_stops_at_stage_limit():
    state = _state()
    state.retries = [
        RetryRecord(
            retry_count=index,
            retry_target=RetryTarget.mentor_research,
            retry_reason="missing evidence",
            previous_state_version=index,
            new_state_version=index + 1,
            triggering_review_id=f"review-{index}",
        )
        for index in (1, 2)
    ]
    decision = ReviewDecision(
        status=ReviewStatus.research_again,
        revision_target=RetryTarget.mentor_research,
        reviewer_summary="retry",
    )

    instruction = RetryController().decide(decision, state, RetryPolicy())

    assert instruction.exhausted
    assert instruction.target is None
