from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session
import tiktoken

from backend.db.models import DocumentChunk, DocumentSection, Paper, ProcessedDocument
from backend.db.repositories import ReportRepository
from backend.db.types import EvidenceType, ProcessedDocumentStatus, ReportSourceScope, ReportStatus, ReportType, SectionRole
from backend.integrations.llm import ChatModelAdapter, FixtureChatModelAdapter, OpenAICompatibleChatModelAdapter
from backend.schemas import ReportGenerationResult, ResolvedProviderConfig, RetrievedChunk
from backend.services.providers import chat_provider_from_settings
from backend.settings import get_settings
from backend.services.retrieval import RetrievalService


DEFAULT_ANALYSIS_INSTRUCTIONS = (
    "Please read the paper thoroughly and generate a structured, critical reading report. "
    "Be specific about methods, experimental design, and key conclusions — avoid vague summaries.\n\n"

    "Before writing the report, first identify the paper type: "
    "method paper, benchmark paper, dataset paper, system paper, application paper, or theoretical paper. "
    "Adapt the emphasis of the report accordingly.\n\n"

    "Output the report in exactly three sections:\n\n"

    "## Part I: Story & Method\n\n"

    "1. Research background and application context:\n"
    "   - What specific problem does the paper address? Which research direction?\n"
    "   - Why is this problem important (practical or theoretical significance)?\n"
    "   - What evidence in the paper supports this motivation? Refer to the relevant section, paragraph, figure, or example if possible.\n\n"

    "2. Core problem definition:\n"
    "   - What are the limitations of existing methods? Be specific, not vague.\n"
    "   - What is the key challenge the authors aim to solve?\n"
    "   - Are these limitations directly supported by the paper's discussion, experiments, or cited evidence?\n\n"

    "3. Method and approach:\n"
    "   - What core method/framework does the paper propose? Describe the overall structure clearly.\n"
    "   - What are the key innovations? Enumerate them.\n"
    "   - What is the essential difference from prior work?\n"
    "   - For each major technical claim, indicate the supporting evidence from the paper, such as a method section, algorithm, figure, table, or experimental result.\n\n"

    "4. Method intuition and mechanism:\n"
    "   - Why might this method work? What is the underlying intuition or principle?\n"
    "   - Does it rely on certain assumptions? Are these assumptions reasonable?\n"
    "   - Clearly distinguish between what the authors explicitly state and your own interpretation.\n\n"

    "## Part II: Experiments & Findings\n\n"

    "1. Experimental setup:\n"
    "   - Which datasets/tasks were used and why?\n"
    "   - Are the baseline comparisons sufficient and appropriate?\n"
    "   - Do the evaluation metrics match the task objectives?\n"
    "   - Indicate where these details appear in the paper, such as experiment setup sections, tables, or appendices.\n\n"

    "2. Experimental results:\n"
    "   - What are the main results? Summarize trends, not just numbers.\n"
    "   - In which scenarios does the method perform best/worst?\n"
    "   - Support the analysis with specific evidence from tables, figures, or reported results.\n\n"

    "3. Key analysis:\n"
    "   - What do ablation studies reveal? Which components matter most?\n"
    "   - Any anomalous results or noteworthy phenomena?\n"
    "   - Are conclusions sufficiently supported by the experiments?\n"
    "   - If the paper lacks ablation studies, robustness tests, or error analysis, explicitly state this.\n\n"

    "4. Limitations from an experimental perspective:\n"
    "   - Are there design flaws or biases in the experiments?\n"
    "   - Are there important scenarios not covered?\n"
    "   - Which limitations are acknowledged by the authors, and which are your own critique?\n\n"

    "## Part III: Summary & Critique\n\n"

    "1. Authors' conclusions:\n"
    "   - What are the main conclusions? How do the authors evaluate their method?\n"
    "   - Distinguish clearly between the authors' explicit claims and your own assessment.\n\n"

    "2. Your summary:\n"
    "   - Summarize the core contributions at a higher level in 1–3 points.\n"
    "   - Explain why these contributions matter for the relevant research area.\n\n"

    "3. Critical analysis:\n"
    "   - What are the main limitations in method, assumptions, or experiments?\n"
    "   - Are there potential risks, overclaims, or misleading conclusions?\n"
    "   - If the paper does not provide enough evidence for a claim, explicitly say that the evidence is insufficient.\n\n"

    "4. Further reflection:\n"
    "   - How could this work be improved?\n"
    "   - Could it transfer to other problems or domains?\n\n"

    "5. Research-oriented reflection:\n"
    "   - How can this paper inspire a new research problem?\n"
    "   - What assumptions could be challenged?\n"
    "   - What parts of the method or evaluation can be reused?\n"
    "   - What would be a natural follow-up paper?\n\n"

    "Additional requirements:\n"
    "1. Distinguish clearly between paper content, reasonable inference, and your own critique.\n"
    "2. For important claims, cite supporting evidence from the paper, such as section, figure, table, experiment, or ablation result.\n"
    "3. If the paper does not provide enough evidence for a claim, explicitly state that the evidence is insufficient.\n"
    "4. Do not invent datasets, baselines, metrics, results, or limitations that are not present in the paper.\n\n"

    "Requirements: synthesize and explain rather than recite; use structured descriptions "
    "for key methods; aim for research reading notes quality, not a simple abstract."
)

