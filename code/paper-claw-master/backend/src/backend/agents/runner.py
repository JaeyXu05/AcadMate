from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
import traceback
from uuid import uuid4

from langchain_core.rate_limiters import InMemoryRateLimiter
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.context import PaperClawContext
from backend.agents.main_agent import create_paper_claw_agent
from backend.api.serializers import run_event_read, run_read
from backend.db.models import AgentRun, AgentRunEvent, Paper, Thread
from backend.db.repositories import AgentRunRepository, ThreadRepository
from backend.db.session import get_session
from backend.db.types import EventLevel, MessageRole, MessageSource, RunStatus, WorkflowName
from backend.schemas import AgentMessageRequest, AgentMessageResponse, AgentStreamEvent, ApprovalRequest, RunEventRead, RunRead
from backend.settings import Settings, get_settings
from backend.tools.context import tool_runtime_context

STREAM_MODES = ["messages", "updates"]
STALE_RUNNING_RUN_AFTER = timedelta(minutes=20)


@dataclass(frozen=True)
class PreparedAgentRun:
    thread_id: int
    run_id: int
    deepagent_thread_id: str
    active_paper_id: int | None
    active_paper_system_info: str | None


def submit_agent_message(session: Session, request: AgentMessageRequest) -> AgentMessageResponse:
    prepared = prepare_agent_message_run(session, request)
    return AgentMessageResponse(
        thread_id=prepared.thread_id,
        run_id=prepared.run_id,
        status=RunStatus.running.value,
    )



def execute_agent_run(run_id: int) -> None:
    with get_session() as session:
        prepared, request = prepare_prepared_agent_run(session, run_id)
        for _event in _stream_agent_graph(session, prepared, request, {"messages": [{"role": "user", "content": request.message}]}):
            pass



def execute_agent_run_resume(run_id: int, request: ApprovalRequest) -> None:
    with get_session() as session:
        if request.decision == "cancel":
            cancel_run(session, run_id)
            return
        prepared, message_request = prepare_prepared_agent_run(session, run_id)
        for _event in _stream_agent_graph(session, prepared, message_request, Command(resume={"decisions": _resume_decisions(request)})):
            pass


def stream_agent_message(session: Session, request: AgentMessageRequest) -> Iterator[AgentStreamEvent]:
    prepared = prepare_agent_message_run(session, request)
    yield AgentStreamEvent(
        type="run_started",
        thread_id=prepared.thread_id,
        run_id=prepared.run_id,
        status=RunStatus.running.value,
        payload={"thread_id": prepared.thread_id},
    )
    yield from _stream_agent_graph(session, prepared, request, {"messages": [{"role": "user", "content": request.message}]})


def resume_agent_run(session: Session, run_id: int, request: ApprovalRequest) -> RunRead:
    if request.decision == "cancel":
        return cancel_run(session, run_id)
    prepare_agent_run_resume(session, run_id, request)
    run = session.get_one(AgentRun, run_id)
    return run_read(run)


def stream_agent_run_resume(session: Session, run_id: int, request: ApprovalRequest) -> Iterator[AgentStreamEvent]:
    prepared, message_request = prepare_agent_run_resume(session, run_id, request)
    yield AgentStreamEvent(
        type="run_resumed",
        thread_id=prepared.thread_id,
        run_id=prepared.run_id,
        status=RunStatus.running.value,
        payload={"thread_id": prepared.thread_id},
    )
    yield from _stream_agent_graph(session, prepared, message_request, Command(resume={"decisions": _resume_decisions(request)}))


def prepare_prepared_agent_run(session: Session, run_id: int) -> tuple[PreparedAgentRun, AgentMessageRequest]:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise ValueError("Run not found")
    thread = session.get(Thread, run.thread_id) if run.thread_id is not None else None
    if thread is None:
        raise ValueError("Run thread not found")
    input_json = dict(run.input_json or {})
    input_json.pop("has_api_key", None)
    message_request = AgentMessageRequest.model_validate({"message": input_json.get("message") or "", **input_json})
    active_paper_id = thread.current_focus_paper_id
    if input_json.get("active_paper_id") is not None:
        active_paper_id = int(input_json["active_paper_id"])
    return (
        PreparedAgentRun(
            thread_id=thread.id,
            run_id=run.id,
            deepagent_thread_id=run.deepagent_thread_id or thread.deepagent_thread_id or "",
            active_paper_id=active_paper_id,
            active_paper_system_info=_active_paper_system_info(session, active_paper_id),
        ),
        message_request,
    )



