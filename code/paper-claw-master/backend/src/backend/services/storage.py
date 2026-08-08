from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Artifact, PaperArtifact
from backend.db.repositories import ArtifactRepository
from backend.db.types import ArtifactKind, ArtifactStatus, PaperArtifactRole, StorageBackend
from backend.integrations.storage import LocalStorage
from backend.settings import get_settings


class ArtifactStorageService:
    def __init__(self, session: Session, storage: LocalStorage | None = None) -> None:
        self.session = session
        root = get_settings().storage_root
        if root is None:
            raise ValueError("Storage root is not configured.")
        self.storage = storage or LocalStorage(root)

    def register_local_pdf(self, paper_id: int, source_path: Path, *, original_filename: str | None = None) -> Artifact:
        destination = self.storage.paper_file_path(paper_id, "original.pdf")
        stored = self.storage.store_file(source_path, destination)
        artifact = self._upsert_artifact(
            kind=ArtifactKind.pdf.value,
            storage_uri=stored.storage_uri,
            original_filename=original_filename or source_path.name,
            mime_type="application/pdf",
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
        )
        self.link_paper_artifact(paper_id, artifact.id, PaperArtifactRole.pdf.value, is_primary=True)
        return artifact

    def register_source_artifact(self, paper_id: int, source_path: Path, *, original_filename: str | None = None) -> Artifact:
        destination = self.storage.paper_file_path(paper_id, f"source/{source_path.name}")
        stored = self.storage.store_file(source_path, destination)
        artifact = self._upsert_artifact(
            kind=ArtifactKind.source_archive.value,
            storage_uri=stored.storage_uri,
            original_filename=original_filename or source_path.name,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
        )
        self.link_paper_artifact(paper_id, artifact.id, PaperArtifactRole.source.value, is_primary=True)
        return artifact

    def link_paper_artifact(self, paper_id: int, artifact_id: int, role: str, *, is_primary: bool = False) -> PaperArtifact:
        existing = self.session.scalar(
            select(PaperArtifact).where(
                PaperArtifact.paper_id == paper_id,
                PaperArtifact.artifact_id == artifact_id,
            )
        )
        if existing is not None:
            existing.role = role
            existing.is_primary = existing.is_primary or is_primary
            self.session.flush()
            return existing
        return ArtifactRepository(self.session).link_paper_artifact(paper_id, artifact_id, role, is_primary=is_primary)

    def _upsert_artifact(self, *, kind: str, storage_uri: str, **values: object) -> Artifact:
        artifact = self.session.scalar(select(Artifact).where(Artifact.storage_uri == storage_uri))
        if artifact is None:
            artifact = ArtifactRepository(self.session).create_artifact(
                kind,
                status=ArtifactStatus.available.value,
                storage_backend=StorageBackend.local.value,
                storage_uri=storage_uri,
                **values,
            )
        else:
            artifact.kind = kind
            artifact.status = ArtifactStatus.available.value
            artifact.storage_backend = StorageBackend.local.value
            for key, value in values.items():
                setattr(artifact, key, value)
            self.session.flush()
        return artifact
