from __future__ import annotations

from threading import RLock
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.db.models import AgentRun, AgentRunEvent
from backend.db.repositories import AgentRunRepository
from backend.db.types import EventLevel, RunStatus, WorkflowName
from backend.mentor_workflow.errors import PersistenceConflictError
from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.schemas import (
    AgentMessage,
    EvidenceRecord,
    RetryRecord,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
    utcnow,
)


class StateStore(Protocol):
    def create_workflow(self, state: WorkflowState) -> WorkflowState: ...

    def get_workflow(self, trace_id: str) -> WorkflowState | None: ...

    def update_workflow(
        self, state: WorkflowState, *, expected_version: int
    ) -> WorkflowState: ...

    def append_event(self, message: AgentMessage) -> None: ...

    def append_evidence(
        self, trace_id: str, evidence: list[EvidenceRecord], *, expected_version: int
    ) -> WorkflowState: ...

    def append_retry(
        self, trace_id: str, retry: RetryRecord, *, expected_version: int
    ) -> WorkflowState: ...

    def set_stage(
        self, trace_id: str, stage: WorkflowStage, *, expected_version: int
    ) -> WorkflowState: ...

    def set_status(
        self, trace_id: str, status: WorkflowStatus, *, expected_version: int
    ) -> WorkflowState: ...

    def increment_version(
        self, trace_id: str, *, expected_version: int
    ) -> WorkflowState: ...

    def list_workflow_events(self, trace_id: str) -> list[AgentMessage]: ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self._states: dict[str, WorkflowState] = {}
        self._events: dict[str, list[AgentMessage]] = {}
        self._lock = RLock()

    def create_workflow(self, state: WorkflowState) -> WorkflowState:
        with self._lock:
            if state.trace_id in self._states:
                raise PersistenceConflictError(
                    f"Workflow {state.trace_id} already exists"
                )
            stored = state.model_copy(deep=True)
            self._states[state.trace_id] = stored
            self._events[state.trace_id] = []
            return stored.model_copy(deep=True)

    def get_workflow(self, trace_id: str) -> WorkflowState | None:
        with self._lock:
            state = self._states.get(trace_id)
            return state.model_copy(deep=True) if state is not None else None

    def update_workflow(
        self, state: WorkflowState, *, expected_version: int
    ) -> WorkflowState:
        with self._lock:
            current = self._required(state.trace_id)
            if current.state_version != expected_version:
                raise PersistenceConflictError(
                    f"Workflow {state.trace_id} version conflict: expected {expected_version}, found {current.state_version}"
                )
            updated = state.model_copy(
                deep=True,
                update={"state_version": expected_version + 1, "updated_at": utcnow()},
            )
            self._states[state.trace_id] = updated
            return updated.model_copy(deep=True)

    def append_event(self, message: AgentMessage) -> None:
        with self._lock:
            self._required(message.trace_id)
            self._events[message.trace_id].append(message.model_copy(deep=True))

    def append_evidence(
        self, trace_id: str, evidence: list[EvidenceRecord], *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        ledger = EvidenceLedger(state.evidence_ledger)
        ledger.extend(evidence)
        state.evidence_ledger = ledger.list()
        return self.update_workflow(state, expected_version=expected_version)

    def append_retry(
        self, trace_id: str, retry: RetryRecord, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        state.retries.append(retry)
        return self.update_workflow(state, expected_version=expected_version)

    def set_stage(
        self, trace_id: str, stage: WorkflowStage, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        state.current_stage = stage
        return self.update_workflow(state, expected_version=expected_version)

    def set_status(
        self, trace_id: str, status: WorkflowStatus, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        state.status = status
        return self.update_workflow(state, expected_version=expected_version)

    def increment_version(
        self, trace_id: str, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        return self.update_workflow(state, expected_version=expected_version)

    def list_workflow_events(self, trace_id: str) -> list[AgentMessage]:
        with self._lock:
            self._required(trace_id)
            return [event.model_copy(deep=True) for event in self._events[trace_id]]

    def _checked_state(self, trace_id: str, expected_version: int) -> WorkflowState:
        state = self.get_workflow(trace_id)
        if state is None:
            raise KeyError(trace_id)
        if state.state_version != expected_version:
            raise PersistenceConflictError(
                f"Workflow {trace_id} version conflict: expected {expected_version}, found {state.state_version}"
            )
        return state

    def _required(self, trace_id: str) -> WorkflowState:
        state = self._states.get(trace_id)
        if state is None:
            raise KeyError(trace_id)
        return state


class SqlAlchemyStateStore:
    """Stores mentor workflow state in the existing AgentRun/AgentRunEvent tables."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_workflow(self, state: WorkflowState) -> WorkflowState:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:trace_id, 0))"),
            {"trace_id": state.trace_id},
        )
        if self._run_for_trace(state.trace_id) is not None:
            raise PersistenceConflictError(f"Workflow {state.trace_id} already exists")
        run = AgentRunRepository(self.session).create(
            WorkflowName.mentor_search.value,
            status=_run_status(state.status),
            deepagent_run_id=state.trace_id,
            started_at=utcnow(),
            input_json=state.request.model_dump(mode="json"),
            output_json=state.model_dump(mode="json"),
            metadata_json={
                "mentor_workflow": True,
                "trace_id": state.trace_id,
                "state_version": state.state_version,
                "current_stage": state.current_stage.value,
            },
        )
        self.session.flush()
        return WorkflowState.model_validate(run.output_json)

    def get_workflow(self, trace_id: str) -> WorkflowState | None:
        run = self._run_for_trace(trace_id)
        if run is None or run.output_json is None:
            return None
        return WorkflowState.model_validate(run.output_json)

    def update_workflow(
        self, state: WorkflowState, *, expected_version: int
    ) -> WorkflowState:
        run = self._required_run(state.trace_id, for_update=True)
        current = WorkflowState.model_validate(run.output_json)
        if current.state_version != expected_version:
            raise PersistenceConflictError(
                f"Workflow {state.trace_id} version conflict: expected {expected_version}, found {current.state_version}"
            )
        updated = state.model_copy(
            deep=True,
            update={"state_version": expected_version + 1, "updated_at": utcnow()},
        )
        run.output_json = updated.model_dump(mode="json")
        run.input_json = updated.request.model_dump(mode="json")
        run.status = _run_status(updated.status)
        run.error_message = (
            updated.errors[-1].message
            if updated.errors and updated.status == WorkflowStatus.failed
            else None
        )
        if updated.status in {WorkflowStatus.completed, WorkflowStatus.failed}:
            run.finished_at = utcnow()
        metadata = dict(run.metadata_json or {})
        metadata.update(
            {
                "state_version": updated.state_version,
                "current_stage": updated.current_stage.value,
                "workflow_status": updated.status.value,
            }
        )
        run.metadata_json = metadata
        self.session.flush()
        return updated

    def append_event(self, message: AgentMessage) -> None:
        run = self._required_run(message.trace_id)
        AgentRunRepository(self.session).append_event(
            run.id,
            message.event_type.value,
            level=EventLevel.error.value if message.error else EventLevel.info.value,
            payload_json=message.model_dump(mode="json"),
        )

    def append_evidence(
        self, trace_id: str, evidence: list[EvidenceRecord], *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        ledger = EvidenceLedger(state.evidence_ledger)
        ledger.extend(evidence)
        state.evidence_ledger = ledger.list()
        return self.update_workflow(state, expected_version=expected_version)

    def append_retry(
        self, trace_id: str, retry: RetryRecord, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        state.retries.append(retry)
        return self.update_workflow(state, expected_version=expected_version)

    def set_stage(
        self, trace_id: str, stage: WorkflowStage, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        state.current_stage = stage
        return self.update_workflow(state, expected_version=expected_version)

    def set_status(
        self, trace_id: str, status: WorkflowStatus, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        state.status = status
        return self.update_workflow(state, expected_version=expected_version)

    def increment_version(
        self, trace_id: str, *, expected_version: int
    ) -> WorkflowState:
        state = self._checked_state(trace_id, expected_version)
        return self.update_workflow(state, expected_version=expected_version)

    def list_workflow_events(self, trace_id: str) -> list[AgentMessage]:
        run = self._required_run(trace_id)
        events = self.session.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run.id)
            .order_by(AgentRunEvent.sequence)
        ).all()
        messages: list[AgentMessage] = []
        for event in events:
            try:
                messages.append(AgentMessage.model_validate(event.payload_json))
            except ValueError:
                continue
        return messages

    def run_id(self, trace_id: str) -> int | None:
        run = self._run_for_trace(trace_id)
        return run.id if run is not None else None

    def _checked_state(self, trace_id: str, expected_version: int) -> WorkflowState:
        state = self.get_workflow(trace_id)
        if state is None:
            raise KeyError(trace_id)
        if state.state_version != expected_version:
            raise PersistenceConflictError(
                f"Workflow {trace_id} version conflict: expected {expected_version}, found {state.state_version}"
            )
        return state

    def _run_for_trace(
        self, trace_id: str, *, for_update: bool = False
    ) -> AgentRun | None:
        statement = select(AgentRun).where(
            AgentRun.workflow == WorkflowName.mentor_search.value,
            AgentRun.deepagent_run_id == trace_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(
            statement.execution_options(populate_existing=for_update)
        )

    def _required_run(self, trace_id: str, *, for_update: bool = False) -> AgentRun:
        run = self._run_for_trace(trace_id, for_update=for_update)
        if run is None:
            raise KeyError(trace_id)
        return run


def _run_status(status: WorkflowStatus) -> str:
    return {
        WorkflowStatus.pending: RunStatus.pending.value,
        WorkflowStatus.running: RunStatus.running.value,
        WorkflowStatus.clarification_required: RunStatus.waiting_for_user.value,
        WorkflowStatus.result_ready: RunStatus.running.value,
        WorkflowStatus.completed: RunStatus.succeeded.value,
        WorkflowStatus.failed: RunStatus.failed.value,
    }[status]
