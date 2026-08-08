from __future__ import annotations

from langchain_core.tools import tool

from backend.db.types import ParseStrategy
from backend.integrations.parsers import LlamaParseConfig, LlamaParseParser, LocalOCRConfig, LocalOCRParser, TexSourceParser
from backend.services.document_processing import DocumentProcessingService
from backend.services.parsing import ParseChainService
from backend.settings import get_settings
from backend.tools.context import resolve_active_paper_id, tool_session


@tool
def parse_paper(paper_id: int | None = None, run_id: int | None = None) -> dict:
    """Run the parser chain for a paper."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            job = default_parse_chain_service(session).run_parse_chain(resolved_paper_id, run_id=run_id)
            return {"paper_id": resolved_paper_id, "parse_job_id": job.id, "status": job.status, "strategy": job.strategy, "error": job.error_message}
    except Exception as exc:
        return {"paper_id": paper_id, "status": "parse_failed", "error": str(exc)}


@tool
def process_paper_document(paper_id: int | None = None) -> dict:
    """Process the latest parsed document into sections, chunks, and references."""
    try:
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            processed = DocumentProcessingService(session).process_latest_parsed_document(resolved_paper_id)
            return {"processed_document_id": processed.id, "paper_id": processed.paper_id, "status": processed.status, "version": processed.version}
    except Exception as exc:
        return {"paper_id": paper_id, "status": "processing_failed", "error": str(exc)}


@tool
def ingest_paper_document(paper_id: int | None = None, run_id: int | None = None) -> dict:
    """Parse and process a paper document in order for ingestion."""
    with tool_session() as session:
        resolved_paper_id = resolve_active_paper_id(session, paper_id)
        try:
            job = default_parse_chain_service(session).run_parse_chain(resolved_paper_id, run_id=run_id)
        except Exception as exc:
            return {
                "paper_id": resolved_paper_id,
                "status": "parse_failed",
                "error": str(exc),
            }
        if job.status != "succeeded":
            return {
                "paper_id": resolved_paper_id,
                "status": "parse_failed",
                "parse_job_id": job.id,
                "strategy": job.strategy,
                "error": job.error_message,
            }
        try:
            processed = DocumentProcessingService(session).process_latest_parsed_document(resolved_paper_id)
        except Exception as exc:
            return {
                "paper_id": resolved_paper_id,
                "status": "processing_failed",
                "parse_job_id": job.id,
                "strategy": job.strategy,
                "error": str(exc),
            }
        return {
            "paper_id": processed.paper_id,
            "status": "ready",
            "parse_job_id": job.id,
            "strategy": job.strategy,
            "processed_document_id": processed.id,
            "processed_status": processed.status,
            "version": processed.version,
        }


def default_parse_chain_service(session) -> ParseChainService:
    settings = get_settings()
    parsers = {ParseStrategy.tex.value: TexSourceParser()}
    if settings.local_ocr_base_url:
        parsers[ParseStrategy.local_ocr.value] = LocalOCRParser(
            LocalOCRConfig(
                api_key=settings.local_ocr_api_key,
                base_url=settings.local_ocr_base_url,
                model=settings.local_ocr_model,
                prompt=settings.local_ocr_prompt,
                max_tokens=settings.local_ocr_max_tokens,
                temperature=settings.local_ocr_temperature,
                top_p=settings.local_ocr_top_p,
                repetition_penalty=settings.local_ocr_repetition_penalty,
                dpi=settings.local_ocr_dpi,
                timeout_seconds=settings.local_ocr_timeout_seconds,
            )
        )
    if settings.llama_parse_api_key:
        parsers[ParseStrategy.llama_parse.value] = LlamaParseParser(
            LlamaParseConfig(
                api_key=settings.llama_parse_api_key,
                tier=settings.llama_parse_tier,
                timeout_seconds=settings.llama_parse_timeout_seconds,
                extra_time_per_page_seconds=settings.llama_parse_extra_time_per_page_seconds,
            )
        )
    return ParseChainService(session, parsers, settings.storage_root)
