from __future__ import annotations

from types import SimpleNamespace

from backend.db.models import Paper, Report, ReportEvidence
from backend.db.repositories import ParsingRepository
from backend.db.types import (
    ProcessedDocumentStatus,
    ReportSourceScope,
    ReportStatus,
    SectionRole,
)
from backend.integrations.llm.openai_compatible import OpenAICompatibleChatModelAdapter
from backend.schemas import ResolvedProviderConfig
from backend.services.reports import (
    COMPRESSED_REMAINDER_START,
    DEFAULT_ANALYSIS_INSTRUCTIONS,
    DEFAULT_REVIEW_ANALYSIS_INSTRUCTIONS,
    ReportGenerationService,
)


def fixture_chat_provider() -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        id=0,
        name="fixture-chat",
        kind="chat",
        provider="fixture",
        model="fixture-chat-model",
        settings={"title": "Generated Fixture Report"},
    )


def report_service(session) -> ReportGenerationService:
    return ReportGenerationService(session, chat_provider=fixture_chat_provider())


VALID_REGULAR_REPORT = """# Reading Report

## Part I: Story & Method

This is a sufficiently detailed regular paper report with method discussion and critique. It explains the research background, the concrete problem, the proposed approach, and the methodological intuition. It distinguishes paper content from critique and includes enough detail to pass a reading-report quality check.

## Part II: Experiments & Findings

This section discusses experiments, findings, baselines, metrics, ablations, and limitations in enough detail. It describes how evidence supports or weakens the paper's claims, identifies missing robustness checks when relevant, and avoids inventing datasets or numerical results beyond the supplied paper body.

## Part III: Summary & Critique

This section summarizes contributions, critiques evidence quality, and suggests follow-up research directions. It includes a higher-level assessment, discusses possible overclaims, and explains how the work could inspire future research while remaining grounded in the supplied content.
"""

VALID_REVIEW_REPORT = """# Review Report

## Part I: Scope & Structure

This section discusses the field scope, taxonomy, review methodology, and coverage quality. It explains the boundaries of the surveyed area, the organizing principles used by the authors, and the evidence from taxonomy figures, section headings, or comparison matrices where available.

## Part II: Comparative Insights

This section compares method families, evidence trends, emerging themes, and gaps. It synthesizes tradeoffs across categories, identifies recurring benchmarks or evaluation issues, and separates well-supported trends from speculative field-level claims.

## Part III: Overall Assessment

This section assesses the review, its limitations, and actionable follow-up reading. It identifies useful frameworks, coverage weaknesses, missing areas, and natural next steps for researchers who want to validate empirical claims by reading original papers.
"""

VALID_CHINESE_REGULAR_REPORT = """# 阅读报告

## Part I: Story & Method

这是一份足够详细的中文阅读报告，讨论论文的研究背景、核心问题、方法设计和关键机制。报告区分论文内容、合理推断和批判性评价，并围绕方法为什么可能有效展开说明，避免编造论文没有提供的数据、实验或结论。它会说明研究问题来自哪里、为什么值得解决、作者提出的方法如何组织，以及关键技术主张是否能够从正文中的方法描述、算法流程、图表或实验结果中得到支持。对于论文没有充分说明的假设，报告会明确指出这些内容属于解释性推断而不是作者原文结论。

## Part II: Experiments & Findings

本节讨论实验设置、主要发现、基线比较、评价指标、消融分析和局限性。报告说明哪些证据支持作者的主张，哪些结论仍然缺少足够支撑，并指出如果论文没有提供鲁棒性分析、误差分析或更广泛任务验证，这些缺口应被明确标注。它还会关注实验任务是否覆盖核心应用场景，指标是否能够衡量论文声称解决的问题，基线是否公平充分，以及不同实验结果之间是否存在异常或需要额外解释的现象。

## Part III: Summary & Critique

本节总结论文贡献，评价证据强度，并提出后续研究方向。报告从研究价值、潜在风险、过度主张和可迁移性等角度进行分析，同时保持内容扎根于给定论文正文，不添加论文之外的事实。它会把作者明确声称的贡献、读者可以合理推断的影响、以及报告本身的批判性判断分开表述，并说明哪些后续实验、理论分析或应用验证最适合作为自然延伸。
"""


