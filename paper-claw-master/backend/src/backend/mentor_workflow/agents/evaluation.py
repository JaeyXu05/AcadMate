from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.query_semantics import (
    build_query_contract,
    candidate_relevance,
    qualifies,
    relevance_threshold,
)
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    EvidenceFreshness,
    IntentPacket,
    MatchDimensionScores,
    MatchResult,
    MentorGoal,
    RetryPolicy,
    RetryTarget,
    ReviewDecision,
    ReviewStatus,
    WorkflowState,
)


class MatchingAgent:
    name = "matching_agent"

    def run(
        self,
        intent: IntentPacket,
        candidates: list[CandidateMentor],
        ledger: EvidenceLedger,
    ) -> list[MatchResult]:
        provisional: list[MatchResult] = []
        for candidate in candidates:
            invalid_refs = ledger.validate_candidate(candidate)
            if invalid_refs:
                raise ValueError(
                    f"Candidate {candidate.candidate_id} references unknown or mismatched evidence: {invalid_refs}"
                )
            if not candidate.evidence_refs:
                raise ValueError(f"Candidate {candidate.candidate_id} has no evidence")
            contract = intent.query_contract
            if not contract.canonical_query:
                contract = build_query_contract(
                    intent.raw_message,
                    intent.research_topics,
                    intent.methods,
                    intent.application_domains,
                )
            methods_verified = _verified_candidate_field(candidate, ledger, "methods")
            scoring_candidate = candidate
            if methods_verified and candidate.source_metadata.get("methods_verified") is not True:
                scoring_candidate = candidate.model_copy(
                    deep=True,
                    update={
                        "source_metadata": {
                            **candidate.source_metadata,
                            "methods_verified": True,
                        }
                    },
                )
            topic_match, match_type, score_breakdown = candidate_relevance(
                contract,
                scoring_candidate,
                fallback=bool(scoring_candidate.source_metadata.get("fallback")),
            )
            if not qualifies(topic_match, match_type):
                continue
            inferred_topic = int(candidate.source_metadata.get("topics_source") or 0) not in {1, 3}
            dimensions = MatchDimensionScores(
                research_topic_match=topic_match,
                method_match=(
                    _overlap_score(intent.methods, candidate.methods)
                    if methods_verified else 0.0
                ),
                application_match=_overlap_score(
                    intent.application_domains,
                    [*candidate.research_topics, *candidate.methods],
                ),
                recent_activity=_recent_activity(candidate, ledger),
                student_background_fit=_background_fit(intent, candidate),
                constraint_satisfaction=_constraint_fit(intent, candidate),
                recruitment_fit=_recruitment_fit(intent, candidate),
                evidence_completeness=_evidence_completeness(candidate),
            )
            overlap = _overlap(intent.research_topics, candidate.research_topics)
            score_source = "calibrated absolute relevance"
            rationale = [
                f"The evidence-backed profile shares {len(overlap)} requested research topic(s): {', '.join(overlap) or 'none explicitly recorded'}.",
                f"The displayed score is the research-topic match ({score_source}), not an eight-dimension average.",
            ]
            risks: list[str] = []
            uncertainty: list[str] = []
            negative_factors: list[str] = []
            if candidate.missing_fields:
                uncertainty.append(
                    f"Unverified fields remain empty: {', '.join(sorted(candidate.missing_fields))}."
                )
            if inferred_topic:
                uncertainty.append(
                    "Research direction was inferred from paper titles "
                    "(not official), so the topic match is discounted."
                )
            if dimensions.research_topic_match < 50:
                negative_factors.append(
                    "The recorded research-topic overlap is limited."
                )
            if candidate.recruitment_status is None:
                risks.append(
                    "Recruitment status is not verified and must not be assumed."
                )
            rank_score, rank_breakdown = self.rank_score(intent, scoring_candidate, dimensions)
            score_breakdown = {
                **score_breakdown,
                **rank_breakdown,
                "eligibility_score": topic_match,
                "ranking_score": rank_score,
                "displayed_topic_score": score_breakdown.get("displayed_topic_score", topic_match),
            }
            provisional.append(
                MatchResult(
                    candidate_id=candidate.candidate_id,
                    total_score=dimensions.mean_score(),
                    rank_score=rank_score,
                    dimension_scores=dimensions,
                    rationale=rationale,
                    negative_factors=negative_factors,
                    risks=risks,
                    uncertainty=uncertainty,
                    evidence_refs=[
                        reference
                        for reference in candidate.evidence_refs
                        if (record := ledger.get(reference)) is not None
                        and record.candidate_id == candidate.candidate_id
                        and record.entity_verified is True
                        and record.source_level in {"L1", "L2", "L3"}
                        and record.query_relevance >= 0.6
                        and record.support_type in {"DIRECT", "ADJACENT"}
                    ],
                    ranking_position=1,
                    match_type=match_type,
                    confidence=round(topic_match / 100.0, 4),
                    score_breakdown={**score_breakdown, **rank_breakdown},
                )
            )
        ranked = sorted(
            provisional,
            key=lambda item: (
                -(item.rank_score or item.score_breakdown.get("ranking_score", item.total_score)),
                -item.total_score,
                item.candidate_id,
            ),
        )
        return [
            item.model_copy(update={"ranking_position": index})
            for index, item in enumerate(ranked, start=1)
        ]

    @staticmethod
    def rank_score(
        intent: IntentPacket,
        candidate: CandidateMentor,
        dimensions: MatchDimensionScores,
    ) -> tuple[float, dict[str, float]]:
        """Rank eligible mentors without changing the displayed topic score.

        A missing or unverified optional field is neutral: it cannot create a
        fictional advantage or penalty.  Only a dimension explicitly requested
        by the user *and* available on the candidate may adjust the order.
        """

        topic_score = dimensions.research_topic_match
        score = topic_score
        applied_weight = 0.0
        components: dict[str, float] = {"eligibility_score": topic_score}

        def apply(name: str, weight: float, value: float, available: bool) -> None:
            nonlocal score, applied_weight
            if not available:
                return
            score += weight * (value - topic_score)
            applied_weight += weight
            components[f"rank_{name}"] = value
            components[f"rank_weight_{name}"] = weight

        apply(
            "method",
            0.15,
            dimensions.method_match,
            bool(
                intent.methods
                and candidate.methods
                and candidate.source_metadata.get("methods_verified") is True
            ),
        )
        apply(
            "application",
            0.10,
            dimensions.application_match,
            bool(
                intent.application_domains
                and getattr(candidate, "application_domains", [])
            ),
        )
        explicit_constraints = bool(
            intent.constraints.departments
            or intent.constraints.mentor_names
            or intent.constraints.candidate_ids
            or intent.constraints.recruitment_required
        )
        apply(
            "constraint",
            0.05,
            dimensions.constraint_satisfaction,
            explicit_constraints
            and (
                not intent.constraints.recruitment_required
                or candidate.recruitment_status is not None
            ),
        )
        components["rank_applied_weight"] = round(applied_weight, 4)
        components["rank_score"] = round(max(0.0, min(100.0, score)), 2)
        return components["rank_score"], components


