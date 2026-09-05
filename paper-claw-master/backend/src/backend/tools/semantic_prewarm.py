"""Prepare the local mentor semantic index before a user needs it.

PDF analysis and dense mentor matching lazily download the FastEmbed model and
embed the 972-mentor corpus on first use.  That turns a slow/failed download
into a first-user timeout.  Running this module during environment setup makes
the expensive part happen once, at install time, while the console can show
progress and actionable network errors.

Run from the repository root (paper-claw-master/) so the relative data dir in
the environment file resolves to the same cache the running service uses:

    python -m backend.tools.semantic_prewarm

or, through uv:

    uv run --project backend python -m backend.tools.semantic_prewarm
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.settings import get_settings
from backend.services.mentor_semantic_retrieval import get_mentor_semantic_index


def warm(rag_path: str | Path | None = None) -> Path:
    settings = get_settings()
    if rag_path is None:
        rag_path = Path(settings.data_dir) / "ustc_mentor_rag.json"
    rag_path = Path(rag_path).expanduser().resolve()
    if not rag_path.exists():
        raise FileNotFoundError(f"Mentor RAG corpus not found: {rag_path}")
    index = get_mentor_semantic_index(rag_path)
    index.warm()
    return rag_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the local embedding model and cache mentor vectors."
    )
    parser.add_argument(
        "--rag",
        type=Path,
        default=None,
        help="Override the path to ustc_mentor_rag.json.",
    )
    args = parser.parse_args()
    rag_path = warm(args.rag)
    settings = get_settings()
    cache_dir = settings.embedding_cache_dir
    print(
        f"OK mentor semantic index ready: {rag_path} "
        f"(model cache: {cache_dir})"
    )


if __name__ == "__main__":
    main()
