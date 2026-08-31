"""Versioned cache for concept-pair relation judgements.

Relation judgements are retrieval control metadata, never evidence.  The cache
key includes the model and registry versions so a registry/model upgrade cannot
silently reuse an old decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import RLock

from backend.mentor_workflow.concept_relations import RelationJudgement, judge_relation
from backend.mentor_workflow.schemas import QueryConcept


@dataclass(frozen=True)
class RelationCacheEntry:
    query_concept: str
    candidate_concept: str
    model_version: str
    registry_version: str
    decision: str
    confidence: float
    review_status: str
    created_at: str
    reason: str = ""

    def as_dict(self) -> dict[str, str | float]:
        return asdict(self)


class RelationCache:
    def __init__(
        self,
        *,
        model_version: str = "deterministic-v2",
        registry_version: str = "seed-v1",
    ) -> None:
        self.model_version = model_version
        self.registry_version = registry_version
        self._entries: dict[tuple[str, str, str, str], RelationCacheEntry] = {}
        self._lock = RLock()

    def get(self, query_concept: str, candidate_concept: str) -> RelationCacheEntry | None:
        key = self._key(query_concept, candidate_concept)
        with self._lock:
            return self._entries.get(key)

    def put(
        self,
        query_concept: str,
        candidate_concept: str,
        judgement: RelationJudgement,
        *,
        review_status: str = "UNREVIEWED",
    ) -> RelationCacheEntry:
        entry = RelationCacheEntry(
            query_concept=query_concept,
            candidate_concept=candidate_concept,
            model_version=self.model_version,
            registry_version=self.registry_version,
            decision=judgement.relation,
            confidence=round(judgement.score / 100.0, 4),
            review_status=review_status,
            created_at=datetime.now(UTC).isoformat(),
            reason=judgement.reason,
        )
        with self._lock:
            self._entries[self._key(query_concept, candidate_concept)] = entry
        return entry

    def judge(
        self,
        query: QueryConcept,
        candidate_concept: str,
    ) -> RelationJudgement:
        cached = self.get(query.canonical, candidate_concept)
        if cached is not None:
            return RelationJudgement(
                relation=cached.decision,
                score=round(cached.confidence * 100.0, 2),
                matched_anchor=candidate_concept,
                reason=f"relation_cache:{cached.review_status}",
            )
        judgement = judge_relation(query, candidate_concept)
        self.put(query.canonical, candidate_concept, judgement)
        return judgement

    def snapshot(self) -> list[dict[str, str | float]]:
        with self._lock:
            return [entry.as_dict() for entry in self._entries.values()]

    def _key(self, query_concept: str, candidate_concept: str) -> tuple[str, str, str, str]:
        return (
            " ".join(str(query_concept or "").casefold().split()),
            " ".join(str(candidate_concept or "").casefold().split()),
            self.model_version,
            self.registry_version,
        )

