"""Internal mentor RAG adapter using dense multilingual retrieval."""

from __future__ import annotations

from backend.mentor_workflow.schemas import (
    DomainJudgement,
    IntentPacket,
    MentorResearchResult,
)
from backend.mentor_workflow.query_semantics import build_query_contract
from backend.mentor_workflow.text_matching import unique as _unique
from backend.services.mentor_semantic_retrieval import MentorSemanticIndex


class DenseInternalMentorRag:
    def __init__(self, index: MentorSemanticIndex, *, top_k: int = 20) -> None:
        self.index = index
        self.top_k = top_k

    def retrieve(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        candidate_ids = set(intent.constraints.candidate_ids)
        mentor_names = {name.casefold().strip() for name in intent.constraints.mentor_names}
        if candidate_ids or mentor_names:
            candidates = [
                item
                for item in self.index.candidates
                if item.candidate_id in candidate_ids
                or item.mentor_name.casefold().strip() in mentor_names
            ][: self.top_k]
        else:
            contract = intent.query_contract
            if not contract.canonical_query:
                contract = build_query_contract(
                    intent.raw_message,
                    intent.research_topics,
                    intent.methods,
                    intent.application_domains,
                )
            # Domain judgements are explanatory/audit metadata.  They are not
            # allowed to inject model-generated parent concepts into the dense
            # query; the manager's typed contract is the sole recall source.
            concepts = _unique(
                [
                    *intent.research_topics,
                    *intent.methods,
                    *intent.application_domains,
                    contract.canonical_query,
                    *contract.expanded_terms,
                ]
            )
            hits = self.index.search(concepts, top_k=self.top_k * 3)
            hits = [
                hit
                for hit in hits
                if hit.candidate.research_topics and hit.candidate.evidence_refs
            ][: self.top_k]
            candidates = [
                hit.candidate.model_copy(
                    deep=True,
                    update={
                        "source_metadata": {
                            **hit.candidate.source_metadata,
                            "retrieve_score": round(hit.score * 100, 4),
                            "retrieve_mode": "dense_multilingual",
                            "embedding_model": self.index.provider.model,
                        }
                    },
                )
                for hit in hits
            ]
        kept_ids = {item.candidate_id for item in candidates}
        return MentorResearchResult(
            candidates=candidates,
            evidence=self.index.evidence_for(kept_ids),
            warnings=[] if candidates else ["内部语义检索未召回导师"],
            used_fallback=False,
            source_chain=["internal_ustc_dense_rag"],
            unresolved_candidate_ids=[],
        )
