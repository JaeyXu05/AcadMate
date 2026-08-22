from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class MentorGoal(StrEnum):
    find_mentors = "find_mentors"
    inspect_mentor = "inspect_mentor"
    compare_mentors = "compare_mentors"
    generate_contact_email = "generate_contact_email"
    follow_up_question = "follow_up_question"


class WorkflowStage(StrEnum):
    input_understanding = "input_understanding"
    planning = "planning"
    domain_expert = "domain_expert"
    mentor_research = "mentor_research"
    matching = "matching"
    evidence_review = "evidence_review"
    result_composer = "result_composer"
    completed = "completed"
    failed = "failed"


class WorkflowStatus(StrEnum):
    pending = "PENDING"
    running = "RUNNING"
    clarification_required = "CLARIFICATION_REQUIRED"
    result_ready = "RESULT_READY"
    completed = "COMPLETED"
    failed = "FAILED"


class WorkflowEventType(StrEnum):
    workflow_created = "WORKFLOW_CREATED"
    input_received = "INPUT_RECEIVED"
    intent_ready = "INTENT_READY"
    clarification_required = "CLARIFICATION_REQUIRED"
    plan_ready = "PLAN_READY"
    domain_analysis_started = "DOMAIN_ANALYSIS_STARTED"
    domain_analysis_ready = "DOMAIN_ANALYSIS_READY"
    research_started = "RESEARCH_STARTED"
    research_done = "RESEARCH_DONE"
    matching_started = "MATCHING_STARTED"
    matching_done = "MATCHING_DONE"
    review_started = "REVIEW_STARTED"
    review_passed = "REVIEW_PASSED"
    review_failed = "REVIEW_FAILED"
    task_retry = "TASK_RETRY"
    composing_result = "COMPOSING_RESULT"
    result_ready = "RESULT_READY"
    workflow_completed = "WORKFLOW_COMPLETED"
    workflow_failed = "WORKFLOW_FAILED"


class ReviewStatus(StrEnum):
    pass_ = "PASS"
    revise = "REVISE"
    research_again = "RESEARCH_AGAIN"
    need_more_input = "NEED_MORE_INPUT"
    failed = "FAILED"


class RetryTarget(StrEnum):
    input_understanding = "input_understanding"
    domain_expert = "domain_expert"
    mentor_research = "mentor_research"
    matching = "matching"
    result_composer = "result_composer"


class ExecutionMode(StrEnum):
    sequential = "sequential"
    parallel_where_safe = "parallel_where_safe"


class EvidenceFreshness(StrEnum):
    current = "current"
    recent = "recent"
    stale = "stale"
    unknown = "unknown"


class WorkflowErrorKind(StrEnum):
    recoverable = "recoverable"
    temporary_tool = "temporary_tool"
    tool_timeout = "tool_timeout"
    agent_timeout = "agent_timeout"
    schema_validation = "schema_validation"
    model_output = "model_output"
    evidence_insufficient = "evidence_insufficient"
    user_input_insufficient = "user_input_insufficient"
    permanent_configuration = "permanent_configuration"
    business = "business"
    persistence = "persistence"


class InputSource(StrEnum):
    text = "text"
    keyword = "keyword"
    pdf = "pdf"
    interaction_trace = "interaction_trace"
    user_profile = "user_profile"
    prior_workflow = "prior_workflow"


class MentorConstraints(BaseModel):
    colleges: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    mentor_names: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    undergraduate_friendly: bool | None = None
    recruitment_required: bool | None = None
    theory_preference: float | None = Field(default=None, ge=0, le=1)
    custom: dict[str, str | int | float | bool] = Field(default_factory=dict)


class UserProfile(BaseModel):
    name: str | None = None
    education_level: str | None = None
    background: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experiences: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class UserProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    technologies: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)


class ParsedDocumentInput(BaseModel):
    source_ref: str
    summary: str = Field(max_length=4000)
    research_topics: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    application_domains: list[str] = Field(default_factory=list)


class InteractionTraceInput(BaseModel):
    source_ref: str
    node_ids: list[str] = Field(default_factory=list)
    research_topics: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)


class MentorWorkflowRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    goal: MentorGoal | None = None
    research_topics: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    application_domains: list[str] = Field(default_factory=list)
    constraints: MentorConstraints = Field(default_factory=MentorConstraints)
    user_profile: UserProfile = Field(default_factory=UserProfile)
    projects: list[UserProjectInput] = Field(default_factory=list)
    parsed_documents: list[ParsedDocumentInput] = Field(default_factory=list)
    interaction_traces: list[InteractionTraceInput] = Field(default_factory=list)
    raw_input_refs: list[str] = Field(default_factory=list)
    execute_immediately: bool = True

    @field_validator(
        "research_topics", "methods", "application_domains", "raw_input_refs"
    )
    @classmethod
    def normalize_string_lists(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values)


class MentorWorkflowSupplement(BaseModel):
    message: str | None = Field(default=None, min_length=1, max_length=10000)
    goal: MentorGoal | None = None
    research_topics: list[str] | None = None
    methods: list[str] | None = None
    application_domains: list[str] | None = None
    constraints: MentorConstraints | None = None
    user_profile: UserProfile | None = None
    projects: list[UserProjectInput] | None = None
    parsed_documents: list[ParsedDocumentInput] | None = None
    interaction_traces: list[InteractionTraceInput] | None = None
    raw_input_refs: list[str] | None = None


class ClarificationRequest(BaseModel):
    missing_fields: list[str]
    questions: list[str]
    reason: str


class IntentPacket(BaseModel):
    trace_id: str
    goal: MentorGoal
    research_topics: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    application_domains: list[str] = Field(default_factory=list)
    input_sources: list[InputSource] = Field(default_factory=list)
    constraints: MentorConstraints = Field(default_factory=MentorConstraints)
    user_profile: UserProfile = Field(default_factory=UserProfile)
    projects: list[UserProjectInput] = Field(default_factory=list)
    raw_message: str = ""
    confidence: float = Field(ge=0, le=1)
    missing_fields: list[str] = Field(default_factory=list)
    raw_input_refs: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    step_id: str
    agent_name: str
    dependencies: list[str] = Field(default_factory=list)
    enabled: bool = True


class AgentAssignment(BaseModel):
    agent_name: str
    responsibility: str
    authorized_tools: list[str] = Field(default_factory=list)
    success_condition: str
    failure_condition: str


class ToolBudget(BaseModel):
    local_calls: int = Field(default=20, ge=0)
    external_calls: int = Field(default=100, ge=0)
    per_tool_timeout_seconds: float = Field(default=240, gt=0)


class RetryPolicy(BaseModel):
    max_retry_count: int = Field(default=3, ge=0)
    max_total_retries: int = Field(default=5, ge=0)
    per_stage_max_retries: dict[RetryTarget, int] = Field(
        default_factory=lambda: {
            RetryTarget.domain_expert: 1,
            RetryTarget.mentor_research: 2,
            RetryTarget.matching: 2,
            RetryTarget.input_understanding: 1,
            RetryTarget.result_composer: 1,
        }
    )


class TaskPlan(BaseModel):
    trace_id: str
    steps: list[PlanStep]
    agent_assignments: list[AgentAssignment]
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.sequential
    tool_budget: ToolBudget = Field(default_factory=ToolBudget)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    stop_conditions: list[str] = Field(default_factory=list)
    skipped_steps: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: f"msg_{uuid4().hex}")
    trace_id: str
    sender: str
    receiver: str
    event_type: WorkflowEventType
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    state_version: int = Field(ge=1)
    parent_message_id: str | None = None
    error: str | None = None


class EvidenceRecord(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid4().hex}")
    candidate_id: str | None = None
    source_type: str
    source_uri: str
    title: str
    extracted_fact: str
    locator: str
    retrieved_at: datetime = Field(default_factory=utcnow)
    freshness: EvidenceFreshness = EvidenceFreshness.unknown
    confidence: float = Field(ge=0, le=1)
    content_hash: str | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_source_and_fact(self) -> EvidenceRecord:
        if (
            not self.source_uri.strip()
            or not self.extracted_fact.strip()
            or not self.locator.strip()
        ):
            raise ValueError("Evidence requires a source, extracted fact, and locator")
        return self


