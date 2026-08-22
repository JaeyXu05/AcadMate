from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import arxiv
import httpx

from backend.integrations.paper_sources.base import PaperSourceSearchResponse
from backend.schemas import PaperSearchResult
from backend.services.papers import normalize_identifier

_ARXIV_ID_RE = re.compile(r"(?:arxiv:\s*|arxiv\.org/(?:abs|pdf)/)?(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


@dataclass(frozen=True)
class ArxivMetadataEntry:
    arxiv_id: str
    arxiv_base_id: str
    title: str
    abstract: str | None
    authors: list[str]
    primary_category: str | None
    categories: list[str]
    published_at: datetime | None
    updated_at: datetime | None
    landing_page_url: str | None
    pdf_url: str | None
    doi: str | None
    journal_ref: str | None
    comment: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class ArxivMetadataQueryResponse:
    query_used: str
    total_results: int
    start: int
    page_size: int
    entries: list[ArxivMetadataEntry]


@dataclass
class ArxivRateLimiter:
    min_interval_seconds: float = 3.0
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_call_at: float | None = None

    def wait(self) -> None:
        now = self.monotonic()
        if self._last_call_at is not None:
            remaining = self.min_interval_seconds - (now - self._last_call_at)
            if remaining > 0:
                self.sleep(remaining)
                now = self.monotonic()
        self._last_call_at = now


class ArxivClient:
    def __init__(
        self,
        *,
        limiter: ArxivRateLimiter | None = None,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        backoff_max_seconds: float = 30.0,
        timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        arxiv_client: arxiv.Client | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.limiter = limiter or ArxivRateLimiter()
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.sleep = sleep
        self.arxiv_client = arxiv_client or arxiv.Client(page_size=25, delay_seconds=limiter.min_interval_seconds if limiter is not None else 3.0, num_retries=0)
        self.http_client = http_client or httpx.Client(follow_redirects=True, timeout=timeout_seconds, trust_env=False)

    def search(self, query: str, max_results: int = 10, *, mode: str = "auto", offset: int = 0) -> PaperSourceSearchResponse:
        warnings: list[str] = []
        max_results = max(1, min(max_results, 25))
        offset = max(0, offset)
        query_used, id_list = _arxiv_query(query, mode, warnings)
        if _is_broad_query(query, mode):
            warnings.append("Broad arXiv query; refine with title terms, author, year, category, or identifier before paging broadly.")
        search = arxiv.Search(
            query="" if id_list else query_used,
            id_list=id_list,
            max_results=max_results + offset,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        results = self._with_retry(lambda: list(self.arxiv_client.results(search)))
        if offset:
            results = results[offset:]
        return PaperSourceSearchResponse(results=[self._to_search_result(result) for result in results[:max_results]], query_used=query_used, warnings=warnings)

    def query_metadata(self, search_query: str, *, page_size: int = 5, offset: int = 0) -> ArxivMetadataQueryResponse:
        query = _validate_search_query(search_query)
        page_size = max(1, min(page_size, 200))
        offset = max(0, offset)
        response = self._metadata_request(query, page_size=page_size, offset=offset, sort_order="descending")
        return _parse_metadata_response(response.text, query, offset, page_size)

    def query_metadata_window(
        self,
        search_query: str,
        start_time: datetime,
        end_time: datetime,
        *,
        page_size: int = 100,
        offset: int = 0,
    ) -> ArxivMetadataQueryResponse:
        base_query = _validate_search_query(search_query)
        start_time = _as_utc(start_time)
        end_time = _as_utc(end_time)
        if end_time <= start_time:
            raise ValueError("arXiv metadata window end_time must be after start_time")
        if end_time - start_time > timedelta(days=1):
            raise ValueError("arXiv metadata window cannot exceed one day")
        page_size = max(1, min(page_size, 200))
        offset = max(0, offset)
        query = f"({base_query}) AND submittedDate:[{_arxiv_datetime(start_time)} TO {_arxiv_datetime(end_time)}]"
        response = self._metadata_request(query, page_size=page_size, offset=offset, sort_order="ascending")
        return _parse_metadata_response(response.text, query, offset, page_size)

    def _metadata_request(self, query: str, *, page_size: int, offset: int, sort_order: str) -> httpx.Response:
        def fetch() -> httpx.Response:
            response = self.http_client.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": query,
                    "start": offset,
                    "max_results": page_size,
                    "sortBy": "submittedDate",
                    "sortOrder": sort_order,
                },
            )
            response.raise_for_status()
            return response

        return self._with_retry(fetch)

    def download_pdf(self, pdf_url: str, destination: Path) -> Path:
        return self._download(pdf_url, destination)

    def download_source(self, arxiv_id: str, destination: Path) -> Path:
        normalized_id = normalize_arxiv_id(arxiv_id)
        return self._download(f"https://arxiv.org/src/{normalized_id}", destination)

    def _download(self, url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)

        def fetch() -> httpx.Response:
            response = self.http_client.get(url)
            response.raise_for_status()
            return response

        response = self._with_retry(fetch)
        destination.write_bytes(response.content)
        return destination

    def _with_retry(self, operation: Callable[[], Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    break
                if attempt >= self.max_retries:
                    break
                self.sleep(min(self.backoff_max_seconds, self.backoff_base_seconds * (2**attempt)))
        raise last_error or RuntimeError("arXiv operation failed")

    def _to_search_result(self, result: arxiv.Result) -> PaperSearchResult:
        arxiv_id = result.get_short_id()
        doi = result.doi.strip() if result.doi else None
        return PaperSearchResult(
            source="arxiv",
            source_record_id=arxiv_id,
            title=result.title,
            abstract=result.summary,
            authors=[author.name for author in result.authors],
            year=result.published.year if result.published else None,
            venue="arXiv",
            doi=doi,
            arxiv_id=arxiv_id,
            landing_page_url=result.entry_id,
            pdf_url=result.pdf_url,
            raw={
                "entry_id": result.entry_id,
                "primary_category": result.primary_category,
                "categories": result.categories,
                "published": result.published.isoformat() if result.published else None,
                "updated": result.updated.isoformat() if result.updated else None,
            },
        )


def arxiv_base_id(value: str) -> str:
    return normalize_arxiv_id(value)


def normalize_arxiv_id_with_version(value: str) -> str:
    match = _ARXIV_ID_RE.search(value.strip())
    if match is not None:
        return match.group("id")
    candidate = value.strip().removesuffix(".pdf")
    if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", candidate):
        return candidate
    return normalize_arxiv_id(candidate)


def normalize_arxiv_id(value: str) -> str:
    arxiv_id = _extract_arxiv_id(value)
    if arxiv_id is not None:
        return arxiv_id
    parsed = urlparse(value.strip())
    candidate = parsed.path.strip("/").split("/")[-1] if parsed.scheme and parsed.netloc else value.strip()
    candidate = candidate.removesuffix(".pdf")
    normalized = normalize_identifier("arxiv", candidate)
    if not normalized or not re.fullmatch(r"\d{4}\.\d{4,5}", normalized):
        raise ValueError(f"Invalid arXiv id: {value}")
    return normalized


def _validate_search_query(search_query: str) -> str:
    stripped = search_query.strip()
    if not stripped:
        raise ValueError("arXiv search query cannot be empty")
    if len(stripped) > 2000:
        raise ValueError("arXiv search query is too long")
    return stripped


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _arxiv_datetime(value: datetime) -> str:
    return _as_utc(value).strftime("%Y%m%d%H%M")


def _parse_metadata_response(xml_text: str, query_used: str, start: int, page_size: int) -> ArxivMetadataQueryResponse:
    root = ET.fromstring(xml_text)
    namespaces = {
        "atom": "http://www.w3.org/2005/Atom",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    total_results = _int_text(root.findtext("opensearch:totalResults", namespaces=namespaces))
    entries = [_parse_metadata_entry(entry, namespaces) for entry in root.findall("atom:entry", namespaces)]
    return ArxivMetadataQueryResponse(query_used=query_used, total_results=total_results, start=start, page_size=page_size, entries=entries)


def _parse_metadata_entry(entry: ET.Element, namespaces: dict[str, str]) -> ArxivMetadataEntry:
    entry_id = _text(entry.findtext("atom:id", namespaces=namespaces))
    arxiv_id = normalize_arxiv_id_with_version(entry_id or "")
    categories = [category.attrib.get("term", "").strip() for category in entry.findall("atom:category", namespaces) if category.attrib.get("term")]
    primary = entry.find("arxiv:primary_category", namespaces)
    primary_category = primary.attrib.get("term") if primary is not None else categories[0] if categories else None
    links = entry.findall("atom:link", namespaces)
    landing_page_url = entry_id
    pdf_url = None
    for link in links:
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href")
        elif link.attrib.get("rel") == "alternate" and link.attrib.get("href"):
            landing_page_url = link.attrib.get("href")
    raw = {
        "entry_id": entry_id,
        "links": [dict(link.attrib) for link in links],
        "primary_category": primary_category,
        "categories": categories,
        "published": _text(entry.findtext("atom:published", namespaces=namespaces)),
        "updated": _text(entry.findtext("atom:updated", namespaces=namespaces)),
    }
    return ArxivMetadataEntry(
        arxiv_id=arxiv_id,
        arxiv_base_id=arxiv_base_id(arxiv_id),
        title=_collapse_space(_text(entry.findtext("atom:title", namespaces=namespaces)) or "Untitled arXiv paper"),
        abstract=_collapse_space(_text(entry.findtext("atom:summary", namespaces=namespaces)) or "") or None,
        authors=[_collapse_space(_text(author.findtext("atom:name", namespaces=namespaces)) or "") for author in entry.findall("atom:author", namespaces) if _text(author.findtext("atom:name", namespaces=namespaces))],
        primary_category=primary_category,
        categories=categories,
        published_at=_datetime_text(entry.findtext("atom:published", namespaces=namespaces)),
        updated_at=_datetime_text(entry.findtext("atom:updated", namespaces=namespaces)),
        landing_page_url=landing_page_url,
        pdf_url=pdf_url,
        doi=_text(entry.findtext("arxiv:doi", namespaces=namespaces)),
        journal_ref=_text(entry.findtext("arxiv:journal_ref", namespaces=namespaces)),
        comment=_text(entry.findtext("arxiv:comment", namespaces=namespaces)),
        raw=raw,
    )


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _collapse_space(value: str) -> str:
    return " ".join(value.split())


def _int_text(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _datetime_text(value: str | None) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _arxiv_query(query: str, mode: str, warnings: list[str]) -> tuple[str, list[str] | None]:
    stripped = query.strip()
    normalized_mode = mode.lower()
    if normalized_mode in {"arxiv_id", "identifier"}:
        arxiv_id = _extract_arxiv_id(stripped)
        if arxiv_id is not None:
            return f"id_list:{arxiv_id}", [arxiv_id]
    if normalized_mode == "auto":
        arxiv_id = _extract_arxiv_id(stripped)
        if arxiv_id is not None:
            return f"id_list:{arxiv_id}", [arxiv_id]
    if normalized_mode == "doi":
        doi = _DOI_PREFIX_RE.sub("", stripped).strip().rstrip(".").lower()
        warnings.append("arXiv DOI search can be incomplete; use OpenAlex DOI search when exact DOI matching is required.")
        return f'doi:"{doi}"', None
    if normalized_mode == "title":
        return f'ti:"{stripped}"', None
    if normalized_mode == "keyword":
        return f'all:"{stripped}"', None
    if normalized_mode == "advanced":
        return stripped, None
    return stripped, None


def _extract_arxiv_id(value: str) -> str | None:
    match = _ARXIV_ID_RE.search(value)
    if match is None:
        return None
    return normalize_identifier("arxiv", match.group("id"))


def _is_broad_query(query: str, mode: str) -> bool:
    if mode not in {"auto", "keyword"}:
        return False
    terms = [term for term in re.split(r"\W+", query.strip()) if term]
    return len(terms) <= 2 or len(query.strip()) < 12
