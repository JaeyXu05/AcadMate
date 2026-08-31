"""Mentor Skill: wrap MentorWorkflowOrchestrator. Does not retrieve itself."""

from __future__ import annotations

from backend.harness.contracts import RunCreate, RunCreated
from backend.harness.runtime import suggest_next_skill
from backend.mentor_workflow.schemas import (
    MentorWorkflowRequest,
    UserProfile,
    UserProjectInput,
)


_MAX_CONTEXT_TOPICS = 24


def start_mentor_match(request: RunCreate, orchestrator, commit, run_id_of) -> RunCreated:
    growth = request.context.growth or {}
    profile = request.context.profile or {}
    background_topics = _historical_background_topics(growth, profile)
    verified_experiences = [
        item
        for item in growth.get("verified_experiences") or []
        if isinstance(item, dict) and item.get("review_status") == "PASS"
    ]
    pending_tasks = [
        item
        for item in growth.get("research_tasks") or []
        if isinstance(item, dict) and item.get("status") in {"pending", "in_progress"}
    ]
    artifacts = [
        item for item in growth.get("artifacts") or [] if isinstance(item, dict)
    ]
    evidence_refs = sorted(
        {
            str(reference)
            for item in [*verified_experiences, *artifacts]
            for reference in item.get("evidence_refs") or []
            if str(reference)
        }
    )
    workflow_request = MentorWorkflowRequest(
        message=request.message,
        research_topics=[],
        user_profile=UserProfile(
            name=profile.get("nickname") or profile.get("name"),
            education_level=profile.get("grade"),
            skills=list(profile.get("skills") or []),
            background=background_topics,
            experiences=[
                str(item.get("summary"))
                for item in verified_experiences
                if item.get("summary")
            ],
            preferences=[
                str(item.get("title"))
                for item in pending_tasks
                if item.get("title")
            ],
        ),
        projects=[
            UserProjectInput(
                name=str(item.get("title") or item.get("id") or "科研产物"),
                description=(
                    f"审核通过的成长产物；类型={item.get('type') or 'artifact'}；"
                    f"来源运行={item.get('source_run_id') or 'unknown'}"
                ),
                outcomes=[str(ref) for ref in item.get("evidence_refs") or []],
            )
            for item in artifacts[:10]
        ],
        raw_input_refs=evidence_refs,
        execute_immediately=False,
    )
    state = orchestrator.create(workflow_request)
    commit()
    numeric_run_id = run_id_of(state.trace_id)
    status = state.status.value if hasattr(state.status, "value") else str(state.status)
    return RunCreated(
        run_id=str(numeric_run_id or state.trace_id),
        skill_id="mentor_match",
        status=status,
        trace_id=state.trace_id,
        suggested_next_skill=suggest_next_skill(growth),
    )


def _historical_background_topics(
    growth: dict, profile: dict, *, limit: int = _MAX_CONTEXT_TOPICS
) -> list[str]:
    """Historical directions are background only, never the current query.

    ``growth.directions`` is append-only and may contain faculty tags from
    earlier matches. Those belong on ``user_profile.background`` so they can
    inform student-background fit, not ``research_topics`` used for recall.
    """

    from backend.mentor_workflow.topic_cleaning import clean_topics

    candidates: list[str] = []
    if isinstance(profile.get("interests"), list):
        candidates.extend(str(item) for item in profile["interests"])
    for item in growth.get("direction_hypotheses") or []:
        if not isinstance(item, dict):
            continue
        if item.get("review_status") not in {None, "PASS"}:
            continue
        for key in ("direction", "title", "name", "summary"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value)
                break
    candidates.extend(str(item) for item in growth.get("directions") or [])
    return [
        topic
        for topic in clean_topics(candidates, limit=limit)
        if len(topic) <= 120
    ]


def mentor_match_result(run_id: int, session, runtime) -> RunCreated:
    """Map a persisted mentor AgentRun back onto the Harness contract."""
    from backend.db.models import AgentRun
    from backend.db.types import WorkflowName

    run = session.get(AgentRun, run_id)
    if run is None or run.workflow != WorkflowName.mentor_search.value:
        raise ValueError("mentor AgentRun not found")
    trace_id = str(run.deepagent_run_id or "")
    state = runtime.store.get_workflow(trace_id) if trace_id else None
    if state is None:
        raise ValueError("mentor workflow not found")
    evidence_refs = [
        str(item.evidence_id)
        for item in (state.evidence_ledger or [])
        if getattr(item, "evidence_id", None)
    ]
    mentors = []
    if state.final_result is not None:
        mentors = [item.model_dump() for item in state.final_result.mentors]
    review_status = (
        state.review_decision.status.value
        if state.review_decision is not None
        else None
    )
    query_contract = state.intent.query_contract.model_dump() if state.intent else {}
    return RunCreated(
        run_id=str(run.id),
        skill_id="mentor_match",
        status=state.status.value if hasattr(state.status, "value") else str(state.status),
        trace_id=trace_id,
        suggested_next_skill="paper_qa" if mentors else None,
        review_status=review_status,
        evidence_refs=evidence_refs,
        artifact={
            "type": "mentor_match_result",
            "schema_version": 2,
            "query_contract": query_contract,
            "retrieval_attempts": list(state.retrieval_attempts),
            "relation_judgements": list(state.relation_judgements),
            "coverage_report": dict(state.coverage_report),
            "quality_status": state.final_result.quality_status
            if state.final_result is not None
            else ("NO_MATCH" if not mentors else "PASS"),
            "mentors": mentors,
        },
    )
