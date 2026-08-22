from __future__ import annotations

from langchain_core.tools import tool

from backend.db.repositories import AgentRunRepository
from backend.db.types import EventLevel, ProviderKind, ProviderName
from backend.schemas import ResolvedProviderConfig
from backend.services.reports import ReportGenerationService
from backend.tools.context import current_tool_context, resolve_active_paper_id, tool_session


@tool
def generate_paper_report(
    orchestrator_instruction: str | None = None,
    output_language: str | None = None,
    instructions: str | None = None,
    paper_id: int | None = None,
) -> dict:
    """Generate a persisted reading report, using the configured report language unless output_language explicitly overrides it."""
    with tool_session() as session:
        resolved_paper_id = resolve_active_paper_id(session, paper_id)
        context = current_tool_context()
        run_id = context.run_id if context is not None else None
        _append_report_generation_event(
            session,
            run_id,
            "report_generation_started",
            {"paper_id": resolved_paper_id, "output_language": output_language},
        )
        result = ReportGenerationService(session, chat_provider=_provider_from_context(context)).generate_reading_report(
            resolved_paper_id,
            orchestrator_instruction=orchestrator_instruction or instructions,
            output_language=output_language,
            thread_id=context.thread_id if context is not None else None,
            run_id=run_id,
        )
        payload = result.model_dump()
        if result.status == "failed":
            error_message = result.error_message or "Report generation failed."
            _append_report_generation_event(
                session,
                run_id,
                "report_generation_failed",
                {"paper_id": resolved_paper_id, "report_id": result.report_id, "error_message": error_message},
                level=EventLevel.error.value,
            )
            raise RuntimeError(f"Report generation failed for report #{result.report_id}: {error_message}")
        else:
            _append_report_generation_event(
                session,
                run_id,
                "report_generation_succeeded",
                {"paper_id": resolved_paper_id, "report_id": result.report_id, "status": result.status},
            )
        return payload


def _append_report_generation_event(session, run_id: int | None, event_type: str, payload: dict, level: str = EventLevel.info.value) -> None:
    if run_id is None:
        return
    AgentRunRepository(session).append_event(run_id, event_type, level=level, payload_json=payload)
    session.commit()


def _provider_from_context(context) -> ResolvedProviderConfig | None:
    if context is None or not getattr(context, "model", None):
        return None
    return ResolvedProviderConfig(
        id=0,
        name=getattr(context, "chat_provider_name", None) or "runtime-chat",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        base_url=getattr(context, "base_url", None),
        model=getattr(context, "model", None),
        api_key=getattr(context, "api_key", None),
        temperature=getattr(context, "temperature", None),
        settings={
            "max_tokens": getattr(context, "max_tokens", None),
            "timeout": getattr(context, "timeout", None),
            "max_retries": getattr(context, "max_retries", None),
            "extra_body": getattr(context, "extra_body", None),
        },
    )
