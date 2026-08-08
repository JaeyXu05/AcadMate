from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import AcquisitionJob, Artifact, Paper, PaperArtifact
from backend.db.repositories import ArtifactRepository
from backend.db.types import AcquisitionSource, ArtifactKind, ArtifactStatus, PaperArtifactRole, RunStatus
from backend.integrations.paper_sources.arxiv import ArxivClient, normalize_arxiv_id
from backend.services.storage import ArtifactStorageService

Downloader = Callable[[str, Path], Path]
MAX_PDF_DOWNLOAD_BYTES = 100 * 1024 * 1024


class AcquisitionService:
    def __init__(self, session: Session, storage_service: ArtifactStorageService | None = None) -> None:
        self.session = session
        self.storage_service = storage_service or ArtifactStorageService(session)

    def plan_acquisition(self, paper_id: int, *, thread_id: int | None = None, run_id: int | None = None) -> AcquisitionJob:
        paper = self._get_paper(paper_id)
        source_artifact = self._find_available_artifact(paper_id, PaperArtifactRole.source.value)
        pdf_artifact = self._find_available_artifact(paper_id, PaperArtifactRole.pdf.value)
        repo = ArtifactRepository(self.session)
        if source_artifact is not None:
            return repo.create_acquisition_job(
                paper_id,
                AcquisitionSource.manual_upload.value,
                thread_id=thread_id,
                run_id=run_id,
                status=RunStatus.succeeded.value,
                result_json={"artifact_id": source_artifact.id, "role": PaperArtifactRole.source.value, "next_step": "parse_tex_source"},
            )
        if pdf_artifact is not None:
            return repo.create_acquisition_job(
                paper_id,
                AcquisitionSource.manual_upload.value,
                thread_id=thread_id,
                run_id=run_id,
                status=RunStatus.succeeded.value,
                result_json={"artifact_id": pdf_artifact.id, "role": PaperArtifactRole.pdf.value, "next_step": "parse_pdf"},
            )
        if paper.best_pdf_url:
            return repo.create_acquisition_job(
                paper_id,
                _source_from_url(paper.best_pdf_url),
                thread_id=thread_id,
                run_id=run_id,
                status=RunStatus.pending.value,
                input_json={"pdf_url": paper.best_pdf_url},
                result_json={"next_step": "download_pdf"},
            )
        return repo.create_acquisition_job(
            paper_id,
            AcquisitionSource.manual_upload.value,
            thread_id=thread_id,
            run_id=run_id,
            status=RunStatus.waiting_for_user.value,
            input_json={"required": ["pdf", "source_archive"]},
            result_json={"message": "Upload a TeX source archive or PDF for this paper."},
        )

    def acquire_pdf_from_url(self, paper_id: int, pdf_url: str, downloader: Downloader, *, thread_id: int | None = None, run_id: int | None = None) -> AcquisitionJob:
        paper = self._get_paper(paper_id)
        job = ArtifactRepository(self.session).create_acquisition_job(
            paper_id,
            _source_from_url(pdf_url),
            thread_id=thread_id,
            run_id=run_id,
            status=RunStatus.running.value,
            input_json={"pdf_url": pdf_url},
        )
        destination = self.storage_service.storage.paper_file_path(paper.id, "original.pdf")
        try:
            downloaded_path = downloader(pdf_url, destination)
            artifact = self.storage_service.register_local_pdf(paper.id, downloaded_path, original_filename="original.pdf")
            paper.best_pdf_url = paper.best_pdf_url or pdf_url
            job.status = RunStatus.succeeded.value
            job.result_json = {"artifact_id": artifact.id, "storage_uri": artifact.storage_uri, "next_step": "parse_pdf"}
        except Exception as exc:
            job.status = RunStatus.failed.value
            job.error_message = str(exc)
        self.session.flush()
        return job

    def download_pdf_from_url(self, paper_id: int, pdf_url: str, *, thread_id: int | None = None, run_id: int | None = None) -> AcquisitionJob:
        return self.acquire_pdf_from_url(paper_id, pdf_url, safe_pdf_downloader, thread_id=thread_id, run_id=run_id)

    def download_arxiv_artifacts(self, paper_id: int, arxiv_id: str, client: ArxivClient, *, thread_id: int | None = None, run_id: int | None = None) -> AcquisitionJob:
        paper = self._get_paper(paper_id)
        normalized_id = normalize_arxiv_id(arxiv_id)
        job = ArtifactRepository(self.session).create_acquisition_job(
            paper_id,
            AcquisitionSource.arxiv.value,
            thread_id=thread_id,
            run_id=run_id,
            status=RunStatus.running.value,
            input_json={"arxiv_id": normalized_id},
        )
        source_result = None
        pdf_result = None
        source_error = None
        pdf_error = None
        try:
            source_path = client.download_source(normalized_id, self.storage_service.storage.paper_file_path(paper.id, f"source/{normalized_id}.tar.gz"))
            if _is_pdf_file(source_path):
                source_path.unlink(missing_ok=True)
                source_error = "arXiv source archive is unavailable"
            else:
                source_artifact = self.storage_service.register_source_artifact(paper.id, source_path, original_filename=f"{normalized_id}.tar.gz")
                source_result = {"artifact_id": source_artifact.id, "storage_uri": source_artifact.storage_uri}
        except Exception as exc:
            source_error = str(exc)
        pdf_url = f"https://arxiv.org/pdf/{normalized_id}"
        try:
            pdf_path = client.download_pdf(pdf_url, self.storage_service.storage.paper_file_path(paper.id, "original.pdf"))
            pdf_artifact = self.storage_service.register_local_pdf(paper.id, pdf_path, original_filename="original.pdf")
            paper.best_pdf_url = paper.best_pdf_url or pdf_url
            pdf_result = {"artifact_id": pdf_artifact.id, "storage_uri": pdf_artifact.storage_uri}
        except Exception as exc:
            pdf_error = str(exc)
        if source_result is not None:
            job.status = RunStatus.succeeded.value
            job.result_json = {"source": source_result, "pdf": pdf_result, "pdf_error": pdf_error, "next_step": "parse_tex_source"}
        elif pdf_result is not None:
            job.status = RunStatus.partial.value
            job.result_json = {"source_error": source_error, "pdf": pdf_result, "next_step": "parse_pdf"}
        else:
            job.status = RunStatus.waiting_for_user.value
            job.error_message = source_error or pdf_error
            job.result_json = {
                "source_error": source_error,
                "pdf_error": pdf_error,
                "message": "Upload a TeX source archive or PDF for this paper.",
            }
        self.session.flush()
        return job

    def mark_waiting_for_upload(self, paper_id: int, reason: str, *, thread_id: int | None = None, run_id: int | None = None) -> AcquisitionJob:
        self._get_paper(paper_id)
        return ArtifactRepository(self.session).create_acquisition_job(
            paper_id,
            AcquisitionSource.manual_upload.value,
            thread_id=thread_id,
            run_id=run_id,
            status=RunStatus.waiting_for_user.value,
            input_json={"required": ["pdf", "source_archive"], "reason": reason},
            result_json={"message": "Upload a TeX source archive or PDF for this paper."},
        )

    def _get_paper(self, paper_id: int) -> Paper:
        paper = self.session.get(Paper, paper_id)
        if paper is None:
            raise ValueError(f"Paper {paper_id} does not exist.")
        return paper

    def _find_available_artifact(self, paper_id: int, role: str) -> Artifact | None:
        return self.session.scalar(
            select(Artifact)
            .join(PaperArtifact)
            .options(selectinload(Artifact.paper_artifacts))
            .where(
                PaperArtifact.paper_id == paper_id,
                PaperArtifact.role == role,
                Artifact.status == ArtifactStatus.available.value,
            )
            .order_by(PaperArtifact.is_primary.desc(), Artifact.created_at.desc())
        )


