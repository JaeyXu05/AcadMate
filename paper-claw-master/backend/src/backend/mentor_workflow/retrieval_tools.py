"""Small protocols shared by Retrieval Manager adapters.

Concrete adapters can implement these interfaces incrementally.  The manager
only needs stable IDs/ranks here; source scores remain local to each retriever
and are never compared directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetrievalRequest:
    concept_id: str
    query: str
    terms: tuple[str, ...] = ()
    limit: int = 30


@dataclass(frozen=True)
class RetrievalHit:
    candidate_id: str
    source: str
    rank: int
    assertion_id: str | None = None
    score: float | None = None


class EntityLookup(Protocol):
    def lookup(self, mentor_names: list[str]) -> list[RetrievalHit]: ...


class StructuredRetriever(Protocol):
    def retrieve(self, request: RetrievalRequest) -> list[RetrievalHit]: ...


class Bm25Retriever(Protocol):
    def retrieve(self, request: RetrievalRequest) -> list[RetrievalHit]: ...


class DenseRetriever(Protocol):
    def retrieve(self, request: RetrievalRequest) -> list[RetrievalHit]: ...


class EvidenceFetcher(Protocol):
    def fetch(self, candidate_id: str, assertion_id: str | None = None) -> list[dict]: ...


def reciprocal_rank_fusion(
    result_sets: list[list[RetrievalHit]],
    *,
    source_weights: dict[str, float] | None = None,
    k: int = 60,
    limit: int = 50,
) -> list[RetrievalHit]:
    """Fuse ranks only; raw BM25/dense scores remain incomparable."""

    weights = source_weights or {}
    fused: dict[tuple[str, str | None], float] = {}
    exemplar: dict[tuple[str, str | None], RetrievalHit] = {}
    for hits in result_sets:
        for hit in hits:
            key = (hit.candidate_id, hit.assertion_id)
            fused[key] = fused.get(key, 0.0) + weights.get(hit.source, 1.0) / max(
                k + max(hit.rank, 1), 1
            )
            exemplar.setdefault(key, hit)
    ranked = sorted(
        fused,
        key=lambda key: (-fused[key], key[0], key[1] or ""),
    )
    return [exemplar[key] for key in ranked[: max(0, limit)]]