def prepare_agent_run_resume(session: Session, run_id: int, request: ApprovalRequest) -> tuple[PreparedAgentRun, AgentMessageRequest]:
    runs = AgentRunRepository(session)
    run = session.get(AgentRun, run_id)
    if run is None:
        raise ValueError("Run not found")
    if run.status != RunStatus.waiting_for_user.value:
        raise ValueError("Run is not waiting for user input")
    thread = session.get(Thread, run.thread_id) if run.thread_id is not None else None
    if thread is None:
        raise ValueError("Run thread not found")
    input_json = dict(run.input_json or {})
    input_json.pop("has_api_key", None)
    message_request = AgentMessageRequest.model_validate({"message": input_json.get("message") or "", **input_json})
    active_paper_id = thread.current_focus_paper_id
    if input_json.get("active_paper_id") is not None:
        active_paper_id = int(input_json["active_paper_id"])
    run.status = RunStatus.running.value
    run.finished_at = None
    run.error_message = None
    runs.append_event(run.id, "agent_resume_requested", payload_json={"decisions": _resume_decisions(request), "comment": request.comment})
    session.commit()
    return (
        PreparedAgentRun(
            thread_id=thread.id,
            run_id=run.id,
            deepagent_thread_id=run.deepagent_thread_id or thread.deepagent_thread_id or "",
            active_paper_id=active_paper_id,
            active_paper_system_info=_active_paper_system_info(session, active_paper_id),
        ),
        message_request,
    )


