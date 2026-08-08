from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from backend.schemas import PaperClawContext
from backend.settings import REPO_ROOT


_OPENAI_PAYLOAD_LOGGER_INSTALLED = False


def runtime_model(request: ModelRequest):
    context = request.runtime.context
    if not isinstance(context, PaperClawContext) or not context.model or not context.model.strip():
        return None
    _install_openai_payload_logger()
    kwargs: dict[str, Any] = {
        "model": context.model,
        "api_key": context.api_key,
        "base_url": context.base_url,
        "temperature": context.temperature,
        "max_tokens": context.max_tokens,
        "timeout": context.timeout,
        "max_retries": context.max_retries,
        "rate_limiter": context.rate_limiter,
    }
    if context.extra_body is not None:
        kwargs["extra_body"] = context.extra_body
    return ChatOpenAI(**kwargs)


def apply_runtime_model(request: ModelRequest) -> None:
    model = runtime_model(request)
    if model is not None:
        request.model = model


@wrap_model_call
def paper_claw_model_middleware(request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
    model = runtime_model(request)
    overrides: dict[str, Any] = {}
    if model is not None:
        overrides["model"] = model
    messages = _messages_with_active_paper_info(request)
    if messages is not request.messages:
        overrides["messages"] = messages
    effective_request = request if not overrides else request.override(**overrides)
    # _log_model_request(effective_request)
    response = handler(effective_request)
    # _log_model_response(effective_request, response)
    return response


def _messages_with_active_paper_info(request: ModelRequest) -> list[Any]:
    context = request.runtime.context
    if not isinstance(context, PaperClawContext) or not context.active_paper_system_info:
        return request.messages
    injected = SystemMessage(content=context.active_paper_system_info)
    messages = list(request.messages)
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if getattr(message, "type", None) == "human" or (isinstance(message, dict) and message.get("role") == "user"):
            return [*messages[:index], injected, *messages[index:]]
    return [*messages, injected]


def _log_model_request(request: ModelRequest) -> None:
    _append_model_call_log(
        {
            "event": "model_request",
            "model": _model_name(request.model),
            "context": _context_payload(request.runtime.context),
            "system_message": _message_payload(request.system_message),
            "messages": [_message_payload(message) for message in request.messages],
            "tools": [_tool_payload(tool) for tool in request.tools],
            "tool_choice": _json_safe(request.tool_choice),
            "model_settings": _json_safe(request.model_settings),
        }
    )


def _log_model_response(request: ModelRequest, response: ModelResponse) -> None:
    _append_model_call_log(
        {
            "event": "model_response",
            "model": _model_name(request.model),
            "context": _context_payload(request.runtime.context),
            "messages": [_message_payload(message) for message in response.result],
            "structured_response": _json_safe(response.structured_response),
        }
    )


def _install_openai_payload_logger() -> None:
    global _OPENAI_PAYLOAD_LOGGER_INSTALLED
    if _OPENAI_PAYLOAD_LOGGER_INSTALLED:
        return
    try:
        from langchain_openai.chat_models.base import BaseChatOpenAI
    except ImportError:
        return

    original_get_request_payload = BaseChatOpenAI._get_request_payload

    def logged_get_request_payload(self: Any, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = original_get_request_payload(self, input_, stop=stop, **kwargs)
        # _append_model_call_log(
        #     {
        #         "event": "openai_request_payload",
        #         "model": _model_name(self),
        #         "payload": _redact_payload(payload),
        #     }
        # )
        return payload

    BaseChatOpenAI._get_request_payload = logged_get_request_payload
    _OPENAI_PAYLOAD_LOGGER_INSTALLED = True


def _append_model_call_log(payload: dict[str, Any]) -> None:
    log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    payload = {"timestamp": datetime.now().astimezone().isoformat(), **payload}
    with (log_dir / "model_calls.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(_json_safe(payload), ensure_ascii=False) + "\n")


def _redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if "api_key" in normalized_key or normalized_key in {"authorization", "headers"}:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = _redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]
    return _json_safe(payload)


def _context_payload(context: Any) -> dict[str, Any] | None:
    if not isinstance(context, PaperClawContext):
        return None
    return {
        "thread_id": context.thread_id,
        "run_id": context.run_id,
        "active_paper_id": context.active_paper_id,
        "has_active_paper_system_info": context.active_paper_system_info is not None,
        "model": context.model,
        "has_api_key": context.api_key is not None,
        "base_url": context.base_url,
        "temperature": context.temperature,
        "max_tokens": context.max_tokens,
        "timeout": context.timeout,
        "max_retries": context.max_retries,
        "has_rate_limiter": context.rate_limiter is not None,
        "chat_provider_name": context.chat_provider_name,
        "embedding_provider_name": context.embedding_provider_name,
    }


def _message_payload(message: Any) -> Any:
    if message is None:
        return None
    if hasattr(message, "model_dump"):
        return _json_safe(message.model_dump())
    return _json_safe(message)


def _tool_payload(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        return _json_safe(tool)
    return {
        "name": getattr(tool, "name", None),
        "description": getattr(tool, "description", None),
        "args_schema": _json_safe(getattr(tool, "args_schema", None)),
    }


def _model_name(model: Any) -> str:
    return getattr(model, "model_name", None) or getattr(model, "model", None) or type(model).__name__


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, type):
        return value.__name__
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    return str(value)
