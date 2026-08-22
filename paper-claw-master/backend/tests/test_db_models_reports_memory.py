from __future__ import annotations

from backend.db.models import Memory, Paper, Report, ReportEvidence
from backend.db.types import EvidenceType, MemoryType, ReportType


def test_report_evidence_and_memory(session):
    paper = Paper(title="Fixture Paper")
    session.add(paper)
    session.flush()
    report = Report(
        title="Fixture Report",
        paper_id=paper.id,
        report_type=ReportType.paper_summary.value,
        markdown_content="Report",
    )
    session.add(report)
    session.flush()
    evidence = ReportEvidence(
        report_id=report.id,
        evidence_type=EvidenceType.paper.value,
        paper_id=paper.id,
        quote_text="evidence",
    )
    memory = Memory(
        path=f"/memories/papers/{paper.id}/fixture-note.md",
        title="fixture-note",
        memory_type=MemoryType.paper_note.value,
        content_text="Remember this fixture paper.",
        source_paper_id=paper.id,
        paper_id=paper.id,
    )
    session.add_all([evidence, memory])
    session.commit()

    assert report.evidence[0].quote_text == "evidence"
    assert memory.source_paper.title == "Fixture Paper"