class RecordingAdapter:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or [VALID_REGULAR_REPORT]
        self.messages: list[list[dict]] = []

    def generate_text(self, provider: ResolvedProviderConfig, messages: list[dict]) -> str:
        self.messages.append(messages)
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class FailingAdapter:
    def generate_text(self, provider: ResolvedProviderConfig, messages: list[dict]) -> str:
        raise TimeoutError("Request timed out.")


def service_with_adapter(session, adapter: RecordingAdapter) -> ReportGenerationService:
    return ReportGenerationService(session, chat_provider=fixture_chat_provider(), adapters={"fixture": adapter})


def create_processed_paper(session):
    paper = Paper(title="Report Paper")
    session.add(paper)
    session.flush()
    repo = ParsingRepository(session)
    job = repo.create_parse_job(paper.id, status="succeeded", strategy="fixture")
    parsed = repo.create_parsed_document(paper.id, job.id, "fixture", plain_text="text", markdown_content="text")
    processed = repo.create_processed_document(
        paper.id,
        parsed.id,
        job.id,
        status=ProcessedDocumentStatus.ready.value,
        content_text="text",
        content_markdown="text",
    )
    alpha = repo.add_chunk(processed.id, "alpha", 1, "retrieval evidence alpha", role=SectionRole.body.value)
    beta = repo.add_chunk(processed.id, "beta", 2, "citation reference beta", role=SectionRole.reference.value)
    session.commit()
    return paper, processed, [alpha, beta]


def test_generate_report_fails_cleanly_without_processed_document(session):
    paper = Paper(title="Unprocessed")
    session.add(paper)
    session.commit()

    result = report_service(session).generate_report(paper.id)

    assert result.status == ReportStatus.failed.value
    report = session.get(Report, result.report_id)
    assert "No processed document" in report.error_message
    assert "No processed document" in result.error_message


def test_fixture_llm_generates_report_and_persists_evidence(session):
    paper, _, chunks = create_processed_paper(session)

    result = report_service(session).generate_report(
        paper.id,
        instructions="Discuss retrieval evidence.",
        source_scope=ReportSourceScope.selected_chunks.value,
        selected_chunk_ids=[chunks[0].id],
    )

    assert result.status == ReportStatus.succeeded.value
    assert "Generated Fixture Report" in result.markdown_content
    evidence = session.query(ReportEvidence).one()
    assert evidence.chunk_id == chunks[0].id
    assert evidence.paper_id == paper.id
    assert "retrieval evidence" in evidence.quote_text


def test_retrieval_selects_evidence_chunks(session):
    paper, _, _ = create_processed_paper(session)

    result = report_service(session).generate_report(paper.id, instructions="citation reference", limit=1)

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert len(report.evidence) == 1
    assert "citation reference" in report.evidence[0].quote_text


def test_full_document_scope_uses_ordered_chunks(session):
    paper, _, chunks = create_processed_paper(session)

    result = report_service(session).generate_report(paper.id, source_scope=ReportSourceScope.full_document.value, limit=2)

    report = session.get(Report, result.report_id)
    assert [evidence.chunk_id for evidence in report.evidence] == [chunks[0].id, chunks[1].id]


def test_openai_compatible_chat_adapter_uses_injected_client():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="model output"))])
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return response

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = ResolvedProviderConfig(
        id=1,
        name="chat",
        kind="chat",
        provider="openai_compatible",
        model="model",
        temperature=0.2,
        settings={
            "max_tokens": 100,
            "timeout": 30,
            "extra_body": {"thinking": {"type": "disabled"}},
            "response_format": {"type": "json_object"},
        },
    )

    text = OpenAICompatibleChatModelAdapter(client).generate_text(provider, [{"role": "user", "content": "hi"}])

    assert text == "model output"
    assert calls[0]["model"] == "model"
    assert calls[0]["max_tokens"] == 100
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_generate_reading_report_fails_without_ready_processed_document(session):
    paper = Paper(title="Unprocessed")
    session.add(paper)
    session.commit()

    result = report_service(session).generate_reading_report(paper.id, output_language="English")

    assert result.status == ReportStatus.failed.value
    assert "No ready processed document" in session.get(Report, result.report_id).error_message
    assert "No ready processed document" in result.error_message


