from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, ValidationError

from backend.integrations.llm.base import ChatModelAdapter
from backend.mentor_workflow.agents.evaluation import MatchingAgent
from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    CandidateResearchAssessment,
    CandidateScreeningResult,
    DomainJudgement,
    EvidenceFreshness,
    EvidenceRecord,
    IntentPacket,
    MatchResult,
    ModelResearchPreparation,
    ResearchAgentContextSnapshot,
    ResearchAuditSnapshot,
    ResearchToolTrace,
)
from backend.mentor_workflow.ustc_sources import (
    InternalMentorRag,
    MentorPaperSearchGateway,
    NullInternalMentorRag,
    PaperSearchHit,
    UstcOfficialMentorSource,
)
from backend.schemas import ResolvedProviderConfig

_DOMAIN_CODES = {
    "artificial_intelligence",
    "computer_systems",
    "cyber_security",
    "mathematics_statistics",
}

_PREPARATION_SYSTEM_CONTEXT = """
You are the model-driven domain and research-planning agent for a USTC mentor
research workflow. Analyze what the user's projects actually demonstrate instead
of copying surface keywords. Infer research problems, methods, capabilities,
primary and adjacent directions, and an evidence-seeking search plan.

Rules:
1. Output JSON only and follow the supplied JSON schema.
2. Do not expose chain-of-thought. Give concise, auditable rationales.
3. Do not invent project details or user skills.
4. Search queries are hypotheses for retrieval, not conclusions.
5. Use domain_codes only from: artificial_intelligence, computer_systems,
   cyber_security, mathematics_statistics.
6. Include several complementary queries: field, method, application, and
   adjacent-direction formulations. Do not rely on one literal keyword.
7. Prefer USTC official identity sources; use papers to establish actual research
   direction and recency; leave unsupported admissions claims unknown.
""".strip()

_PREPARATION_REPAIR_CONTEXT = """
The previous structured response validated as JSON but omitted a required
search boundary. Return the complete schema again. `domain_codes` must contain
at least one allowed code and `primary_directions` must contain at least one
specific direction grounded in the user's message, projects, or topics. Do not
return empty arrays for either field when the user supplied a research topic.
""".strip()

_CANDIDATE_SYSTEM_CONTEXT = """
You are the evidence-analysis and semantic-matching agent in a USTC mentor
workflow. Assess a verified USTC mentor against the user's real project
background. Read the supplied official profile facts and paper title/abstract
metadata. Determine what the papers are actually about and whether the user's
experience transfers to that work.

Rules:
1. Output JSON only and follow the supplied JSON schema.
2. Do not expose chain-of-thought. Return concise evidence-linked explanations.
3. A paper may be relevant even without a literal keyword match, but the decision
   must be supported by its title or abstract.
4. Never use a paper to prove mentor identity or recruitment status.
5. paper_index must refer to the supplied zero-based paper list.
6. Mark unrelated or same-name papers irrelevant.
7. Separate strong fit, transferable fit, missing preparation, and uncertainty.
8. Scores are 0-100 and confidence is 0-1.
""".strip()

_SCREENING_SYSTEM_CONTEXT = """
You are the candidate-screening stage of a USTC mentor research agent.
Return one JSON object only. Do not expose chain-of-thought.

The input is a broad official-faculty recall pool. Judge every supplied candidate
semantically against the user's actual projects and prepared research directions.
Do not require literal keyword overlap. Infer relatedness from research problems,
methods, applications, and transferable skills. Official profile facts are discovery
evidence only; do not invent papers, identity links, or recruitment status.

Set keep_for_paper_search=true only for the strongest candidates worth the more
expensive paper search. Respect max_selected. Low scores are acceptable when the
official pool genuinely lacks a good match; never inflate scores to fill the quota.
Give an evidence-grounded reason and uncertainties for every decision.
""".strip()


class ResearchAuditProvider(Protocol):
    def snapshot(self) -> ResearchAuditSnapshot: ...


