"""Unified mentor retrieval facade over curated RAG + live paper search.

把散落的多套检索逻辑收敛到一个入口：

- 导师召回（离线 RAG 库）：
  正值稠密向量 ``DenseInternalMentorRag``（``MentorSemanticIndex``），
  海量无法用（embedding 未配置/不可用）时回退到手写关键词+TF*IDF向量的
  ``FileInternalMentorRag``。二者导出相同的 ``MentorResearchResult``。
- 论文补充（实时 arXiv/OpenAlex）：
  对所有召回导师主动检索 arXiv/OpenAlex，把归属论文标题写入
  ``CandidateMentor.publications`` 并生成论文证据，使检索结果主动带论文。

对外仍实现 ``backend.mentor_workflow.ustc_sources.InternalMentorRag`` 协议，
调用方（工作流 / PDF / 阅读论文）无需改动。
"""

from __future__ import annotations

import re

from backend.mentor_workflow.schemas import (
    CandidateMentor,
    DomainJudgement,
    EvidenceFreshness,
    EvidenceRecord,
    IntentPacket,
    MentorResearchResult,
)
from backend.mentor_workflow.query_semantics import (
    build_query_contract,
    candidate_relevance,
    evidence_query_relevant,
    expanded_terms_for,
    freshness_label,
    qualifies,
)
from backend.mentor_workflow.text_matching import (
    author_matches as _author_matches,
    author_name as _author_name,
    contains as _contains,
    freshness_from_year as _freshness_from_year,
    normalize as _normalize,
    person_key as _person_key,
    unique as _unique,
)

# ``re`` is still needed for the arXiv/OpenAlex search-spec construction in
# _candidate_papers; the shared text_matching module owns the matching logic.


def _merge_candidate(
    primary: CandidateMentor, secondary: CandidateMentor
) -> CandidateMentor:
    """合并同一候选在 dense/lexical 两路的记录，取并集、保留更完整的一侧。

    列表字段（topics/methods/publications/evidence_refs）合并去重；主侧优先级更高，
    标量字段（affiliation/homepage/recruitment 等）前者缺则补后者的。
    """
    merged_meta = {**secondary.source_metadata, **primary.source_metadata}
    return primary.model_copy(
        update={
            "research_topics": _unique(
                [*primary.research_topics, *secondary.research_topics]
            ),
            "application_domains": _unique(
                [*primary.application_domains, *secondary.application_domains]
            ),
            "methods": _unique([*primary.methods, *secondary.methods]),
            "publications": _unique([*primary.publications, *secondary.publications]),
            "evidence_refs": _unique(
                [*primary.evidence_refs, *secondary.evidence_refs]
            ),
            "projects": _unique([*primary.projects, *secondary.projects]),
            "affiliation": primary.affiliation or secondary.affiliation,
            "department": primary.department or secondary.department,
            "homepage": primary.homepage or secondary.homepage,
            "recruitment_status": primary.recruitment_status
            or secondary.recruitment_status,
            "source_metadata": merged_meta,
            "topic_assertions": [
                *primary.topic_assertions,
                *[item for item in secondary.topic_assertions if item not in primary.topic_assertions],
            ],
            "publication_topics": _unique(
                [*primary.publication_topics, *secondary.publication_topics]
            ),
        }
    )


def _source_level(record: EvidenceRecord) -> str:
    source = record.source_type.casefold()
    if "official_faculty_profile" in source:
        return "L1"
    if "official_faculty_directory" in source:
        return "L2"
    if record.metadata.get("identity_verified") is True and "paper" in source:
        return "L3"
    if any(name in source for name in ("openalex", "s2", "dblp", "arxiv")):
        return "L4"
    return "L5"


