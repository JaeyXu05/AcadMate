"""Paper reading Skill backed by Paper Claw AgentRun and RetrievalService."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.agents.runner import submit_agent_message
from backend.db.models import AgentRun, Paper
from backend.db.repositories import PaperRepository
from backend.db.types import RunStatus, WorkflowName
from backend.harness.contracts import RunCreate, RunCreated
from backend.harness.runtime import suggest_next_skill
from backend.schemas import AgentMessageRequest, RetrievedChunk
from backend.services.retrieval import RetrievalService
from backend.settings import get_settings

CHUNK_CITE_RE = re.compile(r"\[chunk:(\d+)\]")
MIN_CITED_CHUNKS = 2
_ASCII_TERM_RE = re.compile(r"[a-z][a-z0-9-]{2,}")
_CJK_TERM_RE = re.compile(r"[一-鿿]{2,16}")
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;\n])")


def start_paper_qa(request: RunCreate, session: Session) -> RunCreated:
    settings = get_settings()
    if not (settings.chat_model and str(settings.chat_model).strip()):
        raise ValueError("PAPER_CLAW_CHAT_MODEL is not set")
    candidate_id = request.context.candidate_id or ""
    mentor = _load_mentor(candidate_id)
    if mentor is None:
        raise ValueError(f"mentor not found: {candidate_id}")

    publications = [
        str(item).strip()
        for item in list(mentor.get("publications") or [])[:12]
        if str(item).strip()
    ]
    if not publications:
        raise ValueError("selected mentor has no publication metadata")

    topics = [str(item) for item in list(mentor.get("research_topics") or [])[:8]]
    if request.context.paper_id:
        paper = session.get(Paper, int(request.context.paper_id))
        if paper is None:
            raise ValueError(f"paper not found: {request.context.paper_id}")
    else:
        paper = _resolve_or_create_paper(
            session,
            publications,
            candidate_id=candidate_id,
            mentor_name=str(mentor.get("mentor_name") or ""),
            topics=topics,
        )
    query = " ".join(
        part
        for part in [paper.title, *topics, request.message.strip()]
        if part
    )
    preview, retrieve_error = _retrieve_chunks(session, paper.id, query)
    agent_request = AgentMessageRequest(
        message=(
            f"请使用当前论文《{paper.title}》完成证据驱动阅读。"
            "优先调用论文检索工具引用 chunk。"
            f"结论必须明确区分证据、推断与待验证项，"
            f"并用 [chunk:<chunk_id>] 格式至少引用 {MIN_CITED_CHUNKS} 个实际检索到的证据。"
        ),
        active_paper_id=paper.id,
        metadata={
            "harness_skill_id": "paper_qa",
            "harness_user_id": request.context.user_id,
            "candidate_id": candidate_id,
            "mentor_name": mentor.get("mentor_name"),
            "publication_titles": publications,
            "topics": topics,
            "query": query,
            "retrieve_error": retrieve_error,
        },
    )
    if not preview:
        response = submit_agent_message(session, agent_request)
        run = session.get(AgentRun, response.run_id)
        review_status = "RESEARCH_AGAIN" if retrieve_error else "NEED_MORE_INPUT"
        error = retrieve_error or (
            f"论文尚未解析入库。请在导师平台上传 PDF（POST /api/agent/paper-upload，paper_id={paper.id}），"
            "完成页级入库后再重试同一 paper_id 的 paper_qa。"
        )
        if run is not None:
            run.status = RunStatus.waiting_for_user.value
            run.error_message = error
            session.commit()
        artifact = _artifact(
            paper_id=paper.id,
            candidate_id=candidate_id,
            mentor_name=str(mentor.get("mentor_name") or ""),
            selected_publication=paper.title,
            publications=publications,
            topics=topics,
            chunks=[],
            run_status=RunStatus.waiting_for_user.value,
            review_status=review_status,
            error=error,
        )
        return RunCreated(
            run_id=str(response.run_id),
            skill_id="paper_qa",
            status=RunStatus.waiting_for_user.value,
            thread_id=response.thread_id,
            suggested_next_skill="paper_qa",
            review_status=review_status,
            evidence_refs=[],
            artifact=artifact,
        )

    response = submit_agent_message(session, agent_request)
    artifact = _artifact(
        paper_id=paper.id,
        candidate_id=candidate_id,
        mentor_name=str(mentor.get("mentor_name") or ""),
        selected_publication=paper.title,
        publications=publications,
        topics=topics,
        chunks=preview,
        run_status=response.status,
        review_status="PENDING",
    )
    return RunCreated(
        run_id=str(response.run_id),
        skill_id="paper_qa",
        status=response.status,
        thread_id=response.thread_id,
        suggested_next_skill=suggest_next_skill(request.context.growth),
        review_status="PENDING",
        evidence_refs=_evidence_refs(paper.id, preview),
        artifact=artifact,
    )


def paper_qa_result(run_id: int, session: Session) -> RunCreated:
    """Return a reviewed Harness result for a real Paper Claw AgentRun."""
    run = session.get(AgentRun, run_id)
    if run is None or run.workflow != WorkflowName.paper_qa.value:
        raise ValueError("paper AgentRun not found")

    input_json = dict(run.input_json or {})
    metadata = dict(input_json.get("metadata") or {})
    paper_id = int(input_json.get("active_paper_id") or 0)
    query = str(metadata.get("query") or input_json.get("message") or "")
    stored_error = str(run.error_message or metadata.get("retrieve_error") or "") or None
    if run.status == RunStatus.waiting_for_user.value:
        chunks: list[RetrievedChunk] = []
        retrieve_error = stored_error
    else:
        chunks, retrieve_error = (
            _retrieve_chunks(session, paper_id, query) if paper_id else ([], None)
        )
    paper = session.get(Paper, paper_id) if paper_id else None
    answer = str((run.output_json or {}).get("message") or "")
    cited_ids = _supported_cited_chunk_ids(answer, chunks)
    review_status = _review_status(
        run.status,
        chunks,
        answer,
        retrieve_error=retrieve_error or stored_error,
        cited_ids=cited_ids,
    )
    cited_chunks = [item for item in chunks if str(item.chunk_id) in cited_ids]
    evidence_refs = _evidence_refs(paper_id, cited_chunks if review_status == "PASS" else [])
    artifact = _artifact(
        paper_id=paper_id,
        candidate_id=str(metadata.get("candidate_id") or ""),
        mentor_name=str(metadata.get("mentor_name") or ""),
        selected_publication=(paper.title if paper is not None else None),
        publications=[str(item) for item in metadata.get("publication_titles") or []],
        topics=[str(item) for item in metadata.get("topics") or []],
        chunks=chunks,
        cited_chunks=cited_chunks,
        run_status=run.status,
        review_status=review_status,
        answer=answer or None,
        error=retrieve_error or stored_error,
        evidence_refs=evidence_refs,
    )
    return RunCreated(
        run_id=str(run.id),
        skill_id="paper_qa",
        status=run.status,
        thread_id=run.thread_id,
        suggested_next_skill=(
            "paper_qa"
            if review_status in {"REVISE", "RESEARCH_AGAIN", "NEED_MORE_INPUT"}
            else suggest_next_skill({"matched_mentors": [{}], "read_papers": [{}] if review_status == "PASS" else []})
        ),
        review_status=review_status,
        evidence_refs=evidence_refs,
        artifact=artifact,
    )


def _resolve_or_create_paper(
    session: Session,
    publications: list[str],
    *,
    candidate_id: str,
    mentor_name: str,
    topics: list[str],
) -> Paper:
    for title in publications:
        existing = session.scalar(
            select(Paper).where(func.lower(Paper.title) == _normalized_title(title))
        )
        if existing is not None:
            return existing
    return PaperRepository(session).create(
        publications[0],
        authors_json=[mentor_name] if mentor_name else [],
        keywords_json=topics,
        metadata_json={
            "source": "mentor_corpus",
            "mentor_candidate_id": candidate_id,
            "mentor_name": mentor_name,
        },
    )


def _normalized_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _retrieve_chunks(
    session: Session,
    paper_id: int,
    query: str,
    *,
    limit: int = 8,
) -> tuple[list[RetrievedChunk], str | None]:
    try:
        return RetrievalService(session).retrieve(paper_id, query, limit=limit), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _review_status(
    run_status: str,
    chunks: list[RetrievedChunk],
    answer: str = "",
    retrieve_error: str | None = None,
    cited_ids: set[str] | None = None,
) -> str:
    if run_status == RunStatus.waiting_for_user.value:
        return "RESEARCH_AGAIN" if retrieve_error else "NEED_MORE_INPUT"
    if run_status == RunStatus.succeeded.value:
        if retrieve_error:
            return "RESEARCH_AGAIN"
        if not chunks:
            return "NEED_MORE_INPUT"
        supported = cited_ids if cited_ids is not None else _supported_cited_chunk_ids(answer, chunks)
        if len(supported) >= MIN_CITED_CHUNKS:
            return "PASS"
        return "REVISE"
    if run_status in {RunStatus.failed.value, RunStatus.cancelled.value}:
        return "FAILED"
    return "PENDING"


def _cited_chunk_ids(answer: str, chunks: list[RetrievedChunk]) -> set[str]:
    retrieved = {str(item.chunk_id) for item in chunks}
    return {chunk_id for chunk_id in CHUNK_CITE_RE.findall(answer) if chunk_id in retrieved}


def _support_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = {match.group(0).lower() for match in _ASCII_TERM_RE.finditer(lowered)}
    for run in _CJK_TERM_RE.findall(text):
        terms.add(run)
        if len(run) >= 2:
            terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return terms


def _sentences_for_cite(answer: str, chunk_id: str) -> list[str]:
    marker = f"[chunk:{chunk_id}]"
    parts = [part.strip() for part in _SENTENCE_RE.split(answer) if part.strip()]
    hits = [part for part in parts if marker in part]
    return hits or ([answer] if marker in answer else [])


def _chunk_supports_claim(answer: str, chunk_id: str, content: str) -> bool:
    sentences = _sentences_for_cite(answer, chunk_id)
    if not sentences:
        return False
    chunk_terms = _support_terms(content)
    for sentence in sentences:
        cleaned = sentence.replace(f"[chunk:{chunk_id}]", " ")
        sent_terms = _support_terms(cleaned)
        if chunk_terms & sent_terms:
            return True
        has_ascii_chunk = any(term.isascii() for term in chunk_terms)
        has_ascii_sent = bool(_ASCII_TERM_RE.search(cleaned.lower()))
        if has_ascii_chunk and not has_ascii_sent and len(cleaned.strip()) >= 20:
            return True
    return False


def _supported_cited_chunk_ids(answer: str, chunks: list[RetrievedChunk]) -> set[str]:
    by_id = {str(item.chunk_id): item for item in chunks}
    supported: set[str] = set()
    for chunk_id in _cited_chunk_ids(answer, chunks):
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        if _chunk_supports_claim(answer, chunk_id, chunk.content_text):
            supported.add(chunk_id)
    return supported


def _evidence_refs(paper_id: int, chunks: list[RetrievedChunk]) -> list[str]:
    return [f"paper_chunk:{paper_id}:{item.chunk_id}" for item in chunks]


def _artifact(
    *,
    paper_id: int,
    candidate_id: str,
    mentor_name: str,
    selected_publication: str | None,
    publications: list[str],
    topics: list[str],
    chunks: list[RetrievedChunk],
    run_status: str,
    review_status: str,
    answer: str | None = None,
    error: str | None = None,
    cited_chunks: list[RetrievedChunk] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    cited = cited_chunks if cited_chunks is not None else chunks
    refs = evidence_refs if evidence_refs is not None else _evidence_refs(paper_id, cited if review_status == "PASS" else [])
    needs_upload = review_status in {"RESEARCH_AGAIN", "NEED_MORE_INPUT"}
    retrieved_refs = _evidence_refs(paper_id, chunks)
    return {
        "type": "paper_claw_reading",
        "paper_id": paper_id,
        "candidate_id": candidate_id,
        "mentor_name": mentor_name,
        "selected_publication": selected_publication,
        "topics": topics,
        "publications": [selected_publication] if selected_publication else [],
        "available_publications": publications,
        "retrieved_chunks": [
            {
                "evidence_id": evidence_id,
                "chunk_id": item.chunk_id,
                "score": item.score,
                "mode": item.retrieval_mode,
                "content": item.content_text,
                "metadata": item.metadata,
                "cited": str(item.chunk_id) in {str(cited_item.chunk_id) for cited_item in cited},
            }
            for evidence_id, item in zip(retrieved_refs, chunks, strict=True)
        ],
        "answer": answer,
        "run_status": run_status,
        "review_status": review_status,
        "research_tasks": [
            {
                "id": f"research-question:{candidate_id}",
                "title": f"围绕{mentor_name or '该导师'}的论文形成一个可验证研究问题",
                "status": "pending",
                "acceptance_criteria": [
                    f"至少引用 {MIN_CITED_CHUNKS} 个论文证据片段",
                    "写出研究问题、方法假设与最小验证步骤",
                ],
                "evidence_refs": refs,
            }
        ] if review_status == "PASS" else [],
        "retry": (
            {
                "skill_id": "paper_qa",
                "reason": review_status,
                "target": "paper_artifacts" if needs_upload else "paper_evidence",
                "paper_id": paper_id,
                "existing_api": (
                    "POST /api/agent/paper-upload"
                    if needs_upload
                    else None
                ),
            }
            if review_status in {"REVISE", "RESEARCH_AGAIN", "NEED_MORE_INPUT"}
            else None
        ),
        "note": (
            f"Paper Claw AgentRun 已完成，答案实际引用并通过词重叠核验的 chunk 为 {len(refs)} 条。"
            if review_status == "PASS"
            else (
                "没有可引用的论文 chunk：请在当前页面上传 PDF，由导师平台转发 Paper Claw 入库后再重试同一 paper_id。"
                if needs_upload
                else f"只有 AgentRun 成功、答案引用至少 {MIN_CITED_CHUNKS} 个已检索 chunk，且引用句与 chunk 正文有词重叠，才会写回成长状态。"
            )
        ),
        "error": error,
    }


def _load_mentor(candidate_id: str) -> dict | None:
    import sys

    settings = get_settings()
    repo_root = str(settings.data_dir.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from data_scripts.internal_mentor_rag import FileInternalMentorRag

    rag = FileInternalMentorRag(settings.data_dir / "ustc_mentor_rag.json")
    rag._ensure_loaded()
    for candidate in rag._candidates:
        if candidate.candidate_id == candidate_id:
            return candidate.model_dump()
    return None
