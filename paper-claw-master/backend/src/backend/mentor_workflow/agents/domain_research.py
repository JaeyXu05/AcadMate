from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import perf_counter

from backend.mentor_workflow.errors import TemporaryToolError, ToolTimeoutError
from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.research_tools import MentorResearchTool
from backend.mentor_workflow.query_semantics import (
    build_query_contract,
    candidate_relevance,
    evidence_query_relevant,
    freshness_label,
    qualifies,
)
from backend.mentor_workflow.retrieval_manager import RetrievalManagerAgent
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    DomainJudgement,
    EvidenceRecord,
    IntentPacket,
    MentorResearchResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DomainConfig:
    name: str
    expert_name: str
    triggers: tuple[str, ...]
    synonyms: dict[str, tuple[str, ...]]
    exclusions: tuple[str, ...]
    interdisciplinary_links: tuple[str, ...]


DOMAIN_CONFIGS = (
    DomainConfig(
        name="artificial_intelligence",
        expert_name="artificial_intelligence_expert",
        triggers=(
            "人工智能",
            "机器学习",
            "深度学习",
            "强化学习",
            "multi-agent",
            "agent",
            "ai",
            "ml",
        ),
        synonyms={
            "强化学习": ("reinforcement learning", "RL"),
            "多智能体": (
                "multi-agent systems",
                "multi-agent reinforcement learning",
                "MARL",
            ),
            "大模型": ("large language model", "LLM", "foundation model"),
        },
        exclusions=("仅教学介绍且无研究产出",),
        interdisciplinary_links=("mathematics_statistics", "computer_systems"),
    ),
    DomainConfig(
        name="computer_systems",
        expert_name="computer_systems_expert",
        triggers=(
            "系统",
            "分布式",
            "编译",
            "数据库",
            "操作系统",
            "架构",
            "distributed",
            "compiler",
        ),
        synonyms={
            "分布式系统": ("distributed systems", "cloud computing"),
            "计算机体系结构": ("computer architecture", "hardware systems"),
        },
        exclusions=("纯应用开发且无系统研究问题",),
        interdisciplinary_links=("artificial_intelligence", "cyber_security"),
    ),
    DomainConfig(
        name="cyber_security",
        expert_name="cyber_security_expert",
        triggers=(
            "网络安全",
            "安全",
            "隐私",
            "密码",
            "攻防",
            "security",
            "privacy",
            "cryptography",
        ),
        synonyms={
            "网络安全": ("cyber security", "network security"),
            "隐私保护": ("privacy preserving", "data privacy"),
        },
        exclusions=("仅包含 security 一词但语义为系统稳定性",),
        interdisciplinary_links=("computer_systems", "mathematics_statistics"),
    ),
    DomainConfig(
        name="mathematics_statistics",
        expert_name="mathematics_statistics_expert",
        triggers=(
            "数学",
            "统计",
            "优化",
            "博弈",
            "概率",
            "理论",
            "optimization",
            "statistics",
            "game theory",
        ),
        synonyms={
            "博弈论": ("game theory", "mechanism design"),
            "优化": ("optimization", "operations research"),
            "统计": ("statistics", "statistical learning"),
        },
        exclusions=("仅使用现成统计软件且无方法研究",),
        interdisciplinary_links=("artificial_intelligence", "cyber_security"),
    ),
)


