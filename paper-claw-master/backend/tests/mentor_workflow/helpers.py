from __future__ import annotations

from backend.mentor_workflow.schemas import MentorResearchResult


class SequenceResearchTool:
    def __init__(
        self,
        local_results: list[MentorResearchResult] | None = None,
        fallback_result: MentorResearchResult | None = None,
        local_error: Exception | None = None,
    ) -> None:
        self.local_results = local_results or []
        self.fallback_result = fallback_result or MentorResearchResult()
        self.local_error = local_error
        self.local_calls = 0
        self.fallback_calls = 0

    def search_local(self, _intent, _judgements) -> MentorResearchResult:
        self.local_calls += 1
        if self.local_error is not None:
            raise self.local_error
        if not self.local_results:
            return MentorResearchResult()
        index = min(self.local_calls - 1, len(self.local_results) - 1)
        return self.local_results[index].model_copy(deep=True)

    def search_fallback(self, _intent, _judgements) -> MentorResearchResult:
        self.fallback_calls += 1
        return self.fallback_result.model_copy(deep=True)
