from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Iterable

from langgraph.store.base import BaseStore, GetOp, Item, ListNamespacesOp, Op, PutOp, Result, SearchItem, SearchOp
from sqlalchemy.orm import sessionmaker

from backend.db.models import Memory
from backend.db.repositories import MemoryRepository
from backend.db.session import SessionLocal
from backend.db.types import MemoryScope, MemorySource, MemoryStatus, MemoryType


class PaperClawMemoryStore(BaseStore):
    def __init__(self, session_factory: sessionmaker = SessionLocal) -> None:
        self.session_factory = session_factory

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        with self.session_factory() as session:
            repo = MemoryRepository(session)
            results: list[Result] = []
            for op in ops:
                if isinstance(op, GetOp):
                    memory = repo.get_by_path(_store_path(op.key))
                    results.append(_item(op.namespace, memory) if memory is not None else None)
                elif isinstance(op, PutOp):
                    if op.value is None:
                        repo.soft_delete_by_path(_store_path(op.key))
                        results.append(None)
                    else:
                        memory = repo.upsert_by_path(
                            _store_path(op.key),
                            _content_text(op.value),
                            title=_title_from_path(op.key),
                            memory_type=_memory_type(op.key),
                            scope_type=_scope_type(op.key),
                            scope_id=_scope_id(op.key),
                            paper_id=None,
                            content_json=op.value,
                            source=MemorySource.agent.value,
                            status=MemoryStatus.active.value,
                            metadata_json={"namespace": list(op.namespace)},
                        )
                        results.append(_item(op.namespace, memory))
                elif isinstance(op, SearchOp):
                    memories = repo.list(path_prefix=_store_path_prefix(op.namespace_prefix), limit=op.limit, offset=op.offset)
                    results.append([_search_item(op.namespace_prefix, memory) for memory in memories if _matches_filter(memory, op.filter)])
                elif isinstance(op, ListNamespacesOp):
                    results.append(_list_namespaces(repo, op))
                else:
                    raise NotImplementedError(f"Unsupported store operation: {type(op).__name__}")
            session.commit()
            return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        return await asyncio.to_thread(self.batch, list(ops))


def _store_path(key: str) -> str:
    return key if key.startswith("/memories/") else f"/memories/{key.lstrip('/')}"


def _store_path_prefix(namespace_prefix: tuple[str, ...]) -> str:
    return "/memories/"


def _content_text(value: dict[str, Any]) -> str:
    content = value.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return ""


def _item(namespace: tuple[str, ...], memory: Memory) -> Item:
    return Item(
        namespace=namespace,
        key=memory.path,
        value=memory.content_json or {"content": memory.content_text, "encoding": "utf-8"},
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _search_item(namespace: tuple[str, ...], memory: Memory) -> SearchItem:
    return SearchItem(
        namespace=namespace,
        key=memory.path,
        value=memory.content_json or {"content": memory.content_text, "encoding": "utf-8"},
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _list_namespaces(repo: MemoryRepository, op: ListNamespacesOp) -> list[tuple[str, ...]]:
    namespaces = {tuple(_namespace_for_path(memory.path)) for memory in repo.list(limit=10000)}
    filtered = [namespace for namespace in namespaces if _namespace_matches(namespace, op)]
    filtered.sort()
    if op.max_depth is not None:
        filtered = [namespace[: op.max_depth] for namespace in filtered]
        filtered = sorted(set(filtered))
    return filtered[op.offset : op.offset + op.limit]


def _namespace_for_path(path: str) -> list[str]:
    parts = path.strip("/").split("/")
    return parts[:-1] if len(parts) > 1 else parts


def _namespace_matches(namespace: tuple[str, ...], op: ListNamespacesOp) -> bool:
    if not op.match_conditions:
        return True
    for condition in op.match_conditions:
        path = tuple(condition.path)
        if condition.match_type == "prefix" and not namespace[: len(path)] == path:
            return False
        if condition.match_type == "suffix" and not namespace[-len(path) :] == path:
            return False
    return True


def _matches_filter(memory: Memory, filter_: dict[str, Any] | None) -> bool:
    if not filter_:
        return True
    value = memory.content_json or {}
    return all(value.get(key) == expected for key, expected in filter_.items())


def _title_from_path(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _memory_type(path: str) -> str:
    if path.startswith("/memories/user/preferences"):
        return MemoryType.user_preference.value
    if path.startswith("/memories/user/instructions"):
        return MemoryType.instruction.value
    if path.startswith("/memories/papers/"):
        return MemoryType.paper_note.value
    if path.startswith("/memories/research/projects/"):
        return MemoryType.project_state.value
    return MemoryType.research_note.value


def _scope_type(path: str) -> str:
    if path.startswith("/memories/papers/"):
        return MemoryScope.paper.value
    if path.startswith("/memories/research/projects/"):
        return MemoryScope.project.value
    return MemoryScope.global_.value


def _scope_id(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[:2] == ["memories", "papers"]:
        return parts[2]
    if len(parts) >= 4 and parts[:3] == ["memories", "research", "projects"]:
        return parts[3]
    return None


def _paper_id(path: str) -> int | None:
    scope_id = _scope_id(path)
    if scope_id is None or not path.startswith("/memories/papers/"):
        return None
    try:
        return int(scope_id)
    except ValueError:
        return None
