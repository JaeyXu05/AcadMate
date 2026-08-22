from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import Session

from backend.db.models import Paper, Thread
from backend.db.session import get_session
from backend.schemas import PaperClawContext

SessionFactory = Callable[[], Session]

_session_factory: SessionFactory | None = None
_runtime_context: ContextVar[PaperClawContext | None] = ContextVar("paper_claw_tool_runtime_context", default=None)


def set_tool_session_factory(factory: SessionFactory | None) -> None:
    global _session_factory
    _session_factory = factory


@contextmanager
def tool_runtime_context(context: PaperClawContext) -> Iterator[None]:
    token = _runtime_context.set(context)
    try:
        yield
    finally:
        _runtime_context.reset(token)


def current_tool_context() -> PaperClawContext | None:
    return _runtime_context.get()


def resolve_active_paper_id(session: Session, explicit_paper_id: int | None = None) -> int:
    if explicit_paper_id is not None:
        if session.get(Paper, explicit_paper_id) is None:
            raise ValueError(f"Paper {explicit_paper_id} not found")
        return explicit_paper_id
    context = current_tool_context()
    if context is not None:
        if context.active_paper_id is not None:
            if session.get(Paper, context.active_paper_id) is None:
                raise ValueError(f"Paper {context.active_paper_id} not found")
            return context.active_paper_id
        if context.thread_id is not None:
            thread = session.get(Thread, context.thread_id)
            if thread is not None and thread.current_focus_paper_id is not None:
                if session.get(Paper, thread.current_focus_paper_id) is None:
                    raise ValueError(f"Paper {thread.current_focus_paper_id} not found")
                return thread.current_focus_paper_id
    raise ValueError("No active paper. Ask the user to select or confirm a paper first.")


@contextmanager
def tool_session() -> Iterator[Session]:
    if _session_factory is not None:
        session = _session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return
    with get_session() as session:
        yield session