DEFAULT_REVIEW_ANALYSIS_INSTRUCTIONS = (
    "Please analyze this review or survey paper and generate a structured synthesis report. "
    "Focus on how the field is organized, what comparison axes the paper uses, and where the major gaps remain.\n\n"

    "Before writing the report, first identify the type of review: "
    "systematic review, narrative review, taxonomy survey, benchmark-oriented survey, application-oriented survey, or position-style review. "
    "Adapt the emphasis of the report accordingly.\n\n"

    "Output the report in exactly three sections:\n\n"

    "## Part I: Scope & Structure\n\n"

    "1. Field scope:\n"
    "   - What problem space or research area does the review cover?\n"
    "   - What boundaries or inclusion assumptions can be inferred?\n"
    "   - What evidence in the paper supports this scope? Refer to the introduction, scope statement, taxonomy figure, or paper selection criteria if available.\n\n"

    "2. Taxonomy and organization:\n"
    "   - How does the paper divide the literature into categories, paradigms, or stages?\n"
    "   - What comparison axes or organizing principles are most important?\n"
    "   - Is the taxonomy explanatory, or does it mainly list papers?\n"
    "   - Support the analysis with specific evidence from taxonomy tables, figures, section headings, or comparison matrices.\n\n"

    "3. Coverage quality:\n"
    "   - Which subareas, tasks, datasets, or methods receive the most emphasis?\n"
    "   - Are there obvious blind spots or underdeveloped areas in the coverage?\n"
    "   - Are top venues, representative works, and recent papers sufficiently covered?\n"
    "   - Distinguish between limitations acknowledged by the review and your own critique.\n\n"

    "4. Review methodology:\n"
    "   - How were papers selected, if the review explains this?\n"
    "   - Is the timeline of the field clear?\n"
    "   - Are the categories mutually exclusive and collectively exhaustive?\n"
    "   - If the review does not explain its search strategy, inclusion criteria, or selection process, explicitly state this.\n\n"

    "## Part II: Comparative Insights\n\n"

    "1. Method families and tradeoffs:\n"
    "   - What are the main families of methods discussed, and how do they differ?\n"
    "   - What strengths and weaknesses recur across categories?\n"
    "   - Use the paper's tables, figures, or section-level comparisons as supporting evidence where possible.\n\n"

    "2. Evidence and evaluation trends:\n"
    "   - What experimental patterns, benchmarks, datasets, or evaluation habits appear repeatedly?\n"
    "   - Are there common methodological problems or comparability issues?\n"
    "   - Which claims are supported by accumulated evidence, and which are mainly speculative or opinion-based?\n\n"

    "3. Emerging themes:\n"
    "   - What trends, open problems, or future directions stand out?\n"
    "   - Which claims are well supported versus more speculative?\n"
    "   - Are the future directions specific and actionable, or broad and generic?\n\n"

    "## Part III: Overall Assessment\n\n"

    "1. Main takeaways:\n"
    "   - What is the most useful high-level synthesis a reader should retain?\n"
    "   - Summarize the field-level structure in a way that could help a researcher quickly understand the area.\n\n"

    "2. Strengths of the review itself:\n"
    "   - What does this review do especially well in organization, comparison, or insight?\n"
    "   - Which taxonomy, comparison table, or conceptual framework is most useful?\n\n"

    "3. Limitations of the review itself:\n"
    "   - Where is the review incomplete, biased, too shallow, outdated, or otherwise constrained?\n"
    "   - Are there important missing papers, tasks, datasets, or evaluation dimensions?\n"
    "   - If the paper does not provide enough evidence for a field-level claim, explicitly say that the evidence is insufficient.\n\n"

    "4. Actionable follow-up:\n"
    "   - What should a researcher read, investigate, or validate next after this review?\n"
    "   - What subareas deserve deeper reading?\n"
    "   - What empirical claims should be checked by looking at the original papers?\n\n"

    "5. Research-oriented reflection:\n"
    "   - How can this review inspire a new research problem?\n"
    "   - What assumptions in the reviewed field could be challenged?\n"
    "   - What parts of the taxonomy, comparison axes, or evaluation framework can be reused?\n"
    "   - What would be a natural follow-up survey, benchmark, or research paper?\n\n"

    "Additional requirements:\n"
    "1. Distinguish clearly between paper content, reasonable inference, and your own critique.\n"
    "2. For important claims, cite supporting evidence from the paper, such as section, figure, table, comparison matrix, or surveyed evidence.\n"
    "3. If the paper does not provide enough evidence for a claim, explicitly state that the evidence is insufficient.\n"
    "4. Do not invent papers, datasets, benchmarks, methods, trends, or limitations that are not present in the review paper.\n\n"

    "Requirements: synthesize across the surveyed literature rather than treating the paper like a single-method article. "
    "Emphasize taxonomy, comparison, trends, gaps, and research opportunities."
)

