from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.integrations.llm.openai_compatible import (
    OpenAICompatibleChatModelAdapter,
)
from backend.mentor_workflow.agentic_research import (
    AgenticMentorResearchTool,
    AgenticPaperResearchEnricher,
    AgenticResearchSession,
    ModelDrivenDomainExpertAgent,
    ModelDrivenMatchingAgent,
    StructuredMentorReasoner,
)
from backend.mentor_workflow.orchestrator import MentorWorkflowOrchestrator
from backend.mentor_workflow.research_tools import UstcMentorResearchTool
from backend.mentor_workflow.schemas import (
    AgentMessage,
    CandidateMentor,
    EvidenceRecord,
    FinalResult,
    MatchResult,
    MentorWorkflowRequest,
    MentorWorkflowSupplement,
    ResearchAuditSnapshot,
    ReviewDecision,
    WorkflowCreated,
    WorkflowState,
    WorkflowStatusRead,
)
from backend.mentor_workflow.state_store import SqlAlchemyStateStore, StateStore
from backend.mentor_workflow.ustc_sources import (
    HttpxUstcFacultyGateway,
    HttpxUstcProfileFetcher,
    InternalMentorRag,
    MissingDirectionPaperEnricher,
    NullInternalMentorRag,
    SqlAlchemyMentorPaperSearchGateway,
    UstcOfficialMentorSource,
)
from backend.services.providers import chat_provider_from_settings
from backend.settings import get_settings

router = APIRouter(prefix="/mentor-workflows", tags=["mentor-workflows"])


@dataclass(frozen=True)
class MentorWorkflowRuntime:
    store: StateStore
    orchestrator: MentorWorkflowOrchestrator
    commit: Callable[[], None]
    run_id: Callable[[str], int | None]


