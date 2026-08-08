from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from backend.db.models import (
    DocumentChunk,
    DocumentSection,
    Paper,
    PaperReference,
    ParsedDocument,
    ParseJob,
    ParserEvent,
    ProcessedDocument,
)
from backend.db.types import ProcessedDocumentStatus, SectionRole


def create_processed_document(session):
    paper = Paper(title="Fixture Paper")
    session.add(paper)
    session.flush()
    parse_job = ParseJob(paper_id=paper.id, status="succeeded")
    session.add(parse_job)
    session.flush()
    parsed = ParsedDocument(paper_id=paper.id, parse_job_id=parse_job.id, parser_kind="fixture")
    session.add(parsed)
    session.flush()
    processed = ProcessedDocument(
        paper_id=paper.id,
        parsed_document_id=parsed.id,
        parse_job_id=parse_job.id,
        status=ProcessedDocumentStatus.ready.value,
    )
    session.add(processed)
    session.flush()
    return paper, parse_job, parsed, processed


def test_parse_document_section_chunk_reference(session):
    paper, parse_job, parsed, processed = create_processed_document(session)
    event = ParserEvent(
        parse_job_id=parse_job.id,
        paper_id=paper.id,
        sequence=1,
        event_type="started",
        level="info",
        created_at=datetime.now().astimezone(),
    )
    section = DocumentSection(
        processed_document_id=processed.id,
        section_index=1,
        role=SectionRole.abstract.value,
        cleaned_text="abstract",
    )
    chunk = DocumentChunk(
        processed_document_id=processed.id,
        chunk_key="abstract-1",
        chunk_index=1,
        role=SectionRole.abstract.value,
        content_text="abstract",
        embedding=[0.1, 0.2, 0.3],
        embedding_dimension=3,
    )
    reference = PaperReference(processed_document_id=processed.id, reference_index=1, raw_text="Reference")
    session.add_all([event, section, chunk, reference])
    session.commit()

    assert processed.sections[0].cleaned_text == "abstract"
    assert processed.chunks[0].embedding == [0.1, 0.2, 0.3]
    assert processed.references[0].raw_text == "Reference"


def test_processed_document_version_unique(session):
    paper, parse_job, parsed, _ = create_processed_document(session)
    session.add(ProcessedDocument(paper_id=paper.id, parsed_document_id=parsed.id, parse_job_id=parse_job.id, version=1))
    with pytest.raises(IntegrityError):
        session.commit()
