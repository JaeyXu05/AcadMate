from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from backend.integrations.paper_sources.arxiv import ArxivClient, ArxivRateLimiter
from backend.integrations.paper_sources import factory


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_arxiv_rate_limiter_defaults_to_three_seconds():
    assert ArxivRateLimiter().min_interval_seconds == 3.0


def test_arxiv_rate_limiter_waits_between_calls():
    clock = FakeClock()
    limiter = ArxivRateLimiter(min_interval_seconds=3.0, monotonic=clock.monotonic, sleep=clock.sleep)

    limiter.wait()
    limiter.wait()

    assert clock.sleeps == [3.0]


def test_arxiv_search_and_download_share_limiter(tmp_path):
    clock = FakeClock()
    limiter = ArxivRateLimiter(min_interval_seconds=1.0, monotonic=clock.monotonic, sleep=clock.sleep)
    result = SimpleNamespace(
        get_short_id=lambda: "2401.00001",
        doi=None,
        title="Shared limiter paper",
        summary="abstract",
        authors=[SimpleNamespace(name="A")],
        published=datetime(2024, 1, 1, tzinfo=UTC),
        updated=datetime(2024, 1, 2, tzinfo=UTC),
        primary_category="cs.AI",
        categories=["cs.AI"],
        entry_id="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
    )
    fake_arxiv_client = SimpleNamespace(results=lambda search: [result])
    fake_response = SimpleNamespace(content=b"pdf", raise_for_status=lambda: None)
    requested_urls = []
    fake_http_client = SimpleNamespace(get=lambda url: requested_urls.append(url) or fake_response)
    client = ArxivClient(
        limiter=limiter,
        sleep=clock.sleep,
        arxiv_client=fake_arxiv_client,
        http_client=fake_http_client,
    )

    client.search("rag")
    client.download_pdf("https://arxiv.org/pdf/2401.00001", tmp_path / "paper.pdf")
    client.download_source("2401.00001v2", tmp_path / "source.tar.gz")

    assert clock.sleeps == [1.0, 1.0]
    assert requested_urls[-1] == "https://arxiv.org/src/2401.00001"
    assert "/e-print/" not in requested_urls[-1]


def test_arxiv_factory_reuses_shared_limiter():
    factory.clear_paper_source_adapters_cache()
    try:
        adapters = factory.paper_source_adapters_from_settings()

        assert adapters["arxiv"].limiter is factory.arxiv_rate_limiter_from_settings()
    finally:
        factory.clear_paper_source_adapters_cache()


def test_arxiv_retry_uses_exponential_backoff():
    clock = FakeClock()
    limiter = ArxivRateLimiter(min_interval_seconds=1.0, monotonic=clock.monotonic, sleep=clock.sleep)
    calls = {"count": 0}

    def operation():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    client = ArxivClient(limiter=limiter, max_retries=3, backoff_base_seconds=2.0, backoff_max_seconds=5.0, sleep=clock.sleep)

    assert client._with_retry(operation) == "ok"
    assert clock.sleeps == [2.0, 4.0]


def test_arxiv_retry_reraises_last_error():
    clock = FakeClock()
    limiter = ArxivRateLimiter(min_interval_seconds=1.0, monotonic=clock.monotonic, sleep=clock.sleep)
    client = ArxivClient(limiter=limiter, max_retries=1, sleep=clock.sleep)

    with pytest.raises(RuntimeError, match="boom"):
        client._with_retry(lambda: (_ for _ in ()).throw(RuntimeError("boom")))


