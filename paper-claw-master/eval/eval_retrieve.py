"""Deterministic, evidence-anchored retrieval benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT))

from backend.mentor_workflow.query_semantics import (  # noqa: E402
    build_query_contract,
    candidate_relevance,
    qualifies,
)
from backend.mentor_workflow.schemas import CandidateMentor  # noqa: E402


def _trusted(candidate: CandidateMentor) -> bool:
    return int(candidate.source_metadata.get("topics_source") or 0) in {1, 3}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=Path(__file__).with_name("mentor_queries.json"))
    parser.add_argument("--rag", type=Path, default=ROOT / "data" / "ustc_mentor_rag.json")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "retrieve_after.json")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    payload = json.loads(args.rag.read_text(encoding="utf-8"))
    candidates = [CandidateMentor.model_validate(row) for row in payload.get("candidates", [])]
    rows: list[dict] = []
    total_gold = total_found = total_returned = untrusted_returned = zero_misses = 0

    for item in spec["queries"]:
        contract = build_query_contract(item["query"], [item["query"]])
        assessed = []
        for candidate in candidates:
            score, match_type, breakdown = candidate_relevance(contract, candidate)
            if qualifies(score, match_type):
                assessed.append((score, candidate.candidate_id, candidate, match_type, breakdown))
        assessed.sort(key=lambda row: (-row[0], row[1]))
        top = assessed[: args.limit]
        returned_ids = [row[1] for row in top]
        gold = set(item.get("relevant_candidate_ids", []))
        found = gold.intersection(returned_ids)
        forbidden = set(item.get("forbidden_candidate_ids", []))
        forbidden_hits = forbidden.intersection(returned_ids)
        untrusted = [row[1] for row in top if not _trusted(row[2])]
        max_results = item.get("max_results")
        passed = bool(found) if gold else True
        if max_results is not None and len(top) > int(max_results):
            passed = False
            zero_misses += 1
        if item.get("forbid_untrusted_results") and untrusted:
            passed = False
        if forbidden_hits:
            passed = False
        total_gold += len(gold)
        total_found += len(found)
        total_returned += len(top)
        untrusted_returned += len(untrusted)
        rows.append({
            "id": item["id"], "query": item["query"],
            "expected_logic": item.get("logic"), "actual_logic": contract.logic,
            "passed": passed and contract.logic == item.get("logic", contract.logic),
            "gold": sorted(gold), "found": sorted(found),
            "forbidden_hits": sorted(forbidden_hits),
            "returned": [
                {"candidate_id": row[1], "name": row[2].mentor_name, "score": row[0], "match_type": row[3]}
                for row in top
            ],
            "untrusted_returned": untrusted,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_candidates": len(candidates),
        "metrics": {
            "recall_at_k": round(total_found / max(total_gold, 1), 4),
            "untrusted_mismatch_rate": round(untrusted_returned / max(total_returned, 1), 4),
            "zero_result_contract_violations": zero_misses,
            "passed_queries": sum(bool(row["passed"]) for row in rows),
            "total_queries": len(rows)
        },
        "rows": rows
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(row["passed"] for row in rows) else 1)


if __name__ == "__main__":
    main()
