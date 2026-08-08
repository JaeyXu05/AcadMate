from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Paper, PaperIdentifier, Thread
from backend.db.repositories import PaperRepository, ParsingRepository, ThreadRepository
from backend.db.types import IdentifierType, PaperSource, ProcessedDocumentStatus, SectionRole


FIXTURE_PAPERS = [
    {
        "title": "Fixture Survey of Retrieval-Augmented Research Assistants",
        "year": 2024,
        "venue": "Paper Claw Fixtures",
        "abstract": "A fake survey paper for validating local database workflows.",
        "identifier": "fixture:rag-survey-2024",
    },
    {
        "title": "Fixture Method for Evidence-Grounded Paper Reading",
        "year": 2024,
        "venue": "Paper Claw Fixtures",
        "abstract": "A fake method paper for validating parsing and report evidence workflows.",
        "identifier": "fixture:evidence-reading-2024",
    },
    {
        "title": "Fixture Benchmark for Citation-Aware QA",
        "year": 2023,
        "venue": "Paper Claw Fixtures",
        "abstract": "A fake benchmark paper for validating references and QA workflows.",
        "identifier": "fixture:citation-qa-2023",
    },
]


def seed_minimal_database(session: Session) -> None:
    threads = ThreadRepository(session)
    papers = PaperRepository(session)
    parsing = ParsingRepository(session)

    if session.scalar(select(Thread).where(Thread.title == "Fixture database smoke thread")) is None:
        threads.create(title="Fixture database smoke thread", surface="cli", metadata_json={"fixture": True})

    for item in FIXTURE_PAPERS:
        existing = session.scalar(
            select(PaperIdentifier).where(PaperIdentifier.identifier_value == item["identifier"])
        )
        if existing is not None:
            continue

        paper = papers.create(
            title=item["title"],
            abstract=item["abstract"],
            year=item["year"],
            venue=item["venue"],
            authors_json=["Paper Claw Fixture Author"],
            keywords_json=["fixture", "paper-claw"],
            categories_json=["cs.AI"],
            metadata_json={"fixture": True},
        )
        papers.upsert_identifier(paper.id, IdentifierType.manual.value, item["identifier"], is_primary=True)
        papers.upsert_source_record(
            paper.id,
            PaperSource.manual_upload.value,
            item["identifier"],
            raw_json={"fixture": True, "identifier": item["identifier"]},
        )

        parse_job = parsing.create_parse_job(paper.id, status="succeeded", strategy="manual")
        parsed = parsing.create_parsed_document(
            paper.id,
            parse_job.id,
            parser_kind="fixture",
            plain_text=item["abstract"],
            markdown_content=f"# {item['title']}\n\n{item['abstract']}",
            quality_status="usable",
        )
        processed = parsing.create_processed_document(
            paper.id,
            parsed.id,
            parse_job.id,
            status=ProcessedDocumentStatus.ready.value,
            content_text=item["abstract"],
            content_markdown=f"# {item['title']}\n\n{item['abstract']}",
            quality_status="usable",
        )
        section = parsing.add_section(
            processed.id,
            1,
            role=SectionRole.abstract.value,
            heading_path_json=["Abstract"],
            raw_text=item["abstract"],
            cleaned_text=item["abstract"],
        )
        parsing.add_chunk(
            processed.id,
            "abstract-1",
            1,
            item["abstract"],
            role=SectionRole.abstract.value,
            heading_path_json=["Abstract"],
            source_section_ids_json=[section.id],
        )
        parsing.add_reference(
            processed.id,
            1,
            "Fixture Reference. Paper Claw local test data.",
            title="Fixture Reference",
            authors_json=["Paper Claw Fixture Author"],
            year=2024,
        )
