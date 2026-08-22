from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from backend.db.models import AgentRun, AgentRunEvent, Message, Thread
from backend.db.types import MessageRole, WorkflowName


def test_thread_message_run_event_relationships(session):
    thread = Thread(title="research task")
    session.add(thread)
    session.flush()

    run = AgentRun(thread_id=thread.id, workflow=WorkflowName.analysis_report.value)
    session.add(run)
    session.flush()

    message = Message(
        thread_id=thread.id,
        run_id=run.id,
        role=MessageRole.user.value,
        content_text="analyze this paper",
        created_at=datetime.now().astimezone(),
    )
    event = AgentRunEvent(
        run_id=run.id,
        sequence=1,
        event_type="run_started",
        level="info",
        created_at=datetime.now().astimezone(),
    )
    session.add_all([message, event])
    session.commit()

    assert thread.messages[0].content_text == "analyze this paper"
    assert run.events[0].event_type == "run_started"
    assert run.messages[0].id == message.id


def test_agent_run_event_sequence_unique(session):
    thread = Thread(title="research task")
    session.add(thread)
    session.flush()
    run = AgentRun(thread_id=thread.id, workflow=WorkflowName.analysis_report.value)
    session.add(run)
    session.flush()

    now = datetime.now().astimezone()
    session.add_all([
        AgentRunEvent(run_id=run.id, sequence=1, event_type="a", level="info", created_at=now),
        AgentRunEvent(run_id=run.id, sequence=1, event_type="b", level="info", created_at=now),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
