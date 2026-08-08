from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Paper, PaperIdentifier, PaperSourceRecord


class PaperRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, title: str, **values: object) -> Paper:
        paper = Paper(title=title, **values)
        self.session.add(paper)
        self.session.flush()
        return paper

    def get(self, paper_id: int) -> Paper | None:
        return self.session.get(Paper, paper_id)

    def list(self) -> list[Paper]:
        return list(self.session.scalars(select(Paper).order_by(Paper.created_at.desc())))

    def upsert_identifier(self, paper_id: int, identifier_type: str, identifier_value: str, **values: object) -> PaperIdentifier:
        identifier = self.session.scalar(
            select(PaperIdentifier).where(
                PaperIdentifier.identifier_type == identifier_type,
                PaperIdentifier.identifier_value == identifier_value,
            )
        )
        if identifier is None:
            identifier = PaperIdentifier(
                paper_id=paper_id,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                created_at=datetime.now().astimezone(),
                **values,
            )
            self.session.add(identifier)
        else:
            identifier.paper_id = paper_id
            for key, value in values.items():
                setattr(identifier, key, value)
        self.session.flush()
        return identifier

    def upsert_source_record(self, paper_id: int, source: str, source_record_id: str | None, **values: object) -> PaperSourceRecord:
        source_record = None
        if source_record_id is not None:
            source_record = self.session.scalar(
                select(PaperSourceRecord).where(
                    PaperSourceRecord.source == source,
                    PaperSourceRecord.source_record_id == source_record_id,
                )
            )
        if source_record is None:
            source_record = PaperSourceRecord(paper_id=paper_id, source=source, source_record_id=source_record_id, **values)
            self.session.add(source_record)
        else:
            source_record.paper_id = paper_id
            for key, value in values.items():
                setattr(source_record, key, value)
        self.session.flush()
        return source_record
