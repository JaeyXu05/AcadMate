from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Artifact, PaperArtifact, ParseJob, ParserEvent
from backend.db.repositories import ParsingRepository
from backend.db.types import ArtifactStatus, ParseJobStatus, ParseQualityStatus, ParseStrategy, PaperArtifactRole
from backend.integrations.parsers import ParserAdapter
from backend.schemas import ParsedDocumentPayload


@dataclass(frozen=True)
class ParseStrategyAttempt:
    strategy: str
    artifact_id: int | None
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class ParseChainPlan:
    selected_strategy: str
    attempts: list[ParseStrategyAttempt]
    reason: str | None = None


class ParseChainService:
    def __init__(self, session: Session, parsers: dict[str, ParserAdapter] | None = None, storage_root: Path | None = None) -> None:
        self.session = session
        self.parsers = parsers or {}
        self.storage_root = storage_root

    def plan_parse_chain(self, paper_id: int) -> ParseChainPlan:
        source_artifact = self._find_artifact(paper_id, PaperArtifactRole.source.value)
        pdf_artifact = self._find_artifact(paper_id, PaperArtifactRole.pdf.value)
        attempts = [
            ParseStrategyAttempt(ParseStrategy.tex.value, source_artifact.id if source_artifact else None, source_artifact is not None, None if source_artifact else "No TeX source artifact."),
            ParseStrategyAttempt(ParseStrategy.local_ocr.value, pdf_artifact.id if pdf_artifact else None, pdf_artifact is not None and ParseStrategy.local_ocr.value in self.parsers, _pdf_reason(pdf_artifact, ParseStrategy.local_ocr.value, self.parsers)),
            ParseStrategyAttempt(ParseStrategy.llama_parse.value, pdf_artifact.id if pdf_artifact else None, pdf_artifact is not None and ParseStrategy.llama_parse.value in self.parsers, _pdf_reason(pdf_artifact, ParseStrategy.llama_parse.value, self.parsers)),
        ]
        for attempt in attempts:
            if attempt.available:
                return ParseChainPlan(selected_strategy=attempt.strategy, attempts=attempts)
        return ParseChainPlan(selected_strategy=ParseStrategy.unavailable.value, attempts=attempts, reason="No parseable artifact and parser combination is available.")

    def run_parse_chain(self, paper_id: int, *, run_id: int | None = None) -> ParseJob:
        plan = self.plan_parse_chain(paper_id)
        selected = next((attempt for attempt in plan.attempts if attempt.strategy == plan.selected_strategy), None)
        repo = ParsingRepository(self.session)
        job = repo.create_parse_job(
            paper_id,
            run_id=run_id,
            input_artifact_id=selected.artifact_id if selected else None,
            strategy=plan.selected_strategy,
            status=ParseJobStatus.running.value,
            settings_json={"attempts": [attempt.__dict__ for attempt in plan.attempts]},
        )
        sequence = 1
        self._append_event(job, sequence, "parse_started", {"strategy": plan.selected_strategy})
        sequence += 1
        if plan.selected_strategy == ParseStrategy.unavailable.value:
            job.status = ParseJobStatus.failed.value
            job.error_message = plan.reason
            self._append_event(job, sequence, "parse_unavailable", {"reason": plan.reason}, level="warning")
            self.session.flush()
            return job

        warnings: list[str] = []
        for attempt in plan.attempts:
            if not attempt.available:
                if attempt.reason:
                    warnings.append(f"{attempt.strategy}: {attempt.reason}")
                continue
            artifact = self.session.get(Artifact, attempt.artifact_id) if attempt.artifact_id is not None else None
            if artifact is None:
                warnings.append(f"{attempt.strategy}: artifact is missing")
                continue
            parser = self.parsers.get(attempt.strategy)
            if parser is None:
                warnings.append(f"{attempt.strategy}: parser is not configured")
                continue
            try:
                self._append_event(job, sequence, "strategy_started", {"strategy": attempt.strategy, "artifact_id": artifact.id})
                sequence += 1
                payload = parser.parse(self._artifact_path(artifact), warnings=warnings)
                self._persist_payload(job, artifact, payload)
                job.strategy = payload.strategy
                job.status = ParseJobStatus.succeeded.value
                self._append_event(job, sequence, "strategy_succeeded", {"strategy": payload.strategy, "parser_kind": payload.parser_kind})
                self.session.flush()
                return job
            except Exception as exc:
                warning = f"{attempt.strategy}: {exc}"
                warnings.append(warning)
                self._append_event(job, sequence, "strategy_failed", {"strategy": attempt.strategy, "error": str(exc)}, level="warning")
                sequence += 1
        job.status = ParseJobStatus.failed.value
        job.error_message = warnings[-1] if warnings else "No parser produced a document."
        self.session.flush()
        return job

    def _persist_payload(self, job: ParseJob, artifact: Artifact, payload: ParsedDocumentPayload) -> None:
        ParsingRepository(self.session).create_parsed_document(
            job.paper_id,
            job.id,
            payload.parser_kind,
            source_artifact_id=artifact.id,
            plain_text=payload.plain_text,
            markdown_content=payload.markdown_content,
            json_content={**payload.json_content, "warnings": payload.warnings},
            quality_status=ParseQualityStatus.usable.value,
            quality_summary=payload.quality_summary,
        )

    def _append_event(self, job: ParseJob, sequence: int, event_type: str, payload: dict, *, level: str = "info") -> ParserEvent:
        event = ParsingRepository(self.session).append_parser_event(job.id, job.paper_id, sequence, event_type, level=level)
        event.payload_json = payload
        self.session.flush()
        return event

    def _find_artifact(self, paper_id: int, role: str) -> Artifact | None:
        return self.session.scalar(
            select(Artifact)
            .join(PaperArtifact)
            .where(
                PaperArtifact.paper_id == paper_id,
                PaperArtifact.role == role,
                Artifact.status == ArtifactStatus.available.value,
            )
            .order_by(PaperArtifact.is_primary.desc(), Artifact.created_at.desc())
        )

    def _artifact_path(self, artifact: Artifact) -> Path:
        if not artifact.storage_uri:
            raise ValueError("Artifact has no storage URI.")
        if artifact.storage_uri.startswith("local://"):
            if self.storage_root is None:
                raise ValueError("Storage root is required for local artifacts.")
            path = (self.storage_root / artifact.storage_uri.removeprefix("local://")).resolve()
            if not path.is_relative_to(self.storage_root.resolve()):
                raise ValueError("Artifact path must stay under storage root.")
            return path
        return Path(artifact.storage_uri).expanduser().resolve()


def _pdf_reason(artifact: Artifact | None, strategy: str, parsers: dict[str, ParserAdapter]) -> str | None:
    if artifact is None:
        return "No PDF artifact."
    if strategy not in parsers:
        return f"{strategy} parser is not configured."
    return None
