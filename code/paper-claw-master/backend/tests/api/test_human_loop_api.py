from __future__ import annotations

from backend.db.repositories import AgentRunRepository
from backend.db.types import RunStatus, WorkflowName


def test_approval_cancel_updates_run(client, session):
    run = AgentRunRepository(session).create(WorkflowName.analysis_report.value, status=RunStatus.running.value)
    session.commit()

    response = client.post(f"/api/agent/runs/{run.id}/approval", json={"decision": "cancel", "comment": "stop"})

    assert response.status_code == 200
    assert response.json()["status"] == RunStatus.cancelled.value
    assert run.events[-1].event_type == "agent_run_cancelled"
