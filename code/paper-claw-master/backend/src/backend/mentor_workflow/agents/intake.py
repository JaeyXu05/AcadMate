from __future__ import annotations

import re

from backend.mentor_workflow.schemas import (
    AgentAssignment,
    ClarificationRequest,
    ExecutionMode,
    InputSource,
    IntentPacket,
    MentorGoal,
    MentorWorkflowRequest,
    PlanStep,
    RetryPolicy,
    ReviewStatus,
    TaskPlan,
    ToolBudget,
    WorkflowState,
)


class InputUnderstandingAgent:
    name = "input_understanding_agent"

    def run(
        self, request: MentorWorkflowRequest, state: WorkflowState
    ) -> tuple[IntentPacket, ClarificationRequest | None]:
        goal = request.goal or _detect_goal(request.message)
        topics = _unique(
            [
                *request.research_topics,
                *[
                    topic
                    for document in request.parsed_documents
                    for topic in document.research_topics
                ],
                *[
                    topic
                    for trace in request.interaction_traces
                    for topic in trace.research_topics
                ],
                *_topics_from_text(request.message),
            ]
        )
        methods = _unique(
            [
                *request.methods,
                *[
                    method
                    for document in request.parsed_documents
                    for method in document.methods
                ],
            ]
        )
        applications = _unique(
            [
                *request.application_domains,
                *[
                    domain
                    for document in request.parsed_documents
                    for domain in document.application_domains
                ],
            ]
        )
        constraints = request.constraints.model_copy(deep=True)
        if not constraints.colleges:
            constraints.colleges = ["中国科学技术大学"]
        constraints.departments = _unique(
            [
                *constraints.departments,
                *[
                    department
                    for trace in request.interaction_traces
                    for department in trace.departments
                ],
            ]
        )
        sources = [InputSource.text]
        if request.research_topics:
            sources.append(InputSource.keyword)
        if request.parsed_documents:
            sources.append(InputSource.pdf)
        if request.interaction_traces:
            sources.append(InputSource.interaction_trace)
        if any(request.user_profile.model_dump().values()) or request.projects:
            sources.append(InputSource.user_profile)
        if state.final_result is not None:
            sources.append(InputSource.prior_workflow)

        missing = _missing_fields(
            goal, topics, constraints.candidate_ids, constraints.mentor_names, state
        )
        questions = [_question_for(field) for field in missing]
        confidence = (
            0.9 if request.goal or request.research_topics else 0.7 if topics else 0.35
        )
        intent = IntentPacket(
            trace_id=state.trace_id,
            goal=goal,
            research_topics=topics,
            methods=methods,
            application_domains=applications,
            input_sources=_unique_enum(sources),
            constraints=constraints,
            user_profile=request.user_profile.model_copy(deep=True),
            projects=[project.model_copy(deep=True) for project in request.projects],
            raw_message=request.message,
            confidence=confidence,
            missing_fields=missing,
            raw_input_refs=_unique(
                [
                    *request.raw_input_refs,
                    *[document.source_ref for document in request.parsed_documents],
                    *[trace.source_ref for trace in request.interaction_traces],
                ]
            ),
            clarification_questions=questions,
        )
        clarification = None
        if missing:
            clarification = ClarificationRequest(
                missing_fields=missing,
                questions=questions,
                reason="The workflow cannot produce evidence-grounded mentor results until the required fields are supplied.",
            )
        return intent, clarification


class PlanningAgent:
    name = "planning_agent"

    def __init__(
        self,
        *,
        agent_timeout_seconds: float = 300,
        tool_timeout_seconds: float = 240,
        max_total_retries: int = 5,
    ) -> None:
        self.agent_timeout_seconds = agent_timeout_seconds
        self.tool_timeout_seconds = tool_timeout_seconds
        self.max_total_retries = max_total_retries

    def run(self, intent: IntentPacket, state: WorkflowState) -> TaskPlan:
        enabled = _enabled_agents(intent.goal)
        order = [
            "domain_expert",
            "mentor_research",
            "matching",
            "evidence_review",
            "result_composer",
        ]
        steps: list[PlanStep] = []
        previous: str | None = None
        for agent_name in order:
            if agent_name not in enabled:
                continue
            step_dependencies = [previous] if previous is not None else []
            steps.append(
                PlanStep(
                    step_id=agent_name,
                    agent_name=agent_name,
                    dependencies=step_dependencies,
                )
            )
            previous = agent_name
        skipped = [agent for agent in order if agent not in enabled]
        assignments = [_assignment(agent) for agent in enabled]
        dependency_map = {step.step_id: step.dependencies for step in steps}
        return TaskPlan(
            trace_id=intent.trace_id,
            steps=steps,
            agent_assignments=assignments,
            dependencies=dependency_map,
            execution_mode=ExecutionMode.sequential,
            tool_budget=ToolBudget(per_tool_timeout_seconds=self.tool_timeout_seconds),
            retry_policy=RetryPolicy(max_total_retries=self.max_total_retries),
            stop_conditions=[
                "stop_on_clarification_required",
                "stop_on_review_pass",
                "stop_on_retry_limit",
                f"agent_timeout_seconds={self.agent_timeout_seconds}",
            ],
            skipped_steps=skipped,
        )