REPORT_TOKEN_ENCODING = "cl100k_base"
FULL_BODY_TOKEN_LIMIT = 150_000
VERBATIM_PREFIX_TOKEN_LIMIT = 130_000
COMPRESSION_CHUNK_TOKEN_LIMIT = 40_000
COMPRESSED_SUMMARY_TOKEN_LIMIT = 30_000
COMPRESSED_REMAINDER_START = "<COMPRESSED_SECONDARY_EVIDENCE>"
COMPRESSED_REMAINDER_END = "</COMPRESSED_SECONDARY_EVIDENCE>"
_READING_REPORT_VERSION = "reading_report_full_body_v1"
_REVIEW_RULE_PATTERNS = (
    r"\bsystematic review\b",
    r"\bliterature review\b",
    r"\bscoping review\b",
    r"\bmeta-analysis\b",
    r"\bmeta analysis\b",
    r"\bsurvey paper\b",
    r"\breview paper\b",
    r"\ba survey of\b",
    r"\ba review of\b",
    r"\bcomprehensive survey\b",
    r"\bcomprehensive review\b",
    r"\bwe survey\b",
    r"\bwe review\b",
    r"\bthis survey\b",
    r"\bthis review\b",
    r"文献综述",
    r"系统综述",
    r"综述论文",
)
_REVIEW_FALSE_POSITIVES = ("peer review", "under review", "reviewer")


@dataclass(frozen=True)
class ReportClassificationResult:
    instruction_type: Literal["regular", "review_survey"]
    source: Literal["rule", "classifier", "default"]
    confidence: float | None
    reason: str
    matched_signal: str | None = None


@dataclass(frozen=True)
class ReportBodyContext:
    text: str
    token_count: int
    strategy: Literal["full_body", "prefix_plus_compressed_remainder"]
    prefix_token_count: int | None = None
    remainder_token_count: int | None = None
    compressed_remainder_token_count: int | None = None
    compression_chunk_count: int = 0


@dataclass(frozen=True)
class ReportValidationResult:
    passed: bool
    issues: list[str]
    checks: dict[str, bool | str]


