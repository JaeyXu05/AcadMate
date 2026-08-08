from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.db.models import SearchCandidate, SearchSession
from backend.db.types import SearchStatus


class SearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(self, query_text: str, **values: object) -> SearchSession:
        search_session = SearchSession(query_text=query_text, **values)
        self.session.add(search_session)
        self.session.flush()
        return search_session

    def add_candidate(self, search_session_id: int, rank: int, source: str, title: str, **values: object) -> SearchCandidate:
        candidate = SearchCandidate(
            search_session_id=search_session_id,
            rank=rank,
            source=source,
            title=title,
            created_at=datetime.now().astimezone(),
            **values,
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def confirm_candidate(self, search_session_id: int, candidate_id: int) -> SearchSession:
        search_session = self.session.get_one(SearchSession, search_session_id)
        search_session.selected_candidate_id = candidate_id
        search_session.status = SearchStatus.confirmed.value
        self.session.flush()
        return search_session
