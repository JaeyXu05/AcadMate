from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Memory
from backend.db.types import MemoryStatus


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, path: str, content_text: str, **values: object) -> Memory:
        memory = Memory(path=path, content_text=content_text, **values)
        self.session.add(memory)
        self.session.flush()
        return memory

    def get(self, memory_id: int) -> Memory | None:
        return self.session.get(Memory, memory_id)

    def get_by_path(self, path: str, *, include_deleted: bool = False) -> Memory | None:
        statement = select(Memory).where(Memory.path == path)
        if not include_deleted:
            statement = statement.where(Memory.status != MemoryStatus.deleted.value)
        memory = self.session.scalar(statement)
        if memory is not None:
            memory.last_accessed_at = datetime.now().astimezone()
            self.session.flush()
        return memory

    def list(
        self,
        *,
        path_prefix: str | None = None,
        status: str = MemoryStatus.active.value,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        statement = select(Memory)
        if path_prefix is not None:
            statement = statement.where(Memory.path.startswith(path_prefix))
        if status is not None:
            statement = statement.where(Memory.status == status)
        statement = statement.order_by(Memory.path).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def upsert_by_path(self, path: str, content_text: str, **values: object) -> Memory:
        memory = self.get_by_path(path, include_deleted=True)
        if memory is None:
            return self.create(path, content_text, **values)
        memory.content_text = content_text
        for key, value in values.items():
            setattr(memory, key, value)
        if memory.status == MemoryStatus.deleted.value:
            memory.status = MemoryStatus.active.value
        self.session.flush()
        return memory

    def soft_delete_by_path(self, path: str) -> bool:
        memory = self.get_by_path(path, include_deleted=True)
        if memory is None:
            return False
        memory.status = MemoryStatus.deleted.value
        self.session.flush()
        return True
