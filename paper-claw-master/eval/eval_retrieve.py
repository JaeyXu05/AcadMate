"""Run thresholded mentor retrieval on the eval query set and write results/.

Usage (from paper-claw-master):
  python eval/eval_retrieve.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT))

from backend.mentor_workflow.schemas import IntentPacket, MentorGoal  # noqa: E402
from data_scripts.internal_mentor_rag import FileInternalMentorRag  # noqa: E402


def main() -> None:
    eval_dir = Path(__file__).resolve().parent
    spec = json.loads((eval_dir / "mentor_queries.json").read_text(encoding="utf-8"))
    rag = FileInternalMentorRag(ROOT / "data" / "ustc_mentor_rag.json")
    rows = []
    for item in spec["queries"]:
        result = rag.retrieve(
            IntentPacket(
                trace_id=f"eval-{item['id']}",
                goal=MentorGoal.find_mentors,
                research_topics=[item["query"]],
                confidence=1.0,
            ),
            [],
        )
        rows.append(
            {
                "id": item["id"],
                "query": item["query"],
                "count": len(result.candidates),
                "names": [c.mentor_name for c in result.candidates[:8]],
                "hits": [
                    int(c.source_metadata.get("retrieve_hits") or 0)
                    for c in result.candidates[:8]
                ],
                "expect": item["expect"],
            }
        )
    out_dir = eval_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_candidates": len(rag._candidates),
        "rows": rows,
    }
    out_path = out_dir / "retrieve_after.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