class EvidenceReviewAgent:
    name = "evidence_review_agent"

    def run(self, state: WorkflowState) -> ReviewDecision:
        if state.intent is None or state.intent.missing_fields:
            return ReviewDecision(
                status=ReviewStatus.need_more_input,
                failed_checks=["intent_completeness"],
                revision_target=RetryTarget.input_understanding,
                revision_reason="Required user input is missing.",
                reviewer_summary="Review stopped because the intent is incomplete.",
            )
        candidate_ids = [candidate.candidate_id for candidate in state.candidates]
        if not candidate_ids:
            return ReviewDecision(
                status=ReviewStatus.pass_,
                reviewed_candidate_ids=[],
                failed_checks=["no_qualified_match"],
                reviewer_summary="无合格匹配：没有导师同时满足绝对相关性阈值与查询相关证据；不会用全库 Top-K 补满。",
            )
        ledger = EvidenceLedger(state.evidence_ledger)
        invalid_refs: list[str] = []
        for candidate in state.candidates:
            invalid_refs.extend(ledger.validate_candidate(candidate))
            if not candidate.evidence_refs:
                invalid_refs.append(f"candidate:{candidate.candidate_id}:no_evidence")
        for match in state.match_results:
            invalid_refs.extend(ledger.validate_match(match))
        if invalid_refs:
            return ReviewDecision(
                status=ReviewStatus.research_again,
                reviewed_candidate_ids=candidate_ids,
                failed_checks=["evidence_reference_integrity"],
                revision_target=RetryTarget.mentor_research,
                revision_reason="One or more candidate facts or match explanations lack valid evidence.",
                missing_evidence_refs=sorted(set(invalid_refs)),
                reviewer_summary="Evidence references must be repaired before ranking can be approved.",
            )
        unsupported_facts = [
            issue
            for candidate in state.candidates
            for issue in _unsupported_candidate_facts(candidate, ledger)
        ]
        if unsupported_facts:
            return ReviewDecision(
                status=ReviewStatus.research_again,
                reviewed_candidate_ids=candidate_ids,
                failed_checks=["evidence_fact_support"],
                revision_target=RetryTarget.mentor_research,
                revision_reason=(
                    "Candidate identity or populated profile fields are not explicitly "
                    "supported by bound evidence."
                ),
                missing_evidence_refs=sorted(unsupported_facts),
                reviewer_summary=(
                    "Research must obtain explicit mentor-identity and field-level "
                    "support before approval."
                ),
            )
        missing_directions = [
            candidate.candidate_id
            for candidate in state.candidates
            if not candidate.research_topics and not candidate.methods
        ]
        if missing_directions:
            return ReviewDecision(
                status=ReviewStatus.research_again,
                reviewed_candidate_ids=candidate_ids,
                failed_checks=["candidate_research_direction_presence"],
                revision_target=RetryTarget.mentor_research,
                revision_reason=(
                    "One or more USTC mentors still lack an evidence-backed "
                    "research direction."
                ),
                missing_evidence_refs=[
                    f"candidate:{candidate_id}:research_topics"
                    for candidate_id in missing_directions
                ],
                reviewer_summary=(
                    "Official profiles or attributable papers must establish "
                    "a research direction before approval."
                ),
            )
        active_evidence_refs = {
            reference
            for candidate in state.candidates
            for reference in candidate.evidence_refs
        } | {
            reference
            for match in state.match_results
            for reference in match.evidence_refs
        }
        stale = [
            record.evidence_id
            for record in state.evidence_ledger
            if record.evidence_id in active_evidence_refs
            and record.candidate_id in candidate_ids
            and record.freshness == EvidenceFreshness.stale
        ]
        if stale:
            return ReviewDecision(
                status=ReviewStatus.research_again,
                reviewed_candidate_ids=candidate_ids,
                failed_checks=["evidence_freshness"],
                revision_target=RetryTarget.mentor_research,
                revision_reason="Critical candidate evidence is stale.",
                missing_evidence_refs=stale,
                reviewer_summary="Recent sources are required for the affected facts.",
            )
        if state.intent.goal in {MentorGoal.find_mentors, MentorGoal.compare_mentors}:
            weak_matches = [
                match.candidate_id
                for match in state.match_results
                if match.total_score < relevance_threshold()
                or match.match_type not in {"DIRECT", "ADJACENT"}
                or not match.evidence_refs
            ]
            contradictions = [
                candidate.candidate_id
                for candidate in state.candidates
                if not candidate.publications
                and any(
                    "paper" in record.source_type.casefold()
                    or any(name in record.source_type.casefold() for name in ("openalex", "arxiv", "s2"))
                    for record in state.evidence_ledger
                    if record.candidate_id == candidate.candidate_id
                    and record.source_level == "L3"
                )
            ]
            if contradictions:
                return ReviewDecision(
                    status=ReviewStatus.revise,
                    reviewed_candidate_ids=candidate_ids,
                    failed_checks=[f"publication_count_contradiction:{candidate_id}" for candidate_id in contradictions],
                    revision_target=RetryTarget.matching,
                    revision_reason="Displayed publication count is empty while entity-verified paper evidence exists.",
                    reviewer_summary="审核否决：论文计数字段与已绑定论文证据矛盾。",
                )
            if weak_matches:
                return ReviewDecision(
                    status=ReviewStatus.revise,
                    reviewed_candidate_ids=candidate_ids,
                    failed_checks=[f"query_evidence_entailment:{candidate_id}" for candidate_id in weak_matches],
                    revision_target=RetryTarget.matching,
                    revision_reason="A candidate lacks query-specific supporting evidence or misses the absolute relevance threshold.",
                    reviewer_summary="Reviewer vetoed unsupported or parent-only matches.",
                )
            inconsistency = _match_inconsistency(state.match_results, candidate_ids)
            if inconsistency:
                return ReviewDecision(
                    status=ReviewStatus.revise,
                    reviewed_candidate_ids=candidate_ids,
                    failed_checks=inconsistency,
                    revision_target=RetryTarget.matching,
                    revision_reason="Match totals, ranking positions, or candidate coverage are inconsistent.",
                    reviewer_summary="Matching must be recomputed without changing source facts.",
                )
        return ReviewDecision(
            status=ReviewStatus.pass_,
            reviewed_candidate_ids=candidate_ids,
            reviewer_summary="Candidate facts, evidence bindings, freshness, and score consistency passed review.",
        )


