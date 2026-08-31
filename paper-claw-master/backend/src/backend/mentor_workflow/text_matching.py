"""Shared text-matching helpers for the mentor RAG path.

Several modules in the mentor retrieval pipeline
(``unified_mentor_retrieval``, ``dense_rag``, and the legacy copies in
``ustc_sources`` / ``internal_mentor_rag``) re-implement the same small set of
string utilities.  This module is the single source of truth for the version
used by the unified facade and the dense retriever, so behavior stays
consistent and the duplication stops spreading.

Only pure string logic lives here — no schema or I/O dependencies — so it
imports cleanly in any backend or ``data_scripts`` context.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from backend.mentor_workflow.schemas import EvidenceFreshness


def normalize(value: str) -> str:
    """Collapse whitespace and casefold for case-insensitive comparison."""
    return re.sub(r"\s+", " ", value.casefold()).strip()


def contains(text: str, term: str) -> bool:
    """Case-insensitive substring match with a guard for tiny ASCII terms.

    Terms of 1-2 ASCII characters (e.g. ``"RL"``) are matched on a word
    boundary so they don't fire inside unrelated words like ``"world"`` /
    ``"curl"`` / ``"RNA"``.  Everything else uses plain substring semantics,
    which is what Chinese direction names need.
    """
    normalized_term = normalize(term)
    if not normalized_term:
        return False
    hay = normalize(text)
    if re.fullmatch(r"[a-z0-9]{1,2}", normalized_term):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", hay
            )
        )
    return normalized_term in hay


def unique(values: Iterable[str]) -> list[str]:
    """Deduplicate while preserving order and normalizing whitespace."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def person_key(value: str) -> str:
    """Stable identity key for a person name: casefolded alphanumerics + CJK."""
    return re.sub(r"[^a-z0-9一-鿿]", "", value.casefold())


def freshness_from_year(year: int | None) -> EvidenceFreshness:
    """Map a publication year to the ``current`` / ``recent`` / ``stale`` bucket."""
    if year is None:
        return EvidenceFreshness.unknown
    from datetime import UTC, datetime

    current_year = datetime.now(UTC).year
    if year >= current_year - 2:
        return EvidenceFreshness.current
    if year >= current_year - 5:
        return EvidenceFreshness.recent
    return EvidenceFreshness.stale


def author_name(author: object) -> str:
    """Extract a display name from a paper author (string or dict)."""
    if isinstance(author, str):
        return " ".join(author.split()).strip()
    if isinstance(author, dict):
        for key in ("name", "display_name", "full_name"):
            value = author.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split()).strip()
    return ""


def author_matches(authors: list[object], aliases: list[str]) -> bool:
    """True if any paper author can be attributed to one of the mentor aliases.

    Matches on the normalized person key first, then falls back to a
    bag-of-lowercase-tokens comparison so name-order differences
    (``"Hu Huang"`` vs ``"Huang Hu"``) still resolve.
    """
    normalized_aliases = {person_key(alias) for alias in aliases if alias}
    for author in authors:
        name = author_name(author)
        key = person_key(name)
        if key and key in normalized_aliases:
            return True
        if re.search(r"[A-Za-z]", name):
            tokens = sorted(re.findall(r"[a-z]+", name.casefold()))
            if any(
                tokens == sorted(re.findall(r"[a-z]+", alias.casefold()))
                for alias in aliases
                if re.search(r"[A-Za-z]", alias)
            ):
                return True
    return False
