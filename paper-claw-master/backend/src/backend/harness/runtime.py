"""Map growth state into the next Skill. No LLM, no retrieval."""

from __future__ import annotations

from typing import Any


def _pending_tasks(growth: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in growth.get("research_tasks") or []
        if isinstance(item, dict) and item.get("status") in {"pending", "in_progress"}
    ]


def suggest_next_skill(growth: dict[str, Any] | None) -> str | None:
    payload = growth or {}
    matched = payload.get("matched_mentors") or []
    read_papers = payload.get("read_papers") or []
    artifacts = [
        item for item in payload.get("artifacts") or [] if isinstance(item, dict)
    ]
    hypotheses = payload.get("direction_hypotheses") or []
    pending = _pending_tasks(payload)

    if matched and not read_papers:
        return "paper_qa"
    if any(str(item.get("id") or "").startswith("read-mentor:") for item in pending):
        return "paper_qa"
    if matched and not hypotheses:
        return "direction_explore"
    if any(str(item.get("id") or "").startswith("research-question:") for item in pending):
        return "research_task"
    if read_papers and not any(item.get("type") == "contact_email" for item in artifacts):
        return "email_compose"
    if any(item.get("type") == "pdf_document" and item.get("status") == "uploaded" for item in artifacts):
        return "pdf_analyze"
    return None
