from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.db.models import (
    DocumentChunk,
    DocumentSection,
    ParsedDocument,
    PaperReference,
    ParseJob,
    ParserEvent,
    ProcessedDocument,
)


class ParsingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_parse_job(self, paper_id: int, **values: object) -> ParseJob:
        job = ParseJob(paper_id=paper_id, **values)
        self.session.add(job)
        self.session.flush()
        return job

    def append_parser_event(self, parse_job_id: int, paper_id: int, sequence: int, event_type: str, level: str = "info") -> ParserEvent:
        event = ParserEvent(
            parse_job_id=parse_job_id,
            paper_id=paper_id,
            sequence=sequence,
            event_type=event_type,
            level=level,
            created_at=datetime.now().astimezone(),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def create_parsed_document(self, paper_id: int, parse_job_id: int, parser_kind: str, **values: object) -> ParsedDocument:
        document = ParsedDocument(paper_id=paper_id, parse_job_id=parse_job_id, parser_kind=parser_kind, **values)
        self.session.add(document)
        self.session.flush()
        return document

    def create_processed_document(self, paper_id: int, parsed_document_id: int, parse_job_id: int, **values: object) -> ProcessedDocument:
        document = ProcessedDocument(
            paper_id=paper_id,
            parsed_document_id=parsed_document_id,
            parse_job_id=parse_job_id,
            **values,
        )
        self.session.add(document)
        self.session.flush()
        return document

    def add_section(self, processed_document_id: int, section_index: int, **values: object) -> DocumentSection:
        section = DocumentSection(processed_document_id=processed_document_id, section_index=section_index, **values)
        self.session.add(section)
        self.session.flush()
        return section

    def add_chunk(self, processed_document_id: int, chunk_key: str, chunk_index: int, content_text: str, **values: object) -> DocumentChunk:
        chunk = DocumentChunk(
            processed_document_id=processed_document_id,
            chunk_key=chunk_key,
            chunk_index=chunk_index,
            content_text=content_text,
            **values,
        )
        self.session.add(chunk)
        self.session.flush()
        return chunk

    def add_reference(self, processed_document_id: int, reference_index: int, raw_text: str, **values: object) -> PaperReference:
        reference = PaperReference(
            processed_document_id=processed_document_id,
            reference_index=reference_index,
            raw_text=raw_text,
            **values,
        )
        self.session.add(reference)
        self.session.flush()
        return reference
