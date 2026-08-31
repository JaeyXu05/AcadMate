"""Evidence-first PDF mentor analysis.

Pipeline (PaperQA2-inspired): page passages -> multilingual dense recall ->
structured model reranking -> evidence validation -> Review. There is no
lexical/keyword fallback in this skill.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from backend.db.repositories import AgentRunRepository
from backend.db.types import RunStatus, WorkflowName
from backend.harness.contracts import RunCreate, RunCreated
from backend.harness.runtime import suggest_next_skill
from backend.integrations.llm.openai_compatible import OpenAICompatibleChatModelAdapter
from backend.services.mentor_semantic_retrieval import SemanticMentorHit, get_mentor_semantic_index
from backend.services.providers import chat_provider_from_settings
from backend.settings import get_settings
from backend.tools.context import tool_session

_MAX_PASSAGES = 12
_PASSAGE_CHARS = 520
_MAX_RECALL = 6
_MIN_FIT_SCORE = 60


class PdfMentorDecision(BaseModel):
    candidate_id: str
    fit_score: float = Field(ge=0, le=100)
    rationale: str = Field(min_length=1)
    matched_capabilities: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class PdfResearchAnalysis(BaseModel):
    document_summary: str = Field(min_length=1)
    research_directions: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    decisions: list[PdfMentorDecision] = Field(default_factory=list)


def queue_pdf_analyze(request: RunCreate, session: Session) -> RunCreated:
    """Persist a lightweight run so the HTTP request never waits on embeddings or the LLM."""
    pages = [item for item in (request.context.pages or []) if isinstance(item, dict) and str(item.get("text") or "").strip()]
    if not pages:
        return start_pdf_analyze(request, session)
    run = AgentRunRepository(session).create(
        WorkflowName.pdf_analyze.value,
        status=RunStatus.pending.value,
        input_json={
            "message": request.message,
            "metadata": {
                "harness_skill_id": "pdf_analyze",
                "document_id": request.context.document_id or "",
                "page_count": len(pages),
            },
        },
        output_json={
            "review_status": "PENDING",
            "evidence_refs": [],
            "suggested_next_skill": None,
            "artifact": {
                "type": "pdf_analyze_result",
                "document_id": request.context.document_id or "",
                "page_count": len(pages),
                "advisors": [],
                "score_kind": "calibrated_pdf_relevance",
                "analysis": None,
                "evidence_records": [],
                "error": None,
            },
        },
    )
    session.commit()
    return RunCreated(
        run_id=str(run.id), skill_id="pdf_analyze", status=RunStatus.pending.value,
        review_status="PENDING", evidence_refs=[], artifact=run.output_json["artifact"],
    )


def execute_pdf_analyze(run_id: int, request_payload: dict[str, Any]) -> None:
    """Background worker. It reuses the injectable session factory used by tests."""
    request = RunCreate.model_validate(request_payload)
    with tool_session() as session:
        start_pdf_analyze(request, session, run_id=run_id)


def start_pdf_analyze(request: RunCreate, session: Session, *, run_id: int | None = None) -> RunCreated:
    pages = [item for item in (request.context.pages or []) if isinstance(item, dict) and str(item.get("text") or "").strip()]
    document_id = request.context.document_id or ""
    if not pages:
        return _persist(
            session, request, status=RunStatus.waiting_for_user.value,
            review_status="NEED_MORE_INPUT", advisors=[], evidence_refs=[],
            analysis=None, evidence_records=[],
            error="未能抽出可检索正文（扫描件或图片 PDF）。不会按论文数、文件名或关键词冒充相关导师。", run_id=run_id,
        )

    passages = _page_passages(pages)
    try:
        settings = get_settings()
        index = get_mentor_semantic_index(settings.data_dir / "ustc_mentor_rag.json")
        hits = index.search([item["text"] for item in passages], top_k=_MAX_RECALL)
    except Exception as exc:  # noqa: BLE001 - surfaced as an auditable Review failure
        return _persist(
            session, request, status=RunStatus.failed.value, review_status="REVISE",
            advisors=[], evidence_refs=[], analysis=None, evidence_records=[],
            error=f"本地语义检索不可用：{type(exc).__name__}: {exc}", run_id=run_id,
        )
    if not hits:
        return _persist(
            session, request, status=RunStatus.succeeded.value, review_status="REVISE",
            advisors=[], evidence_refs=[], analysis=None, evidence_records=[],
            error="正文已抽出，但多语种向量检索没有召回可审查导师。", run_id=run_id,
        )

    try:
        analysis = _rerank_with_model(request, passages, hits)
        advisors, evidence_records = _validated_advisors(analysis, hits, passages, document_id)
        selected_ids = {str(item["id"]) for item in advisors}
        official_by_candidate: dict[str, list[dict[str, Any]]] = {}
        query_text = "；".join(analysis.research_directions) or request.message
        for record in index.evidence_for(selected_ids):
            metadata = record.metadata or {}
            if metadata.get("identity_verified") is not True:
                continue
            if not record.source_type.startswith("ustc_official_faculty_"):
                continue
            bound = record.model_copy(update={
                "query": query_text,
                "query_relevance": 1.0 if "research_topics" in str(metadata.get("supports_fields") or "") else 0.0,
                "entity_verified": True,
                "support_type": "DIRECT" if "research_topics" in str(metadata.get("supports_fields") or "") else "IDENTITY",
                "source_level": "L1" if "profile" in record.source_type else "L2",
            }).model_dump(mode="json")
            evidence_records.append(bound)
            official_by_candidate.setdefault(str(record.candidate_id), []).append(bound)
        for advisor in advisors:
            candidate_evidence = official_by_candidate.get(str(advisor["id"]), [])
            advisor["evidence"] = candidate_evidence
            advisor["evidenceRefs"] = list(dict.fromkeys([
                *[ref for ref in advisor.get("evidenceRefs", []) if str(ref).startswith("document:")],
                *[str(item["evidence_id"]) for item in candidate_evidence],
            ]))
    except Exception as exc:  # noqa: BLE001 - Review rejects malformed model output
        return _persist(
            session, request, status=RunStatus.succeeded.value, review_status="REVISE",
            advisors=[], evidence_refs=[], analysis=None, evidence_records=[],
            error=f"语义候选已召回，但模型重排未通过结构化审查：{type(exc).__name__}: {exc}", run_id=run_id,
        )

    evidence_refs = list(dict.fromkeys([
        *[str(ref) for advisor in advisors for ref in advisor.get("evidenceRefs", [])],
        *[str(item["evidence_id"]) for item in evidence_records],
    ]))
    if not advisors or not evidence_records:
        return _persist(
            session, request, status=RunStatus.succeeded.value, review_status="REVISE",
            advisors=[], evidence_refs=[], analysis=analysis.model_dump(mode="json"),
            evidence_records=[], error="模型没有给出同时具备有效导师 ID、绝对相关性阈值与 PDF 页级证据的匹配结果。", run_id=run_id,
        )
    return _persist(
        session, request, status=RunStatus.succeeded.value, review_status="PASS",
        advisors=advisors, evidence_refs=evidence_refs,
        analysis=analysis.model_dump(mode="json"), evidence_records=evidence_records,
        error=None, run_id=run_id,
    )


def pdf_analyze_result(run_id: int, session: Session) -> RunCreated:
    from backend.db.models import AgentRun

    run = session.get(AgentRun, run_id)
    if run is None or run.workflow != WorkflowName.pdf_analyze.value:
        raise ValueError("pdf AgentRun not found")
    output = dict(run.output_json or {})
    return RunCreated(
        run_id=str(run.id), skill_id="pdf_analyze", status=run.status,
        review_status=str(output.get("review_status") or "PENDING"),
        suggested_next_skill=output.get("suggested_next_skill"),
        evidence_refs=list(output.get("evidence_refs") or []), artifact=output.get("artifact"),
    )


def _rerank_with_model(request: RunCreate, passages: list[dict[str, Any]], hits: list[SemanticMentorHit]) -> PdfResearchAnalysis:
    settings = get_settings()
    provider = chat_provider_from_settings(settings).model_copy(deep=True)
    provider.settings = {
        **provider.settings,
        "max_tokens": min(settings.chat_max_tokens, 1800),
        "timeout": min(float(provider.settings.get("timeout") or 60), 60),
        "max_retries": 0,
        "response_format": {"type": "json_object"},
    }
    candidates = []
    for hit in hits:
        candidate = hit.candidate
        candidates.append({
            "candidate_id": candidate.candidate_id,
            "mentor_name": candidate.mentor_name,
            "department": candidate.department,
            "research_topics": candidate.research_topics[:6],
            "methods": [],
            "publications": [],
            "dense_recall_score": round(hit.score, 6),
            # The complete passage packet is already supplied once below.  IDs
            # avoid repeating the same PDF text for every recalled mentor.
            "supporting_passage_ids": [passages[index]["passage_id"] for index in hit.segment_indexes],
        })
    payload = {
        "user_request": request.message,
        "pdf_passages": passages,
        "retrieved_candidates": candidates,
        "required_json_schema": PdfResearchAnalysis.model_json_schema(),
    }
    system = (
        "你是科研材料分析与导师匹配的重排智能体。候选已经由多语种稠密向量检索召回。"
        "请理解研究问题、方法和可迁移能力，不做字面关键词匹配。只能从 supplied candidates 选择；"
        "每个结论必须引用 supplied PDF passage 的真实 page；不得编造导师、论文、经历或招生状态。"
        "输出 JSON，符合 schema；按 fit_score 降序，最多 5 人。rationale 说明研究问题/方法层面的联系，"
        "uncertainties 明示材料没有证明的部分，不输出思维链；结论保持精炼。"
    )
    adapter = OpenAICompatibleChatModelAdapter()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Return JSON matching required_json_schema.\n" + json.dumps(payload, ensure_ascii=False)},
    ]
    raw = adapter.generate_text(provider, messages)
    return _parse_json_model(raw, PdfResearchAnalysis)


def _validated_advisors(
    analysis: PdfResearchAnalysis,
    hits: list[SemanticMentorHit],
    passages: list[dict[str, Any]],
    document_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hit_by_id = {hit.candidate.candidate_id: hit for hit in hits}
    passage_by_page: dict[int, list[dict[str, Any]]] = {}
    for passage in passages:
        passage_by_page.setdefault(int(passage["page"]), []).append(passage)
    advisors: list[dict[str, Any]] = []
    evidence_records: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for decision in analysis.decisions:
        hit = hit_by_id.get(decision.candidate_id)
        if hit is None or decision.candidate_id in seen or decision.fit_score < _MIN_FIT_SCORE:
            continue
        # Inferred paper topics are not authoritative research interests. They may
        # explain a verified profile but cannot qualify a candidate by themselves.
        if int(hit.candidate.source_metadata.get("topics_source") or 0) != 1:
            continue
        seen.add(decision.candidate_id)
        allowed_pages = list(dict.fromkeys(int(passages[index]["page"]) for index in hit.segment_indexes))
        pages = [page for page in decision.page_numbers if page in allowed_pages] or allowed_pages[:2]
        if not pages:
            continue
        page_refs: list[str] = []
        for page in pages[:3]:
            evidence_id = f"document:{document_id}:page:{page}" if document_id else f"document:page:{page}"
            page_refs.append(evidence_id)
            evidence_records[evidence_id] = {
                "evidence_id": evidence_id,
                "candidate_id": None,
                "source_type": "uploaded_pdf_page",
                "source_uri": evidence_id,
                "title": f"PDF 第 {page} 页",
                "extracted_fact": passage_by_page[page][0]["text"][:500],
                "locator": f"page={page}",
                "freshness": "unknown",
                "confidence": round(max(0.0, min(1.0, hit.score)), 4),
                "metadata": {"supports_fields": "student_research_direction,student_methods"},
                "page": page,
            }
        candidate = hit.candidate
        advisors.append({
            "id": candidate.candidate_id,
            "name": candidate.mentor_name,
            "title": candidate.source_metadata.get("academic_title") or "",
            "department": candidate.department or "",
            "tags": candidate.research_topics[:8],
            "papers": 0,
            "matchScore": round(decision.fit_score),
            "scoreKind": "calibrated_pdf_relevance",
            "semanticRecallScore": round(hit.score * 100, 2),
            "explanation": decision.rationale,
            "matchedCapabilities": decision.matched_capabilities,
            "uncertainties": decision.uncertainties,
            "publication_status": "unknown_unverified_identity",
            "evidenceRefs": list(dict.fromkeys([*page_refs, *candidate.evidence_refs])),
            "page_hits": [{"page": page} for page in pages[:3]],
        })
    advisors.sort(key=lambda item: (-int(item["matchScore"]), str(item["id"])))
    return advisors[:5], list(evidence_records.values())


def _page_passages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_passages: list[dict[str, Any]] = []
    for item in pages:
        page = int(item.get("page") or 0)
        text = " ".join(str(item.get("text") or "").split())
        for start in range(0, len(text), _PASSAGE_CHARS):
            passage = text[start : start + _PASSAGE_CHARS].strip()
            if passage:
                all_passages.append({
                    "passage_id": f"p{page}-{start // _PASSAGE_CHARS + 1}",
                    "page": page,
                    "text": passage,
                })
    if len(all_passages) <= _MAX_PASSAGES:
        return all_passages
    indexes = {round(index * (len(all_passages) - 1) / (_MAX_PASSAGES - 1)) for index in range(_MAX_PASSAGES)}
    return [all_passages[index] for index in sorted(indexes)]


def _parse_json_model(raw: str, schema: type[BaseModel]) -> Any:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        return schema.model_validate_json(cleaned)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Structured PDF analysis failed validation: {exc}") from exc


def _persist(
    session: Session,
    request: RunCreate,
    *,
    status: str,
    review_status: str,
    advisors: list[dict[str, Any]],
    evidence_refs: list[str],
    analysis: dict[str, Any] | None,
    evidence_records: list[dict[str, Any]],
    error: str | None,
    run_id: int | None = None,
) -> RunCreated:
    document_id = request.context.document_id or ""
    pages = request.context.pages or []
    settings = get_settings()
    artifact = {
        "type": "pdf_analyze_result",
        "document_id": document_id,
        "page_count": len(pages),
        "advisors": advisors,
        "score_kind": "calibrated_pdf_relevance",
        "retrieval": {
            "mode": "dense_multilingual",
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.chat_model,
            "keyword_fallback": False,
        },
        "analysis": analysis,
        "evidence_records": evidence_records,
        "error": error,
        "retry": ({"skill_id": "pdf_analyze", "target": "semantic_review", "reason": review_status} if review_status != "PASS" else None),
    }
    output_json = {
        "review_status": review_status,
        "evidence_refs": evidence_refs,
        "suggested_next_skill": suggest_next_skill(request.context.growth),
        "artifact": artifact,
    }
    if run_id is None:
        run = AgentRunRepository(session).create(
            WorkflowName.pdf_analyze.value,
            status=status,
            input_json={"message": request.message, "metadata": {"harness_skill_id": "pdf_analyze", "document_id": document_id, "page_count": len(pages)}},
            output_json=output_json,
            error_message=error,
        )
    else:
        run = AgentRunRepository(session).update_status(
            run_id, status, output_json=output_json, error_message=error,
        )
    session.commit()
    return RunCreated(
        run_id=str(run.id), skill_id="pdf_analyze", status=status,
        review_status=review_status,
        suggested_next_skill=suggest_next_skill(request.context.growth) if review_status == "PASS" else "pdf_analyze",
        evidence_refs=evidence_refs, artifact=artifact,
    )