def _is_pdf_file(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(5).startswith(b"%PDF-")


def safe_pdf_downloader(url: str, destination: Path) -> Path:
    _validate_public_https_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=False, timeout=30) as client:
        current_url = url
        for _ in range(6):
            _validate_public_https_url(current_url)
            with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect response did not include a Location header")
                    current_url = str(response.url.join(location))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                total = 0
                prefix = b""
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_PDF_DOWNLOAD_BYTES:
                            raise ValueError("PDF download exceeds the maximum allowed size")
                        if len(prefix) < 5:
                            prefix += chunk[: 5 - len(prefix)]
                        handle.write(chunk)
                if "application/pdf" not in content_type and not prefix.startswith(b"%PDF-"):
                    destination.unlink(missing_ok=True)
                    raise ValueError("Downloaded content is not a PDF")
                return destination
        raise ValueError("Too many redirects while downloading PDF")


def _validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Only public https PDF URLs are allowed")
    try:
        ipaddress.ip_address(parsed.hostname)
        hosts = [parsed.hostname]
    except ValueError:
        hosts = [result[4][0] for result in socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)]
    for host in hosts:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ValueError("PDF URL host must resolve to a public address")


def _source_from_url(url: str) -> str:
    if "arxiv.org" in url.lower():
        return AcquisitionSource.arxiv.value
    return AcquisitionSource.url.value