class DynamicDomainExpertAgent:
    name = "dynamic_domain_expert_agent"

    def run(self, intent: IntentPacket) -> list[DomainJudgement]:
        query = " ".join(
            [*intent.research_topics, *intent.methods, *intent.application_domains]
        ).casefold()
        selected = [
            config
            for config in DOMAIN_CONFIGS
            if any(_trigger_hits(trigger, query) for trigger in config.triggers)
        ]
        if not selected:
            return [
                DomainJudgement(
                    expert_name="query_boundary_expert",
                    domain="query_specific",
                    search_concepts=_unique(
                        [
                            *intent.research_topics,
                            *intent.methods,
                            *intent.application_domains,
                            *intent.query_contract.expanded_terms,
                        ]
                    ),
                    exclusions=["parent-concept substitutions", "unrelated application domains"],
                    boundary="Use the query contract only; do not generalize to AI/ML parents.",
                    interdisciplinary_links=[],
                    conflicts=[],
                )
            ]
        judgements: list[DomainJudgement] = []
        for config in selected:
            concepts = [
                *intent.research_topics,
                *intent.methods,
                *intent.application_domains,
                *intent.query_contract.expanded_terms,
            ]
            for term, synonyms in config.synonyms.items():
                if term.casefold() in query or any(
                    synonym.casefold() in query for synonym in synonyms
                ):
                    concepts.extend(synonyms)
            conflicts = []
            if len(selected) > 1:
                conflicts.append(
                    f"{config.name} applies its own boundary; cross-domain relevance remains a structured judgement, not an override."
                )
            judgements.append(
                DomainJudgement(
                    expert_name=config.expert_name,
                    domain=config.name,
                    search_concepts=_unique(concepts),
                    exclusions=list(config.exclusions),
                    boundary=f"Include work with explicit research evidence in {config.name}; exclude incidental keyword mentions.",
                    interdisciplinary_links=list(config.interdisciplinary_links),
                    conflicts=conflicts,
                )
            )
        return judgements


