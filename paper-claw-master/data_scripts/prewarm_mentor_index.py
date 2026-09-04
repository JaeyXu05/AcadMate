"""Build both mentor embedding caches before serving the first request."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from backend.services.mentor_semantic_retrieval import MentorSemanticIndex  # noqa: E402


def main() -> None:
    index = MentorSemanticIndex(ROOT / "data" / "ustc_mentor_rag.json")
    index.warm()
    print(f"mentor semantic index warmed: {len(index.candidates)} candidates")


if __name__ == "__main__":
    main()