class ReportGenerationService:
    def __init__(
        self,
        session: Session,
        *,
        retrieval_service: RetrievalService | None = None,
        adapters: dict[str, ChatModelAdapter] | None = None,
        chat_provider: ResolvedProviderConfig | None = None,
    ) -> None:
        self.session = session
        self.retrieval_service = retrieval_service or RetrievalService(session)
        self.chat_provider = chat_provider
        self.adapters = adapters or {
            "fixture": FixtureChatModelAdapter(),
            "openai_compatible": OpenAICompatibleChatModelAdapter(),
            "openai": OpenAICompatibleChatModelAdapter(),
        }
        self.encoding = tiktoken.get_encoding(REPORT_TOKEN_ENCODING)

    def generate_reading_report(
        self,
        paper_id: int,
        *,
        orchestrator_instruction: str | None = None,
        output_language: str | None = None,
        thread_id: int | None = None,
        run_id: int | None = None,
    ) -> ReportGenerationResult:
        paper = self.session.get(Paper, paper_id)
        if paper is None:
            raise ValueError(f"Paper {paper_id} does not exist.")
        processed = self._latest_ready_processed_document(paper_id)
        if processed is None:
            return self._failed_report(
                paper,
                "No ready processed document exists for this paper.",
                ReportType.paper_summary.value,
                ReportSourceScope.full_document.value,
                thread_id,
                run_id,
            )
        provider = self.chat_provider or chat_provider_from_settings()
        body, body_metadata = self._body_text_without_references(processed)
        if not body.strip():
            return self._failed_report(
                paper,
                "Processed document has no cleaned body text after excluding References.",
                ReportType.paper_summary.value,
                ReportSourceScope.full_document.value,
                thread_id,
                run_id,
            )
        resolved_output_language = output_language or get_settings().report_language
        classification = self._classify_instruction_type(paper, provider)
        report_type = ReportType.critical_review.value if classification.instruction_type == "review_survey" else ReportType.paper_summary.value
        report = ReportRepository(self.session).create(
            f"{paper.title} reading report",
            thread_id=thread_id,
            run_id=run_id,
            paper_id=paper.id,
            processed_document_id=processed.id,
            report_type=report_type,
            status=ReportStatus.running.value,
            instructions=orchestrator_instruction,
            source_scope=ReportSourceScope.full_document.value,
        )
        try:
            context = self._build_body_context(provider, paper, body)
            markdown = self._adapter_for(provider).generate_text(
                provider,
                self._reading_report_messages(paper, classification, orchestrator_instruction, resolved_output_language, context),
            )
            validation = self._validate_report_markdown(markdown, output_language=resolved_output_language, instruction_type=classification.instruction_type)
            regeneration: dict[str, Any] = {"attempted": False, "used": False}
            validations = [asdict(validation)]
            if not validation.passed:
                regeneration["attempted"] = True
                regenerated = self._adapter_for(provider).generate_text(
                    provider,
                    self._reading_report_messages(
                        paper,
                        classification,
                        orchestrator_instruction,
                        resolved_output_language,
                        context,
                        validation_issues=validation.issues,
                    ),
                )
                regenerated_validation = self._validate_report_markdown(
                    regenerated,
                    output_language=resolved_output_language,
                    instruction_type=classification.instruction_type,
                )
                validations.append(asdict(regenerated_validation))
                if regenerated_validation.passed:
                    markdown = regenerated
                    validation = regenerated_validation
                    regeneration["used"] = True
                else:
                    validation = regenerated_validation
            metadata = _reading_report_metadata(
                provider=provider,
                processed=processed,
                body_metadata=body_metadata,
                classification=classification,
                context=context,
                orchestrator_instruction=orchestrator_instruction,
                output_language=resolved_output_language,
                validation=validation,
                validations=validations,
                regeneration=regeneration,
            )
            report.json_content = {
                "provider": provider.name,
                "instruction_type": classification.instruction_type,
                "classification_source": classification.source,
                "context_strategy": context.strategy,
                "validation_passed": validation.passed,
                "regeneration_attempted": regeneration["attempted"],
                "regeneration_used": regeneration["used"],
            }
            report.metadata_json = metadata
            report.source_refs_json = [
                {"type": "processed_document", "id": processed.id},
                {"type": "document_body", "source": body_metadata["body_source"], "references_excluded": True},
            ]
            if validation.passed:
                report.status = ReportStatus.succeeded.value
                report.markdown_content = markdown
                self.session.flush()
                return ReportGenerationResult(report_id=report.id, status=report.status, markdown_content=markdown, json_content=report.json_content)
            report.status = ReportStatus.failed.value
            report.error_message = "Reading report validation failed: " + "; ".join(validation.issues)
            report.markdown_content = markdown[:10000]
            self.session.flush()
            return ReportGenerationResult(
                report_id=report.id,
                status=report.status,
                markdown_content=report.markdown_content,
                json_content=report.json_content,
                error_message=report.error_message,
            )
        except Exception as exc:
            report.status = ReportStatus.failed.value
            report.error_message = str(exc)
            self.session.flush()
            return ReportGenerationResult(report_id=report.id, status=report.status, json_content={"error": str(exc)}, error_message=report.error_message)

    def generate_report(
        self,
        paper_id: int,
        *,
        instructions: str | None = None,
        report_type: str = ReportType.paper_summary.value,
        source_scope: str = ReportSourceScope.retrieval.value,
        query: str | None = None,
        selected_chunk_ids: list[int] | None = None,
        thread_id: int | None = None,
        run_id: int | None = None,
        limit: int = 5,
    ) -> ReportGenerationResult:
        paper = self.session.get(Paper, paper_id)
        if paper is None:
            raise ValueError(f"Paper {paper_id} does not exist.")
        processed = self._latest_processed_document(paper_id)
        if processed is None:
            return self._failed_report(paper, "No processed document exists for this paper.", report_type, source_scope, thread_id, run_id)
        report = ReportRepository(self.session).create(
            f"{paper.title} report",
            thread_id=thread_id,
            run_id=run_id,
            paper_id=paper.id,
            processed_document_id=processed.id,
            report_type=report_type,
            status=ReportStatus.running.value,
            instructions=instructions,
            source_scope=source_scope,
        )
        try:
            provider = self.chat_provider or chat_provider_from_settings()
            evidence = self._select_evidence(paper.id, processed, source_scope, query or instructions or paper.title, selected_chunk_ids, limit)
            markdown = self._adapter_for(provider).generate_text(provider, _messages(paper.title, instructions, evidence, processed))
            evidence_ids = self._persist_evidence(report.id, evidence, paper.id)
            report.status = ReportStatus.succeeded.value
            report.markdown_content = markdown
            report.json_content = {"provider": provider.name, "evidence_chunk_ids": [item.chunk_id for item in evidence]}
            report.source_refs_json = [{"type": "chunk", "id": item.chunk_id} for item in evidence]
            self.session.flush()
            return ReportGenerationResult(report_id=report.id, status=report.status, markdown_content=markdown, json_content=report.json_content, evidence_ids=evidence_ids)
        except Exception as exc:
            report.status = ReportStatus.failed.value
            report.error_message = str(exc)
            self.session.flush()
            return ReportGenerationResult(report_id=report.id, status=report.status, json_content={"error": str(exc)}, error_message=report.error_message)

    def _select_evidence(
        self,
        paper_id: int,
        processed: ProcessedDocument,
        source_scope: str,
        query: str,
        selected_chunk_ids: list[int] | None,
        limit: int,
    ) -> list[RetrievedChunk]:
        if source_scope == ReportSourceScope.selected_chunks.value:
            if not selected_chunk_ids:
                return []
            chunks = list(self.session.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(selected_chunk_ids)).order_by(DocumentChunk.chunk_index)))
            return [_chunk_to_retrieved(chunk, 1.0, "lexical") for chunk in chunks]
        if source_scope == ReportSourceScope.full_document.value:
            chunks = list(
                self.session.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.processed_document_id == processed.id)
                    .order_by(DocumentChunk.chunk_index)
                    .limit(limit)
                )
            )
            return [_chunk_to_retrieved(chunk, 1.0, "lexical") for chunk in chunks]
        return self.retrieval_service.retrieve(paper_id, query, limit=limit)

    def _persist_evidence(self, report_id: int, evidence: list[RetrievedChunk], paper_id: int) -> list[int]:
        ids: list[int] = []
        repo = ReportRepository(self.session)
        for item in evidence:
            row = repo.add_evidence(
                report_id,
                EvidenceType.chunk.value,
                chunk_id=item.chunk_id,
                paper_id=paper_id,
                quote_text=item.content_text[:1000],
                note=f"{item.retrieval_mode} score={item.score:.4f}",
            )
            ids.append(row.id)
        return ids

    def _latest_processed_document(self, paper_id: int) -> ProcessedDocument | None:
        return self.session.scalar(
            select(ProcessedDocument)
            .where(ProcessedDocument.paper_id == paper_id)
            .order_by(ProcessedDocument.version.desc(), ProcessedDocument.id.desc())
        )

    def _latest_ready_processed_document(self, paper_id: int) -> ProcessedDocument | None:
        return self.session.scalar(
            select(ProcessedDocument)
            .where(ProcessedDocument.paper_id == paper_id, ProcessedDocument.status == ProcessedDocumentStatus.ready.value)
            .order_by(ProcessedDocument.version.desc(), ProcessedDocument.id.desc())
        )

    def _body_text_without_references(self, processed: ProcessedDocument) -> tuple[str, dict[str, Any]]:
        if processed.content_text and processed.content_text.strip():
            return processed.content_text.strip(), {
                "body_source": "processed.content_text",
                "excluded_roles": [SectionRole.reference.value],
                "section_count": len(processed.sections),
            }
        sections = list(
            self.session.scalars(
                select(DocumentSection)
                .where(DocumentSection.processed_document_id == processed.id, DocumentSection.role != SectionRole.reference.value)
                .order_by(DocumentSection.section_index)
            )
        )
        body = "\n\n".join(section.cleaned_text.strip() for section in sections if section.cleaned_text and section.cleaned_text.strip()).strip()
        return body, {
            "body_source": "document_sections.cleaned_text",
            "excluded_roles": [SectionRole.reference.value],
            "section_count": len(sections),
        }

    def _classify_instruction_type(self, paper: Paper, provider: ResolvedProviderConfig) -> ReportClassificationResult:
        text = f"{paper.title}\n{paper.abstract or ''}".lower()
        if not any(false_positive in text for false_positive in _REVIEW_FALSE_POSITIVES):
            for pattern in _REVIEW_RULE_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    return ReportClassificationResult("review_survey", "rule", 1.0, f"matched review/survey signal {pattern!r}", pattern)
        raw = self._adapter_for(provider).generate_text(provider, _classification_messages(paper))
        try:
            payload = _extract_json_object(raw)
            kind = str(payload.get("type", "regular"))
            confidence = float(payload.get("confidence", 0.0))
            reason = str(payload.get("reason", "classifier returned no reason"))
        except Exception:
            return ReportClassificationResult("regular", "default", None, "classifier output was invalid; defaulted to regular")
        if kind == "review_survey" and confidence >= 0.65:
            return ReportClassificationResult("review_survey", "classifier", confidence, reason)
        if kind == "regular" and confidence >= 0.5:
            return ReportClassificationResult("regular", "classifier", confidence, reason)
        return ReportClassificationResult("regular", "default", confidence, "classifier was uncertain; defaulted to regular")

    def _build_body_context(self, provider: ResolvedProviderConfig, paper: Paper, body: str) -> ReportBodyContext:
        tokens = self.encoding.encode(body)
        token_count = len(tokens)
        if token_count <= FULL_BODY_TOKEN_LIMIT:
            return ReportBodyContext(text=body, token_count=token_count, strategy="full_body")
        prefix = self.encoding.decode(tokens[:VERBATIM_PREFIX_TOKEN_LIMIT])
        remainder = self.encoding.decode(tokens[VERBATIM_PREFIX_TOKEN_LIMIT:])
        compressed = self._compress_remainder(provider, paper, remainder)
        compressed_tokens = len(self.encoding.encode(compressed))
        wrapped = (
            f"{prefix}\n\n{COMPRESSED_REMAINDER_START}\n"
            "The following is model-compressed secondary evidence from paper sections that did not fit verbatim. "
            "Prefer the verbatim body above for exact claims and use this section for high-level coverage only.\n\n"
            f"{compressed}\n{COMPRESSED_REMAINDER_END}"
        )
        return ReportBodyContext(
            text=wrapped,
            token_count=token_count,
            strategy="prefix_plus_compressed_remainder",
            prefix_token_count=VERBATIM_PREFIX_TOKEN_LIMIT,
            remainder_token_count=token_count - VERBATIM_PREFIX_TOKEN_LIMIT,
            compressed_remainder_token_count=compressed_tokens,
            compression_chunk_count=max(1, _ceil_div(token_count - VERBATIM_PREFIX_TOKEN_LIMIT, COMPRESSION_CHUNK_TOKEN_LIMIT)),
        )

    def _compress_remainder(self, provider: ResolvedProviderConfig, paper: Paper, remainder: str) -> str:
        remainder_tokens = self.encoding.encode(remainder)
        summaries: list[str] = []
        for index, start in enumerate(range(0, len(remainder_tokens), COMPRESSION_CHUNK_TOKEN_LIMIT), start=1):
            chunk = self.encoding.decode(remainder_tokens[start : start + COMPRESSION_CHUNK_TOKEN_LIMIT])
            summaries.append(self._adapter_for(provider).generate_text(provider, _compression_messages(paper, chunk, index)))
        combined = "\n\n".join(summaries).strip()
        if len(self.encoding.encode(combined)) <= COMPRESSED_SUMMARY_TOKEN_LIMIT:
            return combined
        return self._adapter_for(provider).generate_text(provider, _compression_reduce_messages(paper, combined))

    def _reading_report_messages(
        self,
        paper: Paper,
        classification: ReportClassificationResult,
        orchestrator_instruction: str | None,
        output_language: str | None,
        context: ReportBodyContext,
        *,
        validation_issues: list[str] | None = None,
    ) -> list[dict]:
        instructions = DEFAULT_REVIEW_ANALYSIS_INSTRUCTIONS if classification.instruction_type == "review_survey" else DEFAULT_ANALYSIS_INSTRUCTIONS
        regeneration_note = ""
        if validation_issues:
            regeneration_note = "\n\nRegenerate the report and fix these validation issues:\n" + "\n".join(f"- {issue}" for issue in validation_issues)
        return [
            {
                "role": "system",
                "content": (
                    "You generate critical academic reading reports from the provided cleaned paper body. "
                    "The body excludes References. Do not invent unsupported claims. Distinguish paper content, reasonable inference, and critique. "
                    "If compressed secondary evidence is present, treat it as secondary and prefer verbatim body text for exact claims."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Paper title:\n{paper.title}\n\n"
                    f"Abstract:\n{paper.abstract or 'Not available.'}\n\n"
                    f"Instruction type: {classification.instruction_type}\n"
                    f"Output language: {output_language}\n\n"
                    f"Base instruction:\n{instructions}\n\n"
                    f"Orchestrator instruction:\n{orchestrator_instruction or 'No additional instruction.'}\n\n"
                    f"Context strategy: {context.strategy}. The paper body below excludes References.\n"
                    f"{regeneration_note}\n\n"
                    f"Cleaned paper body without References:\n{context.text}"
                ),
            },
        ]

    def _validate_report_markdown(self, markdown: str, *, output_language: str | None, instruction_type: str) -> ReportValidationResult:
        checks: dict[str, bool | str] = {}
        issues: list[str] = []
        text = markdown or ""
        checks["non_empty"] = bool(text.strip())
        checks["minimum_length"] = len(text.strip()) >= 500
        checks["has_markdown_headings"] = "#" in text
        lowered = text.lower()
        checks["no_refusal_placeholder"] = not any(marker in lowered for marker in ("i cannot access", "provided text is missing", "as an ai language model"))
        required = (
            ("Part I: Scope & Structure", "Part II: Comparative Insights", "Part III: Overall Assessment")
            if instruction_type == "review_survey"
            else ("Part I: Story & Method", "Part II: Experiments & Findings", "Part III: Summary & Critique")
        )
        checks["has_required_sections"] = all(section in text for section in required)
        language = output_language.lower()
        if _is_chinese_language(language):
            checks["language"] = bool(re.search(r"[一-鿿]", text))
        elif _is_english_language(language):
            letters = sum(1 for char in text if char.isascii() and char.isalpha())
            cjk = len(re.findall(r"[一-鿿]", text))
            checks["language"] = letters > cjk * 5
        else:
            checks["language"] = "skipped_unknown_language"
        for name, passed in checks.items():
            if passed is False:
                issues.append(name.replace("_", " ") + " check failed")
        return ReportValidationResult(not issues, issues, checks)

    def _adapter_for(self, provider: ResolvedProviderConfig) -> ChatModelAdapter:
        adapter = self.adapters.get(provider.provider)
        if adapter is None:
            raise ValueError(f"No chat adapter configured for provider {provider.provider!r}.")
        return adapter

    def _failed_report(
        self,
        paper: Paper,
        error: str,
        report_type: str,
        source_scope: str,
        thread_id: int | None,
        run_id: int | None,
    ) -> ReportGenerationResult:
        report = ReportRepository(self.session).create(
            f"{paper.title} report",
            thread_id=thread_id,
            run_id=run_id,
            paper_id=paper.id,
            report_type=report_type,
            status=ReportStatus.failed.value,
            source_scope=source_scope,
            error_message=error,
        )
        self.session.flush()
        return ReportGenerationResult(report_id=report.id, status=report.status, json_content={"error": error}, error_message=error)