class MentorResearchAgent:
    name = "mentor_research_agent"

    def __init__(
        self, tool: MentorResearchTool, *, tool_timeout_seconds: float = 240
    ) -> None:
        self.tool = tool
        self.tool_timeout_seconds = tool_timeout_seconds
        self.retrieval_manager = RetrievalManagerAgent()

    def run(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
        existing_evidence: list[EvidenceRecord],
    ) -> MentorResearchResult:
        warnings: list[str] = []
        try:
            combined = self.retrieval_manager.run(
                intent,
                domain_judgements,
                self._call_tool,
            )
        except TemporaryToolError as exc:
            warnings.append(str(exc))
            combined = MentorResearchResult(
                warnings=[str(exc)],
                source_chain=["retrieval_manager:local_failed"],
                retrieval_attempts=[
                    {
                        "attempt": 1,
                        "retriever": "local",
                        "status": "failed",
                        "error": str(exc),
                    }
                ],
            )
        retrieved_count = len(combined.candidates)
        combined = _enforce_query_boundary(combined, intent)
        coverage_report = dict(combined.coverage_report)
        coverage_report.update(
            {
                "retrieved_candidate_count": retrieved_count,
                "qualified_candidate_count": len(combined.candidates),
            }
        )
        if not combined.candidates:
            coverage_report.update(_no_match_diagnostics(coverage_report, intent))
        combined = combined.model_copy(
            deep=True, update={"coverage_report": coverage_report}
        )
        ledger = EvidenceLedger(existing_evidence)
        reference_map: dict[str, str] = {}
        for record in combined.evidence:
            stored = ledger.add(record)
            reference_map[record.evidence_id] = stored.evidence_id
        candidates = [
            _rewrite_refs(candidate, reference_map) for candidate in combined.candidates
        ]
        candidates = [
            candidate for candidate in candidates if _has_research_signal(candidate)
        ]
        ledger_records = ledger.list()
        new_ids = {
            reference_map.get(record.evidence_id, record.evidence_id)
            for record in combined.evidence
        }
        new_evidence = [
            record for record in ledger_records if record.evidence_id in new_ids
        ]
        return MentorResearchResult(
            candidates=candidates,
            evidence=new_evidence,
            warnings=_unique([*warnings, *combined.warnings]),
            used_fallback=combined.used_fallback,
            source_chain=combined.source_chain,
            unresolved_candidate_ids=combined.unresolved_candidate_ids,
            retrieval_attempts=combined.retrieval_attempts,
            coverage_report=combined.coverage_report,
            relation_judgements=combined.relation_judgements,
        )

    def _call_tool(
        self,
        method_name: str,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        started = perf_counter()
        try:
            result = getattr(self.tool, method_name)(intent, domain_judgements)
        except TemporaryToolError as exc:
            _log_tool_call(
                intent.trace_id,
                method_name,
                started,
                status="failed",
                error_type=type(exc).__name__,
            )
            raise
        except Exception as exc:
            _log_tool_call(
                intent.trace_id,
                method_name,
                started,
                status="failed",
                error_type=type(exc).__name__,
            )
            raise TemporaryToolError(f"{method_name} failed: {exc}") from exc
        duration = perf_counter() - started
        if duration > self.tool_timeout_seconds:
            _log_tool_call(
                intent.trace_id,
                method_name,
                started,
                status="timeout",
                error_type=ToolTimeoutError.__name__,
            )
            raise ToolTimeoutError(
                f"{method_name} exceeded the {self.tool_timeout_seconds:.3f}s tool timeout"
            )
        _log_tool_call(intent.trace_id, method_name, started, status="completed")
        return MentorResearchResult.model_validate(result)


def _no_match_diagnostics(
    coverage_report: dict[str, object], intent: IntentPacket
) -> dict[str, object]:
    """Explain an empty result without weakening evidence requirements."""

    retrieved = int(coverage_report.get("retrieved_candidate_count") or 0)
    missing = list(coverage_report.get("missing_concepts") or [])
    zeroed_at = "retrieval" if retrieved == 0 else "semantic_boundary"
    relaxations: list[dict[str, str]] = []
    if len([concept for concept in intent.query_contract.concepts if concept.required]) > 1:
        relaxations.append(
            {
                "action": "allow_adjacent_topic",
                "reason": "多个研究主题当前按 AND 同时要求，可尝试保留主方向并展示相邻方向。",
            }
        )
    if intent.constraints.recruitment_required:
        relaxations.append(
            {
                "action": "include_unverified_recruitment",
                "reason": "可展示方向匹配但招生状态尚未核验的导师，并保留风险提示。",
            }
        )
    if missing:
        relaxations.append(
            {
                "action": "expand_aliases",
                "reason": "部分必需概念在当前语料没有可核验断言，可尝试别名或相邻子领域。",
            }
        )
    return {
        "zeroed_at_stage": zeroed_at,
        "missing_concepts": missing,
        "relaxation_options": relaxations,
    }


def _rewrite_refs(
    candidate: CandidateMentor, reference_map: dict[str, str]
) -> CandidateMentor:
    return candidate.model_copy(
        deep=True,
        update={
            "evidence_refs": _unique(
                [
                    reference_map.get(reference, reference)
                    for reference in candidate.evidence_refs
                ]
            )
        },
    )


def _enforce_query_boundary(
    result: MentorResearchResult,
    intent: IntentPacket,
) -> MentorResearchResult:
    contract = intent.query_contract
    if not contract.canonical_query:
        contract = build_query_contract(
            intent.raw_message,
            intent.research_topics,
            intent.methods,
            intent.application_domains,
        )
    records_by_candidate: dict[str, list[EvidenceRecord]] = {}
    for record in result.evidence:
        if record.candidate_id:
            records_by_candidate.setdefault(record.candidate_id, []).append(record)
    kept: list[CandidateMentor] = []
    scores: dict[str, float] = {}
    match_types: dict[str, str] = {}
    for raw_candidate in result.candidates:
        candidate = raw_candidate.model_copy(deep=True)
        bound = records_by_candidate.get(candidate.candidate_id, [])
        verified_fields = {
            field.strip()
            for record in bound
            if record.metadata.get("identity_verified") is True
            for field in str(record.metadata.get("supports_fields", "")).split(",")
            if field.strip()
        }
        # The legacy paper aggregations are name-only and currently have no
        # verified author identities. Missing facts remain unknown.
        if "methods" not in verified_fields:
            candidate.methods = []
        if "publications" not in verified_fields:
            candidate.publications = []
        if "projects" not in verified_fields:
            candidate.projects = []
        if "recruitment_status" not in verified_fields:
            candidate.recruitment_status = None
        official_topic_support = any(
            record.metadata.get("identity_verified") is True
            and "research_topics" in str(record.metadata.get("supports_fields", ""))
            for record in bound
        )
        meta = dict(candidate.source_metadata)
        if official_topic_support and not meta.get("topics_source"):
            meta["topics_source"] = 1
        meta["methods_verified"] = "methods" in verified_fields
        meta["fallback"] = bool(result.used_fallback)
        candidate.source_metadata = meta
        score, match_type, breakdown = candidate_relevance(
            contract, candidate, fallback=result.used_fallback
        )
        if not qualifies(score, match_type):
            continue
        candidate.source_metadata.update(
            {
                "absolute_relevance": score,
                "match_type": match_type,
                "query_contract": contract.canonical_query,
                "must_preserve": ",".join(contract.must_preserve),
                **{f"score_{key}": value for key, value in breakdown.items()},
            }
        )
        kept.append(candidate)
        scores[candidate.candidate_id] = score
        match_types[candidate.candidate_id] = match_type
    # ``absolute_relevance`` is the semantic gate; local retrieval confidence
    # breaks residual ties deterministically instead of falling through to ID.
    kept.sort(
        key=lambda item: (
            -scores[item.candidate_id],
            -float(item.source_metadata.get("retrieve_score") or 0.0),
            -int(item.source_metadata.get("retrieve_hits") or 0),
            item.candidate_id,
        )
    )
    kept = kept[:5]
    kept_ids = {candidate.candidate_id for candidate in kept}
    evidence: list[EvidenceRecord] = []
    for record in result.evidence:
        if record.candidate_id not in kept_ids:
            continue
        if record.metadata.get("identity_verified") is not True:
            continue
        supports = str(record.metadata.get("supports_fields", ""))
        query_support = "research_topics" in supports or "methods" in supports
        source = record.source_type.casefold()
        level = "L1" if "official_faculty_profile" in source else "L2" if "official_faculty_directory" in source else "L3" if "paper" in source and record.metadata.get("identity_verified") is True else "L4" if any(item in source for item in ("openalex", "s2", "dblp", "arxiv")) else "L5"
        # Source authority and query support are separate dimensions.  An
        # official page can prove identity, but a broad parent topic on that
        # page must not support a narrower query (for example ``人工智能``
        # cannot qualify ``生成式人工智能``).  Every topic/method record is
        # therefore checked against the frozen query contract, regardless of
        # source level.
        if query_support and not evidence_query_relevant(contract, record.title, record.extracted_fact):
            continue
        year = record.metadata.get("year")
        try:
            year_value = int(year) if year is not None and str(year).strip() else None
        except (TypeError, ValueError):
            year_value = None
        evidence.append(
            record.model_copy(
                deep=True,
                update={
                    "query": contract.canonical_query,
                    "query_relevance": 1.0 if query_support and match_types.get(record.candidate_id or "") == "DIRECT" else 0.82 if query_support else 0.0,
                    "entity_verified": bool(record.metadata.get("identity_verified")),
                    "support_type": match_types.get(record.candidate_id or "", "UNRELATED") if query_support else "IDENTITY",
                    "source_level": level,
                    "freshness": freshness_label(year_value, record.freshness.value if hasattr(record.freshness, "value") else str(record.freshness or "")),
                },
            )
        )
    allowed_evidence_ids = {record.evidence_id for record in evidence}
    kept = [
        candidate.model_copy(
            deep=True,
            update={
                "evidence_refs": [
                    reference
                    for reference in candidate.evidence_refs
                    if reference in allowed_evidence_ids
                ]
            },
        )
        for candidate in kept
    ]
    # A score is not enough: after query-conditioned evidence filtering, a
    # candidate must retain at least one direct/adjacent supporting record.
    # Identity-only evidence may remain in the ledger but cannot qualify a
    # recommendation.
    evidence_by_candidate = {}
    for record in evidence:
        if record.candidate_id and record.support_type in {"DIRECT", "ADJACENT"}:
            evidence_by_candidate.setdefault(record.candidate_id, []).append(record)
    kept = [
        candidate
        for candidate in kept
        if candidate.evidence_refs
        and evidence_by_candidate.get(candidate.candidate_id)
    ]
    warnings = list(result.warnings)
    if not kept:
        warnings.append(f"没有导师达到绝对相关性阈值：{contract.canonical_query}")
    return result.model_copy(
        deep=True,
        update={"candidates": kept, "evidence": evidence, "warnings": _unique(warnings)},
    )


def _has_research_signal(candidate: CandidateMentor) -> bool:
    """Drop non-substantive stub candidates (no topics, no methods, no papers, no projects).

    The RAG library has ~278/715 mentors without research_topics; many of those
    also carry no methods/publiations/projects and are unusable placeholder rows.
    Keeping them makes the evidence-review's candidate_research_direction_presence
    check fail the whole workflow. Remove them here so the pipeline only ranks
    mentors that have at least one research signal.
    """
    return bool(
        candidate.research_topics
        or candidate.methods
        or candidate.publications
        or candidate.projects
    )


def _needs_external_fallback(result: MentorResearchResult) -> bool:
    if not result.candidates or result.unresolved_candidate_ids:
        return True
    dense_retrieval = all(
        candidate.source_metadata.get("retrieve_mode") == "dense_multilingual"
        for candidate in result.candidates
    )
    if not dense_retrieval:
        lexical_hits = [
            int(candidate.source_metadata.get("retrieve_hits") or 0)
            for candidate in result.candidates
            if "retrieve_hits" in candidate.source_metadata
        ]
        if lexical_hits and max(lexical_hits) < 1:
            # 旧稀疏检索全是余弦噪声时才走官网/论文补全；稠密检索由后续
            # matching + evidence Review 负责淘汰，不再错误降级成长外部慢链。
            return True
    records = {record.evidence_id: record for record in result.evidence}
    for candidate in result.candidates:
        if not candidate.research_topics or not candidate.evidence_refs:
            return True
        bound = [
            records[reference]
            for reference in candidate.evidence_refs
            if reference in records
        ]
        if not any(
            record.metadata.get("identity_verified") is True
            and record.metadata.get("mentor_role_verified") is not False
            for record in bound
        ):
            return True
    return False


def _merge_research_results(
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
            continue
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
    unresolved.update(
        candidate.candidate_id
        for candidate in candidates
        if not candidate.research_topics or not candidate.evidence_refs
    )
    unresolved.difference_update(
        candidate.candidate_id
        for candidate in candidates
        if candidate.research_topics and candidate.evidence_refs
    )
    return MentorResearchResult(
        candidates=candidates,
        evidence=evidence,
        warnings=_unique([*primary.warnings, *fallback.warnings]),
        used_fallback=True,
        source_chain=_unique([*primary.source_chain, *fallback.source_chain]),
        unresolved_candidate_ids=sorted(unresolved),
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
    target.missing_fields = _candidate_missing_fields(target)
    target.updated_at = max(target.updated_at, incoming.updated_at)


def _candidate_missing_fields(candidate: CandidateMentor) -> list[str]:
    fields = {
        "affiliation": candidate.affiliation,
        "department": candidate.department,
        "research_topics": candidate.research_topics,
        "application_domains": candidate.application_domains,
        "methods": candidate.methods,
        "projects": candidate.projects,
        "homepage": candidate.homepage,
        "recruitment_status": candidate.recruitment_status,
    }
    return [name for name, value in fields.items() if not value]


def _trigger_hits(trigger: str, query: str) -> bool:
    term = trigger.casefold()
    if re.fullmatch(r"[a-z]{1,8}", term):
        return bool(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", query))
    return term in query


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _log_tool_call(
    trace_id: str,
    tool_name: str,
    started: float,
    *,
    status: str,
    error_type: str | None = None,
) -> None:
    logger.info(
        "mentor_workflow_tool_call",
        extra={
            "trace_id": trace_id,
            "agent_name": MentorResearchAgent.name,
            "stage": "mentor_research",
            "tool_name": tool_name,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "status": status,
            "error_type": error_type,
        },
    )
