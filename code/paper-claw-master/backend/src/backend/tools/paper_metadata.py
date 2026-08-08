from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from pydantic import ValidationError

from backend.schemas import PaperIdentifierInput, PaperMetadataPatch, PaperSourceRecordPatch
from backend.services.papers import update_paper_metadata as update_paper_metadata_service
from backend.tools.context import resolve_active_paper_id, tool_session


@tool
def update_paper_metadata(
    paper_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    identifiers: list[dict[str, Any]] | None = None,
    source_records: list[dict[str, Any]] | None = None,
    reason: str | None = None,
) -> dict:
    """Update allow-listed paper catalog metadata after explicit user approval."""
    try:
        metadata_patch = PaperMetadataPatch.model_validate(metadata or {})
        identifier_patches = [PaperIdentifierInput.model_validate(item) for item in (identifiers or [])]
        source_record_patches = [PaperSourceRecordPatch.model_validate(item) for item in (source_records or [])]
        with tool_session() as session:
            resolved_paper_id = resolve_active_paper_id(session, paper_id)
            return update_paper_metadata_service(
                session,
                paper_id=resolved_paper_id,
                metadata=metadata_patch,
                identifiers=identifier_patches,
                source_records=source_record_patches,
                reason=reason,
            )
    except (ValidationError, ValueError) as exc:
        return {"status": "failed", "paper_id": paper_id, "error": str(exc)}
