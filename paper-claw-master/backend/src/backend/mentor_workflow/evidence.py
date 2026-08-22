from __future__ import annotations

import builtins
import hashlib

from backend.mentor_workflow.schemas import CandidateMentor, EvidenceRecord, MatchResult


class EvidenceLedger:
    def __init__(self, records: list[EvidenceRecord] | None = None) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._dedupe_keys: dict[tuple[str, str | None, str], str] = {}
        for record in records or []:
            self.add(record)

    def add(self, record: EvidenceRecord) -> EvidenceRecord:
        content_hash = record.content_hash or evidence_content_hash(record)
        if record.content_hash is None:
            record = record.model_copy(update={"content_hash": content_hash})
        key = (record.source_uri, record.candidate_id, content_hash)
        existing_id = self._dedupe_keys.get(key)
        if existing_id is not None:
            return self._records[existing_id].model_copy(deep=True)
        self._records[record.evidence_id] = record.model_copy(deep=True)
        self._dedupe_keys[key] = record.evidence_id
        return record.model_copy(deep=True)

    def extend(self, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
        return [self.add(record) for record in records]

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        record = self._records.get(evidence_id)
        return record.model_copy(deep=True) if record is not None else None

    def list(self) -> list[EvidenceRecord]:
        return [record.model_copy(deep=True) for record in self._records.values()]

    def missing_refs(self, evidence_refs: builtins.list[str]) -> builtins.list[str]:
        return sorted(
            {reference for reference in evidence_refs if reference not in self._records}
        )

    def validate_candidate(self, candidate: CandidateMentor) -> builtins.list[str]:
        missing = self.missing_refs(candidate.evidence_refs)
        wrong_candidate = [
            evidence_id
            for evidence_id in candidate.evidence_refs
            if evidence_id in self._records
            and self._records[evidence_id].candidate_id
            not in {None, candidate.candidate_id}
        ]
        return sorted(set([*missing, *wrong_candidate]))

    def validate_match(self, match: MatchResult) -> builtins.list[str]:
        missing = self.missing_refs(match.evidence_refs)
        wrong_candidate = [
            evidence_id
            for evidence_id in match.evidence_refs
            if evidence_id in self._records
            and self._records[evidence_id].candidate_id
            not in {None, match.candidate_id}
        ]
        return sorted(set([*missing, *wrong_candidate]))


def evidence_content_hash(record: EvidenceRecord) -> str:
    value = "\n".join(
        [
            record.source_type,
            record.source_uri,
            record.candidate_id or "",
            record.extracted_fact,
            record.locator,
        ]
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
