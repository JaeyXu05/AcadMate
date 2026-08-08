from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker
from langchain.agents.middleware import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agents.checkpointing import _psycopg_connection_string
import backend.agents.main_agent as main_agent_module
from backend.agents.main_agent import create_paper_claw_agent
from backend.agents.model import _json_safe, _messages_with_active_paper_info, apply_runtime_model
from backend.agents.prompts import PAPER_CLAW_SYSTEM_PROMPT
from backend.agents.subagents import create_paper_claw_subagents
from backend.agents.tool_events import record_tool_event_call
from backend.db.models import AgentRun
from backend.db.types import RunStatus, WorkflowName
from backend.schemas import PaperClawContext
from backend.tools.context import current_tool_context, set_tool_session_factory


def test_subagent_names_are_unique():
    subagents = create_paper_claw_subagents()
    names = [subagent["name"] for subagent in subagents]
    assert len(names) == len(set(names))
    assert names == [
        "paper-discovery-specialist",
        "paper-ingestion-specialist",
        "paper-evidence-specialist",
        "paper-report-specialist",
    ]


def test_subagents_have_explicit_isolated_tools():
    subagents = create_paper_claw_subagents()
    tool_names_by_agent = {
        subagent["name"]: {tool.name for tool in subagent["tools"]}
        for subagent in subagents
    }
    assert tool_names_by_agent["paper-discovery-specialist"] == {"search_papers", "get_paper"}
    assert tool_names_by_agent["paper-ingestion-specialist"] == {
        "get_paper_pipeline_status",
        "list_paper_artifacts",
        "download_arxiv_paper_artifacts",
        "download_paper_pdf_from_url",
        "mark_paper_artifact_upload_required",
        "ingest_paper_document",
    }
    assert tool_names_by_agent["paper-evidence-specialist"] == {"get_paper_pipeline_status", "retrieve_paper_evidence"}
    assert tool_names_by_agent["paper-report-specialist"] == {"get_paper_pipeline_status", "list_paper_reports", "generate_paper_report"}
    assert all("tools" in subagent for subagent in subagents)
    assert all("answer_paper_question" not in names for names in tool_names_by_agent.values())


def test_discovery_prompt_returns_structured_candidate_summaries():
    subagent = create_paper_claw_subagents()[0]
    prompt = subagent["system_prompt"]

    assert "Do not confirm, upsert, or claim that an external candidate is active" in prompt
    assert "looks like a full paper title" in prompt
    assert "preserve the full title verbatim" in prompt
    assert "even when it is not quoted" in prompt
    assert "never shorten it to the acronym, prefix, or leading phrase" in prompt
    assert "full paper title plus an abbreviation" in prompt
    assert "search the full title first with title mode" in prompt
    assert "structured candidate summary" in prompt
    assert "exact search_session_id" in prompt
    assert "exact candidate_id" in prompt
    assert "Use field name candidate_id" in prompt
    assert "paper_id only when present on a local persisted paper" in prompt
    assert "needs_user_confirmation" in prompt
    assert "ambiguous" in prompt
    assert "recommend_paper_candidates" not in prompt
    assert "frontend candidate picker" not in prompt
    assert "candidate_refs" not in prompt
    assert "interrupt_on" not in subagent


def test_ingestion_prompt_prepares_artifacts_and_processes_documents():
    subagent = create_paper_claw_subagents()[1]

    assert "get_paper_pipeline_status(include_metadata=True)" in subagent["system_prompt"]
    assert "extract the arXiv id" in subagent["system_prompt"]
    assert "https://arxiv.org/src/{id}" in subagent["system_prompt"]
    assert "download_paper_pdf_from_url" in subagent["system_prompt"]
    assert "call ingest_paper_document exactly once" in subagent["system_prompt"]
    assert "returns one status: ready, parse_failed, or processing_failed" in subagent["system_prompt"]
    assert "frontend-ready markdown" in subagent["system_prompt"]
    assert "structured PaperReference rows" in subagent["system_prompt"]
    assert "must not be described as retrieval chunks or embedding content" in subagent["system_prompt"]
    assert "waiting_for_user_upload" in subagent["system_prompt"]
    assert "parse_failed" in subagent["system_prompt"]
    assert "processing_failed" in subagent["system_prompt"]