def test_arxiv_retry_does_not_retry_rate_limit():
    calls = {"count": 0}
    sleeps: list[float] = []
    request = httpx.Request("GET", "https://export.arxiv.org/api/query")
    response = httpx.Response(429, request=request)
    client = ArxivClient(limiter=ArxivRateLimiter(min_interval_seconds=0), max_retries=3, sleep=sleeps.append)

    def operation():
        calls["count"] += 1
        raise httpx.HTTPStatusError("rate exceeded", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        client._with_retry(operation)

    assert calls["count"] == 1
    assert sleeps == []


def test_arxiv_id_mode_uses_exact_id_lookup():
    captured = []
    fake_arxiv_client = SimpleNamespace(results=lambda search: captured.append(search) or [])
    client = ArxivClient(limiter=ArxivRateLimiter(min_interval_seconds=0), arxiv_client=fake_arxiv_client)

    response = client.search("https://arxiv.org/abs/2401.00001v2", mode="arxiv_id")

    assert response.query_used == "id_list:2401.00001"
    assert captured[0].id_list == ["2401.00001"]


def test_arxiv_metadata_window_builds_submitted_date_query_and_parses_atom():
    captured = {}
    xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\" xmlns:opensearch=\"http://a9.com/-/spec/opensearch/1.1/\" xmlns:arxiv=\"http://arxiv.org/schemas/atom\">
      <opensearch:totalResults>1</opensearch:totalResults>
      <entry>
        <id>https://arxiv.org/abs/2401.00001v2</id>
        <updated>2024-01-02T00:00:00Z</updated>
        <published>2024-01-01T00:00:00Z</published>
        <title> A   metadata   paper </title>
        <summary> Abstract text. </summary>
        <author><name>Ada Lovelace</name></author>
        <arxiv:primary_category term=\"cs.LG\" />
        <category term=\"cs.LG\" />
        <category term=\"cs.AI\" />
        <link rel=\"alternate\" href=\"https://arxiv.org/abs/2401.00001v2\" />
        <link title=\"pdf\" href=\"https://arxiv.org/pdf/2401.00001v2\" />
        <arxiv:doi>10.0000/example</arxiv:doi>
        <arxiv:comment>12 pages</arxiv:comment>
      </entry>
    </feed>
    """
    fake_response = SimpleNamespace(text=xml, raise_for_status=lambda: None)

    def get(url, params):
        captured["url"] = url
        captured["params"] = params
        return fake_response

    client = ArxivClient(limiter=ArxivRateLimiter(min_interval_seconds=0), http_client=SimpleNamespace(get=get))
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=12)

    response = client.query_metadata_window("cat:cs.LG", start, end, page_size=500, offset=10)

    assert captured["url"] == "https://export.arxiv.org/api/query"
    assert captured["params"]["search_query"] == "(cat:cs.LG) AND submittedDate:[202401010000 TO 202401011200]"
    assert captured["params"]["max_results"] == 200
    assert captured["params"]["start"] == 10
    assert captured["params"]["sortBy"] == "submittedDate"
    assert response.total_results == 1
    entry = response.entries[0]
    assert entry.arxiv_id == "2401.00001v2"
    assert entry.arxiv_base_id == "2401.00001"
    assert entry.title == "A metadata paper"
    assert entry.authors == ["Ada Lovelace"]
    assert entry.categories == ["cs.LG", "cs.AI"]
    assert entry.pdf_url == "https://arxiv.org/pdf/2401.00001v2"


def test_arxiv_metadata_window_rejects_windows_over_one_day():
    client = ArxivClient(limiter=ArxivRateLimiter(min_interval_seconds=0))
    start = datetime(2024, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="cannot exceed one day"):
        client.query_metadata_window("cat:cs.LG", start, start + timedelta(days=1, minutes=1))


def test_arxiv_offset_and_max_results_are_applied():
    results = [
        SimpleNamespace(
            get_short_id=lambda index=index: f"2401.0000{index}",
            doi=None,
            title=f"Paper {index}",
            summary="abstract",
            authors=[],
            published=datetime(2024, 1, 1, tzinfo=UTC),
            updated=datetime(2024, 1, 2, tzinfo=UTC),
            primary_category="cs.AI",
            categories=["cs.AI"],
            entry_id=f"https://arxiv.org/abs/2401.0000{index}",
            pdf_url=f"https://arxiv.org/pdf/2401.0000{index}",
        )
        for index in range(30)
    ]
    captured = []
    fake_arxiv_client = SimpleNamespace(results=lambda search: captured.append(search) or results)
    client = ArxivClient(limiter=ArxivRateLimiter(min_interval_seconds=0), arxiv_client=fake_arxiv_client)

    response = client.search("agent", max_results=100, mode="keyword", offset=2)

    assert captured[0].max_results == 27
    assert len(response.results) == 25
    assert response.results[0].title == "Paper 2"
    assert response.warnings
