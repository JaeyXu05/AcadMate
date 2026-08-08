from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.db.models import Report, ReportEvidence


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, title: str, **values: object) -> Report:
        report = Report(title=title, **values)
        self.session.add(report)
        self.session.flush()
        return report

    def add_evidence(self, report_id: int, evidence_type: str, **values: object) -> ReportEvidence:
        evidence = ReportEvidence(
            report_id=report_id,
            evidence_type=evidence_type,
            created_at=datetime.now().astimezone(),
            **values,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence
