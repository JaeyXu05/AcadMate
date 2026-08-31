"""Compatibility facade for the Retrieval Manager V2 concept engine.

The workflow historically imported these helpers directly.  Keeping the
functions here avoids a breaking change while moving query interpretation to
``concept_relations``, where concepts have typed relations instead of an
undifferentiated expansion keyword list.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Iterable

from backend.mentor_workflow.concept_relations import (
    QUALIFYING_RELATIONS,
    Relation,
    best_relation,
    clean_query_text,
    excluded_generalizations_for,
    expanded_terms_for,
    extract_query_concepts,
    family_for,
    preserved_tokens,
)
from backend.mentor_workflow.schemas import CandidateMentor, QueryConcept, QueryContract


def relevance_threshold() -> float:
    raw = os.environ.get("MENTOR_RELEVANCE_THRESHOLD", "60")
    try:
        value = float(raw)
    except ValueError:
        return 60.0
    return value if value > 0 else 60.0


def build_query_contract(
    raw_query: str,
    topics: list[str] | None = None,
    methods: list[str] | None = None,
    applications: list[str] | None = None,
) -> QueryContract:
    """Build a lossless, multi-concept contract.

    ``raw_query`` is authoritative.  Structured fields supplement it only
    when the text does not contain a concept, so an LLM cannot collapse
    ``生成式人工智能`` into ``人工智能``.
    """

    raw = str(raw_query or "")
    topic_values = list(topics or [])
    method_values = list(methods or [])
    application_values = list(applications or [])
    concepts = extract_query_concepts(
        raw,
        topic_values,
        method_values,
        application_values,
    )
    canonical = "；".join(concept.canonical for concept in concepts) if concepts else clean_query_text(raw)
    boundary = None
    if len(concepts) == 1:
        family = family_for(concepts[0].canonical)
        boundary = family.concept_id if family is not None else concepts[0].canonical
    elif concepts:
        boundary = "multi_concept"
    return QueryContract(
        raw_query=raw,
        canonical_query=canonical,
        must_preserve=_unique(
            token for concept in concepts for token in concept.must_preserve
        ) or (preserved_tokens(canonical, canonical) if canonical else []),
        expanded_terms=expanded_terms_for(concepts),
        excluded_generalizations=excluded_generalizations_for(concepts),
        semantic_boundary=boundary,
        concepts=concepts,
        logic="AND" if len([item for item in concepts if item.required]) > 1 else "OR",
    )


def candidate_relevance(
    contract: QueryContract,
    candidate: CandidateMentor,
    *,
    fallback: bool = False,
) -> tuple[float, str, dict[str, float]]:
    """Return a reproducible 0..100 relevance based on typed relations."""

    concepts = contract.concepts or _compat_concepts(contract)
    topics = list(candidate.research_topics or [])
    methods = list(candidate.methods or [])
    per_concept = [
        (
            concept,
            best_relation(
                concept,
                topics,
                methods,
                getattr(candidate, "application_domains", []),
            ),
        )
        for concept in concepts
    ]
    required = [item for item in per_concept if item[0].required] or per_concept
    if not required:
        return 0.0, "UNRELATED", _empty_breakdown(fallback)

    if contract.logic == "AND":
        relation_score = min(item[1].score for item in required)
        all_qualifying = all(item[1].relation in QUALIFYING_RELATIONS for item in required)
    else:
        strongest = max(required, key=lambda item: item[1].score)
        relation_score = strongest[1].score
        all_qualifying = strongest[1].relation in QUALIFYING_RELATIONS

    official_topics = int(candidate.source_metadata.get("topics_source") or 0) == 1
    topic_score = relation_score if official_topics else relation_score * 0.45
    final_score = topic_score * 0.92 * (0.82 if fallback else 1.0)
    final_score = round(max(0.0, min(100.0, final_score)), 2)

    relations = [item[1].relation for item in required]
    if not all_qualifying:
        match_type = "UNRELATED"
    elif all(relation == Relation.EXACT for relation in relations):
        match_type = "DIRECT"
    else:
        match_type = "ADJACENT"
    if final_score < relevance_threshold():
        match_type = "UNRELATED"

    matched = sum(item[1].relation in QUALIFYING_RELATIONS for item in required)
    breakdown = {
        "topic_match": round(topic_score, 2),
        "method_match": 0.0,
        "publication_support": 0.0,
        "concept_coverage": round(matched / max(len(required), 1) * 100, 2),
        "relation_score": round(relation_score, 2),
        "evidence_confidence": 95.0 if official_topics else 45.0,
        "fallback_factor": 0.82 if fallback else 1.0,
    }
    return final_score, match_type, breakdown


def qualifies(score: float, match_type: str) -> bool:
    return score >= relevance_threshold() and match_type in {"DIRECT", "ADJACENT"}


def evidence_query_relevant(contract: QueryContract, title: str, fact: str) -> bool:
    """Check evidence text without treating it as a new query expansion."""

    blob = f"{title} {fact}"
    concepts = contract.concepts or _compat_concepts(contract)
    return any(
        best_relation(concept, [blob]).relation in QUALIFYING_RELATIONS
        for concept in concepts
    )


def freshness_label(year: int | None, declared: str | None = None) -> str:
    if year is not None and year >= 1900:
        current_year = datetime.now(UTC).year
        if year >= current_year - 2:
            return "current"
        if year >= current_year - 5:
            return "recent"
        return "stale"
    if declared in {"recent", "current"}:
        return "unknown"
    return declared or "unknown"


def _compat_concepts(contract: QueryContract) -> list[QueryConcept]:
    values = [item for item in contract.canonical_query.split("；") if item.strip()]
    if not values and contract.canonical_query:
        values = [contract.canonical_query]
    preserved = contract.must_preserve or [contract.canonical_query]
    return [
        QueryConcept(
            concept_id=f"query_concept_{index}",
            surface=value,
            canonical=value,
            must_preserve=preserved if len(values) == 1 else [value],
        )
        for index, value in enumerate(values, start=1)
    ]


def _empty_breakdown(fallback: bool) -> dict[str, float]:
    return {
        "topic_match": 0.0,
        "method_match": 0.0,
        "publication_support": 0.0,
        "concept_coverage": 0.0,
        "relation_score": 0.0,
        "evidence_confidence": 0.0,
        "fallback_factor": 0.82 if fallback else 1.0,
    }


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
