from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Message, Thread
from backend.db.types import ThreadStatus


class ThreadRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, title: str, **values: object) -> Thread:
        thread = Thread(title=title, **values)
        self.session.add(thread)
        self.session.flush()
        return thread

    def get(self, thread_id: int) -> Thread | None:
        return self.session.get(Thread, thread_id)

    def list(self, *, include_archived: bool = False) -> list[Thread]:
        statement = select(Thread).order_by(Thread.updated_at.desc())
        if not include_archived:
            statement = statement.where(Thread.status == ThreadStatus.active.value)
        return list(self.session.scalars(statement))

    def archive(self, thread_id: int) -> Thread | None:
        thread = self.get(thread_id)
        if thread is None:
            return None
        thread.status = ThreadStatus.archived.value
        self.session.flush()
        return thread

    def add_message(self, thread_id: int, role: str, content_text: str | None = None, **values: object) -> Message:
        message = Message(thread_id=thread_id, role=role, content_text=content_text, created_at=datetime.now().astimezone(), **values)
        self.session.add(message)
        self.session.flush()
        return message
