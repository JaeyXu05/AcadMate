from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from backend.integrations.paper_sources.base import PaperSourceSearchResponse
from backend.schemas import PaperSearchResult
from backend.services.papers import normalize_identifier


class OpenAlexClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        email: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        backoff_base_seconds: float = 1.0,
        backoff_max_seconds: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
        http_client: httpx.Client | None = None,
    ) -> None:
        headers = {"User-Agent": "paper-claw"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.email = email
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.sleep = sleep
        self.client = http_client or httpx.Client(base_url="https://api.openalex.org", headers=headers, timeout=timeout_seconds, trust_env=False)

    def search(self, query: str, max_results: int = 10, *, mode: str = "auto", offset: int = 0) -> PaperSourceSearchResponse:
        max_results = max(1, min(max_results, 50))
        offset = max(0, offset)
        params, warnings = self._search_params(query, max_results=max_results, mode=mode, offset=offset)
        response = self._with_retry(lambda: self.client.get("/works", params=params))
        response.raise_for_status()
        payload = response.json()
        query_used = _query_used(params)
        return PaperSourceSearchResponse(results=[self._to_search_result(item) for item in payload.get("results", [])], query_used=query_used, warnings=warnings)

    def _search_params(self, query: str, *, max_results: int, mode: str, offset: int) -> tuple[dict[str, object], list[str]]:
        warnings: list[str] = []
        params: dict[str, object] = {"per-page": max_results}
        if self.email:
            params["mailto"] = self.email
        if offset:
            if offset % max_results != 0:
                warnings.append("OpenAlex offset is mapped to page pagination; non-page-aligned offsets may skip or repeat results.")
            params["page"] = offset // max_results + 1
        normalized_mode = mode.lower()
        stripped = query.strip()
        if normalized_mode in {"doi", "identifier"} and _looks_like_doi(stripped):
            doi = normalize_identifier("doi", stripped)
            params["filter"] = f"doi:https://doi.org/{doi}"
        elif normalized_mode in {"openalex_id", "identifier"} and _looks_like_openalex(stripped):
            params["filter"] = f"openalex:{normalize_identifier('openalex', stripped)}"
            warnings.append("OpenAlex ID filtering support may vary; use the returned query_used to debug provider behavior.")
        elif normalized_mode == "title":
            params["search"] = stripped
            params["sort"] = "relevance_score:desc"
        elif normalized_mode == "advanced":
            params.update(_advanced_params(stripped))
        else:
            if _looks_like_doi(stripped):
                doi = normalize_identifier("doi", stripped)
                params["filter"] = f"doi:https://doi.org/{doi}"
            else:
                params["search"] = stripped
                params["sort"] = "relevance_score:desc"
        return params, warnings

    def _with_retry(self, operation: Callable[[], Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return operation()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                self.sleep(min(self.backoff_max_seconds, self.backoff_base_seconds * (2**attempt)))
        raise last_error or RuntimeError("OpenAlex operation failed")

    def _to_search_result(self, item: dict) -> PaperSearchResult:
        doi = item.get("doi")
        if isinstance(doi, str):
            doi = doi.removeprefix("https://doi.org/")
        authors = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in item.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        ]
        primary_location = item.get("primary_location") or {}
        return PaperSearchResult(
            source="openalex",
            source_record_id=item.get("id"),
            title=item.get("title") or item.get("display_name") or "Untitled OpenAlex work",
            abstract=item.get("abstract_inverted_index") and _restore_abstract(item["abstract_inverted_index"]),
            authors=authors,
            year=item.get("publication_year"),
            venue=(primary_location.get("source") or {}).get("display_name"),
            doi=doi,
            openalex_id=item.get("id"),
            landing_page_url=primary_location.get("landing_page_url") or item.get("id"),
            pdf_url=primary_location.get("pdf_url"),
            raw=item,
        )


def _looks_like_doi(value: str) -> bool:
    normalized = value.lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/").removeprefix("doi:").strip()
    return normalized.startswith("10.") and "/" in normalized


def _looks_like_openalex(value: str) -> bool:
    stripped = value.strip()
    return stripped.upper().startswith("W") or "openalex.org/W" in stripped


def _advanced_params(query: str) -> dict[str, object]:
    params: dict[str, object] = {}
    for part in query.split("&"):
        if not part.strip() or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key in {"search", "filter", "sort", "select", "group_by"}:
            params[key] = value.strip()
    if not params:
        params["search"] = query
    return params


def _query_used(params: dict[str, object]) -> str:
    return "&".join(f"{key}={value}" for key, value in sorted(params.items()))


def _restore_abstract(inverted_index: dict[str, list[int]]) -> str:
    words: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        words.extend((position, word) for position in positions)
    return " ".join(word for _, word in sorted(words))
