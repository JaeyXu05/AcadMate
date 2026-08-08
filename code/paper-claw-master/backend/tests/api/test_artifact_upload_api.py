from __future__ import annotations

from backend.db.models import Paper
from backend.db.repositories import AgentRunRepository
from backend.db.types import ArtifactKind, PaperArtifactRole, RunStatus, WorkflowName


def test_upload_pdf_registers_artifact_and_link(client, session):
    paper = Paper(title="Upload paper")
    session.add(paper)
    session.commit()

    response = client.post(
        f"/api/papers/{paper.id}/artifacts/upload",
        data={"role": PaperArtifactRole.pdf.value},
        files={"file": ("paper.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == ArtifactKind.pdf.value
    assert payload["original_filename"] == "paper.pdf"
    assert paper.paper_artifacts[0].role == PaperArtifactRole.pdf.value


def test_upload_source_registers_artifact_and_run_event(client, session):
    paper = Paper(title="Source paper")
    session.add(paper)
    session.flush()
    run = AgentRunRepository(session).create(WorkflowName.acquisition_upload.value, status=RunStatus.running.value)
    session.commit()

    response = client.post(
        f"/api/papers/{paper.id}/artifacts/upload",
        data={"role": PaperArtifactRole.source.value, "run_id": str(run.id)},
        files={"file": ("source.zip", b"source", "application/zip")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == ArtifactKind.source_archive.value
    assert paper.paper_artifacts[0].role == PaperArtifactRole.source.value
    assert run.events[-1].event_type == "artifact_uploaded"
    assert run.events[-1].payload_json["artifact_id"] == payload["id"]


def test_upload_invalid_role_returns_400(client, session):
    paper = Paper(title="Invalid role paper")
    session.add(paper)
    session.commit()

    response = client.post(
        f"/api/papers/{paper.id}/artifacts/upload",
        data={"role": "supplement"},
        files={"file": ("supplement.txt", b"data", "text/plain")},
    )

    assert response.status_code == 400


def test_get_artifact_returns_metadata(client, session):
    paper = Paper(title="Artifact metadata paper")
    session.add(paper)
    session.commit()
    upload_response = client.post(
        f"/api/papers/{paper.id}/artifacts/upload",
        data={"role": PaperArtifactRole.pdf.value},
        files={"file": ("paper.pdf", b"%PDF-1.4", "application/pdf")},
    )

    response = client.get(f"/api/artifacts/{upload_response.json()['id']}")

    assert response.status_code == 200
    assert response.json()["storage_uri"].startswith("local://")