def test_main_prompt_routes_reports_only_for_explicit_reading_reports():
    assert "own all routing decisions" in PAPER_CLAW_SYSTEM_PROMPT
    assert "only when the user explicitly asks to generate a persisted reading report" in PAPER_CLAW_SYSTEM_PROMPT
    assert "Do not use the report specialist for ordinary paper QA" in PAPER_CLAW_SYSTEM_PROMPT
    assert "multiple times with decomposed subquestions" in PAPER_CLAW_SYSTEM_PROMPT
    assert "answer the user yourself using only returned evidence" in PAPER_CLAW_SYSTEM_PROMPT
    assert "Report language defaults to the configured report language" in PAPER_CLAW_SYSTEM_PROMPT
    assert "looks like a full paper title" in PAPER_CLAW_SYSTEM_PROMPT
    assert "even if it is not quoted" in PAPER_CLAW_SYSTEM_PROMPT
    assert "do not shorten it to an acronym, prefix, or leading phrase" in PAPER_CLAW_SYSTEM_PROMPT
    assert "structured candidate summaries" in PAPER_CLAW_SYSTEM_PROMPT
    assert "Do not treat a search candidate id as a paper id" in PAPER_CLAW_SYSTEM_PROMPT
    assert "ask the user in normal chat to confirm one candidate" in PAPER_CLAW_SYSTEM_PROMPT
    assert "include the exact search_session_id and candidate_id" in PAPER_CLAW_SYSTEM_PROMPT
    assert "call confirm_paper_candidate with an exact search_session_id and candidate_id" in PAPER_CLAW_SYSTEM_PROMPT
    assert "Never guess default ids such as 1" in PAPER_CLAW_SYSTEM_PROMPT
    assert "update_paper_metadata" in PAPER_CLAW_SYSTEM_PROMPT
    assert "Before calling update_paper_metadata, explain" in PAPER_CLAW_SYSTEM_PROMPT
    assert "ask for user confirmation" in PAPER_CLAW_SYSTEM_PROMPT
    assert "Do not call update_paper_metadata until the user approves" in PAPER_CLAW_SYSTEM_PROMPT
    assert "do not use update_paper_metadata to confirm search candidates" in PAPER_CLAW_SYSTEM_PROMPT
    assert "paper_candidates_recommended" not in PAPER_CLAW_SYSTEM_PROMPT
    assert "candidate refs" not in PAPER_CLAW_SYSTEM_PROMPT


def test_evidence_prompt_requires_multi_retrieval_structured_pack():
    subagent = create_paper_claw_subagents()[2]
    prompt = subagent["system_prompt"]

    assert "Decompose complex questions" in prompt
    assert "retrieve_paper_evidence multiple times" in prompt
    assert "Deduplicate by chunk_id" in prompt
    assert "rerank" in prompt
    assert "structured evidence pack" in prompt
    assert "strength direct/indirect/contextual/weak" in prompt
    assert "Do not write the final user-facing answer" in prompt


def test_report_prompt_prepares_and_validates_service_generation():
    subagent = create_paper_claw_subagents()[3]
    prompt = subagent["system_prompt"]

    assert "explicit reading report generation requests" in prompt
    assert "Call get_paper_pipeline_status before generation" in prompt
    assert "no processed cleaned body is ready" in prompt
    assert "Do not manually write report markdown" in prompt
    assert "Call generate_paper_report with the orchestrator instruction" in prompt
    assert "configured report language" in prompt
    assert "pass output_language only when the user explicitly overrides the language" in prompt
    assert "validation metadata" in prompt


def test_agent_factory_constructs_without_external_model_call():
    agent = create_paper_claw_agent(FakeListChatModel(responses=["ok"]))

    assert hasattr(agent, "invoke")
    assert hasattr(agent, "stream")



