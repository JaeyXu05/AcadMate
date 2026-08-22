from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.schemas import PaperSearchResult


@dataclass(frozen=True)
class PaperSourceSearchResponse:
    results: list[PaperSearchResult]
    query_used: str
    warnings: list[str] = field(default_factory=list)


class PaperSourceAdapter(Protocol):
    def search(self, query: str, max_results: int = 10, *, mode: str = "auto", offset: int = 0) -> PaperSourceSearchResponse:
        ...
