from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.agents.runner import cancel_run, execute_agent_run, list_run_events
from backend.api.deps import get_db_session
from backend.api.routers.mentor_workflows import (
    MentorWorkflowRuntime,
    get_mentor_workflow_runtime,
)
from backend.db.models import AgentRun
from backend.db.types import RunStatus, WorkflowName
from backend.harness.contracts import RunCreate, RunCreated
from backend.harness.email_skill import email_compose_result, start_email_compose
from backend.harness.mentor_skill import mentor_match_result, start_mentor_match
from backend.harness.paper_skill import paper_qa_result, start_paper_qa
from backend.harness.pdf_skill import (
    execute_pdf_analyze,
    pdf_analyze_result,
    queue_pdf_analyze,
)
from backend.harness.productivity_skill import (
    execute_plan_coach,
    execute_progress_report,
    productivity_result,
    queue_plan_coach,
    queue_progress_report,
)
from backend.harness.profile_skill import profile_analyze_result, start_profile_analyze
from backend.harness.research_skill import (
    skill_result,
    start_direction_explore,
    start_research_task,
)
from backend.harness.runtime import suggest_next_skill

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunCreated)
def create_run(
    request: RunCreate,
    background_tasks: BackgroundTasks,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
    session: Session = Depends(get_db_session),
) -> RunCreated:
    skill_id = request.skill_id or "mentor_match"
    if skill_id == "mentor_match":
        created = start_mentor_match(
            request,
            runtime.orchestrator,
            runtime.commit,
            runtime.run_id,
        )
        if request.execute_immediately:
            runtime.orchestrator.run(created.trace_id or created.run_id)
            runtime.commit()
        return created
    if skill_id == "paper_qa":
        try:
            created = start_paper_qa(request, session)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if created.status not in {
            RunStatus.waiting_for_user.value,
            RunStatus.failed.value,
            RunStatus.cancelled.value,
        }:
            background_tasks.add_task(execute_agent_run, int(created.run_id))
        return created
    if skill_id == "pdf_analyze":
        created = queue_pdf_analyze(request, session)
        if created.status == RunStatus.pending.value:
            background_tasks.add_task(
                execute_pdf_analyze,
                int(created.run_id),
                request.model_dump(mode="json"),
            )
        return created
    if skill_id == "email_compose":
        return start_email_compose(
            request,
            session,
            runtime.orchestrator,
            runtime.commit,
            runtime.run_id,
        )
    if skill_id == "direction_explore":
        return start_direction_explore(request, session)
    if skill_id == "research_task":
        return start_research_task(request, session)
    if skill_id == "progress_report":
        created = queue_progress_report(request, session)
        if created.status == RunStatus.pending.value:
            background_tasks.add_task(
                execute_progress_report,
                int(created.run_id),
                request.model_dump(mode="json"),
            )
        return created
    if skill_id == "plan_coach":
        created = queue_plan_coach(request, session)
        if created.status == RunStatus.pending.value:
            background_tasks.add_task(
                execute_plan_coach,
                int(created.run_id),
                request.model_dump(mode="json"),
            )
        return created
    if skill_id == "profile_analyze":
        return start_profile_analyze(request, session)
    raise HTTPException(status_code=400, detail=f"unknown skill_id: {skill_id}")


@router.get("/next-skill")
def next_skill(matched: int = 0, read: int = 0) -> dict[str, str | None]:
    growth = {
        "matched_mentors": [{}] * matched,
        "read_papers": [{}] * read,
    }
    return {"suggested_next_skill": suggest_next_skill(growth)}


@router.get("/{run_id}/harness-result", response_model=RunCreated)
def get_harness_result(
    run_id: int,
    session: Session = Depends(get_db_session),
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> RunCreated:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        if run.workflow == WorkflowName.paper_qa.value:
            return paper_qa_result(run_id, session)
        if run.workflow == WorkflowName.mentor_search.value:
            return mentor_match_result(run_id, session, runtime)
        if run.workflow == WorkflowName.pdf_analyze.value:
            return pdf_analyze_result(run_id, session)
        if run.workflow == WorkflowName.email_compose.value:
            return email_compose_result(run_id, session)
        if run.workflow == WorkflowName.direction_explore.value:
            return skill_result(run_id, session, run.workflow, "direction_explore")
        if run.workflow == WorkflowName.research_task.value:
            return skill_result(run_id, session, run.workflow, "research_task")
        if run.workflow == WorkflowName.progress_report.value:
            return productivity_result(run_id, session, run.workflow, "progress_report")
        if run.workflow == WorkflowName.plan_coach.value:
            return productivity_result(run_id, session, run.workflow, "plan_coach")
        if run.workflow == WorkflowName.profile_analyze.value:
            return profile_analyze_result(run_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=404, detail=f"unsupported workflow: {run.workflow}")


@router.get("/{run_id}/events")
def get_productivity_events(
    run_id: int,
    after_sequence: int | None = None,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    run = session.get(AgentRun, run_id)
    if run is None or run.workflow not in {WorkflowName.plan_coach.value, WorkflowName.progress_report.value}:
        raise HTTPException(status_code=404, detail="productivity run not found")
    return [event.model_dump(mode="json") for event in list_run_events(session, run_id, after_sequence)]


@router.post("/{run_id}/cancel", response_model=RunCreated)
def cancel_productivity_run(
    run_id: int,
    session: Session = Depends(get_db_session),
) -> RunCreated:
    run = session.get(AgentRun, run_id)
    if run is None or run.workflow not in {WorkflowName.plan_coach.value, WorkflowName.progress_report.value}:
        raise HTTPException(status_code=404, detail="productivity run not found")
    cancel_run(session, run_id)
    session.commit()
    return productivity_result(run_id, session, run.workflow, "plan_coach" if run.workflow == WorkflowName.plan_coach.value else "progress_report")
