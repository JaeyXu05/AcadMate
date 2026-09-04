"""Single, versioned source for retrieval/query policy shared with D fallback."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

POLICY_PATH = Path(__file__).resolve().parents[4] / "config" / "retrieval_policy.v3.json"


@lru_cache(maxsize=1)
def retrieval_policy() -> dict[str, Any]:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("version") != 3:
        raise ValueError(f"Unsupported retrieval policy version: {payload.get('version')}")
    return payload


def policy_score(name: str) -> float:
    value = retrieval_policy()["scores"][name]
    if name == "relevance_threshold":
        raw = os.environ.get("MENTOR_RELEVANCE_THRESHOLD")
        if raw:
            try:
                override = float(raw)
            except ValueError:
                override = 0.0
            if override > 0:
                return override
    return float(value)


def policy_version() -> int:
    return int(retrieval_policy()["version"])