@dataclass(frozen=True)
class RetryInstruction:
    target: RetryTarget | None
    reason: str
    exhausted: bool = False


class RetryController:
    def decide(
        self,
        review: ReviewDecision,
        state: WorkflowState,
        policy: RetryPolicy,
    ) -> RetryInstruction:
        target = review.revision_target or _target_for_failed_checks(
            review.failed_checks
        )
        if target is None:
            return RetryInstruction(
                None,
                review.revision_reason or "No retry target is available",
                exhausted=True,
            )
        total_retries = len(state.retries)
        stage_retries = sum(
            1 for retry in state.retries if retry.retry_target == target
        )
        stage_limit = policy.per_stage_max_retries.get(target, policy.max_retry_count)
        if total_retries >= policy.max_total_retries or stage_retries >= stage_limit:
            return RetryInstruction(
                None,
                f"Retry limit reached for {target.value}: stage={stage_retries}/{stage_limit}, total={total_retries}/{policy.max_total_retries}",
                exhausted=True,
            )
        return RetryInstruction(
            target, review.revision_reason or review.reviewer_summary
        )


def _target_for_failed_checks(failed_checks: list[str]) -> RetryTarget | None:
    joined = " ".join(failed_checks).casefold()
    if "input" in joined or "intent" in joined:
        return RetryTarget.input_understanding
    if "direction" in joined or "domain" in joined:
        return RetryTarget.domain_expert
    if "evidence" in joined or "source" in joined or "candidate" in joined:
        return RetryTarget.mentor_research
    if (
        "score" in joined
        or "ranking" in joined
        or "match" in joined
        or "rationale" in joined
    ):
        return RetryTarget.matching
    if "format" in joined or "composer" in joined:
        return RetryTarget.result_composer
    return None


