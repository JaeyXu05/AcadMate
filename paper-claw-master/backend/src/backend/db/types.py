from __future__ import annotations

from enum import StrEnum


class ProviderKind(StrEnum):
    chat = "chat"
    embedding = "embedding"
    parser = "parser"
    search = "search"
    storage = "storage"


class ProviderName(StrEnum):
    anthropic = "anthropic"
    openai = "openai"
    openai_compatible = "openai_compatible"
    deepseek = "deepseek"
    ollama = "ollama"
    llama_parse = "llama_parse"
    arxiv = "arxiv"
    openalex = "openalex"
    local = "local"


class ThreadSurface(StrEnum):
    web = "web"
    cli = "cli"
    feishu = "feishu"


class ThreadStatus(StrEnum):
    active = "active"
    archived = "archived"


class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class MessageSource(StrEnum):
    human = "human"
    agent = "agent"
    tool = "tool"
    system = "system"


class WorkflowName(StrEnum):
    search_confirmation = "search_confirmation"
    acquisition_upload = "acquisition_upload"
    parsing = "parsing"
    analysis_report = "analysis_report"
    paper_qa = "paper_qa"
    citation_survey = "citation_survey"
    subscription_ingestion = "subscription_ingestion"
    mentor_search = "mentor_search"
    pdf_analyze = "pdf_analyze"
    email_compose = "email_compose"
    research_task = "research_task"
    direction_explore = "direction_explore"
    progress_report = "progress_report"
    plan_coach = "plan_coach"


class RunStatus(StrEnum):
    pending = "pending"
    waiting_for_user = "waiting_for_user"
    running = "running"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"


class EventLevel(StrEnum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class PaperStatus(StrEnum):
    metadata_only = "metadata_only"
    acquiring = "acquiring"
    acquired = "acquired"
    parse_pending = "parse_pending"
    parsed = "parsed"
    processed = "processed"
    failed = "failed"


class IdentifierType(StrEnum):
    doi = "doi"
    arxiv = "arxiv"
    openalex = "openalex"
    semantic_scholar = "semantic_scholar"
    pubmed = "pubmed"
    acl = "acl"
    url = "url"
    manual = "manual"


class PaperSource(StrEnum):
    local = "local"
    arxiv = "arxiv"
    openalex = "openalex"
    manual_upload = "manual_upload"
    crossref = "crossref"
    semantic_scholar = "semantic_scholar"


class SearchStatus(StrEnum):
    draft = "draft"
    candidates_found = "candidates_found"
    waiting_for_confirmation = "waiting_for_confirmation"
    confirmed = "confirmed"
    rejected = "rejected"
    expired = "expired"
    failed = "failed"


class ArtifactKind(StrEnum):
    pdf = "pdf"
    source_archive = "source_archive"
    metadata = "metadata"
    parsed_markdown = "parsed_markdown"
    parsed_json = "parsed_json"
    processed_markdown = "processed_markdown"
    report_markdown = "report_markdown"
    report_pdf = "report_pdf"
    image = "image"
    other = "other"


class ArtifactStatus(StrEnum):
    pending = "pending"
    available = "available"
    failed = "failed"
    deleted = "deleted"


class StorageBackend(StrEnum):
    local = "local"
    s3 = "s3"
    r2 = "r2"
    feishu = "feishu"


class PaperArtifactRole(StrEnum):
    metadata = "metadata"
    pdf = "pdf"
    source = "source"
    parser_output = "parser_output"
    processed_output = "processed_output"
    supplement = "supplement"


class AcquisitionSource(StrEnum):
    arxiv = "arxiv"
    openalex = "openalex"
    manual_upload = "manual_upload"
    url = "url"


class ParseStrategy(StrEnum):
    tex = "tex"
    local_ocr = "local_ocr"
    llama_parse = "llama_parse"
    grobid = "grobid"
    pdf_text = "pdf_text"
    manual = "manual"
    unavailable = "unavailable"


class ParseJobStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ParseQualityStatus(StrEnum):
    unknown = "unknown"
    good = "good"
    usable = "usable"
    poor = "poor"
    failed = "failed"


class ProcessedDocumentStatus(StrEnum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


class SectionRole(StrEnum):
    title = "title"
    abstract = "abstract"
    front_matter = "front_matter"
    body = "body"
    caption = "caption"
    table = "table"
    appendix = "appendix"
    reference = "reference"
    unknown = "unknown"


class ReportType(StrEnum):
    paper_summary = "paper_summary"
    critical_review = "critical_review"
    method_analysis = "method_analysis"
    experiment_analysis = "experiment_analysis"
    citation_survey = "citation_survey"
    custom = "custom"


class ReportStatus(StrEnum):
    draft = "draft"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    archived = "archived"


class ReportSourceScope(StrEnum):
    retrieval = "retrieval"
    full_document = "full_document"
    selected_chunks = "selected_chunks"
    citation_graph = "citation_graph"
    mixed = "mixed"


class EvidenceType(StrEnum):
    chunk = "chunk"
    reference = "reference"
    paper = "paper"
    external = "external"


class ArxivTaskDailyStatus(StrEnum):
    enabled = "enabled"
    disabled = "disabled"


class ArxivTaskJobKind(StrEnum):
    daily = "daily"
    history = "history"
    manual = "manual"


class ArxivTaskJobStatus(StrEnum):
    pending = "pending"
    running = "running"
    paused = "paused"
    stopping = "stopping"
    stopped = "stopped"
    succeeded = "succeeded"
    failed = "failed"


class ArxivTaskWindowStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    split = "split"
    partial = "partial"
    skipped = "skipped"


class MemoryType(StrEnum):
    user_preference = "user_preference"
    instruction = "instruction"
    research_note = "research_note"
    paper_note = "paper_note"
    project_state = "project_state"
    feedback = "feedback"
    reference = "reference"


class MemoryScope(StrEnum):
    global_ = "global"
    paper = "paper"
    project = "project"
    thread = "thread"


class MemorySource(StrEnum):
    user = "user"
    agent = "agent"
    tool = "tool"
    system = "system"


class MemoryStatus(StrEnum):
    active = "active"
    archived = "archived"
    deleted = "deleted"
