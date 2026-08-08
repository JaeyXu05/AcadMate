from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from backend.mentor_workflow.schemas import WorkflowErrorKind, WorkflowStage

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class MentorWorkflowError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: WorkflowErrorKind,
        stage: WorkflowStage,
        recoverable: bool,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.stage = stage
        self.recoverable = recoverable


class TemporaryToolError(MentorWorkflowError):
    def __init__(
        self, message: str, *, stage: WorkflowStage = WorkflowStage.mentor_research
    ) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.temporary_tool,
            stage=stage,
            recoverable=True,
        )


class ToolTimeoutError(MentorWorkflowError):
    def __init__(
        self, message: str, *, stage: WorkflowStage = WorkflowStage.mentor_research
    ) -> None:
        super().__init__(
            message, kind=WorkflowErrorKind.tool_timeout, stage=stage, recoverable=True
        )


class AgentTimeoutError(MentorWorkflowError):
    def __init__(self, message: str, *, stage: WorkflowStage) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.agent_timeout,
            stage=stage,
            recoverable=False,
        )


class ModelOutputFormatError(MentorWorkflowError):
    def __init__(self, message: str, *, stage: WorkflowStage) -> None:
        super().__init__(
            message, kind=WorkflowErrorKind.model_output, stage=stage, recoverable=True
        )


class SchemaValidationWorkflowError(MentorWorkflowError):
    def __init__(self, message: str, *, stage: WorkflowStage) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.schema_validation,
            stage=stage,
            recoverable=True,
        )


class EvidenceInsufficientError(MentorWorkflowError):
    def __init__(
        self, message: str, *, stage: WorkflowStage = WorkflowStage.evidence_review
    ) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.evidence_insufficient,
            stage=stage,
            recoverable=False,
        )


class UserInputInsufficientError(MentorWorkflowError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.user_input_insufficient,
            stage=WorkflowStage.input_understanding,
            recoverable=True,
        )


class PermanentConfigurationError(MentorWorkflowError):
    def __init__(self, message: str, *, stage: WorkflowStage) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.permanent_configuration,
            stage=stage,
            recoverable=False,
        )


class BusinessWorkflowError(MentorWorkflowError):
    def __init__(self, message: str, *, stage: WorkflowStage) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.business,
            stage=stage,
            recoverable=False,
        )


class PersistenceConflictError(MentorWorkflowError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            kind=WorkflowErrorKind.persistence,
            stage=WorkflowStage.failed,
            recoverable=True,
        )


def parse_structured_output(
    raw: str, schema_type: type[SchemaT], *, stage: WorkflowStage
) -> SchemaT:
    """Parse provider-neutral JSON into a validated workflow schema."""
    try:
        payload = json.loads(raw)
        return schema_type.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ModelOutputFormatError(
            f"Structured model output is invalid: {exc}", stage=stage
        ) from exc