def _match_inconsistency(
    matches: list[MatchResult], candidate_ids: list[str]
) -> list[str]:
    checks: list[str] = []
    if {match.candidate_id for match in matches} != set(candidate_ids):
        checks.append("match_candidate_coverage")
    for match in matches:
        if abs(match.total_score - match.dimension_scores.mean_score()) > 0.01:
            checks.append(f"score_consistency:{match.candidate_id}")
        if match.rationale and not match.evidence_refs:
            checks.append(f"rationale_evidence:{match.candidate_id}")
    expected_order = [
        match.candidate_id
        for match in sorted(matches, key=lambda item: (-(item.rank_score or item.total_score), -item.total_score, item.candidate_id))
    ]
    actual_order = [
        match.candidate_id
        for match in sorted(matches, key=lambda item: item.ranking_position)
    ]
    if expected_order != actual_order or sorted(
        match.ranking_position for match in matches
    ) != list(range(1, len(matches) + 1)):
        checks.append("ranking_consistency")
    return checks


def _verified_candidate_field(
    candidate: CandidateMentor, ledger: EvidenceLedger, field: str
) -> bool:
    """Return whether a candidate field is backed by verified evidence.

    Some adapters preserve verified fields on the candidate but do not attach
    the derived ``*_verified`` metadata flag. Derive it from the bound ledger
    so optional method/application signals can still differentiate ranking.
    """

    if candidate.source_metadata.get(f"{field}_verified") is True:
        return True
    return any(
        record is not None
        and record.entity_verified is True
        and field in {
            item.strip()
            for item in str(record.metadata.get("supports_fields", "")).split(",")
            if item.strip()
        }
        for reference in candidate.evidence_refs
        if (record := ledger.get(reference)) is not None
    )


