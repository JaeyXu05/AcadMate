from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.agents.runner import cancel_run, encode_agent_message_stream, execute_agent_run, list_run_events, submit_agent_message
from backend.api.deps import get_db_session
from backend.schemas import AgentMessageRequest, AgentMessageResponse, RunEventRead, RunRead

router = APIRouter(tags=["agent"])


@router.post("/agent/messages", response_model=AgentMessageResponse)
def post_agent_message(
    request: AgentMessageRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db_session),
) -> AgentMessageResponse:
    response = submit_agent_message(session, request)
    background_tasks.add_task(execute_agent_run, response.run_id)
    return response


@router.post("/agent/messages/stream")
def post_agent_message_stream(request: AgentMessageRequest, session: Session = Depends(get_db_session)) -> StreamingResponse:
    return StreamingResponse(
        encode_agent_message_stream(session, request),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/agent/runs/{run_id}/events", response_model=list[RunEventRead])
def get_run_events(
    run_id: int,
    after_sequence: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[RunEventRead]:
    try:
        return list_run_events(session, run_id, after_sequence)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agent/runs/{run_id}/cancel", response_model=RunRead)
def post_cancel_run(run_id: int, session: Session = Depends(get_db_session)) -> RunRead:
    try:
        return cancel_run(session, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
