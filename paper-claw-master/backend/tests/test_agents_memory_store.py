from __future__ import annotations

from backend.agents.memory_store import PaperClawMemoryStore
from backend.db.models import Memory
from backend.db.session import make_session_factory
from backend.db.types import MemoryScope, MemoryStatus, MemoryType


def test_memory_store_writes_reads_and_deletes_memories(engine, session):
    store = PaperClawMemoryStore(make_session_factory(engine))

    store.put(("paper-claw", "filesystem"), "/memories/user/preferences.md", {"content": "Use Chinese.", "encoding": "utf-8"})

    item = store.get(("paper-claw", "filesystem"), "/memories/user/preferences.md")
    assert item is not None
    assert item.value["content"] == "Use Chinese."

    memory = session.query(Memory).filter_by(path="/memories/user/preferences.md").one()
    assert memory.content_text == "Use Chinese."
    assert memory.memory_type == MemoryType.user_preference.value
    assert memory.scope_type == MemoryScope.global_.value

    store.delete(("paper-claw", "filesystem"), "/memories/user/preferences.md")
    session.refresh(memory)
    assert memory.status == MemoryStatus.deleted.value


def test_memory_store_maps_paper_memory_metadata(engine, session):
    store = PaperClawMemoryStore(make_session_factory(engine))

    store.put(("paper-claw", "filesystem"), "/memories/papers/42/notes.md", {"content": "Important method note.", "encoding": "utf-8"})

    memory = session.query(Memory).filter_by(path="/memories/papers/42/notes.md").one()
    assert memory.memory_type == MemoryType.paper_note.value
    assert memory.scope_type == MemoryScope.paper.value
    assert memory.scope_id == "42"
    assert memory.paper_id is None


def test_memory_store_lists_memories(engine, session):
    store = PaperClawMemoryStore(make_session_factory(engine))
    namespace = ("paper-claw", "filesystem")
    store.put(namespace, "/memories/user/preferences.md", {"content": "A", "encoding": "utf-8"})
    store.put(namespace, "/memories/research/index.md", {"content": "B", "encoding": "utf-8"})

    items = store.search(namespace, limit=10)

    assert [item.key for item in items] == ["/memories/research/index.md", "/memories/user/preferences.md"]