def _unsupported_candidate_facts(
    candidate: CandidateMentor, ledger: EvidenceLedger
) -> list[str]:
    records = [
        record
        for reference in candidate.evidence_refs
        if (record := ledger.get(reference)) is not None
    ]
    supported_fields = {
        field.strip()
        for record in records
        for field in str(record.metadata.get("supports_fields", "")).split(",")
        if field.strip()
    }
    issues: list[str] = []
    if not any(
        record.metadata.get("identity_verified") is True
        and record.metadata.get("mentor_role_verified") is not False
        for record in records
    ):
        issues.append(f"candidate:{candidate.candidate_id}:mentor_identity")
    populated_fields = {
        "affiliation": candidate.affiliation,
        "department": candidate.department,
        "research_topics": candidate.research_topics,
        "methods": candidate.methods,
        "publications": candidate.publications,
        "projects": candidate.projects,
        "homepage": candidate.homepage,
        "recruitment_status": candidate.recruitment_status,
    }
    issues.extend(
        f"candidate:{candidate.candidate_id}:{field_name}"
        for field_name, value in populated_fields.items()
        if value and field_name not in supported_fields
    )
    return issues


def _with_publications(candidate: CandidateMentor) -> list[str]:
    """候选研究方向 + 论文标题，作为"方向面"参与匹配打分。

    RAG 里很多导师 research_topics 为空但论文标题含明确方向，把论文并入
    候选面后，这些导师也能按真实成果获得方向分，而不是被压成 0。
    """
    return [*candidate.research_topics, *candidate.publications]


def _overlap_score(requested: list[str], available: list[str]) -> float:
    if not requested:
        return 0.0
    # 逐条查询项，取它在候选方向里能达到的最高语义重叠度（0..1），再取均值。
    # 用中文二元组 + 英文词元的词法重叠近似语义相似度：整词命中为 1.0，
    # "深度强化学习" vs"强化学习" 这类近义词也能给出足够高的分，避免精确子串把
    # 强相关导师压到 0。候选为空时按 0 处理（有明确需求却对不上方向）。
    normalized_available = [_normalize(item) for item in available]
    per_item: list[float] = []
    for query_item in requested:
        q = _normalize(query_item)
        if not q:
            per_item.append(0.0)
            continue
        best = _contained(q, normalized_available)
        if q in normalized_available:
            best = 1.0  # 整词精确命中
        elif best <= 0.0 and (any(q in a for a in normalized_available)):
            best = 1.0  # 兼容旧的行内子串命中（如含标点的长句）
        per_item.append(best)
    if not per_item:
        return 0.0
    return round(100.0 * sum(per_item) / len(per_item), 2)


