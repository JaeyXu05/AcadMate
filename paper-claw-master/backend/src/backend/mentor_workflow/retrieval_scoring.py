"""Calibrated, auditable score composition for retrieval candidates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreInputs:
    semantic_relevance: float
    evidence_confidence: float
    entity_confidence: float
    recent_activity: float = 50.0
    retrieval_coverage: float = 100.0
    has_query_evidence: bool = True
    inferred_only: bool = False
    fallback: bool = False


@dataclass(frozen=True)
class ScoreResult:
    final_score: float
    cap: float
    breakdown: dict[str, float]


def score_candidate(inputs: ScoreInputs) -> ScoreResult:
    """Compose independent dimensions; never treat the result as probability."""

    semantic = _bounded(inputs.semantic_relevance)
    evidence = _bounded(inputs.evidence_confidence)
    entity = _bounded(inputs.entity_confidence)
    recent = _bounded(inputs.recent_activity)
    coverage = _bounded(inputs.retrieval_coverage)
    final = (
        semantic * 0.60
        + evidence * 0.25
        + entity * 0.10
        + recent * 0.05
    )
    cap = 100.0
    if not inputs.has_query_evidence:
        cap = min(cap, 59.0)
    if inputs.inferred_only:
        cap = min(cap, 49.0)
    if inputs.fallback:
        cap = min(cap, 82.0)
    final = min(final, cap, coverage)
    return ScoreResult(
        final_score=round(final, 2),
        cap=cap,
        breakdown={
            "semantic_relevance": round(semantic, 2),
            "evidence_confidence": round(evidence, 2),
            "entity_confidence": round(entity, 2),
            "recent_activity": round(recent, 2),
            "retrieval_coverage": round(coverage, 2),
            "score_cap": round(cap, 2),
            "evidence_weight": 25.0,
            "entity_weight": 10.0,
        },
    )


def _bounded(value: float) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0