def _stream_agent_graph(session: Session, prepared: PreparedAgentRun, request: AgentMessageRequest, graph_input: Any) -> Iterator[AgentStreamEvent]:
    runs = AgentRunRepository(session)
    message_parts: list[str] = []
    last_message_text: str | None = None
    latest_chunks: list[dict[str, Any]] = []

    try:
        agent = create_paper_claw_agent()
        context = _agent_context(prepared, request)
        with tool_runtime_context(context):
            chunks = iter(
                agent.stream(
                    graph_input,
                    config={
                        "configurable": {"thread_id": prepared.deepagent_thread_id},
                        "metadata": {
                            "assistant_id": "paper-claw",
                            "paper_claw_thread_id": prepared.thread_id,
                            "paper_claw_run_id": prepared.run_id,
                        },
                    },
                    context=context,
                    stream_mode=STREAM_MODES,
                    subgraphs=True,
                    version="v2",
                )
            )
        while True:
            with tool_runtime_context(context):
                try:
                    chunk = next(chunks)
                except StopIteration:
                    break
            if _run_is_cancelled(session, prepared.run_id):
                yield _run_cancelled_event(session, prepared)
                return
            normalized = _normalize_stream_chunk(chunk)
            if normalized["mode"] not in STREAM_MODES:
                continue
            interrupt_payload = _interrupt_payload(normalized)
            if interrupt_payload is not None:
                event = runs.append_event(prepared.run_id, "agent_interrupt_requested", payload_json=interrupt_payload)
                run = session.get_one(AgentRun, prepared.run_id)
                run.status = RunStatus.waiting_for_user.value
                run.output_json = {"interrupt": interrupt_payload, "latest_chunks": _json_safe(latest_chunks)}
                session.commit()
                yield AgentStreamEvent(
                    type="run_waiting_for_user",
                    thread_id=prepared.thread_id,
                    run_id=prepared.run_id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    status=RunStatus.waiting_for_user.value,
                    payload=interrupt_payload,
                )
                return
            text = _stream_message_text(normalized)
            if text:
                message_parts.append(text)
                last_message_text = "".join(message_parts)
            latest_chunks.append(_stream_summary(normalized))
            latest_chunks = latest_chunks[-20:]
            persisted_event = _persistable_stream_event(normalized)
            if persisted_event is not None:
                event = runs.append_event(prepared.run_id, "agent_stream_update", payload_json=persisted_event)
                session.commit()
                sequence = event.sequence
                event_type = event.event_type
            else:
                sequence = None
                event_type = None
            yield AgentStreamEvent(
                type="agent_chunk",
                thread_id=prepared.thread_id,
                run_id=prepared.run_id,
                sequence=sequence,
                event_type=event_type,
                status=RunStatus.running.value,
                message=text,
                payload=_stream_client_payload(normalized),
            )
            if _run_is_cancelled(session, prepared.run_id):
                yield _run_cancelled_event(session, prepared)
                return

        if _run_is_cancelled(session, prepared.run_id):
            yield _run_cancelled_event(session, prepared)
            return

        thread = session.get_one(Thread, prepared.thread_id)
        run = session.get_one(AgentRun, prepared.run_id)
        if run.status in {RunStatus.failed.value, RunStatus.cancelled.value}:
            yield AgentStreamEvent(
                type="run_failed" if run.status == RunStatus.failed.value else "run_cancelled",
                thread_id=prepared.thread_id,
                run_id=prepared.run_id,
                status=run.status,
                error=run.error_message,
                payload={"status": run.status, "error": run.error_message},
            )
            return
        message_text = last_message_text or "".join(message_parts)
        assistant_message = ThreadRepository(session).add_message(
            thread.id,
            MessageRole.assistant.value,
            message_text,
            source=MessageSource.agent.value,
            run_id=run.id,
        )
        run.status = RunStatus.succeeded.value
        run.output_json = {"message": message_text, "stream_modes": STREAM_MODES, "latest_chunks": _json_safe(latest_chunks)}
        run.finished_at = datetime.now().astimezone()
        completed_event = runs.append_event(
            run.id,
            "agent_message_completed",
            payload_json={"assistant_message_id": assistant_message.id, "status": RunStatus.succeeded.value},
        )
        session.commit()
        yield AgentStreamEvent(
            type="run_completed",
            thread_id=thread.id,
            run_id=run.id,
            sequence=completed_event.sequence,
            event_type=completed_event.event_type,
            assistant_message_id=assistant_message.id,
            status=run.status,
            message=message_text,
            payload={"assistant_message_id": assistant_message.id},
        )
    except Exception as exc:
        session.rollback()
        error_payload = _exception_payload(exc)
        run = session.get(AgentRun, prepared.run_id)
        if run is not None:
            if run.status != RunStatus.failed.value:
                run.status = RunStatus.failed.value
                run.error_message = error_payload["error"]
                run.finished_at = datetime.now().astimezone()
                failed_event = AgentRunRepository(session).append_event(
                    run.id,
                    "agent_message_failed",
                    level=EventLevel.error.value,
                    payload_json={**error_payload, "status": RunStatus.failed.value},
                )
            else:
                failed_event = None
            session.commit()
            yield AgentStreamEvent(
                type="run_failed",
                thread_id=prepared.thread_id,
                run_id=prepared.run_id,
                sequence=failed_event.sequence if failed_event is not None else None,
                event_type=failed_event.event_type if failed_event is not None else None,
                status=RunStatus.failed.value,
                error=error_payload["error"],
                payload={**error_payload, "status": RunStatus.failed.value},
            )
        else:
            yield AgentStreamEvent(
                type="run_failed",
                thread_id=prepared.thread_id,
                run_id=prepared.run_id,
                status=RunStatus.failed.value,
                error=error_payload["error"],
                payload=error_payload,
            )


def prepare_agent_message_run(session: Session, request: AgentMessageRequest) -> PreparedAgentRun:
    threads = ThreadRepository(session)
    runs = AgentRunRepository(session)
    thread = threads.get(request.thread_id) if request.thread_id is not None else None
    if request.thread_id is not None and thread is None:
        raise ValueError("Thread not found")
    if thread is None:
        thread = threads.create(_thread_title(request.message), deepagent_thread_id=_new_deepagent_thread_id())
    elif thread.deepagent_thread_id is None:
        thread.deepagent_thread_id = _new_deepagent_thread_id()
    active_paper_id = _resolve_active_paper_id(session, thread, request)
    active_paper_system_info = _active_paper_system_info(session, active_paper_id)
    threads.add_message(thread.id, MessageRole.user.value, request.message, source=MessageSource.human.value)
    run = runs.create(
        WorkflowName.paper_qa.value,
        thread_id=thread.id,
        status=RunStatus.running.value,
        deepagent_thread_id=thread.deepagent_thread_id,
        started_at=datetime.now().astimezone(),
        input_json=_run_input(request),
    )
    runs.append_event(run.id, "agent_message_received", payload_json={"thread_id": thread.id})
    session.commit()
    return PreparedAgentRun(
        thread_id=thread.id,
        run_id=run.id,
        deepagent_thread_id=thread.deepagent_thread_id or "",
        active_paper_id=active_paper_id,
        active_paper_system_info=active_paper_system_info,
    )