def test_generate_reading_report_uses_default_report_language(session):
    paper, _, _ = create_processed_paper(session)
    adapter = RecordingAdapter(["{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}", VALID_CHINESE_REGULAR_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id)

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.metadata_json["output_language"] == "中文"
    assert report.metadata_json["validation"]["checks"]["language"] is True
    assert "Output language: 中文" in adapter.messages[-1][1]["content"]


def test_generate_reading_report_uses_report_language_setting(monkeypatch, session):
    monkeypatch.setenv("PAPER_CLAW_REPORT_LANGUAGE", "English")
    from backend.settings import clear_settings_cache

    clear_settings_cache()
    paper, _, _ = create_processed_paper(session)
    adapter = RecordingAdapter(["{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}", VALID_REGULAR_REPORT])
    try:
        result = service_with_adapter(session, adapter).generate_reading_report(paper.id)
    finally:
        clear_settings_cache()

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.metadata_json["output_language"] == "English"
    assert "Output language: English" in adapter.messages[-1][1]["content"]


def test_generate_reading_report_output_language_overrides_default(session):
    paper, _, _ = create_processed_paper(session)
    adapter = RecordingAdapter(["{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}", VALID_REGULAR_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.metadata_json["output_language"] == "English"
    assert report.metadata_json["validation"]["checks"]["language"] is True
    assert "Output language: English" in adapter.messages[-1][1]["content"]


def test_chinese_language_validation_regenerates_english_output(session):
    paper, _, _ = create_processed_paper(session)
    adapter = RecordingAdapter([
        "{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}",
        VALID_REGULAR_REPORT,
        VALID_CHINESE_REGULAR_REPORT,
    ])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="中文")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.metadata_json["regeneration"] == {"attempted": True, "used": True}
    assert report.metadata_json["validation_attempts"][0]["checks"]["language"] is False
    assert report.metadata_json["validation"]["checks"]["language"] is True



def test_generate_reading_report_uses_processed_body_and_records_metadata(session):
    paper, processed, _ = create_processed_paper(session)
    adapter = RecordingAdapter(["{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}", VALID_REGULAR_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(
        paper.id,
        orchestrator_instruction="Language: English. Focus on methods.",
        output_language="English",
    )

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.processed_document_id == processed.id
    assert report.metadata_json["processed_document"]["body_source"] == "processed.content_text"
    assert report.metadata_json["context_strategy"] == "full_body"
    assert report.metadata_json["validation"]["passed"] is True
    assert report.json_content["instruction_type"] == "regular"
    final_prompt = adapter.messages[-1][1]["content"]
    assert "Language: English. Focus on methods." in final_prompt
    assert DEFAULT_ANALYSIS_INSTRUCTIONS in final_prompt
    assert "retrieval evidence alpha" not in final_prompt


def test_generate_reading_report_returns_error_message_when_llm_fails(session):
    paper, _, _ = create_processed_paper(session)
    paper.title = "A Survey of Multi-Agent Collaboration"

    result = service_with_adapter(session, FailingAdapter()).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.failed.value
    assert result.error_message == "Request timed out."
    assert report.error_message == "Request timed out."
    assert result.json_content == {"error": "Request timed out."}


def test_generate_reading_report_reconstructs_sections_without_references(session):
    paper, processed, _ = create_processed_paper(session)
    processed.content_text = None
    repo = ParsingRepository(session)
    repo.add_section(processed.id, 1, role=SectionRole.body.value, cleaned_text="Body section text")
    repo.add_section(processed.id, 2, role=SectionRole.reference.value, cleaned_text="Reference section text")
    session.commit()
    adapter = RecordingAdapter(["{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}", VALID_REGULAR_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.metadata_json["processed_document"]["body_source"] == "document_sections.cleaned_text"
    final_prompt = adapter.messages[-1][1]["content"]
    assert "Body section text" in final_prompt
    assert "Reference section text" not in final_prompt


def test_review_rule_selects_review_instructions(session):
    paper, _, _ = create_processed_paper(session)
    paper.title = "A Survey of Retrieval Augmented Generation"
    paper.abstract = "We survey recent advances."
    adapter = RecordingAdapter([VALID_REVIEW_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.json_content["instruction_type"] == "review_survey"
    assert report.metadata_json["classification"]["source"] == "rule"
    assert DEFAULT_REVIEW_ANALYSIS_INSTRUCTIONS in adapter.messages[-1][1]["content"]


def test_classifier_fallback_selects_review_when_rule_does_not_match(session):
    paper, _, _ = create_processed_paper(session)
    paper.abstract = "This paper organizes prior work into several groups and compares their assumptions."
    adapter = RecordingAdapter(["{\"type\":\"review_survey\",\"confidence\":0.91,\"reason\":\"broad literature synthesis\"}", VALID_REVIEW_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.json_content["instruction_type"] == "review_survey"
    assert report.metadata_json["classification"]["source"] == "classifier"


def test_weak_review_terms_fall_through_to_classifier(session):
    paper, _, _ = create_processed_paper(session)
    paper.title = "A Taxonomy of Failure Modes for Vision Models"
    paper.abstract = "We provide an overview of observed errors and recent advances that motivate our benchmark."
    adapter = RecordingAdapter(["{\"type\":\"regular\",\"confidence\":0.82,\"reason\":\"benchmark paper with taxonomy section\"}", VALID_REGULAR_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.json_content["instruction_type"] == "regular"
    assert report.metadata_json["classification"]["source"] == "classifier"


def test_invalid_classifier_defaults_to_regular(session):
    paper, _, _ = create_processed_paper(session)
    adapter = RecordingAdapter(["not json", VALID_REGULAR_REPORT])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.json_content["instruction_type"] == "regular"
    assert report.metadata_json["classification"]["source"] == "default"


def test_large_body_uses_compressed_remainder(monkeypatch, session):
    paper, processed, _ = create_processed_paper(session)
    processed.content_text = "one two three four five six seven eight nine ten eleven twelve"
    monkeypatch.setattr("backend.services.reports.FULL_BODY_TOKEN_LIMIT", 5)
    monkeypatch.setattr("backend.services.reports.VERBATIM_PREFIX_TOKEN_LIMIT", 3)
    monkeypatch.setattr("backend.services.reports.COMPRESSION_CHUNK_TOKEN_LIMIT", 4)
    adapter = RecordingAdapter([
        "{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}",
        "compressed remainder",
        "compressed remainder",
        VALID_REGULAR_REPORT,
    ])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.metadata_json["context_strategy"] == "prefix_plus_compressed_remainder"
    assert report.metadata_json["compression"]["used"] is True
    assert COMPRESSED_REMAINDER_START in adapter.messages[-1][1]["content"]


def test_validation_failure_regenerates_once(session):
    paper, _, _ = create_processed_paper(session)
    adapter = RecordingAdapter([
        "{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}",
        "too short",
        VALID_REGULAR_REPORT,
    ])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.succeeded.value
    assert report.metadata_json["regeneration"] == {"attempted": True, "used": True}
    assert len(report.metadata_json["validation_attempts"]) == 2


def test_validation_failure_after_regeneration_persists_failed_report(session):
    paper, _, _ = create_processed_paper(session)
    adapter = RecordingAdapter([
        "{\"type\":\"regular\",\"confidence\":0.9,\"reason\":\"method paper\"}",
        "too short",
        "still short",
    ])

    result = service_with_adapter(session, adapter).generate_reading_report(paper.id, output_language="English")

    report = session.get(Report, result.report_id)
    assert result.status == ReportStatus.failed.value
    assert "validation failed" in report.error_message
    assert "validation failed" in result.error_message
    assert report.metadata_json["regeneration"] == {"attempted": True, "used": False}
