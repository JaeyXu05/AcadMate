from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.mentor_workflow.schemas import (
    CandidateMentor,
    EvidenceFreshness,
    EvidenceRecord,
    MentorResearchResult,
)


@pytest.fixture()
def research_result_factory() -> Callable[..., MentorResearchResult]:
    def factory(
        *,
        candidate_id: str = "mentor_1",
        mentor_name: str = "Professor A",
        freshness: EvidenceFreshness = EvidenceFreshness.current,
        topics: list[str] | None = None,
        missing_fields: list[str] | None = None,
        evidence_id: str | None = None,
    ) -> MentorResearchResult:
        evidence = EvidenceRecord(
            evidence_id=evidence_id or f"ev_{candidate_id}_{freshness.value}",
            candidate_id=candidate_id,
            source_type="ustc_official_faculty_profile",
            source_uri=f"fixture://{candidate_id}/{freshness.value}",
            title=f"Evidence for {mentor_name}",
            extracted_fact=f"{mentor_name} published verified work on multi-agent reinforcement learning.",
            locator="fixture:1",
            freshness=freshness,
            confidence=0.95,
            query="multi-agent reinforcement learning",
            query_relevance=0.92,
            entity_verified=True,
            support_type="DIRECT",
            source_level="L1",
            metadata={
                "identity_verified": True,
                "mentor_role_verified": True,
                "supports_fields": (
                    "affiliation,department,research_topics,methods,"
                    "publications,homepage"
                ),
            },
        )
        candidate = CandidateMentor(
            candidate_id=candidate_id,
            mentor_name=mentor_name,
            affiliation="School of Computer Science",
            department="Artificial Intelligence",
            research_topics=topics or ["multi-agent reinforcement learning"],
            methods=["reinforcement learning"],
            publications=["Verified MARL Paper"],
            projects=[],
            homepage=f"https://example.test/{candidate_id}",
            recruitment_status=None,
            evidence_refs=[evidence.evidence_id],
            missing_fields=missing_fields or ["projects", "recruitment_status"],
            source_metadata={"topics_source": 1},
        )
        return MentorResearchResult(candidates=[candidate], evidence=[evidence])

    return factory
