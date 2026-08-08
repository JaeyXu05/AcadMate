from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path


class LocalSandbox:
    def __init__(self) -> None:
        self._tempdir = TemporaryDirectory(prefix="paper-claw-agent-")
        self.root = Path(self._tempdir.name)

    def close(self) -> None:
        self._tempdir.cleanup()
