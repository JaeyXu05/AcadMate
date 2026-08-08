from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

from backend.mentor_workflow.errors import TemporaryToolError, ToolTimeoutError
from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.research_tools import MentorResearchTool
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
            if any(trigger.casefold() in query for trigger in config.triggers)
        ]
        if not selected:
            selected = [DOMAIN_CONFIGS[0]]
        judgements: list[DomainJudgement] = []
        for config in selected:
            concepts = [
                *intent.research_topics,
                *intent.methods,
                *intent.application_domains,
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

    def run(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
        existing_evidence: list[EvidenceRecord],
    ) -> MentorResearchResult:
        warnings: list[str] = []
        try:
            local = self._call_tool("search_local", intent, domain_judgements)
        except TemporaryToolError as exc:
            warnings.append(str(exc))
            local = MentorResearchResult()
        combined = local
        if _needs_external_fallback(local):
            try:
                fallback = self._call_tool("search_fallback", intent, domain_judgements)
            except TemporaryToolError as exc:
                warnings.append(str(exc))
                fallback = MentorResearchResult(used_fallback=True)
            combined = _merge_research_results(local, fallback)
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
        "methods": candidate.methods,
        "projects": candidate.projects,
        "homepage": candidate.homepage,
        "recruitment_status": candidate.recruitment_status,
    }
    return [name for name, value in fields.items() if not value]


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
