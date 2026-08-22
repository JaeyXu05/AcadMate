from __future__ import annotations

from backend.db.models import Paper
from backend.db.repositories import PaperRepository
from backend.db.types import IdentifierType
from backend.schemas import PaperSearchResult
from backend.schemas import PaperIdentifierInput, PaperMetadataPatch, PaperSourceRecordPatch
from backend.services.papers import find_paper_by_identifier, normalize_identifier, search_papers_by_title, search_papers_catalog, update_paper_metadata, upsert_paper_from_search_result


def test_normalize_identifier():
    assert normalize_identifier(IdentifierType.doi.value, "https://doi.org/10.1000/ABC.") == "10.1000/abc"
    assert normalize_identifier(IdentifierType.arxiv.value, "https://arxiv.org/abs/2401.00001v2") == "2401.00001"
    assert normalize_identifier(IdentifierType.openalex.value, "https://openalex.org/W123") == "W123"


def test_upsert_paper_from_search_result_deduplicates_by_identifier(session):
    first = PaperSearchResult(
        source="arxiv",
        source_record_id="2401.00001",
        title="First title",
        abstract="abstract",
        authors=["A"],
        year=2024,
        doi="10.1000/example",
        arxiv_id="2401.00001v1",
        landing_page_url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
    )
    second = first.model_copy(update={"title": "Updated title", "arxiv_id": "2401.00001v2"})

    paper = upsert_paper_from_search_result(session, first)
    same_paper = upsert_paper_from_search_result(session, second)

    assert same_paper.id == paper.id
    assert same_paper.title == "Updated title"
    assert find_paper_by_identifier(session, IdentifierType.doi.value, "doi:10.1000/EXAMPLE").id == paper.id
    assert find_paper_by_identifier(session, IdentifierType.arxiv.value, "2401.00001v3").id == paper.id
    assert len(session.query(Paper).all()) == 1


def test_update_paper_metadata_updates_allowlisted_fields_without_clearing_omitted(session):
    paper = Paper(title="Original Title", abstract="Original abstract", authors_json=["A"])
    session.add(paper)
    session.commit()

    result = update_paper_metadata(
        session,
        paper_id=paper.id,
        metadata=PaperMetadataPatch(year=2024, venue="EMNLP", best_pdf_url="https://example.com/paper.pdf"),
        reason="metadata enrichment",
    )

    assert result["status"] == "updated"
    assert {item["field"] for item in result["changed_fields"]} == {"year", "venue", "best_pdf_url"}
    assert paper.title == "Original Title"
    assert paper.abstract == "Original abstract"
    assert paper.authors_json == ["A"]
    assert paper.year == 2024
    assert paper.venue == "EMNLP"
    assert paper.best_pdf_url == "https://example.com/paper.pdf"



def test_update_paper_metadata_ignores_none_values(session):
    paper = Paper(title="Original Title", abstract="Original abstract")
    session.add(paper)
    session.commit()

    result = update_paper_metadata(session, paper_id=paper.id, metadata=PaperMetadataPatch(title=None, venue="Venue"))

    assert result["status"] == "updated"
    assert paper.title == "Original Title"
    assert paper.abstract == "Original abstract"
    assert paper.venue == "Venue"



def test_update_paper_metadata_adds_normalized_identifier_and_source_record(session):
    paper = Paper(title="Dual-Space Knowledge Distillation for Large Language Models")
    session.add(paper)
    session.commit()

    result = update_paper_metadata(
        session,
        paper_id=paper.id,
        identifiers=[PaperIdentifierInput(identifier_type=IdentifierType.arxiv.value, identifier_value="https://arxiv.org/abs/2406.17328v3")],
        source_records=[
            PaperSourceRecordPatch(
                source="arxiv",
                source_record_id="2406.17328v3",
                source_url="https://arxiv.org/abs/2406.17328v3",
                is_primary=True,
                raw={"pdf_url": "https://arxiv.org/pdf/2406.17328v3"},
            )
        ],
    )

    assert result["status"] == "updated"
    assert result["identifiers_upserted"][0]["identifier_value"] == "2406.17328"
    assert result["source_records_upserted"][0]["source_record_id"] == "2406.17328v3"
    assert find_paper_by_identifier(session, IdentifierType.arxiv.value, "2406.17328v2").id == paper.id



def test_update_paper_metadata_rejects_empty_update(session):
    paper = Paper(title="No-op Paper")
    session.add(paper)
    session.commit()

    try:
        update_paper_metadata(session, paper_id=paper.id, metadata=PaperMetadataPatch())
    except ValueError as exc:
        assert str(exc) == "At least one metadata field, identifier, or source record is required"
    else:
        raise AssertionError("empty update should fail")



def test_search_papers_by_title_exact_and_fuzzy(session):
    session.add(Paper(title="Retrieval Augmented Generation Survey", abstract="x"))
    session.commit()

    exact = search_papers_by_title(session, "retrieval augmented generation survey")
    fuzzy = search_papers_by_title(session, "retrieval generation")

    assert exact[0].title == "Retrieval Augmented Generation Survey"
    assert fuzzy[0].title == "Retrieval Augmented Generation Survey"


def test_upsert_paper_from_search_result_deduplicates_by_title(session):
    session.add(Paper(title="A Title Match", authors_json=["A"]))
    session.commit()

    paper = upsert_paper_from_search_result(
        session,
        PaperSearchResult(
            source="openalex",
            source_record_id="https://openalex.org/W1",
            title="A Title Match",
            authors=["B"],
            openalex_id="https://openalex.org/W1",
        ),
    )

    assert len(session.query(Paper).all()) == 1
    assert paper.authors_json == ["B"]


def test_search_papers_catalog_finds_doi_identifier(session):
    paper = Paper(title="DOI Paper")
    session.add(paper)
    session.flush()
    PaperRepository(session).upsert_identifier(paper.id, IdentifierType.doi.value, "10.1000/example", is_primary=True)
    session.commit()

    results = search_papers_catalog(session, "https://doi.org/10.1000/EXAMPLE", mode="auto")

    assert results[0].title == "DOI Paper"
    assert results[0].source == "local"
    assert results[0].raw["match_reason"] == "doi_match"


def test_search_papers_catalog_finds_arxiv_identifier(session):
    paper = Paper(title="arXiv Paper")
    session.add(paper)
    session.flush()
    PaperRepository(session).upsert_identifier(paper.id, IdentifierType.arxiv.value, "2401.00001", is_primary=True)
    session.commit()

    results = search_papers_catalog(session, "https://arxiv.org/abs/2401.00001v2", mode="auto")

    assert results[0].title == "arXiv Paper"
    assert results[0].raw["match_reason"] == "arxiv_match"


def test_search_papers_catalog_finds_openalex_identifier(session):
    paper = Paper(title="OpenAlex Paper")
    session.add(paper)
    session.flush()
    PaperRepository(session).upsert_identifier(paper.id, IdentifierType.openalex.value, "W123", is_primary=True)
    session.commit()

    results = search_papers_catalog(session, "https://openalex.org/W123", mode="auto")

    assert results[0].title == "OpenAlex Paper"
    assert results[0].raw["match_reason"] == "openalex_match"


def test_search_papers_catalog_keyword_searches_metadata(session):
    session.add(Paper(title="Unrelated", abstract="recursive agent systems", venue="Conference", authors_json=["A"] ))
    session.commit()

    results = search_papers_catalog(session, "recursive agent", mode="keyword")

    assert results[0].title == "Unrelated"
    assert results[0].raw["match_reason"] == "keyword"