class AgenticResearchSession:
    def __init__(self, provider: ResolvedProviderConfig) -> None:
        self.provider = provider
        self.contexts: list[ResearchAgentContextSnapshot] = []
        self.preparation: ModelResearchPreparation | None = None
        self.candidate_screening: CandidateScreeningResult | None = None
        self.candidate_assessments: list[CandidateResearchAssessment] = []
        self.tool_trace: list[ResearchToolTrace] = []
        self.notes: list[str] = [
            (
                "The visible context is a sanitized operational context, "
                "not hidden chain-of-thought."
            ),
            (
                "Current tools are in-process Python adapters; "
                "mcp_server=false is reported explicitly."
            ),
        ]

    def add_trace(
        self,
        *,
        agent_name: str,
        tool_name: str,
        transport: str,
        input_summary: dict[str, str | int | float | bool],
        output_summary: dict[str, str | int | float | bool],
        status: str,
        duration_ms: float,
        evidence_refs: list[str] | None = None,
    ) -> None:
        self.tool_trace.append(
            ResearchToolTrace(
                sequence=len(self.tool_trace) + 1,
                agent_name=agent_name,
                tool_name=tool_name,
                transport=transport,
                mcp_server=False,
                input_summary=input_summary,
                output_summary=output_summary,
                evidence_refs=evidence_refs or [],
                status=status,
                duration_ms=round(duration_ms, 2),
            )
        )

    def snapshot(self) -> ResearchAuditSnapshot:
        return ResearchAuditSnapshot(
            provider_name=self.provider.name,
            model=self.provider.model or "unknown",
            contexts=list(self.contexts),
            preparation=self.preparation,
            candidate_screening=self.candidate_screening,
            candidate_assessments=list(self.candidate_assessments),
            tool_trace=list(self.tool_trace),
            notes=list(self.notes),
        )


