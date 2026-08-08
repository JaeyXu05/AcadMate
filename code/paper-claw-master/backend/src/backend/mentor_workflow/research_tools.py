from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Paper
from backend.mentor_workflow.schemas import (
    CandidateMentor,
    DomainJudgement,
    EvidenceFreshness,
    EvidenceRecord,
    IntentPacket,
    MentorResearchResult,
)
from backend.mentor_workflow.ustc_sources import (
    InternalMentorRag,
    MissingDirectionPaperEnricher,
    NullInternalMentorRag,
    UstcOfficialMentorSource,
)


class MentorResearchTool(Protocol):
    def search_local(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult: ...

    def search_fallback(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult: ...


class UstcMentorResearchTool:
    """USTC-first source chain with an internal RAG extension point.

    Source priority is:
    internal curated RAG -> official USTC faculty/profile pages ->
    arXiv/OpenAlex paper evidence only for mentors whose official pages do not
    expose a research direction.
    """

    def __init__(
        self,
        *,
        internal_rag: InternalMentorRag | None = None,
        official_source: UstcOfficialMentorSource,
        paper_enricher: MissingDirectionPaperEnricher,
    ) -> None:
        self.internal_rag = internal_rag or NullInternalMentorRag()
        self.official_source = official_source
        self.paper_enricher = paper_enricher

    def search_local(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        return self.internal_rag.retrieve(intent, domain_judgements)

    def search_fallback(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        official = self.official_source.search(intent, domain_judgements)
        if not official.unresolved_candidate_ids:
            return official
        return self.paper_enricher.enrich(
            official,
            intent,
            domain_judgements,
        )


class PaperCatalogMentorResearchTool:
    """Adapts the existing paper catalog into a conservative local mentor source.

    Paper authors become candidates only when a catalog record literally matches a
    requested concept. Missing affiliation, homepage, project, and recruitment data
    remain empty; the adapter never infers them from model knowledge.
    """

    def __init__(self, session: Session, *, max_papers: int = 100) -> None:
        self.session = session
        self.max_papers = max_papers

    def search_local(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        papers = list(
            self.session.scalars(
                select(Paper).order_by(Paper.updated_at.desc()).limit(self.max_papers)
            )
        )
        concepts = _search_concepts(intent, domain_judgements)
        mentor_filter = {name.casefold() for name in intent.constraints.mentor_names}
        candidate_filter = set(intent.constraints.candidate_ids)
        candidates: dict[str, CandidateMentor] = {}
        evidence: list[EvidenceRecord] = []

        for paper in papers:
            text = " ".join(
                [paper.title or "", paper.abstract or "", paper.venue or ""]
            )
            matched_concepts = [
                concept for concept in concepts if _contains(text, concept)
            ]
            if (
                concepts
                and not matched_concepts
                and not mentor_filter
                and not candidate_filter
            ):
                continue
            for raw_author in paper.authors_json or []:
                author = _author_name(raw_author)
                if not author:
                    continue
                candidate_id = _candidate_id(author)
                if mentor_filter and author.casefold() not in mentor_filter:
                    continue
                if candidate_filter and candidate_id not in candidate_filter:
                    continue
                record = EvidenceRecord(
                    candidate_id=candidate_id,
                    source_type="local_paper_catalog",
                    source_uri=f"paper:{paper.id}",
                    title=paper.title,
                    extracted_fact=_paper_fact(
                        author,
                        paper.title,
                        matched_concepts,
                        [
                            method
                            for method in intent.methods
                            if _contains(text, method)
                        ],
                    ),
                    locator="papers.authors_json",
                    freshness=_freshness_from_year(paper.year),
                    confidence=0.95,
                    metadata={
                        "paper_id": paper.id,
                        "year": paper.year or 0,
                        "supports_fields": "research_topics,methods,publications",
                        "identity_verified": False,
                    },
                )
                evidence.append(record)
                current = candidates.get(candidate_id)
                if current is None:
                    current = CandidateMentor(
                        candidate_id=candidate_id,
                        mentor_name=author,
                        research_topics=list(matched_concepts),
                        methods=[
                            method
                            for method in intent.methods
                            if _contains(text, method)
                        ],
                        publications=[paper.title],
                        evidence_refs=[record.evidence_id],
                        updated_at=paper.updated_at,
                    )
                    candidates[candidate_id] = current
                else:
                    current.research_topics = _unique(
                        [*current.research_topics, *matched_concepts]
                    )
                    current.methods = _unique(
                        [
                            *current.methods,
                            *[
                                method
                                for method in intent.methods
                                if _contains(text, method)
                            ],
                        ]
                    )
                    current.publications = _unique([*current.publications, paper.title])
                    current.evidence_refs = _unique(
                        [*current.evidence_refs, record.evidence_id]
                    )

        for candidate in candidates.values():
            candidate.missing_fields = _candidate_missing_fields(candidate)
        return MentorResearchResult(
            candidates=list(candidates.values()), evidence=evidence
        )

    def search_fallback(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        return MentorResearchResult(
            warnings=[
                "No external mentor web adapter is configured; the workflow degraded to the local paper catalog."
            ],
            used_fallback=True,
        )


def _search_concepts(
    intent: IntentPacket, domain_judgements: list[DomainJudgement]
) -> list[str]:
    return _unique(
        [
            *intent.research_topics,
            *intent.methods,
            *intent.application_domains,
            *[
                concept
                for judgement in domain_judgements
                for concept in judgement.search_concepts
            ],
        ]
    )


def _candidate_id(name: str) -> str:
    digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:16]
    return f"mentor_{digest}"


def _author_name(author: object) -> str:
    if isinstance(author, str):
        return " ".join(author.split()).strip()
    if isinstance(author, dict):
        for key in ("name", "display_name", "full_name"):
            value = author.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split()).strip()
    return ""


def _contains(text: str, term: str) -> bool:
    normalized_text = _normalize(text)
    normalized_term = _normalize(term)
    return bool(normalized_term and normalized_term in normalized_text)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return result


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


def _paper_fact(author: str, title: str, topics: list[str], methods: list[str]) -> str:
    details = _unique([*topics, *methods])
    suffix = (
        f" The catalog title or abstract explicitly contains: {', '.join(details)}."
        if details
        else ""
    )
    return f"{author} is listed as an author of {title}.{suffix}"


def _freshness_from_year(year: int | None) -> EvidenceFreshness:
    if year is None:
        return EvidenceFreshness.unknown
    current_year = datetime.now(UTC).year
    if year >= current_year - 2:
        return EvidenceFreshness.current
    if year >= current_year - 5:
        return EvidenceFreshness.recent
    return EvidenceFreshness.stale
