from __future__ import annotations

import httpx

from backend.integrations.paper_sources.openalex import OpenAlexClient


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeHttpClient:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {"results": []}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, path: str, params: dict[str, object]) -> FakeResponse:
        self.calls.append((path, params))
        return FakeResponse(self.payload)


def test_openalex_doi_mode_uses_exact_filter():
    http_client = FakeHttpClient()
    client = OpenAlexClient(email="me@example.test", http_client=http_client)

    response = client.search("https://doi.org/10.1000/ABC", mode="doi")

    assert http_client.calls[0][0] == "/works"
    assert http_client.calls[0][1]["filter"] == "doi:https://doi.org/10.1000/abc"
    assert http_client.calls[0][1]["mailto"] == "me@example.test"
    assert "filter=doi:https://doi.org/10.1000/abc" in response.query_used


def test_openalex_keyword_mode_uses_search_and_page_offset():
    http_client = FakeHttpClient()
    client = OpenAlexClient(http_client=http_client)

    response = client.search("multi agent", max_results=10, mode="keyword", offset=20)

    assert http_client.calls[0][1]["search"] == "multi agent"
    assert http_client.calls[0][1]["page"] == 3
    assert response.warnings == []


def test_openalex_offset_warning_when_not_page_aligned():
    http_client = FakeHttpClient()
    client = OpenAlexClient(http_client=http_client)

    response = client.search("multi agent", max_results=10, mode="keyword", offset=5)

    assert response.warnings


def test_openalex_response_mapping_preserves_metadata():
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1000/example",
                "display_name": "Mapped Work",
                "abstract_inverted_index": {"hello": [0], "world": [1]},
                "authorships": [{"author": {"display_name": "Alice"}}],
                "publication_year": 2024,
                "primary_location": {
                    "source": {"display_name": "Venue"},
                    "landing_page_url": "https://example.test/work",
                    "pdf_url": "https://example.test/work.pdf",
                },
            }
        ]
    }
    client = OpenAlexClient(http_client=FakeHttpClient(payload))

    result = client.search("mapped", mode="title").results[0]

    assert result.source == "openalex"
    assert result.openalex_id == "https://openalex.org/W1"
    assert result.doi == "10.1000/example"
    assert result.title == "Mapped Work"
    assert result.abstract == "hello world"
    assert result.authors == ["Alice"]
    assert result.year == 2024
    assert result.venue == "Venue"
    assert result.pdf_url == "https://example.test/work.pdf"


def test_openalex_retries_transient_transport_errors():
    calls = {"count": 0}

    class FlakyClient:
        def get(self, path: str, params: dict[str, object]) -> FakeResponse:
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.TransportError("transient")
            return FakeResponse({"results": []})

    sleeps: list[float] = []
    client = OpenAlexClient(http_client=FlakyClient(), sleep=sleeps.append, max_retries=1)

    client.search("agent")

    assert calls["count"] == 2
    assert sleeps == [1.0]
