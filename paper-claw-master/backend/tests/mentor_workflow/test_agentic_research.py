from __future__ import annotations

import json

from backend.mentor_workflow.agentic_research import (
    AgenticMentorResearchTool,
    AgenticPaperResearchEnricher,
    AgenticResearchSession,
    ModelDrivenDomainExpertAgent,
    ModelDrivenMatchingAgent,
    StructuredMentorReasoner,
)
from backend.mentor_workflow.orchestrator import MentorWorkflowOrchestrator
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    EvidenceFreshness,
    EvidenceRecord,
    MentorGoal,
    MentorResearchResult,
    MentorWorkflowRequest,
    UserProjectInput,
    WorkflowStatus,
)
from backend.mentor_workflow.state_store import InMemoryStateStore
from backend.mentor_workflow.ustc_sources import (
    PaperSearchHit,
    PaperSearchPage,
)
from backend.schemas import ResolvedProviderConfig


class SequenceJsonAdapter:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[ResolvedProviderConfig, list[dict]]] = []

    def generate_text(
        self, provider: ResolvedProviderConfig, messages: list[dict]
    ) -> str:
        self.calls.append((provider, messages))
        return json.dumps(self.payloads.pop(0), ensure_ascii=False)


class EmptyInternalRag:
    def retrieve(self, _intent, _judgements) -> MentorResearchResult:
        return MentorResearchResult(source_chain=["internal_ustc_rag"])


class StaticOfficialSource:
    def __init__(self, result: MentorResearchResult) -> None:
        self.result = result
        self.calls = 0

    def search(self, _intent, _judgements) -> MentorResearchResult:
        self.calls += 1
        return self.result.model_copy(deep=True)


class StaticPaperGateway:
    def __init__(self, hit: PaperSearchHit) -> None:
        self.hit = hit
        self.calls: list[tuple[str, str, str, int]] = []

    def search(
        self,
        query: str,
        *,
        source: str,
        mode: str,
        max_results: int,
    ) -> PaperSearchPage:
        self.calls.append((query, source, mode, max_results))
        return PaperSearchPage(hits=[self.hit], warnings=[])


def _provider() -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        id=0,
        name="test-openai-compatible",
        kind="chat",
        provider="openai_compatible",
        base_url="https://example.invalid",
        model="test-model",
        api_key="not-recorded",
        temperature=0.1,
        settings={"max_tokens": 8000, "timeout": 30},
    )


def _preparation() -> dict:
    return {
        "stated_goal": "根据机器人强化学习项目寻找中科大人工智能导师",
        "project_interpretations": [
            {
                "project_name": "机器人避障",
                "project_summary": "使用PPO训练移动机器人策略",
                "inferred_research_problems": ["序贯决策", "样本效率"],
                "inferred_domains": ["强化学习", "机器人学习"],
                "inferred_methods": ["PPO", "reward shaping"],
                "demonstrated_capabilities": ["PyTorch训练", "仿真实验"],
                "transferable_directions": ["安全强化学习", "多智能体学习"],
                "rationale": "项目包含策略优化、环境建模和实验评估。",
                "confidence": 0.91,
            }
        ],
        "primary_directions": ["机器人学习", "强化学习"],
        "adjacent_directions": ["多智能体系统", "安全强化学习"],
        "domain_codes": ["artificial_intelligence"],
        "methods": ["策略优化", "PPO"],
        "application_domains": ["自主机器人"],
        "search_queries": [
            {
                "query": "robot learning sequential decision making",
                "purpose": "发现不使用强化学习字面词但研究问题相关的导师",
                "preferred_sources": ["ustc_official", "openalex", "arxiv"],
                "expected_signal": "近期论文涉及策略学习或序贯决策",
            }
        ],
        "exclusions": ["只在应用中调用现成模型而无学习算法研究"],
        "uncertainties": ["尚不了解用户的数学基础"],
        "overall_explanation": "项目更接近机器人学习和序贯决策，而非泛人工智能。",
    }


def _assessment() -> dict:
    return {
        "candidate_id": "ustc_faculty_100",
        "overall_relevance": 87,
        "research_topic_fit": 92,
        "method_fit": 88,
        "application_fit": 90,
        "project_background_fit": 84,
        "direction_summary": "近期论文研究安全机器人策略学习。",
        "project_alignment": ["用户的PPO训练经验可迁移到候选人的策略优化研究。"],
        "relevant_papers": [
            {
                "paper_index": 0,
                "relevant": True,
                "actual_direction": "安全机器人强化学习",
                "inferred_topics": ["安全强化学习", "机器人学习"],
                "inferred_methods": ["策略优化", "约束强化学习"],
                "evidence_basis": "摘要明确讨论约束下的机器人策略学习。",
                "project_fit": "PPO和reward shaping经验可以直接迁移。",
                "confidence": 0.94,
            }
        ],
        "preparation_advice": ["补充约束优化和强化学习理论"],
        "gaps": ["缺少真实机器人实验"],
        "recommendation": "方向高度相关，建议先复现其近期安全策略论文。",
        "uncertainty": ["招生状态未知"],
        "evidence_refs": ["ev-model-invented"],
        "confidence": 0.9,
    }


