"""Coverage checks used by Retrieval Manager quality gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backend.mentor_workflow.concept_relations import QUALIFYING_RELATIONS, best_relation
from backend.mentor_workflow.schemas import CandidateMentor, QueryContract


@dataclass(frozen=True)
class CoverageAudit:
    status: str
    required_concepts: list[str]
    covered_concepts: list[str]
    missing_concepts: list[str]
    retrievers_attempted: list[str]
    notes: list[str]

    @property
    def sufficient(self) -> bool:
        return self.status == "SUFFICIENT"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "required_concepts": self.required_concepts,
            "covered_concepts": self.covered_concepts,
            "missing_concepts": self.missing_concepts,
            "retrievers_attempted": self.retrievers_attempted,
            "notes": self.notes,
        }


def audit_coverage(
    contract: QueryContract,
    candidates: Iterable[CandidateMentor],
    *,
    retrievers_attempted: Iterable[str] = (),
) -> CoverageAudit:
    required = [concept.canonical for concept in contract.concepts if concept.required]
    if not required and contract.canonical_query:
        required = [contract.canonical_query]
    covered: list[str] = []
    candidate_list = list(candidates)
    for concept in required:
        matching_concept = next(
            (
                item
                for item in contract.concepts
                if item.canonical == concept
            ),
            None,
        )
        if matching_concept is not None and any(
            best_relation(
                matching_concept,
                candidate.research_topics,
                candidate.methods,
                getattr(candidate, "application_domains", []),
            ).relation
            in QUALIFYING_RELATIONS
            for candidate in candidate_list
        ):
            covered.append(concept)
        elif matching_concept is None and any(
            concept.casefold()
            in " ".join([*candidate.research_topics, *candidate.methods]).casefold()
            for candidate in candidate_list
        ):
            covered.append(concept)
    missing = [concept for concept in required if concept not in covered]
    retrievers = list(dict.fromkeys(str(item) for item in retrievers_attempted if item))
    notes: list[str] = []
    if not retrievers:
        notes.append("no retriever reported an attempt")
    if missing:
        notes.append("one or more required concepts have no recalled assertion")
    return CoverageAudit(
        status="SUFFICIENT" if not missing and retrievers else "INSUFFICIENT",
        required_concepts=required,
        covered_concepts=covered,
        missing_concepts=missing,
        retrievers_attempted=retrievers,
        notes=notes,
    )
