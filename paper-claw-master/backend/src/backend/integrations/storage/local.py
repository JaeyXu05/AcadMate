from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredFile:
    path: Path
    storage_uri: str
    size_bytes: int
    checksum_sha256: str


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def paper_file_path(self, paper_id: int, relative_path: str) -> Path:
        path = (self.root / "papers" / str(paper_id) / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage path must stay under the configured root.")
        return path

    def store_file(self, source_path: Path, destination: Path) -> StoredFile:
        source_path = source_path.expanduser().resolve()
        destination = destination.expanduser().resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("Storage destination must stay under the configured root.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path != destination:
            shutil.copyfile(source_path, destination)
        return self.describe_file(destination)

    def describe_file(self, path: Path) -> StoredFile:
        path = path.expanduser().resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage path must stay under the configured root.")
        return StoredFile(
            path=path,
            storage_uri=self.to_uri(path),
            size_bytes=path.stat().st_size,
            checksum_sha256=_sha256(path),
        )

    def to_uri(self, path: Path) -> str:
        path = path.expanduser().resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage path must stay under the configured root.")
        return f"local://{path.relative_to(self.root).as_posix()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