def _screening() -> dict:
    return {
        "decisions": [
            {
                "candidate_id": "ustc_faculty_100",
                "coarse_relevance": 90,
                "keep_for_paper_search": True,
                "likely_overlap": ["机器人策略学习", "强化学习"],
                "reason": "官方方向与用户的PPO机器人项目存在语义重叠。",
                "uncertainty": ["需要用论文确认近期方向"],
            },
            {
                "candidate_id": "ustc_faculty_200",
                "coarse_relevance": 5,
                "keep_for_paper_search": False,
                "likely_overlap": [],
                "reason": "官方方向为材料化学，与用户项目缺少交集。",
                "uncertainty": [],
            },
        ],
        "strategy_summary": "先从官方广召回，再把论文检索预算给语义最相关者。",
    }


def test_model_driven_research_runs_full_workflow_with_audit():
    adapter = SequenceJsonAdapter([_preparation(), _screening(), _assessment()])
    provider = _provider()
    audit = AgenticResearchSession(provider)
    reasoner = StructuredMentorReasoner(adapter, provider, audit)
    official_evidence = EvidenceRecord(
        evidence_id="ev-official",
        candidate_id="ustc_faculty_100",
        source_type="ustc_official_faculty_directory",
        source_uri="https://faculty.ustc.edu.cn/search.jsp",
        title="中科大官方教师记录",
        extracted_fact="中科大官方系统列出测试导师为博士生导师。",
        locator="teacherData[a=100]",
        freshness=EvidenceFreshness.current,
        confidence=0.99,
        metadata={
            "identity_verified": True,
            "mentor_role_verified": True,
            "supports_fields": "affiliation,department,homepage",
        },
    )
    official_result = MentorResearchResult(
        candidates=[
            CandidateMentor(
                candidate_id="ustc_faculty_100",
                mentor_name="测试导师",
                affiliation="中国科学技术大学",
                department="人工智能与数据科学学院",
                homepage="https://faculty.ustc.edu.cn/test/zh_CN/index.htm",
                evidence_refs=["ev-official"],
                source_metadata={
                    "english_name": "Test Mentor",
                    "mentor_role": "博士生导师",
                },
            ),
            CandidateMentor(
                candidate_id="ustc_faculty_200",
                mentor_name="无关导师",
                affiliation="中国科学技术大学",
                department="化学与材料科学学院",
                research_topics=["材料化学"],
                homepage="https://faculty.ustc.edu.cn/unrelated/zh_CN/index.htm",
                evidence_refs=["ev-unrelated"],
            ),
        ],
        evidence=[
            official_evidence,
            EvidenceRecord(
                evidence_id="ev-unrelated",
                candidate_id="ustc_faculty_200",
                source_type="ustc_official_faculty_directory",
                source_uri="https://faculty.ustc.edu.cn/search.jsp",
                title="中科大官方教师记录",
                extracted_fact="官方方向为材料化学。",
                locator="teacherData[a=200]",
                freshness=EvidenceFreshness.current,
                confidence=0.99,
            ),
        ],
        unresolved_candidate_ids=["ustc_faculty_100"],
        source_chain=["ustc_official_faculty", "ustc_official_profile"],
    )
    hit = PaperSearchHit(
        source="openalex",
        title="Safe Policy Learning for Autonomous Robots",
        abstract="We study constrained policy optimization for safe robot learning.",
        authors=["Test Mentor"],
        year=2026,
        venue="Robotics",
        doi="10.1000/test",
        arxiv_id=None,
        openalex_id="W100",
        landing_page_url="https://openalex.org/W100",
        pdf_url=None,
    )
    paper_enricher = AgenticPaperResearchEnricher(
        StaticPaperGateway(hit),
        reasoner,
        audit,
        max_candidates=1,
        max_results_per_source=2,
        max_papers_per_candidate=2,
    )
    tool = AgenticMentorResearchTool(
        internal_rag=EmptyInternalRag(),
        official_source=StaticOfficialSource(official_result),
        paper_enricher=paper_enricher,
        reasoner=reasoner,
        session=audit,
    )
    orchestrator = MentorWorkflowOrchestrator(
        InMemoryStateStore(),
        tool,
        domain_agent=ModelDrivenDomainExpertAgent(reasoner),
        matching_agent=ModelDrivenMatchingAgent(audit),
        research_audit=audit,
    )
    state = orchestrator.create(
        MentorWorkflowRequest(
            message="我想学习人工智能，请根据我的项目推荐中科大导师",
            goal=MentorGoal.find_mentors,
            research_topics=["人工智能"],
            projects=[
                UserProjectInput(
                    name="机器人避障",
                    description="使用PPO和reward shaping训练移动机器人避障策略。",
                    technologies=["PyTorch", "Gymnasium"],
                    outcomes=["完成仿真消融实验"],
                )
            ],
        )
    )

    assert state.status == WorkflowStatus.completed
    assert state.review_decision is not None
    assert state.review_decision.status.value == "PASS"
    assert state.research_audit is not None
    assert state.research_audit.preparation is not None
    assert state.research_audit.preparation.primary_directions[0] == "机器人学习"
    assert state.research_audit.candidate_screening is not None
    assert len(state.research_audit.contexts) == 3
    assert all(
        context.hidden_reasoning_exposed is False
        for context in state.research_audit.contexts
    )
    assert all(trace.mcp_server is False for trace in state.research_audit.tool_trace)
    assert "api_key" not in state.research_audit.model_dump_json()
    # A name-only paper hit may enrich the audit trail but cannot become an
    # authoritative mentor direction without entity disambiguation.
    assert state.candidates == []
    assert state.match_results == []
    assert state.final_result is not None
    assert state.final_result.mentors == []
