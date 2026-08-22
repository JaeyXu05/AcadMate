from __future__ import annotations

from backend.mentor_workflow.agents.domain_research import MentorResearchAgent
from backend.mentor_workflow.orchestrator import MentorWorkflowOrchestrator
from backend.mentor_workflow.research_tools import UstcMentorResearchTool
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    EvidenceFreshness,
    EvidenceRecord,
    IntentPacket,
    MentorGoal,
    MentorResearchResult,
    MentorWorkflowRequest,
    ReviewStatus,
    WorkflowStatus,
)
from backend.mentor_workflow.state_store import InMemoryStateStore
from backend.mentor_workflow.ustc_sources import (
    MissingDirectionPaperEnricher,
    PaperSearchHit,
    PaperSearchPage,
    UstcFacultyRecord,
    UstcFacultySearchPage,
    UstcOfficialMentorSource,
    parse_ustc_faculty_profile,
)


def _intent(**updates) -> IntentPacket:
    payload = {
        "trace_id": "trace-ustc",
        "goal": MentorGoal.find_mentors,
        "research_topics": ["multi-agent reinforcement learning"],
        "methods": ["reinforcement learning"],
        "application_domains": [],
        "confidence": 0.9,
    }
    payload.update(updates)
    return IntentPacket.model_validate(payload)


def _faculty_record(**updates) -> UstcFacultyRecord:
    payload = {
        "faculty_id": "1364",
        "name": "张辉",
        "english_name": "Hui Zhang",
        "college": "计算机科学与技术学院",
        "unit": "计算机科学与技术学院",
        "academic_title": "副教授",
        "graduate_tutor_role": "硕士生导师",
        "doctoral_tutor_role": "",
        "profile_url": "https://faculty.ustc.edu.cn/zhanghui/zh_CN/index.htm",
    }
    payload.update(updates)
    return UstcFacultyRecord(**payload)


class FakeFacultyGateway:
    def __init__(self, records: list[UstcFacultyRecord]) -> None:
        self.records = records
        self.calls: list[dict] = []

    def search(self, **kwargs) -> UstcFacultySearchPage:
        self.calls.append(kwargs)
        return UstcFacultySearchPage(
            records=list(self.records),
            total_pages=1,
            total_records=len(self.records),
        )


class FakeProfileFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        return self.pages[url]


class FakePaperGateway:
    def __init__(self, hits: list[PaperSearchHit]) -> None:
        self.hits = hits
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
        return PaperSearchPage(hits=list(self.hits), warnings=[])


class StaticInternalRag:
    def __init__(self, result: MentorResearchResult) -> None:
        self.result = result
        self.calls = 0

    def retrieve(self, _intent, _judgements) -> MentorResearchResult:
        self.calls += 1
        return self.result.model_copy(deep=True)


class CountingOfficialSource:
    def __init__(self, result: MentorResearchResult) -> None:
        self.result = result
        self.calls = 0

    def search(self, _intent, _judgements) -> MentorResearchResult:
        self.calls += 1
        return self.result.model_copy(deep=True)


class PassThroughEnricher:
    def __init__(self) -> None:
        self.calls = 0

    def enrich(self, result, _intent, _judgements) -> MentorResearchResult:
        self.calls += 1
        return result


def _verified_internal_result() -> MentorResearchResult:
    evidence = EvidenceRecord(
        evidence_id="ev-internal",
        candidate_id="ustc_faculty_1364",
        source_type="internal_ustc_rag",
        source_uri="rag://ustc/faculty/1364",
        title="Curated USTC mentor record",
        extracted_fact="张辉是中科大导师，研究多智能体强化学习。",
        locator="mentor:1364",
        freshness=EvidenceFreshness.current,
        confidence=0.99,
        metadata={
            "identity_verified": True,
            "mentor_role_verified": True,
            "supports_fields": ("affiliation,department,research_topics,homepage"),
        },
    )
    return MentorResearchResult(
        candidates=[
            CandidateMentor(
                candidate_id="ustc_faculty_1364",
                mentor_name="张辉",
                affiliation="中国科学技术大学",
                department="计算机科学与技术学院",
                research_topics=["multi-agent reinforcement learning"],
                homepage="https://faculty.ustc.edu.cn/zhanghui/zh_CN/index.htm",
                evidence_refs=[evidence.evidence_id],
            )
        ],
        evidence=[evidence],
        source_chain=["internal_ustc_rag"],
    )