class CandidateMentor(BaseModel):
    candidate_id: str
    mentor_name: str
    affiliation: str | None = None
    department: str | None = None
    research_topics: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    homepage: str | None = None
    recruitment_status: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    source_metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)


class MatchDimensionScores(BaseModel):
    research_topic_match: float = Field(ge=0, le=100)
    method_match: float = Field(ge=0, le=100)
    application_match: float = Field(ge=0, le=100)
    recent_activity: float = Field(ge=0, le=100)
    student_background_fit: float = Field(ge=0, le=100)
    constraint_satisfaction: float = Field(ge=0, le=100)
    recruitment_fit: float = Field(ge=0, le=100)
    evidence_completeness: float = Field(ge=0, le=100)

    def mean_score(self) -> float:
        values = list(self.model_dump().values())
        return round(sum(values) / len(values), 2)


class MatchResult(BaseModel):
    candidate_id: str
    total_score: float = Field(ge=0, le=100)
    dimension_scores: MatchDimensionScores
    rationale: list[str] = Field(default_factory=list)
    negative_factors: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    ranking_position: int = Field(ge=1)


class DomainJudgement(BaseModel):
    expert_name: str
    domain: str
    search_concepts: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    boundary: str
    interdisciplinary_links: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    review_id: str = Field(default_factory=lambda: f"review_{uuid4().hex}")
    status: ReviewStatus
    reviewed_candidate_ids: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    revision_target: RetryTarget | None = None
    revision_reason: str | None = None
    missing_evidence_refs: list[str] = Field(default_factory=list)
    reviewer_summary: str
    created_at: datetime = Field(default_factory=utcnow)


class RetryRecord(BaseModel):
    retry_id: str = Field(default_factory=lambda: f"retry_{uuid4().hex}")
    retry_count: int = Field(ge=1)
    retry_target: RetryTarget
    retry_reason: str
    previous_state_version: int = Field(ge=1)
    new_state_version: int = Field(ge=1)
    triggering_review_id: str
    created_at: datetime = Field(default_factory=utcnow)


class WorkflowErrorRecord(BaseModel):
    error_id: str = Field(default_factory=lambda: f"error_{uuid4().hex}")
    kind: WorkflowErrorKind
    stage: WorkflowStage
    message: str
    recoverable: bool
    created_at: datetime = Field(default_factory=utcnow)


class FinalMentorResult(BaseModel):
    candidate: CandidateMentor
    match: MatchResult | None = None


class FinalResult(BaseModel):
    trace_id: str
    goal: MentorGoal
    mentors: list[FinalMentorResult] = Field(default_factory=list)
    comparison_summary: list[str] = Field(default_factory=list)
    research_direction_suggestions: list[str] = Field(default_factory=list)
    contact_email_draft: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class MentorResearchResult(BaseModel):
    candidates: list[CandidateMentor] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    used_fallback: bool = False
    source_chain: list[str] = Field(default_factory=list)
    unresolved_candidate_ids: list[str] = Field(default_factory=list)


class ProjectResearchInterpretation(BaseModel):
    project_name: str
    project_summary: str
    inferred_research_problems: list[str] = Field(default_factory=list)
    inferred_domains: list[str] = Field(default_factory=list)
    inferred_methods: list[str] = Field(default_factory=list)
    demonstrated_capabilities: list[str] = Field(default_factory=list)
    transferable_directions: list[str] = Field(default_factory=list)
    rationale: str
    confidence: float = Field(ge=0, le=1)


class ResearchQuerySpec(BaseModel):
    query: str
    purpose: str
    preferred_sources: list[str] = Field(default_factory=list)
    expected_signal: str


class ModelResearchPreparation(BaseModel):
    stated_goal: str
    project_interpretations: list[ProjectResearchInterpretation] = Field(
        default_factory=list
    )
    primary_directions: list[str] = Field(default_factory=list)
    adjacent_directions: list[str] = Field(default_factory=list)
    domain_codes: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    application_domains: list[str] = Field(default_factory=list)
    search_queries: list[ResearchQuerySpec] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    overall_explanation: str


class PaperDirectionFinding(BaseModel):
    paper_index: int = Field(ge=0)
    relevant: bool
    actual_direction: str
    inferred_topics: list[str] = Field(default_factory=list)
    inferred_methods: list[str] = Field(default_factory=list)
    evidence_basis: str
    project_fit: str
    confidence: float = Field(ge=0, le=1)


class CandidateResearchAssessment(BaseModel):
    candidate_id: str
    overall_relevance: float = Field(ge=0, le=100)
    research_topic_fit: float = Field(ge=0, le=100)
    method_fit: float = Field(ge=0, le=100)
    application_fit: float = Field(ge=0, le=100)
    project_background_fit: float = Field(ge=0, le=100)
    direction_summary: str
    project_alignment: list[str] = Field(default_factory=list)
    relevant_papers: list[PaperDirectionFinding] = Field(default_factory=list)
    preparation_advice: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommendation: str
    uncertainty: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class CandidateScreeningDecision(BaseModel):
    candidate_id: str
    coarse_relevance: float = Field(ge=0, le=100)
    keep_for_paper_search: bool
    likely_overlap: list[str] = Field(default_factory=list)
    reason: str
    uncertainty: list[str] = Field(default_factory=list)


class CandidateScreeningResult(BaseModel):
    decisions: list[CandidateScreeningDecision] = Field(default_factory=list)
    strategy_summary: str


class ResearchAgentContextSnapshot(BaseModel):
    agent_name: str
    objective: str
    model: str
    deployment_scope: str = "ustc"
    allowed_tools: list[str] = Field(default_factory=list)
    evidence_policy: list[str] = Field(default_factory=list)
    source_policy: list[str] = Field(default_factory=list)
    input_summary: dict[str, str | int | float | bool] = Field(default_factory=dict)
    system_context: str
    hidden_reasoning_exposed: bool = False


class ResearchToolTrace(BaseModel):
    sequence: int = Field(ge=1)
    agent_name: str
    tool_name: str
    transport: str
    mcp_server: bool = False
    input_summary: dict[str, str | int | float | bool] = Field(default_factory=dict)
    output_summary: dict[str, str | int | float | bool] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    status: str
    duration_ms: float = Field(ge=0)


class ResearchAuditSnapshot(BaseModel):
    mode: str = "model_driven"
    provider_name: str
    model: str
    contexts: list[ResearchAgentContextSnapshot] = Field(default_factory=list)
    preparation: ModelResearchPreparation | None = None
    candidate_screening: CandidateScreeningResult | None = None
    candidate_assessments: list[CandidateResearchAssessment] = Field(
        default_factory=list
    )
    tool_trace: list[ResearchToolTrace] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WorkflowState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    trace_id: str
    current_stage: WorkflowStage = WorkflowStage.input_understanding
    status: WorkflowStatus = WorkflowStatus.pending
    state_version: int = Field(default=1, ge=1)
    request: MentorWorkflowRequest
    intent: IntentPacket | None = None
    clarification_request: ClarificationRequest | None = None
    task_plan: TaskPlan | None = None
    domain_judgements: list[DomainJudgement] = Field(default_factory=list)
    candidates: list[CandidateMentor] = Field(default_factory=list)
    evidence_ledger: list[EvidenceRecord] = Field(default_factory=list)
    match_results: list[MatchResult] = Field(default_factory=list)
    research_audit: ResearchAuditSnapshot | None = None
    review_decision: ReviewDecision | None = None
    retries: list[RetryRecord] = Field(default_factory=list)
    final_result: FinalResult | None = None
    errors: list[WorkflowErrorRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowCreated(BaseModel):
    trace_id: str
    run_id: int | None = None
    status: WorkflowStatus
    current_stage: WorkflowStage
    state_version: int


class WorkflowStatusRead(BaseModel):
    trace_id: str
    status: WorkflowStatus
    current_stage: WorkflowStage
    state_version: int
    retry_count: int
    clarification_request: ClarificationRequest | None = None
    error_count: int
    created_at: datetime
    updated_at: datetime


def new_workflow_state(
    request: MentorWorkflowRequest, trace_id: str | None = None
) -> WorkflowState:
    return WorkflowState(trace_id=trace_id or f"mentor_{uuid4().hex}", request=request)


def _unique_nonempty(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip()
        normalized = cleaned.casefold()
        if cleaned and normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)
    return result
