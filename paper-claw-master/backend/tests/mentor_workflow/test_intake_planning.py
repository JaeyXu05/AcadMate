from __future__ import annotations

import pytest

from backend.mentor_workflow.agents.intake import InputUnderstandingAgent, PlanningAgent
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    FinalResult,
    MentorConstraints,
    MentorGoal,
    MentorWorkflowRequest,
    ParsedDocumentInput,
    ReviewDecision,
    ReviewStatus,
    UserProfile,
    new_workflow_state,
)


@pytest.mark.parametrize(
    ("workflow_request", "expected_topic", "expected_missing"),
    [
        (
            MentorWorkflowRequest(
                message="帮我找做多智能体强化学习的导师",
                research_topics=["multi-agent reinforcement learning"],
            ),
            "多智能体强化学习",
            [],
        ),
        (MentorWorkflowRequest(message="帮我找导师"), None, ["research_topics"]),
        (
            MentorWorkflowRequest(
                message="找强化学习导师",
                research_topics=["reinforcement learning"],
                methods=["policy gradient"],
            ),
            "强化学习",
            [],
        ),
        (
            MentorWorkflowRequest(
                message="找 AI 导师",
                research_topics=["AI"],
                constraints=MentorConstraints(departments=["Computer Science"]),
            ),
            "AI",
            [],
        ),
        (
            MentorWorkflowRequest(
                message="找 AI 导师",
                research_topics=["AI"],
                user_profile=UserProfile(background=["mathematics"], skills=["Python"]),
            ),
            "AI",
            [],
        ),
        (
            MentorWorkflowRequest(
                message="根据论文找导师",
                parsed_documents=[
                    ParsedDocumentInput(
                        source_ref="pdf:1",
                        summary="A paper about graph learning.",
                        research_topics=["graph learning"],
                    )
                ],
            ),
            "graph learning",
            [],
        ),
        (MentorWorkflowRequest(message="计算机视觉"), "计算机视觉", []),
        (MentorWorkflowRequest(message="推荐系统"), "推荐系统", []),
        (MentorWorkflowRequest(message="找计算机视觉导师"), "计算机视觉", []),
        (MentorWorkflowRequest(message="computer vision"), "computer vision", []),
        (
            MentorWorkflowRequest(
                message="我想找计算机视觉方向的博导，关注目标检测和三维重建"
            ),
            "计算机视觉",
            [],
        ),
    ],
)
def test_input_understanding_handles_supported_inputs(
    workflow_request, expected_topic, expected_missing
):
    state = new_workflow_state(workflow_request, trace_id="trace-input")

    intent, clarification = InputUnderstandingAgent().run(workflow_request, state)

    assert (
        (expected_topic in intent.research_topics)
        if expected_topic
        else not intent.research_topics
    )
    assert intent.missing_fields == expected_missing
    assert (clarification is not None) == bool(expected_missing)


def test_current_message_topics_are_not_merged_with_historical_research_topics():
    request = MentorWorkflowRequest(
        message="推荐系统",
        research_topics=["几何拓扑", "动力系统", "邮政编码：230026", "具身智能"],
    )
    intent, clarification = InputUnderstandingAgent().run(
        request, new_workflow_state(request, trace_id="trace-current-intent")
    )

    assert intent.research_topics == ["推荐系统"]
    assert clarification is None
    assert "几何拓扑" not in intent.research_topics
    assert "邮政编码：230026" not in intent.research_topics


def test_query_contract_keeps_preferences_out_of_required_topics():
    request = MentorWorkflowRequest(
        message="我想找做多智能体强化学习、图神经网络，偏理论且正在招生的导师"
    )
    intent, clarification = InputUnderstandingAgent().run(
        request, new_workflow_state(request, trace_id="trace-preferences")
    )

    assert clarification is None
    required = [
        concept.canonical for concept in intent.query_contract.concepts if concept.required
    ]
    assert required == ["multi-agent reinforcement learning", "graph learning"]
    assert intent.constraints.recruitment_required is True
    assert intent.constraints.theory_preference == 1.0


def test_input_understanding_corrects_unambiguous_search_verb_typo():
    request = MentorWorkflowRequest(message="找作强化学习的老师")
    intent, _ = InputUnderstandingAgent().run(
        request, new_workflow_state(request, trace_id="trace-typo")
    )

    assert intent.research_topics == ["强化学习"]
    assert intent.query_contract.canonical_query == "强化学习"


def test_input_understanding_requires_candidate_for_compare():
    request = MentorWorkflowRequest(
        message="比较这些导师", goal=MentorGoal.compare_mentors
    )
    intent, clarification = InputUnderstandingAgent().run(
        request, new_workflow_state(request)
    )

    assert intent.missing_fields == ["candidate_ids_or_mentor_names"]
    assert clarification is not None


def test_input_understanding_email_requires_prior_approved_result():
    request = MentorWorkflowRequest(
        message="生成联系邮件", goal=MentorGoal.generate_contact_email
    )
    state = new_workflow_state(request)

    intent, _ = InputUnderstandingAgent().run(request, state)
    assert intent.missing_fields == ["approved_result"]

    state.review_decision = ReviewDecision(
        status=ReviewStatus.pass_, reviewer_summary="approved"
    )
    state.candidates = [
        CandidateMentor(candidate_id="mentor-1", mentor_name="Professor A")
    ]
    intent, clarification = InputUnderstandingAgent().run(request, state)
    assert intent.missing_fields == []
    assert clarification is None


@pytest.mark.parametrize(
    ("goal", "expected", "skipped"),
    [
        (
            MentorGoal.find_mentors,
            [
                "domain_expert",
                "mentor_research",
                "matching",
                "evidence_review",
                "result_composer",
            ],
            [],
        ),
        (
            MentorGoal.inspect_mentor,
            ["mentor_research", "evidence_review", "result_composer"],
            ["domain_expert", "matching"],
        ),
        (
            MentorGoal.compare_mentors,
            ["mentor_research", "matching", "evidence_review", "result_composer"],
            ["domain_expert"],
        ),
        (
            MentorGoal.generate_contact_email,
            ["result_composer"],
            ["domain_expert", "mentor_research", "matching", "evidence_review"],
        ),
        (
            MentorGoal.follow_up_question,
            ["result_composer"],
            ["domain_expert", "mentor_research", "matching", "evidence_review"],
        ),
    ],
)
def test_planning_builds_goal_specific_plan(goal, expected, skipped):
    request = MentorWorkflowRequest(
        message="task",
        goal=goal,
        research_topics=["AI"],
        constraints=MentorConstraints(mentor_names=["Professor A"]),
    )
    state = new_workflow_state(request, trace_id="trace-plan")
    if goal in {MentorGoal.generate_contact_email, MentorGoal.follow_up_question}:
        state.review_decision = ReviewDecision(
            status=ReviewStatus.pass_, reviewer_summary="approved"
        )
        state.candidates = [
            CandidateMentor(candidate_id="mentor-1", mentor_name="Professor A")
        ]
    if goal == MentorGoal.follow_up_question:
        state.final_result = FinalResult(
            trace_id=state.trace_id, goal=MentorGoal.find_mentors
        )
    intent, clarification = InputUnderstandingAgent().run(request, state)
    assert clarification is None

    plan = PlanningAgent().run(intent, state)

    assert [step.agent_name for step in plan.steps] == expected
    assert plan.skipped_steps == skipped
    assert plan.retry_policy.max_total_retries == 5
