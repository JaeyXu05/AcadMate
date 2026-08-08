from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from langchain.agents.middleware import ToolCallRequest, wrap_tool_call
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from backend.agents.context import PaperClawContext
from backend.db.repositories import AgentRunRepository
from backend.db.types import EventLevel, RunStatus
from backend.tools.context import tool_runtime_context, tool_session


def record_tool_event_call(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
) -> ToolMessage | Command[Any]:
    context = request.runtime.context
    run_id = context.run_id if isinstance(context, PaperClawContext) else None
    tool_call = request.tool_call
    tool_name = _tool_name(request)
    tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
    if run_id is not None:
        _append_tool_event(
            run_id,
            "agent_tool_call_started",
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "args": _redact(tool_call.get("args", {}) if isinstance(tool_call, dict) else {}),
            },
        )
    try:
        if isinstance(context, PaperClawContext):
            with tool_runtime_context(context):
                result = handler(request)
        else:
            result = handler(request)
    except Exception as exc:
        if run_id is not None:
            _append_tool_event(
                run_id,
                "agent_tool_call_failed",
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "error": str(exc),
                },
                level=EventLevel.error.value,
            )
            if tool_name == "task":
                _mark_run_failed_from_tool_error(run_id, str(exc))
        raise
    if run_id is not None:
        preview = _result_preview(result)
        _append_tool_event(
            run_id,
            "agent_tool_call_completed",
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "result_preview": preview,
                "result_size": len(preview),
            },
        )
    return result


paper_claw_tool_event_middleware = wrap_tool_call(record_tool_event_call)


def _append_tool_event(run_id: int, event_type: str, payload: dict[str, Any], level: str = EventLevel.info.value) -> None:
    with tool_session() as session:
        AgentRunRepository(session).append_event(run_id, event_type, level=level, payload_json=payload)


def _mark_run_failed_from_tool_error(run_id: int, error: str) -> None:
    with tool_session() as session:
        run = AgentRunRepository(session).get(run_id)
        if run is None or run.status not in {RunStatus.pending.value, RunStatus.running.value, RunStatus.waiting_for_user.value}:
            return
        run.status = RunStatus.failed.value
        run.error_message = error
        run.finished_at = datetime.now().astimezone()
        AgentRunRepository(session).append_event(
            run_id,
            "agent_message_failed",
            level=EventLevel.error.value,
            payload_json={"error": error, "status": RunStatus.failed.value, "source": "tool", "tool_name": "task"},
        )


def _tool_name(request: ToolCallRequest) -> str | None:
    if request.tool is not None:
        return request.tool.name
    if isinstance(request.tool_call, dict):
        return request.tool_call.get("name")
    return None


def _result_preview(result: Any) -> str:
    content = getattr(result, "content", result)
    if not isinstance(content, str):
        content = str(content)
    return content[:1000]


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if "api_key" in normalized or "token" in normalized or normalized in {"authorization", "headers", "password", "secret"}:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
