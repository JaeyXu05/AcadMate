from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ServiceError(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ProviderResolutionError(Exception):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error = ServiceError(code=code, message=message, detail=detail or {})


class ResolvedProviderConfig(BaseModel):
    id: int
    name: str
    kind: str
    provider: str
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_ref: str | None = None
    temperature: float | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class PaperIdentifierInput(BaseModel):
    identifier_type: str
    identifier_value: str
    is_primary: bool = False


class PaperMetadataPatch(BaseModel):
    title: str | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    authors: list[str] | None = None
    best_pdf_url: str | None = None
    landing_page_url: str | None = None


class PaperSourceRecordPatch(BaseModel):
    source: str
    source_record_id: str | None = None
    source_url: str | None = None
    is_primary: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class PaperSearchResult(BaseModel):
    source: str
    source_record_id: str | None = None
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    landing_page_url: str | None = None
    pdf_url: str | None = None
    score: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ParsedDocumentPayload(BaseModel):
    strategy: str
    parser_kind: str
    plain_text: str | None = None
    markdown_content: str | None = None
    json_content: dict[str, Any] = Field(default_factory=dict)
    quality_summary: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    chunk_id: int
    processed_document_id: int
    content_text: str
    score: float
    retrieval_mode: Literal["vector", "lexical"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportGenerationResult(BaseModel):
    report_id: int
    status: str
    markdown_content: str | None = None
    json_content: dict[str, Any] | None = None
    error_message: str | None = None
    evidence_ids: list[int] = Field(default_factory=list)


class AgentMessageRequest(BaseModel):
    thread_id: int | None = None
    message: str
    active_paper_id: int | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout: int = 60
    max_retries: int = 2
    chat_provider_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMessageResponse(BaseModel):
    thread_id: int
    run_id: int
    assistant_message_id: int | None = None
    status: str
    message: str | None = None
    error: str | None = None


class AgentStreamEvent(BaseModel):
    type: str
    thread_id: int
    run_id: int
    sequence: int | None = None
    event_type: str | None = None
    status: str | None = None
    message: str | None = None
    assistant_message_id: int | None = None
    error: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MessageRead(BaseModel):
    id: int
    thread_id: int
    role: str
    content_text: str | None = None
    content_json: dict[str, Any] | None = None
    source: str
    run_id: int | None = None
    created_at: datetime


class RunEventRead(BaseModel):
    id: int
    run_id: int
    sequence: int
    event_type: str
    level: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RunRead(BaseModel):
    id: int
    thread_id: int | None = None
    workflow: str
    status: str
    error_message: str | None = None
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    events: list[RunEventRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ThreadSummary(BaseModel):
    id: int
    title: str
    surface: str
    status: str
    current_focus_paper_id: int | None = None
    created_at: datetime
    updated_at: datetime


class ThreadDetail(ThreadSummary):
    messages: list[MessageRead] = Field(default_factory=list)
    runs: list[RunRead] = Field(default_factory=list)


class MemoryRead(BaseModel):
    id: int
    path: str
    title: str | None = None
    memory_type: str
    scope_type: str
    scope_id: str | None = None
    paper_id: int | None = None
    content_text: str
    content_json: dict[str, Any] | None = None
    source: str
    status: str
    source_thread_id: int | None = None
    source_paper_id: int | None = None
    last_accessed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class RuntimeSettingsRead(BaseModel):
    environment: str
    data_dir: str
    storage_root: str | None = None
    database_configured: bool
    chat: dict[str, Any] = Field(default_factory=dict)
    embedding: dict[str, Any] = Field(default_factory=dict)
    arxiv: dict[str, Any] = Field(default_factory=dict)
    openalex: dict[str, Any] = Field(default_factory=dict)
    parsing: dict[str, Any] = Field(default_factory=dict)


class ArtifactRead(BaseModel):
    id: int
    kind: str
    status: str
    storage_backend: str
    storage_uri: str | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None


class PaperSummary(BaseModel):
    id: int
    title: str
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    status: str
    current_pdf_url: str | None = None


class PaperDetail(PaperSummary):
    authors: list[Any] = Field(default_factory=list)
    identifiers: list[dict[str, Any]] = Field(default_factory=list)
    source_records: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    parse_jobs: list[dict[str, Any]] = Field(default_factory=list)
    processed_documents: list[dict[str, Any]] = Field(default_factory=list)
    reports: list[dict[str, Any]] = Field(default_factory=list)


class SearchCandidateRead(BaseModel):
    id: int
    rank: int
    source: str
    source_record_id: str | None = None
    paper_id: int | None = None
    title: str
    abstract: str | None = None
    authors: list[Any] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    landing_page_url: str | None = None
    pdf_url: str | None = None
    score: float | None = None


class SearchSessionRead(BaseModel):
    id: int
    thread_id: int | None = None
    run_id: int | None = None
    query_text: str
    status: str
    selected_candidate_id: int | None = None
    candidates: list[SearchCandidateRead] = Field(default_factory=list)


class RunDecision(BaseModel):
    type: Literal["approve", "edit", "reject", "respond"]
    args: dict[str, Any] | None = None
    edited_action: dict[str, Any] | None = None
    message: str | None = None


class ApprovalRequest(BaseModel):
    decisions: list[RunDecision] = Field(default_factory=list)
    decision: Literal["approve", "reject", "revise", "cancel"] | None = None
    comment: str | None = None


class ReportSummary(BaseModel):
    id: int
    title: str
    paper_id: int | None = None
    processed_document_id: int | None = None
    report_type: str
    status: str
    source_scope: str
    created_at: datetime
    updated_at: datetime


class ReportRead(ReportSummary):
    paper_title: str | None = None
    markdown_content: str | None = None
    json_content: dict[str, Any] | None = None
    source_refs: list[Any] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class ArxivTaskDailyConfigRead(BaseModel):
    id: int
    enabled: bool
    run_time: str
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ArxivTaskDailyConfigUpdateRequest(BaseModel):
    enabled: bool = True
    run_time: str


class ArxivTaskSubscriptionRead(BaseModel):
    id: int
    name: str
    query: str
    description: str | None = None
    enabled: bool
    last_refreshed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ArxivTaskSubscriptionCreateRequest(BaseModel):
    name: str
    query: str
    description: str | None = None
    enabled: bool = True


class ArxivTaskSubscriptionUpdateRequest(BaseModel):
    name: str
    query: str
    description: str | None = None
    enabled: bool = True


class ArxivTaskSubscriptionTestRequest(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)


class ArxivTaskPaperRead(BaseModel):
    id: int
    arxiv_id: str
    arxiv_base_id: str
    title: str
    abstract: str | None = None
    authors: list[Any] = Field(default_factory=list)
    primary_category: str | None = None
    categories: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    updated_at_source: datetime | None = None
    landing_page_url: str | None = None
    pdf_url: str | None = None
    comment: str | None = None
    journal_ref: str | None = None
    doi: str | None = None
    created_at: datetime
    updated_at: datetime


class ArxivTaskSubscriptionTestPaperRead(BaseModel):
    arxiv_id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    primary_category: str | None = None
    categories: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    updated_at_source: datetime | None = None
    landing_page_url: str | None = None
    pdf_url: str | None = None


class ArxivTaskSubscriptionTestRead(BaseModel):
    query: str
    total_results: int
    papers: list[ArxivTaskSubscriptionTestPaperRead] = Field(default_factory=list)


class ArxivTaskQueryWindowRead(BaseModel):
    id: int
    subscription_id: int
    query_snapshot: str
    job_id: int | None = None
    kind: str
    window_start: datetime
    window_end: datetime
    status: str
    total_results: int | None = None
    fetched_count: int
    inserted_count: int
    updated_count: int
    page_size: int | None = None
    page_count: int
    error_message: str | None = None
    warning_code: str | None = None
    parent_window_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ArxivTaskHarvestJobRead(BaseModel):
    id: int
    kind: str
    status: str
    subscription_ids: list[int] = Field(default_factory=list)
    requested_start: datetime | None = None
    requested_end: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ArxivTaskHistoryJobCreateRequest(BaseModel):
    subscription_ids: list[int]
    start_time: datetime
    end_time: datetime


class ArxivTaskStatusRead(BaseModel):
    daily_config: ArxivTaskDailyConfigRead
    subscriptions: list[ArxivTaskSubscriptionRead] = Field(default_factory=list)
    enabled_subscription_ids: list[int] = Field(default_factory=list)
    coverage_subscription_ids: list[int] = Field(default_factory=list)
    active_job: ArxivTaskHarvestJobRead | None = None
    recent_jobs: list[ArxivTaskHarvestJobRead] = Field(default_factory=list)
    recent_windows: list[ArxivTaskQueryWindowRead] = Field(default_factory=list)
    recent_papers: list[ArxivTaskPaperRead] = Field(default_factory=list)
    total_papers: int


@dataclass(frozen=True)
class PaperClawContext:
    thread_id: int | None = None
    run_id: int | None = None
    active_paper_id: int | None = None
    active_paper_system_info: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout: int = 60
    max_retries: int = 2
    extra_body: dict[str, Any] | None = None
    rate_limiter: Any | None = None
    chat_provider_name: str | None = None
    embedding_provider_name: str | None = None
