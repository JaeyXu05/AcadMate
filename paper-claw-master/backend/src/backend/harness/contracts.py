"""Harness transport contracts shared by deterministic and model-backed skills."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SharedContext(BaseModel):
    user_id: str | None = None
    query: str = ""
    profile: dict[str, Any] = Field(default_factory=dict)
    growth: dict[str, Any] = Field(default_factory=dict)
    candidate_id: str | None = None
    document_id: str | None = None
    paper_id: int | None = None
    resume_trace_id: str | None = None
    task_id: str | None = None
    pages: list[dict[str, Any]] = Field(default_factory=list)
    report_period: str | None = None
    progress_events: list[dict[str, Any]] = Field(default_factory=list)
    chat_summary: list[dict[str, Any]] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)


class RunCreate(BaseModel):
    skill_id: str = "mentor_match"
    message: str = Field(min_length=1, max_length=10000)
    context: SharedContext = Field(default_factory=SharedContext)
    execute_immediately: bool = False


class RunCreated(BaseModel):
    run_id: str
    skill_id: str
    status: str
    trace_id: str | None = None
    thread_id: int | None = None
    suggested_next_skill: str | None = None
    review_status: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    artifact: dict[str, Any] | None = None