def _contained(query: str, available: list[str]) -> float:
    """query 与候选集合中某一项的 token 级 Jaccard 重叠，取最大值。"""
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return 0.0
    best = 0.0
    for item in available:
        if not item:
            continue
        item_tokens = set(_tokens(item))
        if not item_tokens:
            continue
        overlap = len(query_tokens & item_tokens) / len(query_tokens)
        if overlap > best:
            best = overlap
    return best


def _overlap(requested: list[str], available: list[str]) -> list[str]:
    available_normalized = {_normalize(item) for item in available}
    return [item for item in requested if _normalize(item) in available_normalized]


def _recent_activity(candidate: CandidateMentor, ledger: EvidenceLedger) -> float:
    publication_years = [
        int(record.metadata["year"])
        for reference in candidate.evidence_refs
        if (record := ledger.get(reference)) is not None
        and isinstance(record.metadata.get("year"), int)
        and int(record.metadata["year"]) > 0
    ]
    if publication_years:
        age_years = datetime.now(UTC).year - max(publication_years)
        if age_years <= 2:
            return 100.0
        if age_years <= 5:
            return 70.0
        return 40.0
    return 0.0


def _background_fit(intent: IntentPacket, candidate: CandidateMentor) -> float:
    profile_terms = [*intent.user_profile.background, *intent.user_profile.skills]
    if not profile_terms:
        return 0.0
    return _overlap_score(
        profile_terms, [*candidate.research_topics, *candidate.methods]
    )


def _constraint_fit(intent: IntentPacket, candidate: CandidateMentor) -> float:
    requested = intent.constraints
    checks: list[float] = []
    if requested.colleges:
        checks.append(
            100.0
            if candidate.affiliation in requested.colleges
            else 20.0
            if candidate.affiliation is None
            else 0.0
        )
    if requested.departments:
        checks.append(
            100.0
            if candidate.department in requested.departments
            else 20.0
            if candidate.department is None
            else 0.0
        )
    if requested.mentor_names:
        checks.append(
            100.0
            if candidate.mentor_name.casefold()
            in {name.casefold() for name in requested.mentor_names}
            else 0.0
        )
    if requested.candidate_ids:
        checks.append(
            100.0 if candidate.candidate_id in requested.candidate_ids else 0.0
        )
    return round(sum(checks) / len(checks), 2) if checks else 100.0


def _recruitment_fit(intent: IntentPacket, candidate: CandidateMentor) -> float:
    if not intent.constraints.recruitment_required:
        return 0.0 if candidate.recruitment_status is None else 100.0
    if candidate.recruitment_status is None:
        return 20.0
    status = candidate.recruitment_status.casefold()
    return (
        100.0
        if any(term in status for term in ("open", "recruit", "招生", "available"))
        else 0.0
    )


def _evidence_completeness(candidate: CandidateMentor) -> float:
    expected_fields = 8
    missing = len(set(candidate.missing_fields))
    field_score = max(
        0.0, 100.0 * (expected_fields - min(expected_fields, missing)) / expected_fields
    )
    reference_score = min(100.0, len(candidate.evidence_refs) * 25.0)
    return round((field_score + reference_score) / 2, 2)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


_CJK = re.compile(r"[一-鿿]")


def _tokens(value: str) -> list[str]:
    """把文本切成可比较的词元：英文词 + 中文整短语 + 中文二元组。

    与 data_scripts/internal_mentor_rag 的检索词元一致：整段中文短语保留语义，
    二元组捕捉"深度强化学习" 与"强化学习" 这类近义变换的共享片段。
    """
    text = value.casefold()
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9][a-z0-9\-\.]*", text):
        if len(word) >= 2:
            tokens.append(word)
    chars = _CJK.findall(text)
    if chars:
        tokens.append("".join(chars))
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i + 1])
    return tokens