def test_agent_factory_interrupts_on_metadata_update(monkeypatch):
    calls = []

    def fake_create_deep_agent(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(invoke=lambda *_args, **_kwargs: None, stream=lambda *_args, **_kwargs: iter(()))

    monkeypatch.setattr(main_agent_module, "create_deep_agent", fake_create_deep_agent)

    create_paper_claw_agent(FakeListChatModel(responses=["ok"]))

    assert calls[0]["interrupt_on"] == {"update_paper_metadata": {"allowed_decisions": ["approve", "edit", "reject"]}}


def test_checkpoint_connection_string_uses_psycopg_driver_url():
    assert (
        _psycopg_connection_string("postgresql+psycopg://paper_claw:paper_claw@localhost:5432/paper_claw")
        == "postgresql://paper_claw:paper_claw@localhost:5432/paper_claw"
    )


def test_json_safe_serializes_model_classes_without_calling_model_dump():
    class ToolArgs(BaseModel):
        query: str

    assert _json_safe({"args_schema": ToolArgs}) == {"args_schema": "ToolArgs"}


def test_active_paper_system_info_is_inserted_before_latest_user_message():
    request = ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        messages=[AIMessage(content="previous"), HumanMessage(content="question")],
        runtime=SimpleNamespace(context=PaperClawContext(active_paper_system_info="System info: Active paper is #1.")),
    )

    messages = _messages_with_active_paper_info(request)

    assert [message.type for message in messages] == ["ai", "system", "human"]
    assert messages[1].content == "System info: Active paper is #1."
    assert request.messages == [AIMessage(content="previous"), HumanMessage(content="question")]


def test_tool_middleware_binds_runtime_context():
    seen = []
    request = SimpleNamespace(
        runtime=SimpleNamespace(context=PaperClawContext(thread_id=12, active_paper_id=56)),
        tool_call={"id": "call-1", "args": {}},
        tool=SimpleNamespace(name="fake_tool"),
    )

    def handler(_request):
        seen.append(current_tool_context())
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = record_tool_event_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert seen == [PaperClawContext(thread_id=12, active_paper_id=56)]
    assert current_tool_context() is None


def test_tool_middleware_marks_run_failed_for_task_tool_error(session, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    run = AgentRun(workflow=WorkflowName.paper_qa.value, status=RunStatus.running.value)
    session.add(run)
    session.commit()
    request = SimpleNamespace(
        runtime=SimpleNamespace(context=PaperClawContext(run_id=run.id)),
        tool_call={"id": "call-1", "args": {}},
        tool=SimpleNamespace(name="task"),
    )

    def handler(_request):
        raise RuntimeError("peer closed connection without sending complete message body")

    set_tool_session_factory(factory)
    try:
        with pytest.raises(RuntimeError):
            record_tool_event_call(request, handler)
    finally:
        set_tool_session_factory(None)

    session.refresh(run)
    assert run.status == RunStatus.failed.value
    assert run.error_message == "peer closed connection without sending complete message body"
    assert [event.event_type for event in run.events] == [
        "agent_tool_call_started",
        "agent_tool_call_failed",
        "agent_message_failed",
    ]



def test_model_middleware_forwards_runtime_context(monkeypatch):
    calls = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("backend.agents.model.ChatOpenAI", FakeChatOpenAI)
    request = SimpleNamespace(
        runtime=SimpleNamespace(
            context=PaperClawContext(
                model="openai:gpt-4o-mini",
                api_key="key",
                base_url="https://example.test/v1",
                temperature=0.3,
                max_tokens=123,
                timeout=45,
                max_retries=4,
                extra_body={"thinking": {"type": "disabled"}},
                rate_limiter="limiter",
            )
        ),
        model=None,
    )

    apply_runtime_model(request)

    assert isinstance(request.model, FakeChatOpenAI)
    assert calls[0] == {
        "model": "openai:gpt-4o-mini",
        "api_key": "key",
        "base_url": "https://example.test/v1",
        "temperature": 0.3,
        "max_tokens": 123,
        "timeout": 45,
        "max_retries": 4,
        "rate_limiter": "limiter",
        "extra_body": {"thinking": {"type": "disabled"}},
    }
