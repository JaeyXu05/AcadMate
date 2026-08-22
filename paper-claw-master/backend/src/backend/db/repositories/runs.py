from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.db.models import AgentRun, AgentRunEvent


class AgentRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, workflow: str, **values: object) -> AgentRun:
        run = AgentRun(workflow=workflow, **values)
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: int) -> AgentRun | None:
        return self.session.get(AgentRun, run_id)

    def update_status(self, run_id: int, status: str, **values: object) -> AgentRun:
        run = self.session.get_one(AgentRun, run_id)
        run.status = status
        for key, value in values.items():
            setattr(run, key, value)
        self.session.flush()
        return run

    def append_event(self, run_id: int, event_type: str, level: str = "info", payload_json: dict | None = None) -> AgentRunEvent:
        self.session.execute(text("SELECT pg_advisory_xact_lock(:run_id)"), {"run_id": run_id})
        next_sequence = self.session.scalar(
            select(func.coalesce(func.max(AgentRunEvent.sequence), 0) + 1).where(AgentRunEvent.run_id == run_id)
        )
        event = AgentRunEvent(
            run_id=run_id,
            sequence=int(next_sequence),
            event_type=event_type,
            level=level,
            payload_json=payload_json or {},
            created_at=datetime.now().astimezone(),
        )
        self.session.add(event)
        self.session.flush()
        return event
