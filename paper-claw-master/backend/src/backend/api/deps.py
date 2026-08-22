from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from backend.db.session import get_session


def get_db_session() -> Iterator[Session]:
    with get_session() as session:
        yield session
