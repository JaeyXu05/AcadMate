"""Retrieval Manager V2.

This module is the control layer between the workflow and concrete retrieval
adapters.  It owns query-preserving recall, quality-driven fallback and the
attempt ledger; it deliberately does not manufacture a mentor or evidence.

The manager may add typed aliases/subfields to the *internal recall request*,
but the original ``IntentPacket.raw_message`` and ``QueryContract`` are passed
unchanged to downstream scoring and evidence validation.  This is the key
separation that prevents query expansion from becoming a new query.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from backend.mentor_workflow.concept_relations import expanded_terms_for
from backend.mentor_workflow.coverage_audit import audit_coverage
from backend.mentor_workflow.relation_cache import RelationCache
from backend.mentor_workflow.query_semantics import build_query_contract, candidate_relevance
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    DomainJudgement,
    IntentPacket,
    MentorResearchResult,
)


ToolCall = Callable[
    [str, IntentPacket, list[DomainJudgement]], MentorResearchResult
]


@dataclass(frozen=True)
class RetrievalPlan:
    """Deterministic plan produced from a lossless query contract."""

    canonical_query: str
    recall_terms: tuple[str, ...]
    max_attempts: int = 2


class RetrievalManagerAgent:
    """Manage retrieval attempts without changing the user's semantics.

    The first attempt is always the configured local retriever.  A fallback is
    only invoked when the local result fails a small quality gate (no candidate,
    no bound evidence, no semantic signal, or unresolved records).  This keeps
    healthy local searches fast while allowing a quality failure to recover.
    """

    name = "retrieval_manager_agent"

    def __init__(self, *, max_attempts: int = 2) -> None:
        self.max_attempts = max(1, max_attempts)
        self.relation_cache = RelationCache()

    def build_plan(self, intent: IntentPacket) -> RetrievalPlan:
        contract = intent.query_contract
        if not contract.canonical_query:
            contract = build_query_contract(
                intent.raw_message,
                intent.research_topics,
                intent.methods,
                intent.application_domains,
            )
        # Expanded terms are typed aliases/subfields only.  General parents
        # (e.g. ``人工智能`` for ``生成式人工智能``) are intentionally excluded.
        recall_terms = _unique(
            [
                *intent.research_topics,
                *intent.methods,
                *intent.application_domains,
                *expanded_terms_for(contract.concepts),
            ]
        )
        return RetrievalPlan(
            canonical_query=contract.canonical_query,
            recall_terms=tuple(recall_terms),
            max_attempts=self.max_attempts,
        )

    def run(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
        call_tool: ToolCall,
    ) -> MentorResearchResult:
        plan = self.build_plan(intent)
        contract = intent.query_contract
        if not contract.canonical_query:
            contract = build_query_contract(
                intent.raw_message,
                intent.research_topics,
                intent.methods,
                intent.application_domains,
            )
        effective_intent = intent.model_copy(
            deep=True,
            update={"query_contract": contract},
        )
        recall_intent = _recall_intent(effective_intent, plan.recall_terms)
        attempts: list[dict[str, str | int | float | bool]] = []
        local_error: Exception | None = None

        try:
            local = call_tool("search_local", recall_intent, domain_judgements)
        except Exception as exc:
            local_error = exc
            local = MentorResearchResult(
                warnings=[f"local retrieval failed: {exc}"],
                source_chain=["retrieval_manager:local_failed"],
            )
            attempts.append(
                {
                    "attempt": 1,
                    "retriever": "local",
                    "status": "failed",
                    "error": str(exc),
                    "canonical_query": plan.canonical_query,
                }
            )
        else:
            attempts.append(
                _attempt_record(
                    "local",
                    local,
                    canonical_query=plan.canonical_query,
                    recall_terms=plan.recall_terms,
                )
            )
        combined = local

        if self.max_attempts > 1 and _quality_failed(local, effective_intent):
            try:
                # Fallback receives the original intent.  Its adapter may use
                # the contract's typed aliases, but it must not receive a
                # rewritten/generalised query as a new source of truth.
                fallback = call_tool("search_fallback", effective_intent, domain_judgements)
            except Exception as exc:
                # The outer research agent converts tool failures to a warning;
                # keep the manager's audit trail useful if a custom caller does
                # not use that wrapper.
                attempts.append(
                    {
                        "attempt": 2,
                        "retriever": "fallback",
                        "status": "failed",
                        "error": str(exc),
                        "canonical_query": plan.canonical_query,
                    }
                )
                fallback = MentorResearchResult(
                    used_fallback=True,
                    warnings=[f"fallback retrieval failed: {exc}"],
                    source_chain=["retrieval_manager:fallback_failed"],
                )
            attempts.append(
                _attempt_record(
                    "fallback",
                    fallback,
                    canonical_query=plan.canonical_query,
                    recall_terms=plan.recall_terms,
                )
            )
            combined = _merge_results(local, fallback)
            if local_error is not None and _quality_failed(fallback, effective_intent):
                # No usable source survived a typed tool failure.  Preserve the
                # typed error so the orchestrator's retry policy can act; a
                # normal empty result still becomes an explicit NO_MATCH.
                raise local_error

        return combined.model_copy(
            deep=True,
            update={
                "retrieval_attempts": [
                    *combined.retrieval_attempts,
                    *attempts,
                ],
                "warnings": _unique(combined.warnings),
                "coverage_report": audit_coverage(
                    contract,
                    combined.candidates,
                    retrievers_attempted=(
                        str(item.get("retriever"))
                        for item in attempts
                        if item.get("status") == "completed"
                    ),
                    ).as_dict(),
                "relation_judgements": [
                    *combined.relation_judgements,
                    *_relation_records(
                        contract,
                        combined.candidates,
                        self.relation_cache,
                    ),
                ],
            },
        )


def _recall_intent(intent: IntentPacket, recall_terms: Iterable[str]) -> IntentPacket:
    """Create an internal recall view while retaining the original contract."""

    return intent.model_copy(
        deep=True,
        update={"research_topics": _unique(recall_terms)},
    )


def _quality_failed(result: MentorResearchResult, intent: IntentPacket) -> bool:
    if not result.candidates or not result.evidence:
        return True
    if result.unresolved_candidate_ids:
        return True
    evidence_ids = {record.evidence_id for record in result.evidence}
    evidence_by_candidate: dict[str, list[Any]] = {}
    for record in result.evidence:
        if record.candidate_id:
            evidence_by_candidate.setdefault(record.candidate_id, []).append(record)
    for candidate in result.candidates:
        if not candidate.evidence_refs:
            return True
        if not any(reference in evidence_ids for reference in candidate.evidence_refs):
            return True
        # Curated internal records carry identity-verified topic evidence even
        # when the adapter does not pre-populate ``topics_source``.  Mirror the
        # authoritative boundary step here so a healthy local hit does not
        # trigger an unnecessary slow external search.
        has_verified_topics = any(
            record.metadata.get("identity_verified") is True
            and "research_topics" in str(record.metadata.get("supports_fields", ""))
            for record in evidence_by_candidate.get(candidate.candidate_id, [])
        )
        score_candidate = candidate
        if has_verified_topics and not candidate.source_metadata.get("topics_source"):
            score_candidate = candidate.model_copy(
                deep=True,
                update={
                    "source_metadata": {
                        **candidate.source_metadata,
                        "topics_source": 1,
                    }
                },
            )
        score, match_type, _ = candidate_relevance(
            intent.query_contract,
            score_candidate,
            fallback=result.used_fallback,
        )
        # This is only a trigger for a second retriever.  The authoritative
        # threshold/filter remains ``_enforce_query_boundary`` after merging.
        if score >= 45 and match_type != "UNRELATED":
            return False
    return True


def _attempt_record(
    retriever: str,
    result: MentorResearchResult,
    *,
    canonical_query: str,
    recall_terms: Iterable[str],
) -> dict[str, str | int | float | bool]:
    return {
        "attempt": 1 if retriever == "local" else 2,
        "retriever": retriever,
        "status": "completed",
        "candidate_count": len(result.candidates),
        "evidence_count": len(result.evidence),
        "used_fallback": bool(result.used_fallback),
        "canonical_query": canonical_query,
        "recall_term_count": len(tuple(recall_terms)),
    }


def _relation_records(
    contract: Any,
    candidates: Iterable[CandidateMentor],
    cache: RelationCache,
) -> list[dict[str, str | int | float | bool]]:
    records: list[dict[str, str | int | float | bool]] = []
    for candidate in candidates:
        for concept in contract.concepts:
            values = list(candidate.research_topics)
            if concept.role.value == "METHOD":
                values = list(candidate.methods)
            elif concept.role.value == "APPLICATION_DOMAIN":
                values = list(getattr(candidate, "application_domains", []))
            if not values:
                continue
            judgement = max(
                (cache.judge(concept, value) for value in values),
                key=lambda item: item.score,
            )
            records.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "query_concept": concept.canonical,
                    "candidate_assertion": judgement.matched_anchor or "",
                    "relation": judgement.relation,
                    "relation_confidence": round(judgement.score / 100.0, 4),
                    "source": "relation_cache",
                }
            )
    return records


def _merge_results(
    primary: MentorResearchResult,
    fallback: MentorResearchResult,
) -> MentorResearchResult:
    candidates = [candidate.model_copy(deep=True) for candidate in primary.candidates]
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    by_name: dict[str, list[CandidateMentor]] = {}
    for candidate in candidates:
        by_name.setdefault(candidate.mentor_name.casefold(), []).append(candidate)

    candidate_id_map: dict[str, str] = {}
    for incoming in fallback.candidates:
        current = by_id.get(incoming.candidate_id)
        if current is None:
            same_name = by_name.get(incoming.mentor_name.casefold(), [])
            current = same_name[0] if len(same_name) == 1 else None
        if current is None:
            copied = incoming.model_copy(deep=True)
            candidates.append(copied)
            by_id[copied.candidate_id] = copied
            by_name.setdefault(copied.mentor_name.casefold(), []).append(copied)
            candidate_id_map[incoming.candidate_id] = copied.candidate_id
        else:
            candidate_id_map[incoming.candidate_id] = current.candidate_id
            _merge_candidate(current, incoming)

    evidence = [record.model_copy(deep=True) for record in primary.evidence]
    evidence.extend(
        record.model_copy(
            deep=True,
            update={
                "candidate_id": candidate_id_map.get(
                    record.candidate_id or "", record.candidate_id
                )
            },
        )
        for record in fallback.evidence
    )
    unresolved = {
        candidate_id_map.get(candidate_id, candidate_id)
        for candidate_id in [
            *primary.unresolved_candidate_ids,
            *fallback.unresolved_candidate_ids,
        ]
    }
    return MentorResearchResult(
        candidates=candidates,
        evidence=evidence,
        warnings=_unique([*primary.warnings, *fallback.warnings]),
        used_fallback=True,
        source_chain=_unique([*primary.source_chain, *fallback.source_chain]),
        unresolved_candidate_ids=sorted(unresolved),
        retrieval_attempts=[
            *primary.retrieval_attempts,
            *fallback.retrieval_attempts,
        ],
    )


def _merge_candidate(target: CandidateMentor, incoming: CandidateMentor) -> None:
    for field in (
        "affiliation",
        "department",
        "homepage",
        "recruitment_status",
    ):
        if not getattr(target, field) and getattr(incoming, field):
            setattr(target, field, getattr(incoming, field))
    for field in (
        "research_topics",
        "application_domains",
        "methods",
        "publications",
        "projects",
        "evidence_refs",
    ):
        setattr(
            target,
            field,
            _unique([*getattr(target, field), *getattr(incoming, field)]),
        )
    target.topic_assertions = [
        *target.topic_assertions,
        *[
            item
            for item in incoming.topic_assertions
            if item not in target.topic_assertions
        ],
    ]
    target.publication_topics = _unique(
        [*target.publication_topics, *incoming.publication_topics]
    )
    target.source_metadata = {
        **incoming.source_metadata,
        **target.source_metadata,
    }
    target.missing_fields = _unique(
        [*target.missing_fields, *incoming.missing_fields]
    )
    target.updated_at = max(target.updated_at, incoming.updated_at)


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
