"""Audit every concise research-topic label in the curated mentor corpus.

The audit is offline and deterministic.  It reports which stage loses a
direction: lexical recall, semantic/evidence boundary, candidate breadth, or
score discrimination.  Run from ``paper-claw-master``.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT)]

from backend.mentor_workflow.agents.domain_research import (  # noqa: E402
    DynamicDomainExpertAgent,
    _enforce_query_boundary,
)
from backend.mentor_workflow.query_semantics import build_query_contract  # noqa: E402
from backend.mentor_workflow.schemas import IntentPacket, MentorGoal  # noqa: E402
from backend.mentor_workflow.topic_cleaning import clean_topics  # noqa: E402
from data_scripts.internal_mentor_rag import FileInternalMentorRag  # noqa: E402


def usable_topic(value: object) -> bool:
    text = " ".join(str(value or "").split())
    if not 2 <= len(text) <= 48:
        return False
    return not re.search(r"(?:http|邮箱|电话|邮编|获奖|项目编号|访问学者)", text, re.I)


def main() -> None:
    payload = json.loads((ROOT / "data" / "ustc_mentor_rag.json").read_text(encoding="utf-8"))
    topic_counts: Counter[str] = Counter()
    departments: dict[str, set[str]] = {}
    topic_sources: dict[str, set[int]] = {}
    for candidate in payload.get("candidates", []):
        department = str(candidate.get("department") or "未标注院系")
        try:
            topics_source = int((candidate.get("source_metadata") or {}).get("topics_source") or 0)
        except (TypeError, ValueError):
            topics_source = 0
        # Audit exactly the direction labels that the runtime retriever sees,
        # not template residue that happened to survive in the source JSON.
        for topic in clean_topics(candidate.get("research_topics") or []):
            topic = " ".join(str(topic).split())
            if usable_topic(topic):
                topic_counts[topic] += 1
                departments.setdefault(topic, set()).add(department)
                topic_sources.setdefault(topic, set()).add(topics_source)

    rag = FileInternalMentorRag(ROOT / "data" / "ustc_mentor_rag.json")
    expert = DynamicDomainExpertAgent()
    rows = []
    for index, (topic, corpus_count) in enumerate(sorted(topic_counts.items()), start=1):
        contract = build_query_contract(topic, [topic])
        intent = IntentPacket(
            trace_id=f"all-topic-{index}", goal=MentorGoal.find_mentors,
            raw_message=topic, research_topics=[topic], query_contract=contract,
            confidence=1.0,
        )
        raw = rag.retrieve(intent, expert.run(intent))
        qualified = _enforce_query_boundary(raw, intent)
        scores = [float(c.source_metadata.get("absolute_relevance") or 0) for c in qualified.candidates]
        # ``topics_source=2`` means that the label was inferred from paper
        # titles, not asserted by an official mentor profile.  The production
        # boundary deliberately refuses to promote it to a verified match;
        # count it as a data-verification queue rather than a retrieval fault.
        if topic_sources.get(topic) == {2}:
            node = "inferred_only_direction"
        elif not raw.candidates:
            node = "recall_zero"
        elif not qualified.candidates:
            node = "boundary_or_evidence_reject"
        elif len(qualified.candidates) == 1:
            node = "single_candidate"
        elif max(scores) - min(scores) < 1.0:
            node = "score_tie"
        else:
            node = "healthy"
        rows.append({
            "topic": topic, "corpus_mentions": corpus_count,
            "topic_sources": sorted(topic_sources.get(topic, set())),
            "departments": sorted(departments[topic]), "raw_count": len(raw.candidates),
            "qualified_count": len(qualified.candidates), "score_span": round(max(scores) - min(scores), 2) if scores else 0,
            "node": node, "top_names": [c.mentor_name for c in qualified.candidates[:5]],
            "warnings": qualified.warnings,
        })
    counts = Counter(row["node"] for row in rows)
    weak = [row for row in rows if row["node"] != "healthy"]
    weak.sort(key=lambda row: (row["node"], row["corpus_mentions"], row["topic"]))
    report = {"generated_at": datetime.now(UTC).isoformat(), "direction_count": len(rows),
              "node_counts": counts, "weak_directions": weak, "all_rows": rows}
    out = ROOT / "eval" / "results" / "all_directions_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"direction_count": len(rows), "node_counts": counts,
                      "weak_examples": weak[:30], "output": str(out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
