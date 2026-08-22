from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from backend.db.models import Paper, PaperIdentifier, PaperSourceRecord
from backend.db.types import IdentifierType, PaperSource


def test_paper_identifier_and_source_record(session):
    paper = Paper(title="Fixture Paper", authors_json=["A"], keywords_json=["k"], categories_json=["cs.AI"])
    session.add(paper)
    session.flush()

    identifier = PaperIdentifier(
        paper_id=paper.id,
        identifier_type=IdentifierType.manual.value,
        identifier_value="fixture:paper",
        created_at=datetime.now().astimezone(),
    )
    source_record = PaperSourceRecord(
        paper_id=paper.id,
        source=PaperSource.manual_upload.value,
        source_record_id="fixture:paper",
        retrieved_at=datetime.now().astimezone(),
        raw_json={"ok": True},
    )
    session.add_all([identifier, source_record])
    session.commit()

    assert paper.identifiers[0].identifier_value == "fixture:paper"
    assert paper.source_records[0].raw_json == {"ok": True}


def test_paper_identifier_unique(session):
    paper = Paper(title="Fixture Paper")
    session.add(paper)
    session.flush()
    now = datetime.now().astimezone()
    session.add_all([
        PaperIdentifier(paper_id=paper.id, identifier_type=IdentifierType.manual.value, identifier_value="fixture:dup", created_at=now),
        PaperIdentifier(paper_id=paper.id, identifier_type=IdentifierType.manual.value, identifier_value="fixture:dup", created_at=now),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
