from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from backend.db.models import Paper, PaperIdentifier, PaperSourceRecord
from backend.db.repositories import PaperRepository
from backend.db.types import IdentifierType, PaperSource
from backend.schemas import PaperIdentifierInput, PaperMetadataPatch, PaperSearchResult, PaperSourceRecordPatch

_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_ARXIV_PREFIX_RE = re.compile(r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)", re.IGNORECASE)
_OPENALEX_PREFIX_RE = re.compile(r"^https?://openalex\.org/", re.IGNORECASE)
_VERSION_SUFFIX_RE = re.compile(r"v\d+$", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def normalize_identifier(identifier_type: str, value: str) -> str:
    value = value.strip()
    if identifier_type == IdentifierType.doi.value:
        value = _DOI_PREFIX_RE.sub("", value).strip().lower()
        return value.rstrip(".")
    if identifier_type == IdentifierType.arxiv.value:
        value = _ARXIV_PREFIX_RE.sub("", value).strip()
        value = value.removesuffix(".pdf")
        return _VERSION_SUFFIX_RE.sub("", value).lower()
    if identifier_type == IdentifierType.openalex.value:
        return _OPENALEX_PREFIX_RE.sub("", value).strip().upper()
    if identifier_type == IdentifierType.url.value:
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            return parsed._replace(fragment="").geturl().rstrip("/")
    return value.strip()


def normalize_title(title: str) -> str:
    return _SPACE_RE.sub(" ", title).strip().lower()


def identifiers_from_search_result(result: PaperSearchResult) -> list[PaperIdentifierInput]:
    identifiers: list[PaperIdentifierInput] = []
    if result.doi:
        identifiers.append(PaperIdentifierInput(identifier_type=IdentifierType.doi.value, identifier_value=normalize_identifier(IdentifierType.doi.value, result.doi), is_primary=True))
    if result.arxiv_id:
        identifiers.append(PaperIdentifierInput(identifier_type=IdentifierType.arxiv.value, identifier_value=normalize_identifier(IdentifierType.arxiv.value, result.arxiv_id), is_primary=not identifiers))
    if result.openalex_id:
        identifiers.append(PaperIdentifierInput(identifier_type=IdentifierType.openalex.value, identifier_value=normalize_identifier(IdentifierType.openalex.value, result.openalex_id), is_primary=not identifiers))
    if result.landing_page_url:
        identifiers.append(PaperIdentifierInput(identifier_type=IdentifierType.url.value, identifier_value=normalize_identifier(IdentifierType.url.value, result.landing_page_url), is_primary=False))
    return _dedupe_identifiers(identifiers)


def find_paper_by_identifier(session: Session, identifier_type: str, identifier_value: str) -> Paper | None:
    normalized = normalize_identifier(identifier_type, identifier_value)
    return session.scalar(
        select(Paper)
        .join(PaperIdentifier)
        .where(
            PaperIdentifier.identifier_type == identifier_type,
            PaperIdentifier.identifier_value == normalized,
        )
    )


def search_papers_by_title(session: Session, title: str, limit: int = 10) -> list[Paper]:
    normalized = normalize_title(title)
    if not normalized:
        return []
    exact = list(session.scalars(select(Paper).where(func.lower(Paper.title) == normalized).limit(limit)))
    if exact:
        return exact
    terms = [term for term in normalized.split(" ") if len(term) >= 3][:6]
    if not terms:
        return []
    statement = select(Paper)
    for term in terms:
        statement = statement.where(Paper.title.ilike(f"%{term}%"))
    return list(session.scalars(statement.limit(limit)))


def search_papers_catalog(session: Session, query: str, *, mode: str = "auto", limit: int = 10) -> list[PaperSearchResult]:
    query = query.strip()
    if not query:
        return []
    normalized_mode = mode.lower()
    papers: list[tuple[Paper, str]] = []
    if normalized_mode in {"auto", "identifier", "doi", "arxiv_id", "openalex_id"}:
        papers.extend(_identifier_matches(session, query, normalized_mode))
        if papers and normalized_mode != "auto":
            return _local_results(_dedupe_papers(papers)[:limit])
    if normalized_mode in {"auto", "title"}:
        papers.extend((paper, "title") for paper in search_papers_by_title(session, query, limit=limit))
        if papers and normalized_mode == "title":
            return _local_results(_dedupe_papers(papers)[:limit])
    if normalized_mode in {"auto", "keyword"}:
        papers.extend((paper, "keyword") for paper in _keyword_matches(session, query, limit=limit))
    return _local_results(_dedupe_papers(papers)[:limit])


def upsert_paper_from_search_result(session: Session, result: PaperSearchResult) -> Paper:
    identifiers = identifiers_from_search_result(result)
    for identifier in identifiers:
        paper = find_paper_by_identifier(session, identifier.identifier_type, identifier.identifier_value)
        if paper is not None:
            _update_paper_metadata(paper, result)
            _upsert_paper_links(session, paper, result, identifiers)
            session.flush()
            return paper

    title_matches = search_papers_by_title(session, result.title, limit=1)
    if title_matches:
        paper = title_matches[0]
        _update_paper_metadata(paper, result)
    else:
        paper = PaperRepository(session).create(
            result.title,
            abstract=result.abstract,
            year=result.year,
            venue=result.venue,
            authors_json=result.authors,
            best_pdf_url=result.pdf_url,
            landing_page_url=result.landing_page_url,
            metadata_json={"source": result.source},
        )
    _upsert_paper_links(session, paper, result, identifiers)
    session.flush()
    return paper


def update_paper_metadata(
    session: Session,
    *,
    paper_id: int,
    metadata: PaperMetadataPatch | None = None,
    identifiers: list[PaperIdentifierInput] | None = None,
    source_records: list[PaperSourceRecordPatch] | None = None,
    reason: str | None = None,
) -> dict:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise ValueError(f"Paper {paper_id} not found")

    metadata = metadata or PaperMetadataPatch()
    identifiers = identifiers or []
    source_records = source_records or []
    field_values = metadata.model_dump(exclude_none=True)
    if not field_values and not identifiers and not source_records:
        raise ValueError("At least one metadata field, identifier, or source record is required")

    changed_fields = _apply_paper_metadata_patch(paper, field_values)
    repo = PaperRepository(session)
    identifiers_upserted = []
    for identifier in identifiers:
        normalized_value = normalize_identifier(identifier.identifier_type, identifier.identifier_value)
        row = repo.upsert_identifier(
            paper.id,
            identifier.identifier_type,
            normalized_value,
            is_primary=identifier.is_primary,
        )
        identifiers_upserted.append(
            {
                "id": row.id,
                "identifier_type": row.identifier_type,
                "identifier_value": row.identifier_value,
                "is_primary": row.is_primary,
            }
        )

    source_records_upserted = []
    for source_record in source_records:
        row = repo.upsert_source_record(
            paper.id,
            source_record.source,
            source_record.source_record_id,
            source_url=source_record.source_url,
            retrieved_at=datetime.now().astimezone(),
            is_primary=source_record.is_primary,
            raw_json=source_record.raw,
        )
        source_records_upserted.append(
            {
                "id": row.id,
                "source": row.source,
                "source_record_id": row.source_record_id,
                "source_url": row.source_url,
                "is_primary": row.is_primary,
            }
        )

    session.flush()
    changed = bool(changed_fields or identifiers_upserted or source_records_upserted)
    return {
        "status": "updated" if changed else "no_change",
        "paper_id": paper.id,
        "changed_fields": changed_fields,
        "identifiers_upserted": identifiers_upserted,
        "source_records_upserted": source_records_upserted,
        "reason": reason,
    }



def _apply_paper_metadata_patch(paper: Paper, field_values: dict[str, object]) -> list[dict[str, object]]:
    changed_fields = []
    field_map = {"authors": "authors_json"}
    for field, new_value in field_values.items():
        attr = field_map.get(field, field)
        old_value = getattr(paper, attr)
        if old_value == new_value:
            continue
        setattr(paper, attr, new_value)
        changed_fields.append({"field": field, "old": old_value, "new": new_value})
    return changed_fields



def _identifier_matches(session: Session, query: str, mode: str) -> list[tuple[Paper, str]]:
    candidates: list[tuple[str, str]] = []
    if mode in {"auto", "identifier", "doi"} and _looks_like_doi(query):
        candidates.append((IdentifierType.doi.value, query))
    if mode in {"auto", "identifier", "arxiv_id"} and _looks_like_arxiv(query):
        candidates.append((IdentifierType.arxiv.value, query))
    if mode in {"auto", "identifier", "openalex_id"} and _looks_like_openalex(query):
        candidates.append((IdentifierType.openalex.value, query))
    matches: list[tuple[Paper, str]] = []
    for identifier_type, value in candidates:
        paper = find_paper_by_identifier(session, identifier_type, value)
        if paper is not None:
            matches.append((paper, f"{identifier_type}_match"))
    return matches


def _keyword_matches(session: Session, query: str, *, limit: int) -> list[Paper]:
    terms = [term for term in normalize_title(query).split(" ") if len(term) >= 3][:6]
    if not terms:
        return []
    statement = select(Paper)
    for term in terms:
        pattern = f"%{term}%"
        statement = statement.where(
            or_(
                Paper.title.ilike(pattern),
                Paper.abstract.ilike(pattern),
                Paper.venue.ilike(pattern),
                Paper.authors_json.cast(String).ilike(pattern),
            )
        )
    return list(session.scalars(statement.limit(limit)))


def _local_results(papers: list[tuple[Paper, str]]) -> list[PaperSearchResult]:
    return [
        PaperSearchResult(
            source=PaperSource.local.value,
            source_record_id=f"paper:{paper.id}",
            title=paper.title,
            abstract=paper.abstract,
            authors=list(paper.authors_json or []),
            year=paper.year,
            venue=paper.venue,
            landing_page_url=paper.landing_page_url,
            pdf_url=paper.best_pdf_url,
            score=1.0 if match_reason.endswith("_match") else None,
            raw={"paper_id": paper.id, "local": True, "match_reason": match_reason},
        )
        for paper, match_reason in papers
    ]


def _dedupe_papers(papers: list[tuple[Paper, str]]) -> list[tuple[Paper, str]]:
    seen: set[int] = set()
    deduped: list[tuple[Paper, str]] = []
    for paper, match_reason in papers:
        if paper.id in seen:
            continue
        seen.add(paper.id)
        deduped.append((paper, match_reason))
    return deduped


def _looks_like_doi(value: str) -> bool:
    normalized = _DOI_PREFIX_RE.sub("", value).strip().lower()
    return normalized.startswith("10.") and "/" in normalized


def _looks_like_arxiv(value: str) -> bool:
    normalized = _ARXIV_PREFIX_RE.sub("", value).strip().removesuffix(".pdf")
    return bool(re.search(r"\d{4}\.\d{4,5}(?:v\d+)?", normalized))


def _looks_like_openalex(value: str) -> bool:
    normalized = _OPENALEX_PREFIX_RE.sub("", value).strip().upper()
    return normalized.startswith("W") and any(char.isdigit() for char in normalized)


def _update_paper_metadata(paper: Paper, result: PaperSearchResult) -> None:
    paper.title = result.title or paper.title
    paper.abstract = result.abstract or paper.abstract
    paper.year = result.year or paper.year
    paper.venue = result.venue or paper.venue
    paper.authors_json = result.authors or paper.authors_json
    paper.best_pdf_url = result.pdf_url or paper.best_pdf_url
    paper.landing_page_url = result.landing_page_url or paper.landing_page_url
    metadata = dict(paper.metadata_json or {})
    metadata.setdefault("source", result.source)
    paper.metadata_json = metadata


def _upsert_paper_links(session: Session, paper: Paper, result: PaperSearchResult, identifiers: list[PaperIdentifierInput]) -> None:
    repo = PaperRepository(session)
    for identifier in identifiers:
        repo.upsert_identifier(
            paper.id,
            identifier.identifier_type,
            identifier.identifier_value,
            is_primary=identifier.is_primary,
        )
    repo.upsert_source_record(
        paper.id,
        result.source,
        result.source_record_id,
        source_url=result.landing_page_url,
        retrieved_at=datetime.now().astimezone(),
        is_primary=result.source in {PaperSource.arxiv.value, PaperSource.openalex.value},
        raw_json=result.raw,
    )


def _dedupe_identifiers(identifiers: list[PaperIdentifierInput]) -> list[PaperIdentifierInput]:
    seen: set[tuple[str, str]] = set()
    deduped: list[PaperIdentifierInput] = []
    for identifier in identifiers:
        key = (identifier.identifier_type, identifier.identifier_value)
        if key not in seen:
            seen.add(key)
            deduped.append(identifier)
    return deduped
