from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from backend.agents.checkpointing import get_agent_checkpointer
from backend.agents.context import PaperClawContext
from backend.agents.memory_store import PaperClawMemoryStore
from backend.agents.model import paper_claw_model_middleware
from backend.agents.prompts import PAPER_CLAW_SYSTEM_PROMPT
from backend.agents.subagents import create_paper_claw_subagents
from backend.agents.tool_events import paper_claw_tool_event_middleware
from backend.tools import MAIN_AGENT_TOOLS

CONFIRM_INTERRUPT = {"allowed_decisions": ["approve", "edit", "reject"]}


def create_paper_claw_agent(
    model: str | BaseChatModel | None = None,
    *,
    checkpointer: Any | None = None,
    backend: Any | None = None,
    store: Any | None = None,
):
    runtime_model = model or FakeListChatModel(responses=["Paper Claw runtime model placeholder."])
    runtime_checkpointer = checkpointer if checkpointer is not None else None if model is not None else get_agent_checkpointer()
    runtime_store = store or PaperClawMemoryStore()
    runtime_backend = backend or CompositeBackend(
        default=StateBackend(),
        routes={"/memories/": StoreBackend(store=runtime_store, namespace=lambda _runtime: ("paper-claw", "filesystem"))},
    )
    return create_deep_agent(
        model=runtime_model,
        tools=MAIN_AGENT_TOOLS,
        system_prompt=PAPER_CLAW_SYSTEM_PROMPT,
        middleware=[paper_claw_tool_event_middleware, paper_claw_model_middleware],
        subagents=create_paper_claw_subagents(),
        context_schema=PaperClawContext,
        checkpointer=runtime_checkpointer,
        backend=runtime_backend,
        store=runtime_store,
        interrupt_on={"update_paper_metadata": CONFIRM_INTERRUPT},
        name="paper-claw",
    )
