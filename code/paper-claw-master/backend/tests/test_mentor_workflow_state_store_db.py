from __future__ import annotations

import pytest
from backend.db.models import AgentRun
from backend.db.types import RunStatus, WorkflowName
from backend.mentor_workflow.errors import PersistenceConflictError
from backend.mentor_workflow.schemas import (
    AgentMessage,
    EvidenceRecord,
    MentorWorkflowRequest,
    WorkflowEventType,
    WorkflowStage,
    WorkflowStatus,
    new_workflow_state,
)
from backend.mentor_workflow.state_store import SqlAlchemyStateStore
from sqlalchemy.orm import Session


def test_sqlalchemy_state_store_round_trips_state_events_and_evidence(session):
    store = SqlAlchemyStateStore(session)
    state = new_workflow_state(
        MentorWorkflowRequest(message="find AI mentors", research_topics=["AI"]),
        trace_id="trace-db-round-trip",
    )

    created = store.create_workflow(state)
    store.append_event(
        AgentMessage(
            trace_id=created.trace_id,
            sender="test",
            receiver="workflow",
            event_type=WorkflowEventType.workflow_created,
            state_version=created.state_version,
        )
    )
    staged = store.set_stage(
        created.trace_id,
        WorkflowStage.mentor_research,
        expected_version=created.state_version,
    )
    with_evidence = store.append_evidence(
        created.trace_id,
        [
            EvidenceRecord(
                evidence_id="ev-db-1",
                candidate_id="mentor-db-1",
                source_type="fixture",
                source_uri="fixture://mentor-db-1",
                title="Verified source",
                extracted_fact="Mentor DB authored the verified source.",
                locator="fixture:1",
                confidence=0.9,
            )
        ],
        expected_version=staged.state_version,
    )
    completed = store.set_status(
        created.trace_id,
        WorkflowStatus.completed,
        expected_version=with_evidence.state_version,
    )
    session.flush()
    session.expire_all()

    reloaded = store.get_workflow(created.trace_id)
    run = session.get_one(AgentRun, store.run_id(created.trace_id))

    assert reloaded is not None
    assert reloaded.state_version == 4
    assert reloaded.current_stage == WorkflowStage.mentor_research
    assert reloaded.status == WorkflowStatus.completed
    assert [item.evidence_id for item in reloaded.evidence_ledger] == ["ev-db-1"]
    assert [
        event.event_type for event in store.list_workflow_events(created.trace_id)
    ] == [WorkflowEventType.workflow_created]
    assert run.workflow == WorkflowName.mentor_search.value
    assert run.status == RunStatus.succeeded.value
    assert run.finished_at is not None

    with pytest.raises(PersistenceConflictError):
        store.increment_version(
            completed.trace_id,
            expected_version=completed.state_version - 1,
        )


def test_sqlalchemy_state_store_rejects_a_stale_cross_session_update(session, engine):
    trace_id = "trace-db-concurrency"
    SqlAlchemyStateStore(session).create_workflow(
        new_workflow_state(
            MentorWorkflowRequest(
                message="find systems mentors", research_topics=["systems"]
            ),
            trace_id=trace_id,
        )
    )
    session.commit()

    with (
        Session(engine, expire_on_commit=False) as first_session,
        Session(engine, expire_on_commit=False) as second_session,
    ):
        first_store = SqlAlchemyStateStore(first_session)
        second_store = SqlAlchemyStateStore(second_session)
        first_state = first_store.get_workflow(trace_id)
        stale_state = second_store.get_workflow(trace_id)
        assert first_state is not None
        assert stale_state is not None

        first_state.status = WorkflowStatus.running
        first_store.update_workflow(
            first_state,
            expected_version=first_state.state_version,
        )
        first_session.commit()

        stale_state.status = WorkflowStatus.failed
        with pytest.raises(PersistenceConflictError):
            second_store.update_workflow(
                stale_state,
                expected_version=stale_state.state_version,
            )
