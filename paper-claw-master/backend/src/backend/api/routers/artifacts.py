from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.api.serializers import artifact_read
from backend.db.models import Artifact, Paper
from backend.db.repositories import AgentRunRepository
from backend.db.types import EventLevel, PaperArtifactRole
from backend.schemas import ArtifactRead
from backend.services.storage import ArtifactStorageService

router = APIRouter(tags=["artifacts"])


@router.post("/papers/{paper_id}/artifacts/upload", response_model=ArtifactRead)
def upload_paper_artifact(
    paper_id: int,
    file: UploadFile = File(...),
    role: str = Form(...),
    run_id: int | None = Form(default=None),
    session: Session = Depends(get_db_session),
) -> ArtifactRead:
    if session.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    if role not in {PaperArtifactRole.pdf.value, PaperArtifactRole.source.value}:
        raise HTTPException(status_code=400, detail="Artifact upload role must be 'pdf' or 'source'.")
    suffix = Path(file.filename or "upload.bin").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(file.file.read())
    try:
        service = ArtifactStorageService(session)
        if role == PaperArtifactRole.pdf.value:
            artifact = service.register_local_pdf(paper_id, temp_path, original_filename=file.filename)
        else:
            artifact = service.register_source_artifact(paper_id, temp_path, original_filename=file.filename)
    finally:
        temp_path.unlink(missing_ok=True)
    if run_id is not None:
        AgentRunRepository(session).append_event(
            run_id,
            "artifact_uploaded",
            level=EventLevel.info.value,
            payload_json={"paper_id": paper_id, "artifact_id": artifact.id, "role": role},
        )
    return artifact_read(artifact)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: int, session: Session = Depends(get_db_session)) -> ArtifactRead:
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact_read(artifact)
