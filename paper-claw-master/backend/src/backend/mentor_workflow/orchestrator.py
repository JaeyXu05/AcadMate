from __future__ import annotations

import logging
from collections.abc import Callable
from time import perf_counter
from typing import Protocol, TypeVar

from pydantic import ValidationError

from backend.mentor_workflow.agentic_research import ResearchAuditProvider
from backend.mentor_workflow.agents.composer import ResultComposerAgent
from backend.mentor_workflow.agents.domain_research import (
    DynamicDomainExpertAgent,
    MentorResearchAgent,
)
from backend.mentor_workflow.agents.evaluation import (
    EvidenceReviewAgent,
    MatchingAgent,
    RetryController,
)
from backend.mentor_workflow.agents.intake import InputUnderstandingAgent, PlanningAgent
from backend.mentor_workflow.errors import (
    AgentTimeoutError,
    BusinessWorkflowError,
    EvidenceInsufficientError,
    MentorWorkflowError,
    SchemaValidationWorkflowError,
    UserInputInsufficientError,
)
from backend.mentor_workflow.event_bus import EventBus, InMemoryEventBus
from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.research_tools import MentorResearchTool
from backend.mentor_workflow.schemas import (
    AgentMessage,
    CandidateMentor,
    ClarificationRequest,
    DomainJudgement,
    IntentPacket,
    MatchResult,
    MentorWorkflowRequest,
    MentorWorkflowSupplement,
    RetryRecord,
    RetryTarget,
    ReviewStatus,
    WorkflowErrorKind,
    WorkflowErrorRecord,
    WorkflowEventType,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
    new_workflow_state,
)
from backend.mentor_workflow.state_store import StateStore

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


class DomainExpertRunner(Protocol):
    name: str

    def run(self, intent: IntentPacket) -> list[DomainJudgement]: ...


class MatchingRunner(Protocol):
    name: str

    def run(
        self,
        intent: IntentPacket,
        candidates: list[CandidateMentor],
        ledger: EvidenceLedger,
    ) -> list[MatchResult]: ...