class StructuredMentorReasoner:
    def __init__(
        self,
        adapter: ChatModelAdapter,
        provider: ResolvedProviderConfig,
        session: AgenticResearchSession,
    ) -> None:
        self.adapter = adapter
        self.provider = provider
        self.session = session
        self._preparation_trace_id: str | None = None

    def prepare(self, intent: IntentPacket) -> ModelResearchPreparation:
        if (
            self.session.preparation is not None
            and self._preparation_trace_id == intent.trace_id
        ):
            return self.session.preparation
        self.session.contexts.append(
            ResearchAgentContextSnapshot(
                agent_name="model_driven_domain_expert_agent",
                objective=(
                    "Interpret the user's projects and create a semantic mentor and "
                    "paper search plan."
                ),
                model=self.provider.model or "unknown",
                allowed_tools=[
                    "structured_chat_model",
                    "internal_ustc_rag",
                    "ustc_official_faculty",
                    "ustc_official_profile",
                    "arxiv_search",
                    "openalex_search",
                ],
                evidence_policy=[
                    "Official USTC sources prove identity and mentor role.",
                    "Paper title/abstract evidence may establish research direction.",
                    "Recruitment remains unknown without explicit evidence.",
                ],
                source_policy=[
                    "internal curated RAG first",
                    "USTC official directory and profile second",
                    "arXiv/OpenAlex paper evidence third",
                ],
                input_summary={
                    "goal": intent.goal.value,
                    "project_count": len(intent.projects),
                    "stated_topic_count": len(intent.research_topics),
                    "institution_scope": "中国科学技术大学",
                },
                system_context=_PREPARATION_SYSTEM_CONTEXT,
            )
        )
        payload = {
            "intent": intent.model_dump(mode="json"),
            "required_json_schema": ModelResearchPreparation.model_json_schema(),
        }
        preparation = self._generate(
            agent_name="model_driven_domain_expert_agent",
            system_context=_PREPARATION_SYSTEM_CONTEXT,
            payload=payload,
            schema=ModelResearchPreparation,
        )
        invalid_codes = [
            code for code in preparation.domain_codes if code not in _DOMAIN_CODES
        ]
        if invalid_codes:
            raise ValueError(
                f"Model returned unsupported domain codes: {invalid_codes}"
            )
        if not preparation.domain_codes or not preparation.primary_directions:
            # Some OpenAI-compatible models occasionally satisfy the JSON
            # syntax/schema while leaving semantic arrays empty. Give the model
            # one focused repair pass before using the deterministic routing
            # fallback below.
            try:
                repaired = self._generate(
                    agent_name="model_driven_domain_expert_agent_repair",
                    system_context=(
                        _PREPARATION_SYSTEM_CONTEXT
                        + "\n\n"
                        + _PREPARATION_REPAIR_CONTEXT
                    ),
                    payload={
                        **payload,
                        "previous_preparation": preparation.model_dump(mode="json"),
                        "validation_error": (
                            "domain_codes and primary_directions must both be non-empty"
                        ),
                    },
                    schema=ModelResearchPreparation,
                )
                if repaired.domain_codes or repaired.primary_directions:
                    preparation = repaired
                    invalid_codes = [
                        code
                        for code in preparation.domain_codes
                        if code not in _DOMAIN_CODES
                    ]
                    if invalid_codes:
                        raise ValueError(
                            f"Model returned unsupported domain codes: {invalid_codes}"
                        )
            except Exception as exc:  # noqa: BLE001 - fallback is intentional
                self.session.notes.append(
                    f"Structured preparation repair unavailable: {type(exc).__name__}."
                )

        if not preparation.domain_codes:
            inferred_codes = _infer_domain_codes(intent, preparation)
            preparation = preparation.model_copy(update={"domain_codes": inferred_codes})
            self.session.notes.append(
                "Domain codes were routed deterministically from the supplied user context."
            )
        if not preparation.primary_directions:
            inferred_directions = _infer_primary_directions(intent, preparation)
            preparation = preparation.model_copy(
                update={"primary_directions": inferred_directions}
            )
            self.session.notes.append(
                "Primary directions were recovered from the supplied user context."
            )
        self.session.preparation = preparation
        self._preparation_trace_id = intent.trace_id
        return preparation

    def domain_judgements(self, intent: IntentPacket) -> list[DomainJudgement]:
        preparation = self.prepare(intent)
        search_concepts = _unique(
            [
                *preparation.primary_directions,
                *preparation.adjacent_directions,
                *preparation.methods,
                *[query.query for query in preparation.search_queries],
            ]
        )
        return [
            DomainJudgement(
                expert_name=f"model_driven_{domain}_expert",
                domain=domain,
                search_concepts=search_concepts,
                exclusions=list(preparation.exclusions),
                boundary=preparation.overall_explanation,
                interdisciplinary_links=[
                    other for other in preparation.domain_codes if other != domain
                ],
                conflicts=list(preparation.uncertainties),
            )
            for domain in preparation.domain_codes
        ]

    def assess_candidate(
        self,
        candidate: CandidateMentor,
        hits: list[PaperSearchHit],
        intent: IntentPacket,
        official_evidence: list[EvidenceRecord],
    ) -> CandidateResearchAssessment:
        preparation = self.prepare(intent)
        self.session.contexts.append(
            ResearchAgentContextSnapshot(
                agent_name="model_driven_candidate_evidence_agent",
                objective=(
                    "Infer the mentor's actual recent research and explain semantic "
                    "fit to the user's projects."
                ),
                model=self.provider.model or "unknown",
                allowed_tools=[
                    "structured_chat_model",
                    "official_evidence_reader",
                    "paper_metadata_reader",
                ],
                evidence_policy=[
                    (
                        "Use only supplied official facts and paper "
                        "title/abstract metadata."
                    ),
                    "Relevant paper indices must point to supplied papers.",
                    "Model interpretation is linked back to the underlying source URL.",
                ],
                source_policy=[
                    "official profile facts",
                    "attributable recent arXiv/OpenAlex papers",
                ],
                input_summary={
                    "candidate_id": candidate.candidate_id,
                    "paper_count": len(hits),
                    "project_count": len(intent.projects),
                },
                system_context=_CANDIDATE_SYSTEM_CONTEXT,
            )
        )
        payload = {
            "user_research_preparation": preparation.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "official_evidence": [
                {
                    "evidence_id": record.evidence_id,
                    "source_uri": record.source_uri,
                    "extracted_fact": record.extracted_fact,
                    "supports_fields": record.metadata.get("supports_fields", ""),
                }
                for record in official_evidence
            ],
            "papers": [
                {
                    "paper_index": index,
                    "source": hit.source,
                    "title": hit.title,
                    "abstract": hit.abstract,
                    "authors": hit.authors,
                    "year": hit.year,
                    "venue": hit.venue,
                    "source_uri": _paper_uri(hit),
                }
                for index, hit in enumerate(hits)
            ],
            "required_json_schema": CandidateResearchAssessment.model_json_schema(),
        }
        assessment = self._generate(
            agent_name="model_driven_candidate_evidence_agent",
            system_context=_CANDIDATE_SYSTEM_CONTEXT,
            payload=payload,
            schema=CandidateResearchAssessment,
        )
        if assessment.candidate_id != candidate.candidate_id:
            raise ValueError("Model assessment candidate_id does not match input")
        invalid_indices = [
            finding.paper_index
            for finding in assessment.relevant_papers
            if finding.paper_index >= len(hits)
        ]
        if invalid_indices:
            raise ValueError(
                f"Model referenced unavailable paper indices: {invalid_indices}"
            )
        return assessment

    def screen_candidates(
        self,
        candidates: list[CandidateMentor],
        intent: IntentPacket,
        evidence: list[EvidenceRecord],
        *,
        max_selected: int,
    ) -> CandidateScreeningResult:
        preparation = self.prepare(intent)
        candidate_facts: dict[str, list[str]] = {}
        for record in evidence:
            if record.candidate_id is None:
                continue
            candidate_facts.setdefault(record.candidate_id, []).append(
                record.extracted_fact
            )
        self.session.contexts.append(
            ResearchAgentContextSnapshot(
                agent_name="candidate_screening_agent",
                objective=(
                    "Semantically screen a broad official USTC faculty pool before "
                    "expensive paper retrieval."
                ),
                model=self.provider.model or "unknown",
                allowed_tools=["validated JSON model inference"],
                evidence_policy=[
                    "Judge only supplied official profile facts.",
                    "Screening is discovery, not proof of paper authorship.",
                    "Do not force weak candidates into the selected set.",
                ],
                source_policy=[
                    "Official USTC faculty search and profile input.",
                    "Selected candidates proceed to arXiv/OpenAlex verification.",
                ],
                input_summary={
                    "candidate_pool_size": len(candidates),
                    "max_selected": max_selected,
                    "project_count": len(intent.projects),
                },
                system_context=_SCREENING_SYSTEM_CONTEXT,
            )
        )
        payload = {
            "task": (
                "Return JSON matching CandidateScreeningResult and decide whether "
                "each candidate merits paper search."
            ),
            "max_selected": max_selected,
            "prepared_user_research_profile": preparation.model_dump(mode="json"),
            "user_projects": [
                project.model_dump(mode="json") for project in intent.projects
            ],
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "mentor_name": candidate.mentor_name,
                    "department": candidate.department,
                    "research_topics": candidate.research_topics,
                    "official_facts": candidate_facts.get(
                        candidate.candidate_id, []
                    )[:6],
                }
                for candidate in candidates
            ],
            "required_json_schema": CandidateScreeningResult.model_json_schema(),
        }
        result = self._generate(
            agent_name="candidate_screening_agent",
            system_context=_SCREENING_SYSTEM_CONTEXT,
            payload=payload,
            schema=CandidateScreeningResult,
        )
        allowed_ids = {candidate.candidate_id for candidate in candidates}
        result.decisions = [
            decision
            for decision in result.decisions
            if decision.candidate_id in allowed_ids
        ]
        self.session.candidate_screening = result
        return result

    def _generate(
        self,
        *,
        agent_name: str,
        system_context: str,
        payload: dict,
        schema: type[BaseModel],
    ):
        provider = self.provider.model_copy(deep=True)
        provider.settings = {
            **provider.settings,
            "response_format": {"type": "json_object"},
        }
        started = perf_counter()
        try:
            raw = self.adapter.generate_text(
                provider,
                [
                    {"role": "system", "content": system_context},
                    {
                        "role": "user",
                        "content": (
                            "Return json matching required_json_schema.\n"
                            + json.dumps(payload, ensure_ascii=False)
                        ),
                    },
                ],
            )
            parsed = _parse_json_model(raw, schema)
        except Exception:
            self.session.add_trace(
                agent_name=agent_name,
                tool_name="chat_model.generate_structured",
                transport="openai_compatible_https",
                input_summary={"schema": schema.__name__},
                output_summary={"validated": False},
                status="failed",
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise
        self.session.add_trace(
            agent_name=agent_name,
            tool_name="chat_model.generate_structured",
            transport="openai_compatible_https",
            input_summary={"schema": schema.__name__},
            output_summary={"validated": True},
            status="completed",
            duration_ms=(perf_counter() - started) * 1000,
        )
        return parsed


class ModelDrivenDomainExpertAgent:
    name = "model_driven_domain_expert_agent"

    def __init__(self, reasoner: StructuredMentorReasoner) -> None:
        self.reasoner = reasoner

    def run(self, intent: IntentPacket) -> list[DomainJudgement]:
        return self.reasoner.domain_judgements(intent)


class AgenticPaperResearchEnricher:
    def __init__(
        self,
        gateway: MentorPaperSearchGateway,
        reasoner: StructuredMentorReasoner,
        session: AgenticResearchSession,
        *,
        max_candidates: int = 5,
        max_results_per_source: int = 8,
        max_papers_per_candidate: int = 10,
        min_relevance_score: float = 35,
    ) -> None:
        self.gateway = gateway
        self.reasoner = reasoner
        self.session = session
        self.max_candidates = max_candidates
        self.max_results_per_source = max_results_per_source
        self.max_papers_per_candidate = max_papers_per_candidate
        self.min_relevance_score = min_relevance_score

    def enrich(
        self,
        result,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ):
        enriched = result.model_copy(deep=True)
        all_evidence = list(enriched.evidence)
        warnings = list(enriched.warnings)
        unresolved: set[str] = set()
        for candidate in enriched.candidates[: self.max_candidates]:
            hits, search_warnings = self._search_candidate(candidate, domain_judgements)
            warnings.extend(search_warnings)
            official_evidence = [
                record
                for record in all_evidence
                if record.candidate_id == candidate.candidate_id
            ]
            assessment = self.reasoner.assess_candidate(
                candidate, hits, intent, official_evidence
            )
            new_evidence = self._apply_assessment(candidate, hits, assessment)
            assessment.evidence_refs = _unique(
                [
                    *candidate.evidence_refs,
                    *[record.evidence_id for record in new_evidence],
                ]
            )
            self.session.candidate_assessments = [
                current
                for current in self.session.candidate_assessments
                if current.candidate_id != assessment.candidate_id
            ]
            self.session.candidate_assessments.append(assessment)
            all_evidence.extend(new_evidence)
            if not candidate.research_topics:
                unresolved.add(candidate.candidate_id)
            candidate.missing_fields = _candidate_missing_fields(candidate)
        assessed = {
            assessment.candidate_id: assessment
            for assessment in self.session.candidate_assessments
        }
        retained: list[CandidateMentor] = []
        for candidate in enriched.candidates:
            candidate_assessment = assessed.get(candidate.candidate_id)
            if candidate_assessment is not None and (
                candidate_assessment.overall_relevance < self.min_relevance_score
                or not candidate.research_topics
            ):
                continue
            retained.append(candidate)
        enriched.candidates = retained
        retained_ids = {candidate.candidate_id for candidate in retained}
        unresolved.intersection_update(retained_ids)
        enriched.evidence = all_evidence
        enriched.warnings = _unique(warnings)
        enriched.used_fallback = True
        enriched.source_chain = _unique(
            [
                *enriched.source_chain,
                "agentic_paper_research_arxiv_openalex",
                "model_semantic_evidence_assessment",
            ]
        )
        enriched.unresolved_candidate_ids = sorted(unresolved)
        return enriched

    def _search_candidate(
        self,
        candidate: CandidateMentor,
        domain_judgements: list[DomainJudgement],
    ) -> tuple[list[PaperSearchHit], list[str]]:
        aliases = _unique(
            [
                candidate.mentor_name,
                str(candidate.source_metadata.get("english_name", "")),
            ]
        )
        english_name = next(
            (alias for alias in aliases if re.search(r"[A-Za-z]", alias)), None
        )
        primary_name = english_name or candidate.mentor_name
        concepts = _unique(
            [
                concept
                for judgement in domain_judgements
                for concept in judgement.search_concepts
            ]
        )
        specs: list[tuple[str, str, str]] = []
        if english_name:
            specs.append(("arxiv", "advanced", f'au:"{english_name}"'))
        specs.append(
            (
                "openalex",
                "auto",
                " ".join([primary_name, *concepts[:2]]).strip(),
            )
        )
        hits: list[PaperSearchHit] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for source, mode, query in specs:
            started = perf_counter()
            try:
                page = self.gateway.search(
                    query,
                    source=source,
                    mode=mode,
                    max_results=self.max_results_per_source,
                )
            except Exception as exc:  # noqa: BLE001 - isolate external source failures
                warnings.append(
                    f"{source} search failed for {candidate.mentor_name}: "
                    f"{type(exc).__name__}: {exc}"
                )
                self.session.add_trace(
                    agent_name="mentor_research_agent",
                    tool_name=f"{source}_paper_search",
                    transport="in_process_http_adapter",
                    input_summary={
                        "candidate": candidate.mentor_name,
                        "query": query,
                    },
                    output_summary={"error": type(exc).__name__},
                    status="failed",
                    duration_ms=(perf_counter() - started) * 1000,
                )
                continue
            warnings.extend(page.warnings)
            attributable = [
                hit
                for hit in page.hits
                if _paper_author_matches(hit.authors, aliases)
                and _paper_freshness(hit.year) != EvidenceFreshness.stale
            ]
            self.session.add_trace(
                agent_name="mentor_research_agent",
                tool_name=f"{source}_paper_search",
                transport="in_process_http_adapter",
                input_summary={
                    "candidate": candidate.mentor_name,
                    "query": query,
                },
                output_summary={
                    "returned": len(page.hits),
                    "author_attributed": len(attributable),
                },
                status="completed",
                duration_ms=(perf_counter() - started) * 1000,
            )
            for hit in attributable:
                key = hit.doi or hit.arxiv_id or hit.openalex_id or hit.title.casefold()
                if key in seen:
                    continue
                seen.add(key)
                hits.append(hit)
                if len(hits) >= self.max_papers_per_candidate:
                    return hits, warnings
        return hits, warnings

    def _apply_assessment(
        self,
        candidate: CandidateMentor,
        hits: list[PaperSearchHit],
        assessment: CandidateResearchAssessment,
    ) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for finding in assessment.relevant_papers:
            if not finding.relevant:
                continue
            hit = hits[finding.paper_index]
            record = EvidenceRecord(
                candidate_id=candidate.candidate_id,
                source_type=f"{hit.source}_paper_semantic_assessment",
                source_uri=_paper_uri(hit),
                title=hit.title,
                extracted_fact=(
                    f"论文标题/摘要证据被模型归纳为“{finding.actual_direction}”；"
                    f"证据依据：{finding.evidence_basis}；"
                    f"与用户项目的关系：{finding.project_fit}。"
                ),
                locator="paper title/abstract/authors + structured model assessment",
                freshness=_paper_freshness(hit.year),
                confidence=finding.confidence,
                metadata={
                    "identity_verified": False,
                    "supports_fields": "research_topics,methods,publications",
                    "year": hit.year or 0,
                    "source_priority": "paper_semantic_fallback",
                    "interpretation_model": self.session.provider.model or "unknown",
                },
            )
            records.append(record)
            candidate.evidence_refs = _unique(
                [*candidate.evidence_refs, record.evidence_id]
            )
            candidate.research_topics = _unique(
                [*candidate.research_topics, *finding.inferred_topics]
            )
            candidate.methods = _unique([*candidate.methods, *finding.inferred_methods])
            candidate.publications = _unique([*candidate.publications, hit.title])
        return records


class AgenticMentorResearchTool:
    def __init__(
        self,
        *,
        official_source: UstcOfficialMentorSource,
        paper_enricher: AgenticPaperResearchEnricher,
        reasoner: StructuredMentorReasoner,
        session: AgenticResearchSession,
        internal_rag: InternalMentorRag | None = None,
    ) -> None:
        self.official_source = official_source
        self.paper_enricher = paper_enricher
        self.reasoner = reasoner
        self.session = session
        self.internal_rag = internal_rag or NullInternalMentorRag()

    def search_local(
        self, intent: IntentPacket, domain_judgements: list[DomainJudgement]
    ):
        started = perf_counter()
        result = self.internal_rag.retrieve(intent, domain_judgements)
        self.session.add_trace(
            agent_name="mentor_research_agent",
            tool_name="internal_ustc_rag",
            transport="in_process_protocol",
            input_summary={"trace_id": intent.trace_id},
            output_summary={"candidate_count": len(result.candidates)},
            status="completed",
            duration_ms=(perf_counter() - started) * 1000,
        )
        return result

    def search_fallback(
        self, intent: IntentPacket, domain_judgements: list[DomainJudgement]
    ):
        preparation = self.reasoner.prepare(intent)
        # Preparation is an evidence-seeking plan, not permission to replace
        # the user's topic with a broad model-generated parent.  Keep the
        # original concepts and only use the contract's typed recall aliases;
        # adjacent directions remain audit context for paper reasoning.
        contract_terms = intent.query_contract.expanded_terms
        semantic_intent = intent.model_copy(
            deep=True,
            update={
                "research_topics": _unique(
                    [
                        *intent.research_topics,
                        *contract_terms,
                    ]
                ),
                "methods": _unique(intent.methods),
                "application_domains": _unique(intent.application_domains),
            },
        )
        started = perf_counter()
        official = self.official_source.search(semantic_intent, domain_judgements)
        self.session.add_trace(
            agent_name="mentor_research_agent",
            tool_name="ustc_official_faculty_and_profiles",
            transport="in_process_https_adapters",
            input_summary={
                "semantic_direction_count": len(preparation.primary_directions),
                "query_plan_count": len(preparation.search_queries),
            },
            output_summary={
                "candidate_count": len(official.candidates),
                "evidence_count": len(official.evidence),
                "unresolved_count": len(official.unresolved_candidate_ids),
            },
            status="completed",
            duration_ms=(perf_counter() - started) * 1000,
            evidence_refs=[record.evidence_id for record in official.evidence],
        )
        if len(official.candidates) > self.paper_enricher.max_candidates:
            screening = self.reasoner.screen_candidates(
                official.candidates,
                semantic_intent,
                official.evidence,
                max_selected=self.paper_enricher.max_candidates,
            )
            selected = sorted(
                (
                    decision
                    for decision in screening.decisions
                    if decision.keep_for_paper_search
                ),
                key=lambda decision: (
                    -decision.coarse_relevance,
                    decision.candidate_id,
                ),
            )[: self.paper_enricher.max_candidates]
            selected_ids = {decision.candidate_id for decision in selected}
            official.candidates = [
                candidate
                for candidate in official.candidates
                if candidate.candidate_id in selected_ids
            ]
            official.evidence = [
                record
                for record in official.evidence
                if record.candidate_id is None
                or record.candidate_id in selected_ids
            ]
            official.unresolved_candidate_ids = [
                candidate_id
                for candidate_id in official.unresolved_candidate_ids
                if candidate_id in selected_ids
            ]
            self.session.add_trace(
                agent_name="candidate_screening_agent",
                tool_name="semantic_candidate_pool_filter",
                transport="in_process_structured_decision",
                input_summary={
                    "pool_size": len(screening.decisions),
                    "max_selected": self.paper_enricher.max_candidates,
                },
                output_summary={"selected_count": len(official.candidates)},
                status="completed",
                duration_ms=0,
                evidence_refs=[
                    record.evidence_id for record in official.evidence
                ],
            )
        return self.paper_enricher.enrich(official, semantic_intent, domain_judgements)


class ModelDrivenMatchingAgent:
    name = "model_driven_matching_agent"

    def __init__(self, session: AgenticResearchSession) -> None:
        self.session = session
        self.base = MatchingAgent()

    def run(
        self,
        intent: IntentPacket,
        candidates: list[CandidateMentor],
        ledger: EvidenceLedger,
    ) -> list[MatchResult]:
        base_results = self.base.run(intent, candidates, ledger)
        assessments = {
            assessment.candidate_id: assessment
            for assessment in self.session.candidate_assessments
        }
        revised: list[MatchResult] = []
        for result in base_results:
            assessment = assessments.get(result.candidate_id)
            if assessment is None:
                revised.append(result)
                continue
            valid_assessment_refs = [
                reference
                for reference in assessment.evidence_refs
                if ledger.get(reference) is not None
            ]
            dimensions = result.dimension_scores.model_copy(
                update={
                    "research_topic_match": assessment.research_topic_fit,
                    "method_match": assessment.method_fit,
                    "application_match": assessment.application_fit,
                    "student_background_fit": assessment.project_background_fit,
                }
            )
            revised.append(
                result.model_copy(
                    update={
                        # Model assessment may refine ordering, but it must not
                        # rewrite the deterministic eligibility/display score.
                        "total_score": result.total_score,
                        "dimension_scores": dimensions,
                        "score_breakdown": {
                            **result.score_breakdown,
                            "eligibility_score": result.total_score,
                            "ranking_score": dimensions.mean_score(),
                        },
                        "rationale": _unique(
                            [
                                assessment.direction_summary,
                                *assessment.project_alignment,
                                assessment.recommendation,
                            ]
                        ),
                        "negative_factors": _unique(
                            [*result.negative_factors, *assessment.gaps]
                        ),
                        "uncertainty": _unique(
                            [*result.uncertainty, *assessment.uncertainty]
                        ),
                        "evidence_refs": _unique(
                            [*result.evidence_refs, *valid_assessment_refs]
                        ),
                    }
                )
            )
        ranked = sorted(
            revised,
            key=lambda item: (
                -item.score_breakdown.get("ranking_score", item.total_score),
                item.candidate_id,
            ),
        )
        return [
            item.model_copy(update={"ranking_position": index})
            for index, item in enumerate(ranked, start=1)
        ]


def _parse_json_model(raw: str, schema: type[BaseModel]):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        return schema.model_validate_json(cleaned)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Structured model output failed {schema.__name__} validation: {exc}"
        ) from exc


