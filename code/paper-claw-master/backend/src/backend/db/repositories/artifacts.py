from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.db.models import AcquisitionJob, Artifact, PaperArtifact


class ArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_artifact(self, kind: str, **values: object) -> Artifact:
        artifact = Artifact(kind=kind, **values)
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def link_paper_artifact(self, paper_id: int, artifact_id: int, role: str, **values: object) -> PaperArtifact:
        paper_artifact = PaperArtifact(
            paper_id=paper_id,
            artifact_id=artifact_id,
            role=role,
            created_at=datetime.now().astimezone(),
            **values,
        )
        self.session.add(paper_artifact)
        self.session.flush()
        return paper_artifact

    def create_acquisition_job(self, paper_id: int, requested_source: str, **values: object) -> AcquisitionJob:
        job = AcquisitionJob(paper_id=paper_id, requested_source=requested_source, **values)
        self.session.add(job)
        self.session.flush()
        return job