def test_profile_parser_extracts_role_direction_and_recruitment():
    profile = parse_ustc_faculty_profile(
        """
        <html><body>
        <div>博士生导师 硕士生导师</div>
        <h2>研究方向 Research Focus</h2>
        <ul>
          <li>多智能体强化学习</li>
          <li>图神经网络</li>
        </ul>
        <p>欢迎对强化学习感兴趣的博士生和本科生联系。</p>
        </body></html>
        """
    )

    assert profile.mentor_role_verified
    assert profile.research_topics == ["多智能体强化学习", "图神经网络"]
    assert profile.recruitment_status == ("欢迎对强化学习感兴趣的博士生和本科生联系。")


def test_official_source_uses_faculty_search_and_profile_evidence():
    faculty = _faculty_record()
    gateway = FakeFacultyGateway([faculty])
    fetcher = FakeProfileFetcher(
        {
            faculty.profile_url: """
                <div>硕士生导师</div>
                <h2>研究方向</h2>
                <p>multi-agent reinforcement learning、graph learning</p>
            """
        }
    )
    source = UstcOfficialMentorSource(
        gateway,
        fetcher,
        max_queries=1,
    )

    result = source.search(_intent(), [])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.candidate_id == "ustc_faculty_1364"
    assert candidate.affiliation == "中国科学技术大学"
    assert candidate.department == "计算机科学与技术学院"
    assert candidate.research_topics == [
        "multi-agent reinforcement learning",
        "graph learning",
    ]
    assert candidate.homepage == faculty.profile_url
    assert result.unresolved_candidate_ids == []
    assert {record.source_type for record in result.evidence} == {
        "ustc_official_faculty_directory",
        "ustc_official_faculty_profile",
    }
    identity = result.evidence[0]
    assert identity.metadata["identity_verified"] is True
    assert identity.metadata["mentor_role_verified"] is True
    assert gateway.calls[0]["research_direction"] == (
        "multi-agent reinforcement learning"
    )


def test_official_source_filters_non_mentor_faculty_records():
    faculty = _faculty_record(
        graduate_tutor_role="",
        doctoral_tutor_role="",
    )
    source = UstcOfficialMentorSource(
        FakeFacultyGateway([faculty]),
        FakeProfileFetcher({faculty.profile_url: "<p>教授</p>"}),
        max_queries=1,
    )

    result = source.search(_intent(), [])

    assert result.candidates == []
    assert result.evidence == []


def test_missing_official_direction_is_filled_from_attributable_papers():
    faculty = _faculty_record()
    official = UstcOfficialMentorSource(
        FakeFacultyGateway([faculty]),
        FakeProfileFetcher(
            {faculty.profile_url: "<div>硕士生导师</div><p>暂无内容</p>"}
        ),
        max_queries=1,
    ).search(_intent(), [])
    assert official.unresolved_candidate_ids == ["ustc_faculty_1364"]
    paper_gateway = FakePaperGateway(
        [
            PaperSearchHit(
                source="openalex",
                title="Verified Multi-Agent Reinforcement Learning",
                abstract=(
                    "A study of multi-agent reinforcement learning and "
                    "reinforcement learning."
                ),
                authors=["Hui Zhang", "Coauthor"],
                year=2026,
                venue="Conference",
                doi="10.1000/ustc-demo",
                arxiv_id=None,
                openalex_id="W123",
                landing_page_url="https://openalex.org/W123",
                pdf_url=None,
            )
        ]
    )
    enricher = MissingDirectionPaperEnricher(paper_gateway)

    enriched = enricher.enrich(official, _intent(), [])

    candidate = enriched.candidates[0]
    assert candidate.research_topics == [
        "multi-agent reinforcement learning",
        "reinforcement learning",
    ]
    assert candidate.publications == ["Verified Multi-Agent Reinforcement Learning"]
    assert enriched.unresolved_candidate_ids == []
    assert any(
        record.source_type == "openalex_paper_metadata" for record in enriched.evidence
    )
    assert {call[1] for call in paper_gateway.calls} == {"arxiv", "openalex"}