def _reading_report_metadata(
    *,
    provider: ResolvedProviderConfig,
    processed: ProcessedDocument,
    body_metadata: dict[str, Any],
    classification: ReportClassificationResult,
    context: ReportBodyContext,
    orchestrator_instruction: str | None,
    output_language: str | None,
    validation: ReportValidationResult,
    validations: list[dict[str, Any]],
    regeneration: dict[str, Any],
) -> dict[str, Any]:
    return {
        "report_generation_version": _READING_REPORT_VERSION,
        "orchestrator_instruction": orchestrator_instruction,
        "output_language": output_language,
        "provider": {"name": provider.name, "provider": provider.provider, "model": provider.model, "base_url": provider.base_url},
        "instruction_type": classification.instruction_type,
        "classification": asdict(classification),
        "token_counts": {
            "body": context.token_count,
            "prefix": context.prefix_token_count,
            "remainder": context.remainder_token_count,
            "compressed_remainder": context.compressed_remainder_token_count,
            "tokenizer_encoding": REPORT_TOKEN_ENCODING,
        },
        "context_strategy": context.strategy,
        "compression": {
            "used": context.strategy == "prefix_plus_compressed_remainder",
            "chunk_count": context.compression_chunk_count,
            "start_marker": COMPRESSED_REMAINDER_START,
            "end_marker": COMPRESSED_REMAINDER_END,
        },
        "validation": asdict(validation),
        "validation_attempts": validations,
        "regeneration": regeneration,
        "processed_document": {"id": processed.id, "version": processed.version, **body_metadata},
    }