def list_run_events(session: Session, run_id: int, after_sequence: int | None = None) -> list[RunEventRead]:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise ValueError("Run not found")
    mark_stale_running_run_failed(session, run)
    statement = select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
    if after_sequence is not None:
        statement = statement.where(AgentRunEvent.sequence > after_sequence)
    events = session.scalars(statement.order_by(AgentRunEvent.sequence)).all()
    return [run_event_read(event) for event in events]


def mark_stale_running_run_failed(session: Session, run: AgentRun) -> None:
    if run.status != RunStatus.running.value:
        return
    last_event_at = max((event.created_at for event in run.events), default=run.updated_at or run.started_at or run.created_at)
    if datetime.now().astimezone() - last_event_at < STALE_RUNNING_RUN_AFTER:
        return
    run.status = RunStatus.failed.value
    run.error_message = "Agent run stopped before completion. Please retry the request."
    run.finished_at = datetime.now().astimezone()
    AgentRunRepository(session).append_event(
        run.id,
        "agent_message_failed",
        level=EventLevel.error.value,
        payload_json={"error": run.error_message, "status": RunStatus.failed.value, "source": "stale_run_reaper"},
    )
    session.commit()
    session.expire(run, ["events"])



def _exception_payload(exc: Exception) -> dict[str, Any]:
    message = str(exc) or repr(exc) or type(exc).__name__
    return {
        "error": message,
        "error_type": f"{type(exc).__module__}.{type(exc).__name__}",
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8000:],
    }


def _resume_decisions(request: ApprovalRequest) -> list[dict[str, Any]]:
    if request.decisions:
        return [decision.model_dump(exclude_none=True) for decision in request.decisions]
    if request.decision == "approve":
        return [{"type": "approve"}]
    if request.decision in {"reject", "revise"}:
        return [{"type": "reject", "args": {"comment": request.comment}}]
    raise ValueError("At least one HITL decision is required")


def _interrupt_payload(normalized: dict[str, Any]) -> dict[str, Any] | None:
    data = normalized.get("data")
    if not isinstance(data, dict):
        return None
    interrupt = data.get("__interrupt__")
    if interrupt is None:
        return None
    interrupts = interrupt if isinstance(interrupt, list) else [interrupt]
    payloads = [_interrupt_value(item) for item in interrupts]
    action_requests: list[Any] = []
    review_configs: list[Any] = []
    for payload in payloads:
        if isinstance(payload, dict):
            actions = payload.get("action_requests")
            reviews = payload.get("review_configs")
            if isinstance(actions, list):
                action_requests.extend(actions)
            if isinstance(reviews, list):
                review_configs.extend(reviews)
    return {
        "interrupts": _json_safe(payloads),
        "action_requests": _json_safe(action_requests),
        "review_configs": _json_safe(review_configs),
        "raw": _json_safe(interrupt),
    }


def _interrupt_value(interrupt: Any) -> Any:
    if isinstance(interrupt, dict) and "value" in interrupt:
        return interrupt["value"]
    value = getattr(interrupt, "value", None)
    if value is not None:
        return value
    return interrupt


def _run_is_cancelled(session: Session, run_id: int) -> bool:
    session.expire_all()
    run = session.get(AgentRun, run_id)
    return run is not None and run.status == RunStatus.cancelled.value