def test_paper_fallback_rejects_results_from_a_different_author():
    faculty = _faculty_record()
    official = UstcOfficialMentorSource(
        FakeFacultyGateway([faculty]),
        FakeProfileFetcher({faculty.profile_url: "<div>硕士生导师</div>"}),
        max_queries=1,
    ).search(_intent(), [])
    enricher = MissingDirectionPaperEnricher(
        FakePaperGateway(
            [
                PaperSearchHit(
                    source="openalex",
                    title="Multi-Agent Reinforcement Learning",
                    abstract="multi-agent reinforcement learning",
                    authors=["Different Author"],
                    year=2026,
                    venue=None,
                    doi=None,
                    arxiv_id=None,
                    openalex_id="W999",
                    landing_page_url="https://openalex.org/W999",
                    pdf_url=None,
                )
            ]
        )
    )

    enriched = enricher.enrich(official, _intent(), [])

    assert enriched.candidates[0].research_topics == []
    assert enriched.unresolved_candidate_ids == ["ustc_faculty_1364"]
    assert all(
        record.source_type != "openalex_paper_metadata" for record in enriched.evidence
    )


def test_complete_internal_rag_result_skips_all_external_sources():
    internal = StaticInternalRag(_verified_internal_result())
    official = CountingOfficialSource(MentorResearchResult())
    enricher = PassThroughEnricher()
    tool = UstcMentorResearchTool(
        internal_rag=internal,
        official_source=official,  # type: ignore[arg-type]
        paper_enricher=enricher,  # type: ignore[arg-type]
    )

    result = MentorResearchAgent(tool).run(_intent(), [], [])

    assert result.candidates[0].mentor_name == "张辉"
    assert result.source_chain == ["internal_ustc_rag"]
    assert internal.calls == 1
    assert official.calls == 0
    assert enricher.calls == 0


def test_partial_internal_rag_merges_with_official_candidate():
    internal_result = _verified_internal_result()
    internal_result.candidates[0].research_topics = []
    internal_result.candidates[0].missing_fields = ["research_topics"]
    internal_result.unresolved_candidate_ids = ["ustc_faculty_1364"]
    official_result = _verified_internal_result()
    official_result.source_chain = ["ustc_official_faculty"]
    internal = StaticInternalRag(internal_result)
    official = CountingOfficialSource(official_result)
    tool = UstcMentorResearchTool(
        internal_rag=internal,
        official_source=official,  # type: ignore[arg-type]
        paper_enricher=PassThroughEnricher(),  # type: ignore[arg-type]
    )

    result = MentorResearchAgent(tool).run(_intent(), [], [])

    assert len(result.candidates) == 1
    assert result.candidates[0].research_topics == [
        "multi-agent reinforcement learning"
    ]
    assert result.source_chain == [
        "internal_ustc_rag",
        "ustc_official_faculty",
    ]
    assert official.calls == 1


def test_ustc_official_workflow_completes_with_verified_profile():
    faculty = _faculty_record()
    official = UstcOfficialMentorSource(
        FakeFacultyGateway([faculty]),
        FakeProfileFetcher(
            {
                faculty.profile_url: """
                    <div>硕士生导师</div>
                    <h2>研究方向</h2>
                    <p>multi-agent reinforcement learning</p>
                """
            }
        ),
        max_queries=1,
    )
    tool = UstcMentorResearchTool(
        internal_rag=StaticInternalRag(MentorResearchResult()),
        official_source=official,
        paper_enricher=PassThroughEnricher(),  # type: ignore[arg-type]
    )

    state = MentorWorkflowOrchestrator(InMemoryStateStore(), tool).create(
        MentorWorkflowRequest(
            message="帮我找中科大多智能体强化学习导师",
            research_topics=["multi-agent reinforcement learning"],
            methods=["reinforcement learning"],
        ),
        trace_id="trace-ustc-integration",
    )

    assert state.status == WorkflowStatus.completed
    assert state.review_decision is not None
    assert state.review_decision.status == ReviewStatus.pass_
    assert state.candidates[0].affiliation == "中国科学技术大学"
    assert state.final_result is not None
    assert state.final_result.mentors[0].candidate.mentor_name == "张辉"
