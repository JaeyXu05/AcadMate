from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from threading import RLock
from typing import Protocol

from backend.mentor_workflow.schemas import AgentMessage, WorkflowEventType

EventHandler = Callable[[AgentMessage], None]


class EventBus(Protocol):
    def publish(self, message: AgentMessage) -> None: ...

    def subscribe(
        self, event_type: WorkflowEventType, handler: EventHandler
    ) -> None: ...

    def list_events(self, trace_id: str) -> list[AgentMessage]: ...


class InMemoryEventBus:
    """Thread-safe process-local bus used by the first workflow version and tests."""

    def __init__(self) -> None:
        self._handlers: dict[WorkflowEventType, list[EventHandler]] = defaultdict(list)
        self._events: list[AgentMessage] = []
        self._lock = RLock()

    def publish(self, message: AgentMessage) -> None:
        with self._lock:
            self._events.append(message.model_copy(deep=True))
            handlers = list(self._handlers.get(message.event_type, []))
        for handler in handlers:
            handler(message.model_copy(deep=True))

    def subscribe(self, event_type: WorkflowEventType, handler: EventHandler) -> None:
        with self._lock:
            self._handlers[event_type].append(handler)

    def list_events(self, trace_id: str) -> list[AgentMessage]:
        with self._lock:
            return [
                event.model_copy(deep=True)
                for event in self._events
                if event.trace_id == trace_id
            ]
