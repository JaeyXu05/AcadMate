"""Ingest page-level PDF text into Paper Claw chunks (Docling-style page provenance)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import ProcessedDocument
from backend.db.repositories import ParsingRepository
from backend.db.types import ParseJobStatus, ParseQualityStatus, ParseStrategy, ProcessedDocumentStatus, SectionRole


def ingest_page_texts(
    session: Session,
    paper_id: int,
    pages: list[dict],
    *,
    run_id: int | None = None,
    artifact_id: int | None = None,
) -> dict:
    cleaned: list[tuple[int, str]] = []
    for item in pages:
        page_no = int(item.get("page") or 0)
        text = " ".join(str(item.get("text") or "").split()).strip()
        if page_no <= 0 or not text:
            continue
        cleaned.append((page_no, text))
    if not cleaned:
        raise ValueError("no extractable page text")

    repo = ParsingRepository(session)
    job = repo.create_parse_job(
        paper_id,
        run_id=run_id,
        input_artifact_id=artifact_id,
        strategy=ParseStrategy.pdf_text.value,
        status=ParseJobStatus.succeeded.value,
        parser_version="d-platform-unpdf",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    plain = "\n\n".join(f"[page {page}]\n{text}" for page, text in cleaned)
    parsed = repo.create_parsed_document(
        paper_id,
        job.id,
        "pdf_text",
        source_artifact_id=artifact_id,
        plain_text=plain,
        markdown_content=plain,
        quality_status=ParseQualityStatus.usable.value,
        quality_summary=f"{len(cleaned)} pages ingested from extracted text",
    )
    version = int(
        session.scalar(
            select(func.coalesce(func.max(ProcessedDocument.version), 0)).where(
                ProcessedDocument.paper_id == paper_id
            )
        )
        or 0
    ) + 1
    processed = repo.create_processed_document(
        paper_id,
        parsed.id,
        job.id,
        version=version,
        status=ProcessedDocumentStatus.ready.value,
        content_text=plain,
        content_markdown=plain,
        quality_status=ParseQualityStatus.usable.value,
        processing_profile="page_text_ingest",
        metadata_json={"page_count": len(cleaned), "source": "mentor_platform_pdf"},
    )
    chunk_ids: list[int] = []
    for index, (page_no, text) in enumerate(cleaned, start=1):
        section = repo.add_section(
            processed.id,
            index,
            role=SectionRole.body.value,
            heading_path_json=[f"page {page_no}"],
            page_start=page_no,
            page_end=page_no,
            raw_text=text,
            cleaned_text=text,
        )
        chunk = repo.add_chunk(
            processed.id,
            f"page-{page_no}",
            index,
            text[:8000],
            role=SectionRole.body.value,
            heading_path_json=[f"page {page_no}"],
            source_section_ids_json=[section.id],
            page_start=page_no,
            page_end=page_no,
            metadata_json={"page": page_no},
        )
        chunk_ids.append(chunk.id)
    session.flush()
    return {
        "paper_id": paper_id,
        "parse_job_id": job.id,
        "processed_document_id": processed.id,
        "chunk_ids": chunk_ids,
        "page_count": len(cleaned),
        "status": "ready",
    }