class MentorWorkflowOrchestrator:
    def __init__(
        self,
        store: StateStore,
        research_tool: MentorResearchTool,
        *,
        event_bus: EventBus | None = None,
        agent_timeout_seconds: float = 300,
        tool_timeout_seconds: float = 240,
        max_total_retries: int = 5,
        domain_agent: DomainExpertRunner | None = None,
        matching_agent: MatchingRunner | None = None,
        research_audit: ResearchAuditProvider | None = None,
    ) -> None:
        self.store = store
        self.event_bus = event_bus or InMemoryEventBus()
        self.agent_timeout_seconds = agent_timeout_seconds
        self.input_agent = InputUnderstandingAgent()
        self.planning_agent = PlanningAgent(
            agent_timeout_seconds=agent_timeout_seconds,
            tool_timeout_seconds=tool_timeout_seconds,
            max_total_retries=max_total_retries,
        )
        self.domain_agent = domain_agent or DynamicDomainExpertAgent()
        self.research_agent = MentorResearchAgent(
            research_tool, tool_timeout_seconds=tool_timeout_seconds
        )
        self.matching_agent = matching_agent or MatchingAgent()
        self.research_audit = research_audit
        self.review_agent = EvidenceReviewAgent()
        self.retry_controller = RetryController()
        self.composer_agent = ResultComposerAgent()

    def create(
        self, request: MentorWorkflowRequest, *, trace_id: str | None = None
    ) -> WorkflowState:
        state = self.store.create_workflow(
            new_workflow_state(request, trace_id=trace_id)
        )
        self._emit(
            state,
            WorkflowEventType.workflow_created,
            sender="workflow_orchestrator",
            receiver="input_understanding_agent",
            payload={"status": state.status.value},
        )
        if request.execute_immediately:
            return self.run(state.trace_id)
        return state

    def run(self, trace_id: str) -> WorkflowState:
        state = self._required_state(trace_id)
        try:
            state.status = WorkflowStatus.running
            state.current_stage = WorkflowStage.input_understanding
            state = self._commit(state)
            self._emit(
                state,
                WorkflowEventType.input_received,
                sender="workflow_orchestrator",
                receiver=self.input_agent.name,
                payload={
                    "has_documents": bool(state.request.parsed_documents),
                    "has_profile": bool(
                        state.request.user_profile.model_dump(exclude_none=True)
                    ),
                },
            )
            intent, clarification = self._invoke(
                state.trace_id,
                WorkflowStage.input_understanding,
                self.input_agent.name,
                lambda: self.input_agent.run(state.request, state),
            )
            state.intent = intent
            state.clarification_request = clarification
            state = self._commit(state)
            if clarification is not None:
                return self._clarification(state, clarification)
            self._emit(
                state,
                WorkflowEventType.intent_ready,
                sender=self.input_agent.name,
                receiver=self.planning_agent.name,
                payload={
                    "goal": intent.goal.value,
                    "topic_count": len(intent.research_topics),
                },
            )

            state.current_stage = WorkflowStage.planning
            state = self._commit(state)
            task_plan = self._invoke(
                state.trace_id,
                WorkflowStage.planning,
                self.planning_agent.name,
                lambda: self.planning_agent.run(intent, state),
            )
            state.task_plan = task_plan
            state = self._commit(state)
            self._emit(
                state,
                WorkflowEventType.plan_ready,
                sender=self.planning_agent.name,
                receiver="workflow_orchestrator",
                payload={
                    "steps": [step.step_id for step in task_plan.steps],
                    "skipped_steps": task_plan.skipped_steps,
                },
            )

            enabled = {step.agent_name for step in task_plan.steps if step.enabled}
            if "evidence_review" in enabled:
                state = self._run_review_loop(state, enabled)
                if state.status in {
                    WorkflowStatus.failed,
                    WorkflowStatus.clarification_required,
                }:
                    return state
            if "result_composer" in enabled:
                state = self._compose(state)
            state.current_stage = WorkflowStage.completed
            state.status = WorkflowStatus.completed
            state = self._commit(state)
            self._emit(
                state,
                WorkflowEventType.workflow_completed,
                sender="workflow_orchestrator",
                receiver="api",
                payload={"status": state.status.value},
                evidence_refs=state.final_result.evidence_refs
                if state.final_result
                else [],
            )
            return state
        except Exception as exc:
            return self._fail(state, exc)

    def supplement(
        self, trace_id: str, supplement: MentorWorkflowSupplement
    ) -> WorkflowState:
        state = self._required_state(trace_id)
        request_data = state.request.model_dump()
        updates = supplement.model_dump(exclude_unset=True)
        for key, value in updates.items():
            if value is not None:
                request_data[key] = value
        request_data["execute_immediately"] = True
        state.request = MentorWorkflowRequest.model_validate(request_data)
        preserve_approved = (
            state.request.goal is not None
            and state.request.goal.value
            in {
                "generate_contact_email",
                "follow_up_question",
            }
        )
        state.status = WorkflowStatus.pending
        state.current_stage = WorkflowStage.input_understanding
        state.clarification_request = None
        state.intent = None
        state.task_plan = None
        if not preserve_approved:
            state.domain_judgements = []
            state.candidates = []
            state.evidence_ledger = []
            state.match_results = []
            state.research_audit = None
            state.review_decision = None
            state.final_result = None
        state = self._commit(state)
        return self.run(trace_id)

    def _run_review_loop(
        self, state: WorkflowState, enabled: set[str]
    ) -> WorkflowState:
        target: RetryTarget | None = None
        while True:
            if target is None or target == RetryTarget.domain_expert:
                if "domain_expert" in enabled:
                    state = self._domain(state)
            if target in {None, RetryTarget.domain_expert, RetryTarget.mentor_research}:
                if "mentor_research" in enabled:
                    state = self._research(state)
            if target in {
                None,
                RetryTarget.domain_expert,
                RetryTarget.mentor_research,
                RetryTarget.matching,
            }:
                if "matching" in enabled:
                    state = self._matching(state)
            state = self._review(state)
            if (
                state.review_decision is not None
                and state.review_decision.status == ReviewStatus.pass_
            ):
                return state
            if state.review_decision is None or state.task_plan is None:
                return self._fail(
                    state, ValueError("Review did not produce a decision")
                )
            instruction = self.retry_controller.decide(
                state.review_decision, state, state.task_plan.retry_policy
            )
            if instruction.exhausted or instruction.target is None:
                return self._fail(
                    state,
                    _retry_exhausted_error(
                        instruction.reason,
                        state.review_decision.status,
                        state.current_stage,
                    ),
                )
            if instruction.target == RetryTarget.input_understanding:
                clarification = ClarificationRequest(
                    missing_fields=state.intent.missing_fields
                    if state.intent
                    else ["user_input"],
                    questions=state.intent.clarification_questions
                    if state.intent
                    else ["请补充任务所需信息。"],
                    reason=instruction.reason,
                )
                return self._clarification(state, clarification)
            previous_version = state.state_version
            retry = RetryRecord(
                retry_count=len(state.retries) + 1,
                retry_target=instruction.target,
                retry_reason=instruction.reason,
                previous_state_version=previous_version,
                new_state_version=previous_version + 1,
                triggering_review_id=state.review_decision.review_id,
            )
            state = self.store.append_retry(
                state.trace_id, retry, expected_version=previous_version
            )
            self._emit(
                state,
                WorkflowEventType.task_retry,
                sender="retry_controller",
                receiver=instruction.target.value,
                payload={
                    "retry_count": retry.retry_count,
                    "retry_target": retry.retry_target.value,
                    "retry_reason": retry.retry_reason,
                    "previous_state_version": retry.previous_state_version,
                    "new_state_version": retry.new_state_version,
                    "triggering_review_id": retry.triggering_review_id,
                },
            )
            target = instruction.target

    def _domain(self, state: WorkflowState) -> WorkflowState:
        state.current_stage = WorkflowStage.domain_expert
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.domain_analysis_started,
            sender="workflow_orchestrator",
            receiver=self.domain_agent.name,
        )
        state.domain_judgements = self._invoke(
            state.trace_id,
            WorkflowStage.domain_expert,
            self.domain_agent.name,
            lambda: self.domain_agent.run(_required_intent(state)),
        )
        self._sync_research_audit(state)
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.domain_analysis_ready,
            sender=self.domain_agent.name,
            receiver=self.research_agent.name,
            payload={"expert_count": len(state.domain_judgements)},
        )
        return state

    def _research(self, state: WorkflowState) -> WorkflowState:
        state.current_stage = WorkflowStage.mentor_research
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.research_started,
            sender="workflow_orchestrator",
            receiver=self.research_agent.name,
        )
        result = self._invoke(
            state.trace_id,
            WorkflowStage.mentor_research,
            self.research_agent.name,
            lambda: self.research_agent.run(
                _required_intent(state), state.domain_judgements, state.evidence_ledger
            ),
        )
        ledger = EvidenceLedger(state.evidence_ledger)
        ledger.extend(result.evidence)
        state.evidence_ledger = ledger.list()
        state.candidates = result.candidates
        self._sync_research_audit(state)
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.research_done,
            sender=self.research_agent.name,
            receiver=self.matching_agent.name,
            payload={
                "candidate_count": len(state.candidates),
                "new_evidence_count": len(result.evidence),
                "used_fallback": result.used_fallback,
                "warnings": result.warnings[:5],
            },
            evidence_refs=[record.evidence_id for record in result.evidence],
        )
        return state

    def _matching(self, state: WorkflowState) -> WorkflowState:
        state.current_stage = WorkflowStage.matching
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.matching_started,
            sender="workflow_orchestrator",
            receiver=self.matching_agent.name,
        )
        state.match_results = self._invoke(
            state.trace_id,
            WorkflowStage.matching,
            self.matching_agent.name,
            lambda: self.matching_agent.run(
                _required_intent(state),
                state.candidates,
                EvidenceLedger(state.evidence_ledger),
            ),
        )
        self._sync_research_audit(state)
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.matching_done,
            sender=self.matching_agent.name,
            receiver=self.review_agent.name,
            payload={"match_count": len(state.match_results)},
            evidence_refs=[
                reference
                for match in state.match_results
                for reference in match.evidence_refs
            ],
        )
        return state

    def _review(self, state: WorkflowState) -> WorkflowState:
        state.current_stage = WorkflowStage.evidence_review
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.review_started,
            sender="workflow_orchestrator",
            receiver=self.review_agent.name,
        )
        review_decision = self._invoke(
            state.trace_id,
            WorkflowStage.evidence_review,
            self.review_agent.name,
            lambda: self.review_agent.run(state),
        )
        state.review_decision = review_decision
        state = self._commit(state)
        passed = review_decision.status == ReviewStatus.pass_
        self._emit(
            state,
            WorkflowEventType.review_passed
            if passed
            else WorkflowEventType.review_failed,
            sender=self.review_agent.name,
            receiver="result_composer_agent" if passed else "retry_controller",
            payload={
                "review_id": review_decision.review_id,
                "status": review_decision.status.value,
                "failed_checks": review_decision.failed_checks,
                "revision_target": review_decision.revision_target.value
                if review_decision.revision_target
                else None,
            },
            evidence_refs=review_decision.missing_evidence_refs,
        )
        return state

    def _compose(self, state: WorkflowState) -> WorkflowState:
        state.current_stage = WorkflowStage.result_composer
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.composing_result,
            sender="workflow_orchestrator",
            receiver=self.composer_agent.name,
        )
        final_result = self._invoke(
            state.trace_id,
            WorkflowStage.result_composer,
            self.composer_agent.name,
            lambda: self.composer_agent.run(state),
        )
        state.final_result = final_result
        state.status = WorkflowStatus.result_ready
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.result_ready,
            sender=self.composer_agent.name,
            receiver="api",
            payload={"mentor_count": len(final_result.mentors)},
            evidence_refs=final_result.evidence_refs,
        )
        return state

    def _clarification(
        self, state: WorkflowState, clarification: ClarificationRequest
    ) -> WorkflowState:
        state.clarification_request = clarification
        state.status = WorkflowStatus.clarification_required
        state.current_stage = WorkflowStage.input_understanding
        state = self._commit(state)
        self._emit(
            state,
            WorkflowEventType.clarification_required,
            sender=self.input_agent.name,
            receiver="user",
            payload={
                "missing_fields": clarification.missing_fields,
                "questions": clarification.questions,
            },
        )
        return state

    def _fail(self, state: WorkflowState, exc: Exception) -> WorkflowState:
        latest = self.store.get_workflow(state.trace_id) or state
        if isinstance(exc, MentorWorkflowError):
            kind = exc.kind
            stage = exc.stage
            recoverable = exc.recoverable
        elif isinstance(exc, ValidationError):
            schema_error = SchemaValidationWorkflowError(
                str(exc), stage=latest.current_stage
            )
            kind = schema_error.kind
            stage = schema_error.stage
            recoverable = schema_error.recoverable
        else:
            kind = WorkflowErrorKind.business
            stage = latest.current_stage
            recoverable = False
        latest.errors.append(
            WorkflowErrorRecord(
                kind=kind,
                stage=stage,
                message=str(exc) or type(exc).__name__,
                recoverable=recoverable,
            )
        )
        latest.status = WorkflowStatus.failed
        latest.current_stage = WorkflowStage.failed
        try:
            latest = self._commit(latest)
        except Exception:
            logger.exception(
                "mentor_workflow_persistence_failure",
                extra={"trace_id": latest.trace_id},
            )
            return latest
        self._emit(
            latest,
            WorkflowEventType.workflow_failed,
            sender="workflow_orchestrator",
            receiver="api",
            payload={"error_type": kind.value, "recoverable": recoverable},
            error=str(exc) or type(exc).__name__,
        )
        return latest

    def _invoke(
        self,
        trace_id: str,
        stage: WorkflowStage,
        agent_name: str,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        started = perf_counter()
        try:
            result = operation()
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            logger.exception(
                "mentor_workflow_agent_failed",
                extra={
                    "trace_id": trace_id,
                    "agent_name": agent_name,
                    "stage": stage.value,
                    "duration_ms": round(duration_ms, 2),
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            raise
        duration_ms = (perf_counter() - started) * 1000
        if duration_ms > self.agent_timeout_seconds * 1000:
            logger.warning(
                "mentor_workflow_agent_timeout",
                extra={
                    "trace_id": trace_id,
                    "agent_name": agent_name,
                    "stage": stage.value,
                    "duration_ms": round(duration_ms, 2),
                    "status": "timeout",
                    "error_type": AgentTimeoutError.__name__,
                },
            )
            raise AgentTimeoutError(
                f"{agent_name} exceeded the {self.agent_timeout_seconds:.3f}s agent timeout",
                stage=stage,
            )
        logger.info(
            "mentor_workflow_agent_completed",
            extra={
                "trace_id": trace_id,
                "agent_name": agent_name,
                "stage": stage.value,
                "duration_ms": round(duration_ms, 2),
                "status": "completed",
            },
        )
        return result

    def _commit(self, state: WorkflowState) -> WorkflowState:
        return self.store.update_workflow(state, expected_version=state.state_version)

    def _sync_research_audit(self, state: WorkflowState) -> None:
        if self.research_audit is not None:
            state.research_audit = self.research_audit.snapshot()

    def _emit(
        self,
        state: WorkflowState,
        event_type: WorkflowEventType,
        *,
        sender: str,
        receiver: str,
        payload: dict[str, object] | None = None,
        evidence_refs: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        message = AgentMessage(
            trace_id=state.trace_id,
            sender=sender,
            receiver=receiver,
            event_type=event_type,
            payload=payload or {},
            evidence_refs=list(dict.fromkeys(evidence_refs or [])),
            state_version=state.state_version,
            error=error,
        )
        self.event_bus.publish(message)
        self.store.append_event(message)
        logger.info(
            "mentor_workflow_event",
            extra={
                "trace_id": state.trace_id,
                "agent_name": sender,
                "stage": state.current_stage.value,
                "event_type": event_type.value,
                "state_version": state.state_version,
                "retry_count": len(state.retries),
                "status": state.status.value,
                "error_type": (payload or {}).get("error_type")
                if error is not None
                else None,
            },
        )

    def _required_state(self, trace_id: str) -> WorkflowState:
        state = self.store.get_workflow(trace_id)
        if state is None:
            raise KeyError(trace_id)
        return state


def _required_intent(state: WorkflowState) -> IntentPacket:
    if state.intent is None:
        raise ValueError("Workflow IntentPacket is missing")
    return state.intent


def _retry_exhausted_error(
    reason: str, review_status: ReviewStatus, stage: WorkflowStage
) -> MentorWorkflowError:
    if review_status == ReviewStatus.research_again:
        return EvidenceInsufficientError(reason, stage=stage)
    if review_status == ReviewStatus.need_more_input:
        return UserInputInsufficientError(reason)
    return BusinessWorkflowError(reason, stage=stage)