class UnifiedMentorRetrieval:
    """Facade: dense语义召回（主力）+ 手写向量回退 + 主动论文补充。"""

    def __init__(
        self,
        *,
        dense: object | None = None,
        lexical: object | None = None,
        paper_gateway: object | None = None,
        max_results_per_source: int = 5,
        max_papers_per_candidate: int = 3,
        dense_threshold: float = 0.5,
        lexical_min_hits: int = 1,
        max_fused_candidates: int = 80,
        enable_live_paper_enrichment: bool = False,
    ) -> None:
        self._dense = dense
        self._lexical = lexical
        self._paper_gateway = paper_gateway
        self.max_results_per_source = max_results_per_source
        self.max_papers_per_candidate = max_papers_per_candidate
        # 融合召回的相关性阈值：
        # - dense_threshold：dense 余弦分数（0~1）低于此值且无 lexical 精确命中的候选丢弃，
        #   过滤"学习/数据"等泛词的语义漂移噪声。
        # - lexical_min_hits：lexical 子串命中数 ≥ 此值的候选无条件保留（精确命中是金标准）。
        # - max_fused_candidates：在语义边界过滤前保留的候选上限。不能过早截为
        #   8：短而精确的 query 可能有大量 lexical 命中，先按 dense/ID 截断会把
        #   真正的合格导师排除在边界过滤之外。默认与 lexical Top-K 对齐；最终
        #   对用户仍只返回最多 5 位导师。
        self._dense_threshold = dense_threshold
        self._lexical_min_hits = lexical_min_hits
        self._max_fused_candidates = max_fused_candidates
        self._enable_live_paper_enrichment = enable_live_paper_enrichment

    def retrieve(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        # 1. 导师召回：dense 与 lexical **都跑**，再按相关性阈值融合去重排序。
        #    dense 擅长宽领域语义召回，但窄主题/短查询会有语义漂移；lexical 的精确
        #    子串命中能稳定捞回 dense 漏掉的导师（如"强化学习"漏掉王洪波）。
        errors: list[str] = []
        dense_result: MentorResearchResult | None = None
        lexical_result: MentorResearchResult | None = None
        if self._dense is not None:
            try:
                dense_result = self._dense.retrieve(intent, domain_judgements)
            except Exception as exc:  # noqa: BLE001 - continue with lexical
                errors.append(f"dense retrieval failed: {type(exc).__name__}: {exc}")
        if self._lexical is not None:
            try:
                lexical_result = self._lexical.retrieve(intent, domain_judgements)
            except Exception as exc:  # noqa: BLE001 - surface as warning
                errors.append(
                    f"lexical retrieval failed: {type(exc).__name__}: {exc}"
                )

        result = self._fuse_results(dense_result, lexical_result, errors)
        if result is not None:
            result = self._apply_query_boundary(result, intent)

        if result is None or not result.candidates:
            return MentorResearchResult(
                warnings=_unique([*errors, *result.warnings])
                if result is not None
                else _unique([*errors, "没有可用的检索器"]),
                source_chain=["internal_ustc_rag"],
            )

        # 2. 主动对每个召回导师检索论文（不再只针对缺方向导师）。
        if self._enable_live_paper_enrichment and self._paper_gateway is not None and result.candidates:
            result = self._attach_papers(result, intent, domain_judgements)

        result.warnings = _unique([*result.warnings, *errors])
        return result

    def _apply_query_boundary(
        self,
        result: MentorResearchResult,
        intent: IntentPacket,
    ) -> MentorResearchResult:
        """Apply the same absolute relevance gate to every retriever path."""
        contract = intent.query_contract
        if not contract.canonical_query:
            contract = build_query_contract(
                intent.raw_message,
                intent.research_topics,
                intent.methods,
                intent.application_domains,
            )
        kept: list[CandidateMentor] = []
        match_types: dict[str, str] = {}
        scores: dict[str, float] = {}
        for candidate in result.candidates:
            bound_records = [
                record
                for record in result.evidence
                if record.candidate_id == candidate.candidate_id
            ]
            official_topic_support = any(
                record.metadata.get("identity_verified") is True
                and "research_topics" in str(record.metadata.get("supports_fields", ""))
                for record in bound_records
            )
            scored_candidate = candidate
            if official_topic_support and not candidate.source_metadata.get("topics_source"):
                scored_candidate = candidate.model_copy(
                    deep=True,
                    update={
                        "source_metadata": {
                            **candidate.source_metadata,
                            "topics_source": 1,
                        }
                    },
                )
            score, match_type, breakdown = candidate_relevance(
                contract,
                scored_candidate,
                fallback=result.used_fallback,
            )
            if not qualifies(score, match_type):
                continue
            meta = dict(candidate.source_metadata)
            meta.update(
                {
                    "absolute_relevance": score,
                    "match_type": match_type,
                    "query_contract": contract.canonical_query,
                    "must_preserve": ",".join(contract.must_preserve),
                    **{f"score_{key}": value for key, value in breakdown.items()},
                }
            )
            kept.append(candidate.model_copy(deep=True, update={"source_metadata": meta}))
            match_types[candidate.candidate_id] = match_type
            scores[candidate.candidate_id] = score
        kept.sort(key=lambda item: (-scores[item.candidate_id], item.candidate_id))
        kept = kept[:5]
        kept_ids = {item.candidate_id for item in kept}
        evidence: list[EvidenceRecord] = []
        for record in result.evidence:
            if record.candidate_id not in kept_ids:
                continue
            if record.metadata.get("identity_verified") is not True:
                continue
            supports = {
                item.strip()
                for item in str(record.metadata.get("supports_fields", "")).split(",")
                if item.strip()
            }
            supports_query = bool({"research_topics", "methods"} & supports)
            source_level = _source_level(record)
            # A source level is not a substitute for query support: an official
            # profile can still contain only a broad parent concept.  Keep a
            # record as candidate evidence only when its text supports one of
            # the typed query concepts.
            if supports_query and not evidence_query_relevant(contract, record.title, record.extracted_fact):
                continue
            if supports_query and source_level in {"L4", "L5"}:
                continue
            year = record.metadata.get("year")
            year_value = int(year) if isinstance(year, int) else None
            evidence.append(
                record.model_copy(
                    deep=True,
                    update={
                        "query": contract.canonical_query,
                        "query_relevance": 1.0 if supports_query and match_types.get(record.candidate_id or "") == "DIRECT" else 0.82 if supports_query else 0.0,
                        "entity_verified": bool(record.metadata.get("identity_verified")),
                        "support_type": match_types.get(record.candidate_id or "", "UNRELATED") if supports_query else "IDENTITY",
                        "source_level": source_level,
                        "freshness": freshness_label(
                            year_value,
                            record.freshness.value if hasattr(record.freshness, "value") else str(record.freshness or ""),
                        ),
                    },
                )
            )
        allowed_evidence_ids = {record.evidence_id for record in evidence}
        verified_fields_by_candidate: dict[str, set[str]] = {}
        for record in evidence:
            if not record.candidate_id:
                continue
            verified_fields_by_candidate.setdefault(record.candidate_id, set()).update(
                item.strip()
                for item in str(record.metadata.get("supports_fields", "")).split(",")
                if item.strip()
            )
        kept = [
            candidate.model_copy(
                deep=True,
                update={
                    "methods": candidate.methods if "methods" in verified_fields_by_candidate.get(candidate.candidate_id, set()) else [],
                    "publications": candidate.publications if "publications" in verified_fields_by_candidate.get(candidate.candidate_id, set()) else [],
                    "projects": candidate.projects if "projects" in verified_fields_by_candidate.get(candidate.candidate_id, set()) else [],
                    "evidence_refs": [
                        reference
                        for reference in candidate.evidence_refs
                        if reference in allowed_evidence_ids
                    ],
                },
            )
            for candidate in kept
        ]
        evidence_candidates = {
            record.candidate_id
            for record in evidence
            if record.candidate_id and record.support_type in {"DIRECT", "ADJACENT"}
        }
        kept = [candidate for candidate in kept if candidate.candidate_id in evidence_candidates]
        warnings = list(result.warnings)
        if not kept:
            warnings.append(f"没有导师达到绝对相关性阈值：{contract.canonical_query}")
        return result.model_copy(
            deep=True,
            update={"candidates": kept, "evidence": evidence, "warnings": _unique(warnings)},
        )

    def _fuse_results(
        self,
        dense_result: MentorResearchResult | None,
        lexical_result: MentorResearchResult | None,
        errors: list[str],
    ) -> MentorResearchResult:
        """合并 dense 与 lexical 两路召回，按相关性阈值过滤 + 归一化排序。

        规则：
        - lexical 精确命中（``retrieve_hits >= lexical_min_hits``）无条件保留、优先排前。
        - 其余候选仅当 dense 余弦分数 >= dense_threshold 才保留。
        - 按 candidate_id 去重，evidence / source_chain / warnings 合并。
        每个候选的 source_metadata 写入 ``dense_score`` / ``lexical_hits`` /
        ``fused`` 供观测与下游 debug。
        """
        merged: dict[str, CandidateMentor] = {}
        dense_score: dict[str, float] = {}
        lexical_hits: dict[str, int] = {}
        evidence: list[EvidenceRecord] = []
        source_chain: list[str] = []
        warnings: list[str] = []
        for result, label in (
            (dense_result, "dense"),
            (lexical_result, "lexical"),
        ):
            if result is None:
                continue
            source_chain = _unique([*source_chain, *result.source_chain])
            warnings.extend(result.warnings)
            for candidate in result.candidates:
                cid = candidate.candidate_id
                meta = candidate.source_metadata
                if label == "dense":
                    # dense 的 retrieve_score 已落在 0~100（余弦*100），存回 0~1。
                    dense_score[cid] = float(meta.get("retrieve_score", 0.0)) / 100.0
                else:
                    lexical_hits[cid] = int(meta.get("retrieve_hits", 0))
                if cid not in merged:
                    merged[cid] = candidate
                else:
                    merged[cid] = _merge_candidate(merged[cid], candidate)
        if dense_result is not None:
            evidence.extend(dense_result.evidence)
        if lexical_result is not None:
            evidence.extend(lexical_result.evidence)

        # 相关性过滤：lexical 精确命中保留；否则要求 dense 分数过阈值。
        kept: list[CandidateMentor] = []
        for cid, candidate in merged.items():
            hits = lexical_hits.get(cid, 0)
            score = dense_score.get(cid, 0.0)
            if hits < self._lexical_min_hits and score < self._dense_threshold:
                continue
            meta = dict(candidate.source_metadata)
            meta["dense_score"] = round(score, 4)
            meta["lexical_hits"] = hits
            meta["fused"] = 1
            kept.append(
                candidate.model_copy(deep=True, update={"source_metadata": meta})
            )

        kept.sort(
            key=lambda c: (
                -lexical_hits.get(c.candidate_id, 0),
                -dense_score.get(c.candidate_id, 0.0),
                c.candidate_id,
            )
        )
        kept = kept[: self._max_fused_candidates]
        kept_ids = {candidate.candidate_id for candidate in kept}
        return MentorResearchResult(
            candidates=kept,
            evidence=[e for e in evidence if e.candidate_id in kept_ids],
            warnings=_unique(warnings),
            used_fallback=dense_result is None or not dense_result.candidates,
            source_chain=_unique(source_chain),
            unresolved_candidate_ids=[],
        )

    def _attach_papers(
        self,
        result: MentorResearchResult,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        enriched = result.model_copy(deep=True)
        contract = intent.query_contract
        if not contract.canonical_query:
            contract = build_query_contract(
                intent.raw_message,
                intent.research_topics,
                intent.methods,
                intent.application_domains,
            )
        concepts = _unique(
            [
                *intent.research_topics,
                *intent.methods,
                *intent.application_domains,
                contract.canonical_query,
                *contract.expanded_terms,
                *expanded_terms_for(contract.concepts),
            ]
        )
        evidence = list(enriched.evidence)
        warnings = list(enriched.warnings)
        for candidate in enriched.candidates:
            records, paper_warnings = self._candidate_papers(
                candidate, concepts, intent.methods
            )
            warnings.extend(paper_warnings)
            evidence.extend(records)
        enriched.evidence = evidence
        enriched.warnings = _unique(warnings)
        enriched.source_chain = _unique(
            [*enriched.source_chain, "paper_search_arxiv_openalex"]
        )
        return enriched

    def _candidate_papers(
        self,
        candidate: CandidateMentor,
        concepts: list[str],
        methods: list[str],
    ) -> tuple[list[EvidenceRecord], list[str]]:
        from backend.mentor_workflow.ustc_sources import _paper_evidence

        aliases = _unique(
            [
                candidate.mentor_name,
                str(candidate.source_metadata.get("english_name", "")),
            ]
        )
        english_alias = next(
            (alias for alias in aliases if re.search(r"[A-Za-z]", alias)), None
        )
        topic_query = " ".join(concepts[:2]) if concepts else ""
        search_specs: list[tuple[str, str, str]] = []
        records: list[EvidenceRecord] = []
        warnings: list[str] = []
        seen: set[str] = set()
        if english_alias:
            search_specs.append(
                (
                    "arxiv",
                    "advanced",
                    f'au:"{english_alias}"'
                    + (f' AND all:"{topic_query}"' if topic_query else ""),
                )
            )
        primary_alias = english_alias
        if english_alias:
            search_specs.append(
                (
                    "openalex",
                    "auto",
                    " ".join(value for value in (primary_alias, topic_query) if value),
                )
            )
        else:
            warnings.append(
                f"OpenAlex skipped for {candidate.mentor_name}: no English name for author disambiguation"
            )
        for source, mode, query in search_specs:
            try:
                page = self._paper_gateway.search(
                    query,
                    source=source,
                    mode=mode,
                    max_results=self.max_results_per_source,
                )
            except Exception as exc:  # noqa: BLE001 - isolate per-source failure
                warnings.append(
                    f"{source} paper search failed for {candidate.mentor_name}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            warnings.extend(page.warnings)
            for hit in page.hits:
                if not _author_matches(hit.authors, aliases):
                    continue
                text = " ".join(
                    value
                    for value in (hit.title, hit.abstract or "", hit.venue or "")
                    if value
                )
                matched_concepts = [
                    concept for concept in concepts if _contains(text, concept)
                ]
                if _freshness_from_year(hit.year) == EvidenceFreshness.stale:
                    continue
                paper_key = (
                    hit.doi or hit.arxiv_id or hit.openalex_id or _normalize(hit.title)
                )
                if not paper_key or paper_key in seen:
                    continue
                seen.add(paper_key)
                record = _paper_evidence(candidate, hit, matched_concepts, methods)
                records.append(record)
                candidate.evidence_refs = _unique(
                    [*candidate.evidence_refs, record.evidence_id]
                )
                candidate.publications = _unique([*candidate.publications, hit.title])
                if len(records) >= self.max_papers_per_candidate:
                    return records, warnings
        return records, warnings