def _run_cancelled_event(session: Session, prepared: PreparedAgentRun) -> AgentStreamEvent:
    session.expire_all()
    run = session.get(AgentRun, prepared.run_id)
    return AgentStreamEvent(
        type="run_cancelled",
        thread_id=prepared.thread_id,
        run_id=prepared.run_id,
        status=run.status if run is not None else RunStatus.cancelled.value,
        payload={"status": RunStatus.cancelled.value},
    )


def cancel_run(session: Session, run_id: int) -> RunRead:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise ValueError("Run not found")
    if run.status in {RunStatus.pending.value, RunStatus.running.value, RunStatus.waiting_for_user.value}:
        run.status = RunStatus.cancelled.value
        run.finished_at = datetime.now().astimezone()
        AgentRunRepository(session).append_event(run.id, "agent_run_cancelled")
        session.flush()
    return run_read(run)


def encode_agent_message_stream(session: Session, request: AgentMessageRequest) -> Iterator[str]:
    import json

    for event in stream_agent_message(session, request):
        yield json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n"


def _agent_context(prepared: PreparedAgentRun, request: AgentMessageRequest) -> PaperClawContext:
    settings = get_settings()
    if request.model is not None:
        model = request.model
        api_key = request.api_key or settings.chat_api_key
        base_url = request.base_url or settings.chat_base_url
        temperature = request.temperature if request.temperature != 0.2 else settings.chat_temperature
        max_tokens = request.max_tokens if request.max_tokens != 4096 else settings.chat_max_tokens
        timeout = request.timeout if request.timeout != 60 else settings.chat_timeout_seconds
        max_retries = request.max_retries if request.max_retries != 2 else settings.chat_max_retries
        provider_name = request.chat_provider_name or "settings-chat"
    else:
        model = settings.chat_model
        api_key = request.api_key or settings.chat_api_key
        base_url = request.base_url or settings.chat_base_url
        temperature = request.temperature if request.temperature != 0.2 else settings.chat_temperature
        max_tokens = request.max_tokens if request.max_tokens != 4096 else settings.chat_max_tokens
        timeout = request.timeout if request.timeout != 60 else settings.chat_timeout_seconds
        max_retries = request.max_retries if request.max_retries != 2 else settings.chat_max_retries
        provider_name = "settings-chat"
    if not model or not model.strip():
        raise ValueError("PAPER_CLAW_CHAT_MODEL is not set.")
    return PaperClawContext(
        thread_id=prepared.thread_id,
        run_id=prepared.run_id,
        active_paper_id=prepared.active_paper_id,
        active_paper_system_info=prepared.active_paper_system_info,
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        extra_body=settings.chat_extra_body,
        rate_limiter=_chat_rate_limiter(settings),
        chat_provider_name=provider_name,
    )


def _resolve_active_paper_id(session: Session, thread: Thread, request: AgentMessageRequest) -> int | None:
    if request.active_paper_id is not None:
        if session.get(Paper, request.active_paper_id) is None:
            raise ValueError(f"Paper {request.active_paper_id} not found")
        thread.current_focus_paper_id = request.active_paper_id
        return request.active_paper_id
    return thread.current_focus_paper_id


def _active_paper_system_info(session: Session, paper_id: int | None) -> str | None:
    if paper_id is None:
        return None
    paper = session.get(Paper, paper_id)
    if paper is None:
        return f"System info: Active paper id is #{paper_id}, but it was not found in the paper catalog."
    details = [f"System info: Active paper is #{paper.id}: {paper.title}."]
    if paper.year is not None:
        details.append(f"Year: {paper.year}.")
    if paper.authors_json:
        details.append(f"Authors: {', '.join(str(author) for author in paper.authors_json[:5])}.")
    details.append(
        'Use this paper as the default target when the user says "this paper", "the paper", '
        "or asks for paper-specific retrieval, QA, artifact, or report work without naming another paper."
    )
    return "\n".join(details)


def _chat_rate_limiter(settings: Settings) -> InMemoryRateLimiter | None:
    if settings.chat_rate_limiter_requests_per_second is None:
        return None
    return InMemoryRateLimiter(
        requests_per_second=settings.chat_rate_limiter_requests_per_second,
        check_every_n_seconds=settings.chat_rate_limiter_check_every_n_seconds,
        max_bucket_size=settings.chat_rate_limiter_max_bucket_size,
    )


