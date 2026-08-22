from __future__ import annotations

from pathlib import Path
from typing import Protocol

from backend.schemas import ParsedDocumentPayload


class ParserAdapter(Protocol):
    def parse(self, artifact_path: Path, warnings: list[str] | None = None) -> ParsedDocumentPayload:
        ...
