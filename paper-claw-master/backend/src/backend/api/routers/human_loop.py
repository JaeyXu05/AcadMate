from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.agents.runner import execute_agent_run_resume, resume_agent_run
from backend.api.deps import get_db_session
from backend.db.repositories import AgentRunRepository
from backend.schemas import ApprovalRequest, RunRead

router = APIRouter(tags=["human-loop"])



@router.post("/agent/runs/{run_id}/approval", response_model=RunRead)
def approve_run(
    run_id: int,
    request: ApprovalRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db_session),
) -> RunRead:
    try:
        run = resume_agent_run(session, run_id, request)
        if request.decision != "cancel":
            background_tasks.add_task(execute_agent_run_resume, run_id, request)
        return run
    except ValueError as exc:
        detail = str(exc)
        if detail == "Run not found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
