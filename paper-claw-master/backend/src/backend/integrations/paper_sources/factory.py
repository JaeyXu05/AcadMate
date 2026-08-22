from __future__ import annotations

from functools import lru_cache

from backend.integrations.paper_sources.arxiv import ArxivClient, ArxivRateLimiter
from backend.integrations.paper_sources.base import PaperSourceAdapter
from backend.integrations.paper_sources.openalex import OpenAlexClient
from backend.settings import Settings, get_settings


@lru_cache(maxsize=1)
def paper_source_adapters_from_settings() -> dict[str, PaperSourceAdapter]:
    settings = get_settings()
    return _paper_source_adapters(settings, arxiv_rate_limiter_from_settings())


@lru_cache(maxsize=1)
def arxiv_rate_limiter_from_settings() -> ArxivRateLimiter:
    settings = get_settings()
    return ArxivRateLimiter(min_interval_seconds=settings.arxiv_min_interval_seconds)


def clear_paper_source_adapters_cache() -> None:
    paper_source_adapters_from_settings.cache_clear()
    arxiv_rate_limiter_from_settings.cache_clear()


def _paper_source_adapters(settings: Settings, arxiv_limiter: ArxivRateLimiter) -> dict[str, PaperSourceAdapter]:
    return {
        "arxiv": ArxivClient(
            limiter=arxiv_limiter,
            max_retries=settings.arxiv_max_retries,
            backoff_base_seconds=settings.arxiv_backoff_base_seconds,
            backoff_max_seconds=settings.arxiv_backoff_max_seconds,
            timeout_seconds=settings.arxiv_timeout_seconds,
        ),
        "openalex": OpenAlexClient(
            api_key=settings.openalex_api_key,
            email=settings.openalex_email,
            timeout_seconds=settings.openalex_timeout_seconds,
        ),
    }
