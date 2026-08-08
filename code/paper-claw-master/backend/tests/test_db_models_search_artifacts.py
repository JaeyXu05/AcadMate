from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from backend.db.models import Artifact, Paper, PaperArtifact, SearchCandidate, SearchSession
from backend.db.types import ArtifactKind, PaperArtifactRole, PaperSource, SearchStatus


def test_search_session_candidates_and_selection(session):
    search = SearchSession(query_text="rag", status=SearchStatus.waiting_for_confirmation.value)
    session.add(search)
    session.flush()
    candidate = SearchCandidate(
        search_session_id=search.id,
        rank=1,
        source=PaperSource.openalex.value,
        title="Candidate",
        created_at=datetime.now().astimezone(),
    )
    session.add(candidate)
    session.flush()
    search.selected_candidate_id = candidate.id
    search.status = SearchStatus.confirmed.value
    session.commit()

    assert search.selected_candidate.title == "Candidate"
    assert candidate.paper is None


def test_paper_artifact_unique(session):
    paper = Paper(title="Fixture Paper")
    artifact = Artifact(kind=ArtifactKind.pdf.value, storage_uri="local://paper.pdf")
    session.add_all([paper, artifact])
    session.flush()
    now = datetime.now().astimezone()
    session.add_all([
        PaperArtifact(paper_id=paper.id, artifact_id=artifact.id, role=PaperArtifactRole.pdf.value, created_at=now),
        PaperArtifact(paper_id=paper.id, artifact_id=artifact.id, role=PaperArtifactRole.pdf.value, created_at=now),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