def get_internal_mentor_rag() -> InternalMentorRag:
    """Dependency seam for the curated internal USTC RAG adapter.

    加载 ``data/ustc_mentor_rag.json``（由 data_scripts 抓取+组装）提供的
    ``FileInternalMentorRag``，让内部库在命中时跳过外部官方源。该文件缺失或
    导入失败时回退到 Null（用外部源），保证工作流可用。
    """
    # data_scripts 是仓库根的顶层命名空间包，需把仓库根加入 sys.path 才能导入；
    # data_dir（默认 仓库根/data）来自同一份 settings，保证路径一致。
    import sys

    data_dir = get_settings().data_dir
    repo_root = str(data_dir.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from data_scripts.internal_mentor_rag import FileInternalMentorRag

    except Exception:  # noqa: BLE001 - 库文件缺失/依赖不全时降级
        return NullInternalMentorRag()
    return FileInternalMentorRag(rag_path=data_dir / "ustc_mentor_rag.json")


def get_mentor_workflow_runtime(
    session: Session = Depends(get_db_session),
    internal_rag: InternalMentorRag = Depends(get_internal_mentor_rag),
) -> MentorWorkflowRuntime:
    store = SqlAlchemyStateStore(session)
    return MentorWorkflowRuntime(
        store=store,
        orchestrator=_orchestrator(session, store, internal_rag),
        commit=session.commit,
        run_id=store.run_id,
    )


@router.post("", response_model=WorkflowCreated)
def create_mentor_workflow(
    request: MentorWorkflowRequest,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> WorkflowCreated:
    state = runtime.orchestrator.create(request)
    runtime.commit()
    return WorkflowCreated(
        trace_id=state.trace_id,
        run_id=runtime.run_id(state.trace_id),
        status=state.status,
        current_stage=state.current_stage,
        state_version=state.state_version,
    )


@router.get("/{trace_id}", response_model=WorkflowState)
def get_mentor_workflow(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> WorkflowState:
    return _state_or_404(runtime.store, trace_id)


@router.get("/{trace_id}/status", response_model=WorkflowStatusRead)
def get_mentor_workflow_status(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> WorkflowStatusRead:
    state = _state_or_404(runtime.store, trace_id)
    return WorkflowStatusRead(
        trace_id=state.trace_id,
        status=state.status,
        current_stage=state.current_stage,
        state_version=state.state_version,
        retry_count=len(state.retries),
        clarification_request=state.clarification_request,
        error_count=len(state.errors),
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


@router.get("/{trace_id}/events", response_model=list[AgentMessage])
def get_mentor_workflow_events(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> list[AgentMessage]:
    _state_or_404(runtime.store, trace_id)
    return runtime.store.list_workflow_events(trace_id)


@router.get("/{trace_id}/candidates", response_model=list[CandidateMentor])
def get_mentor_workflow_candidates(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> list[CandidateMentor]:
    return _state_or_404(runtime.store, trace_id).candidates


@router.get("/{trace_id}/matches", response_model=list[MatchResult])
def get_mentor_workflow_matches(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> list[MatchResult]:
    return _state_or_404(runtime.store, trace_id).match_results


@router.get("/{trace_id}/evidence", response_model=list[EvidenceRecord])
def get_mentor_workflow_evidence(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> list[EvidenceRecord]:
    return _state_or_404(runtime.store, trace_id).evidence_ledger


@router.get("/{trace_id}/audit", response_model=ResearchAuditSnapshot | None)
def get_mentor_workflow_research_audit(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> ResearchAuditSnapshot | None:
    return _state_or_404(runtime.store, trace_id).research_audit


@router.get("/{trace_id}/review", response_model=ReviewDecision | None)
def get_mentor_workflow_review(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> ReviewDecision | None:
    return _state_or_404(runtime.store, trace_id).review_decision


@router.get("/{trace_id}/result", response_model=FinalResult | None)
def get_mentor_workflow_result(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> FinalResult | None:
    return _state_or_404(runtime.store, trace_id).final_result


@router.post("/{trace_id}/input", response_model=WorkflowState)
def submit_mentor_workflow_input(
    trace_id: str,
    supplement: MentorWorkflowSupplement,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> WorkflowState:
    _state_or_404(runtime.store, trace_id)
    state = runtime.orchestrator.supplement(trace_id, supplement)
    runtime.commit()
    return state


@router.post("/{trace_id}/resume", response_model=WorkflowState)
def resume_mentor_workflow(
    trace_id: str,
    runtime: MentorWorkflowRuntime = Depends(get_mentor_workflow_runtime),
) -> WorkflowState:
    _state_or_404(runtime.store, trace_id)
    state = runtime.orchestrator.run(trace_id)
    runtime.commit()
    return state


def _orchestrator(
    session: Session,
    store: SqlAlchemyStateStore,
    internal_rag: InternalMentorRag,
) -> MentorWorkflowOrchestrator:
    settings = get_settings()
    official_source = UstcOfficialMentorSource(
        HttpxUstcFacultyGateway(
            endpoint=settings.ustc_faculty_search_endpoint,
            timeout_seconds=settings.ustc_faculty_http_timeout_seconds,
        ),
        HttpxUstcProfileFetcher(
            timeout_seconds=settings.ustc_faculty_http_timeout_seconds
        ),
        college_id=settings.ustc_faculty_college_id,
        page_size=settings.ustc_faculty_search_page_size,
        max_pages_per_query=settings.ustc_faculty_search_max_pages,
        max_queries=settings.ustc_faculty_search_max_queries,
        max_candidates=settings.ustc_faculty_max_candidates,
        broad_domain_discovery=settings.mentor_workflow_model_reasoning_enabled,
    )
    paper_gateway = SqlAlchemyMentorPaperSearchGateway(session)
    if settings.mentor_workflow_model_reasoning_enabled:
        provider = chat_provider_from_settings(settings)
        provider.settings = {
            **provider.settings,
            "max_tokens": settings.mentor_workflow_model_max_tokens,
        }
        audit = AgenticResearchSession(provider)
        reasoner = StructuredMentorReasoner(
            OpenAICompatibleChatModelAdapter(),
            provider,
            audit,
        )
        agentic_enricher = AgenticPaperResearchEnricher(
            paper_gateway,
            reasoner,
            audit,
            max_candidates=settings.mentor_workflow_model_max_candidates,
            max_results_per_source=(
                settings.mentor_paper_fallback_max_results_per_source
            ),
            max_papers_per_candidate=(
                settings.mentor_paper_fallback_max_papers_per_candidate
            ),
        )
        research_tool = AgenticMentorResearchTool(
            internal_rag=internal_rag,
            official_source=official_source,
            paper_enricher=agentic_enricher,
            reasoner=reasoner,
            session=audit,
        )
        return MentorWorkflowOrchestrator(
            store,
            research_tool,
            agent_timeout_seconds=settings.mentor_workflow_agent_timeout_seconds,
            tool_timeout_seconds=settings.mentor_workflow_tool_timeout_seconds,
            max_total_retries=settings.mentor_workflow_max_total_retries,
            domain_agent=ModelDrivenDomainExpertAgent(reasoner),
            matching_agent=ModelDrivenMatchingAgent(audit),
            research_audit=audit,
        )
    paper_enricher = MissingDirectionPaperEnricher(
        paper_gateway,
        max_candidates=settings.mentor_paper_fallback_max_candidates,
        max_results_per_source=(settings.mentor_paper_fallback_max_results_per_source),
        max_papers_per_candidate=(
            settings.mentor_paper_fallback_max_papers_per_candidate
        ),
    )
    return MentorWorkflowOrchestrator(
        store,
        UstcMentorResearchTool(
            internal_rag=internal_rag,
            official_source=official_source,
            paper_enricher=paper_enricher,
        ),
        agent_timeout_seconds=settings.mentor_workflow_agent_timeout_seconds,
        tool_timeout_seconds=settings.mentor_workflow_tool_timeout_seconds,
        max_total_retries=settings.mentor_workflow_max_total_retries,
    )


def _state_or_404(store: StateStore, trace_id: str) -> WorkflowState:
    state = store.get_workflow(trace_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Mentor workflow not found")
    return state