def _paper_author_matches(authors: list[object], aliases: list[str]) -> bool:
    normalized_aliases = {_person_key(alias) for alias in aliases if alias}
    return any(
        _person_key(_author_name(author)) in normalized_aliases
        for author in authors
        if _author_name(author)
    )


def _author_name(author: object) -> str:
    if isinstance(author, str):
        return author
    if isinstance(author, dict):
        for key in ("name", "display_name", "author_name"):
            if value := author.get(key):
                return str(value)
    return ""


def _person_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold())


def _paper_uri(hit: PaperSearchHit) -> str:
    return (
        hit.landing_page_url
        or hit.pdf_url
        or (f"https://doi.org/{hit.doi}" if hit.doi else "")
        or f"{hit.source}:{hit.title}"
    )


def _paper_freshness(year: int | None) -> EvidenceFreshness:
    if year is None:
        return EvidenceFreshness.unknown
    age = datetime.now(UTC).year - year
    if age <= 2:
        return EvidenceFreshness.current
    if age <= 5:
        return EvidenceFreshness.recent
    return EvidenceFreshness.stale


def _candidate_missing_fields(candidate: CandidateMentor) -> list[str]:
    fields = {
        "affiliation": candidate.affiliation,
        "department": candidate.department,
        "research_topics": candidate.research_topics,
        "methods": candidate.methods,
        "publications": candidate.publications,
        "projects": candidate.projects,
        "homepage": candidate.homepage,
        "recruitment_status": candidate.recruitment_status,
    }
    return [name for name, value in fields.items() if not value]


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _infer_domain_codes(
    intent: IntentPacket, preparation: ModelResearchPreparation
) -> list[str]:
    """Infer routing domains only from explicit user/model context.

    This is a search-router safeguard, not a mentor claim. It prevents one
    malformed model response from turning a valid topic into an unrecoverable
    workflow while keeping the allowed domain vocabulary closed.
    """

    values = [
        *intent.research_topics,
        *intent.methods,
        *intent.application_domains,
        *preparation.primary_directions,
        *preparation.adjacent_directions,
        intent.raw_message,
    ]
    text = " ".join(values).casefold()
    rules = (
        (
            "cyber_security",
            ("网络安全", "系统安全", "信息安全", "cyber", "security", "privacy"),
        ),
        (
            "mathematics_statistics",
            ("数学", "统计", "概率", "几何", "拓扑", "math", "statistics", "theorem"),
        ),
        (
            "computer_systems",
            ("计算机系统", "软件系统", "云原生", "量子计算", "computer systems", "distributed systems"),
        ),
        (
            "artificial_intelligence",
            (
                "人工智能", "机器学习", "深度学习", "推荐系统", "大模型", "智能体",
                "ai", "machine learning", "deep learning", "recommendation", "llm",
            ),
        ),
    )
    inferred = [
        code
        for code, keywords in rules
        if any(_keyword_present(text, keyword) for keyword in keywords)
    ]
    return inferred


def _keyword_present(text: str, keyword: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in keyword):
        return keyword in text
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _infer_primary_directions(
    intent: IntentPacket, preparation: ModelResearchPreparation
) -> list[str]:
    values = _unique(
        [
            *intent.research_topics,
            *intent.application_domains,
            *preparation.adjacent_directions,
            *preparation.methods,
        ]
    )
    if values:
        return values[:3]
    message = " ".join(intent.raw_message.split()).strip()
    return [message[:120] or "人工智能导师匹配"]