def _thread_title(message: str) -> str:
    title = " ".join(message.strip().split())[:80]
    return title or "New thread"


def _new_deepagent_thread_id() -> str:
    return f"paper-claw-thread-{uuid4()}"


def _run_input(request: AgentMessageRequest) -> dict[str, Any]:
    data = request.model_dump(exclude={"api_key"})
    data["has_api_key"] = request.api_key is not None
    return data


def _assistant_text(output: Any) -> str:
    if isinstance(output, dict) and "messages" in output:
        for message in reversed(output["messages"]):
            content = _message_content(message)
            if content:
                return content
    content = _message_content(output)
    return content or ""


def _message_content(message: Any) -> str | None:
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return None


def _normalize_stream_chunk(chunk: Any) -> dict[str, Any]:
    mode: str | None = None
    namespace: tuple[Any, ...] = ()
    data: Any = chunk
    if isinstance(chunk, dict) and "type" in chunk:
        mode = str(chunk.get("type"))
        raw_namespace = chunk.get("ns", ())
        namespace = tuple(raw_namespace) if isinstance(raw_namespace, list | tuple) else (raw_namespace,)
        data = chunk.get("data")
    elif isinstance(chunk, tuple):
        if len(chunk) == 2:
            mode = str(chunk[0])
            data = chunk[1]
        elif len(chunk) == 3:
            raw_namespace, raw_mode, data = chunk
            mode = str(raw_mode)
            namespace = tuple(raw_namespace) if isinstance(raw_namespace, list | tuple) else (raw_namespace,)
    mode = mode or "unknown"
    normalized_data = _normalize_stream_data(mode, data)
    return {"mode": mode, "namespace": [str(item) for item in namespace], "data": normalized_data}


def _normalize_stream_data(mode: str, data: Any) -> Any:
    if mode == "messages" and isinstance(data, tuple) and len(data) == 2:
        message, metadata = data
        return {"content": _message_content(message) or "", "message": _json_safe(message), "metadata": _json_safe(metadata)}
    return _json_safe(data)


def _stream_message_text(normalized: dict[str, Any]) -> str | None:
    if normalized.get("mode") != "messages":
        return None
    data = normalized.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("content"), str):
        return None
    metadata = data.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("langgraph_node") != "model" or metadata.get("lc_agent_name") is not None:
        return None
    message = data.get("message")
    if isinstance(message, dict) and str(message.get("type", "")).lower() not in {"ai", "aichunk", "aimessagechunk"}:
        return None
    return data["content"]


def _stream_client_payload(normalized: dict[str, Any]) -> dict[str, Any]:
    if normalized.get("mode") == "messages":
        return {"mode": "messages", "namespace": normalized.get("namespace", []), "data": {"content": _stream_message_text(normalized) or ""}}
    return _stream_summary(normalized)


def _persistable_stream_event(normalized: dict[str, Any]) -> dict[str, Any] | None:
    if normalized.get("mode") == "messages":
        return None
    summary = _stream_summary(normalized)
    data = summary.get("data")
    if data in ({}, None):
        return None
    return summary


def _stream_summary(normalized: dict[str, Any]) -> dict[str, Any]:
    mode = normalized.get("mode")
    namespace = normalized.get("namespace", [])
    if mode == "messages":
        return {"mode": "messages", "namespace": namespace, "data": {"content_length": len(_stream_message_text(normalized) or "")}}
    data = normalized.get("data")
    if isinstance(data, dict):
        return {"mode": mode, "namespace": namespace, "data": {str(key): _stream_summary_value(value) for key, value in data.items()}}
    return {"mode": mode, "namespace": namespace, "data": _stream_summary_value(data)}


def _stream_summary_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return {"type": "list", "size": len(value)}
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value.keys())[:20]}
    content = getattr(value, "content", None)
    if isinstance(content, str):
        return {"type": type(value).__name__, "content_length": len(content)}
    return {"type": type(value).__name__}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return _json_safe(value)
    return {"result": _json_safe(value)}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    interrupt_value = getattr(value, "value", None)
    if interrupt_value is not None:
        return {"value": _json_safe(interrupt_value)}
    content = getattr(value, "content", None)
    if content is not None:
        return {"content": _json_safe(content)}
    return str(value)