def _is_chinese_language(value: str) -> bool:
    return "chinese" in value or "中文" in value or "汉语" in value or "用中文" in value or "中文生成" in value


def _is_english_language(value: str) -> bool:
    return "english" in value or "英语" in value


def _classification_messages(paper: Paper) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "Classify whether a paper is primarily a review/survey/tutorial/taxonomy/meta-analysis paper. Return strict JSON only.",
        },
        {
            "role": "user",
            "content": (
                "Use only the title and abstract. If uncertain, return regular. Do not infer review/survey from generic related-work language.\n"
                "Return exactly: {\"type\":\"regular|review_survey\",\"confidence\":0.0,\"reason\":\"...\"}\n\n"
                f"Title: {paper.title}\nAbstract: {paper.abstract or 'Not available.'}"
            ),
        },
    ]


def _compression_messages(paper: Paper, chunk: str, index: int) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "Compress paper content into dense markdown notes. Preserve section headings, methods, datasets, experiments, results, limitations, and author claims. Do not invent content.",
        },
        {"role": "user", "content": f"Paper: {paper.title}\nRemainder chunk {index}:\n{chunk}"},
    ]


def _compression_reduce_messages(paper: Paper, combined: str) -> list[dict]:
    return [
        {"role": "system", "content": "Compress these chunk summaries into one dense secondary-evidence summary. Do not invent content."},
        {"role": "user", "content": f"Paper: {paper.title}\nChunk summaries:\n{combined}"},
    ]


def _messages(paper_title: str, instructions: str | None, evidence: list[RetrievedChunk], processed: ProcessedDocument) -> list[dict]:
    evidence_text = "\n\n".join(f"[chunk:{item.chunk_id}] {item.content_text}" for item in evidence)
    return [
        {
            "role": "system",
            "content": "You write evidence-grounded academic paper reports. Cite evidence as [chunk:<id>] and do not invent unsupported claims.",
        },
        {
            "role": "user",
            "content": f"Paper: {paper_title}\nInstructions: {instructions or 'Write a concise structured report.'}\nProcessed document id: {processed.id}\nEvidence:\n{evidence_text}",
        },
    ]


def _chunk_to_retrieved(chunk: DocumentChunk, score: float, mode: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        processed_document_id=chunk.processed_document_id,
        content_text=chunk.content_text,
        score=score,
        retrieval_mode=mode,
        metadata={"chunk_key": chunk.chunk_key, "heading_path": chunk.heading_path_json},
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    if not stripped.startswith("{"):
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match is None:
            raise ValueError("No JSON object found")
        stripped = match.group(0)
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("Classifier output is not an object")
    return payload


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)