def _detect_goal(message: str) -> MentorGoal:
    normalized = message.casefold()
    if any(term in normalized for term in ("邮件", "email", "联系信", "套磁")):
        return MentorGoal.generate_contact_email
    if any(term in normalized for term in ("比较", "对比", "compare")):
        return MentorGoal.compare_mentors
    if any(
        term in normalized
        for term in ("介绍这位导师", "查看导师", "inspect", "这位老师")
    ):
        return MentorGoal.inspect_mentor
    if any(term in normalized for term in ("继续", "追问", "follow up", "follow-up")):
        return MentorGoal.follow_up_question
    return MentorGoal.find_mentors


def _topics_from_text(message: str) -> list[str]:
    broad = {"帮我找导师", "找导师", "推荐导师", "please find mentors", "find mentors"}
    normalized = " ".join(message.casefold().split()).strip("。.!！?")
    if normalized in broad:
        return []
    patterns = [
        r"(?:做|研究|方向(?:是|为)?|关注)([^，,。；;]{2,80}?)(?:的导师|的老师|方向|，|,|。|；|;|$)",
        r"(?:in|on) ([a-z][a-z0-9\- ]{2,80}?)(?: mentors?| professors?|,|\.|$)",
    ]
    topics: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, message, flags=re.IGNORECASE):
            value = match.group(1).strip()
            for part in re.split(r"[、/]|\band\b", value):
                cleaned = part.strip()
                if cleaned and not any(
                    marker in cleaned
                    for marker in ("偏理论", "愿意带", "本科生", "招生", "学院")
                ):
                    topics.append(cleaned)
    return _unique(topics)


def _missing_fields(
    goal: MentorGoal,
    topics: list[str],
    candidate_ids: list[str],
    mentor_names: list[str],
    state: WorkflowState,
) -> list[str]:
    missing: list[str] = []
    if goal == MentorGoal.find_mentors and not topics:
        missing.append("research_topics")
    if (
        goal in {MentorGoal.inspect_mentor, MentorGoal.compare_mentors}
        and not candidate_ids
        and not mentor_names
    ):
        missing.append("candidate_ids_or_mentor_names")
    if goal == MentorGoal.generate_contact_email:
        if (
            state.review_decision is None
            or state.review_decision.status != ReviewStatus.pass_
            or not state.candidates
        ):
            missing.append("approved_result")
    if goal == MentorGoal.follow_up_question and state.final_result is None:
        missing.append("prior_workflow_result")
    return missing


def _question_for(field: str) -> str:
    return {
        "research_topics": "请补充至少一个具体研究方向、方法或感兴趣的论文主题。",
        "candidate_ids_or_mentor_names": "请提供要查看或比较的导师姓名或候选编号。",
        "approved_result": "请先完成并通过导师证据审核，再生成联系邮件。",
        "prior_workflow_result": "当前没有可复用的已完成导师检索结果，请补充问题背景。",
    }[field]


def _enabled_agents(goal: MentorGoal) -> list[str]:
    return {
        MentorGoal.find_mentors: [
            "domain_expert",
            "mentor_research",
            "matching",
            "evidence_review",
            "result_composer",
        ],
        MentorGoal.inspect_mentor: [
            "mentor_research",
            "evidence_review",
            "result_composer",
        ],
        MentorGoal.compare_mentors: [
            "mentor_research",
            "matching",
            "evidence_review",
            "result_composer",
        ],
        MentorGoal.generate_contact_email: ["result_composer"],
        MentorGoal.follow_up_question: ["result_composer"],
    }[goal]


def _assignment(agent_name: str) -> AgentAssignment:
    data = {
        "domain_expert": (
            "Expand terminology and preserve domain disagreements.",
            ["domain_configuration", "terminology_dictionary"],
            "At least one structured DomainJudgement is produced.",
            "No defensible search boundary can be formed.",
        ),
        "mentor_research": (
            (
                "Collect USTC mentor facts from the internal RAG, official "
                "faculty pages, and attributable paper evidence."
            ),
            [
                "internal_ustc_rag",
                "ustc_official_faculty",
                "ustc_official_profile",
                "arxiv_paper_fallback",
                "openalex_paper_fallback",
            ],
            "Candidates and evidence records are structurally valid.",
            "No candidates or sources are available.",
        ),
        "matching": (
            "Score candidates across evidence-grounded dimensions.",
            ["deterministic_scoring"],
            "Every score and rationale references ledger evidence.",
            "A candidate lacks usable evidence.",
        ),
        "evidence_review": (
            "Independently verify facts, citations, freshness, and score consistency.",
            ["evidence_ledger", "score_consistency_checker"],
            "ReviewDecision is PASS or a precise revision target is returned.",
            "The decision cannot identify a safe next action.",
        ),
        "result_composer": (
            "Compose only an approved, frontend-consumable result.",
            ["contact_email_template"],
            "Output preserves evidence references, risks, and uncertainty.",
            "The review is not PASS.",
        ),
    }[agent_name]
    return AgentAssignment(
        agent_name=agent_name,
        responsibility=data[0],
        authorized_tools=data[1],
        success_condition=data[2],
        failure_condition=data[3],
    )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _unique_enum(values: list[InputSource]) -> list[InputSource]:
    return list(dict.fromkeys(values))
