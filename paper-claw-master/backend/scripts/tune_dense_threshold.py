"""Sweep dense_threshold for mpnet and report candidate counts + dense score
distributions, so the threshold can be re-calibrated after the model swap.

mpnet's dense scores cluster lower than MiniLM's, so the old 0.5 threshold
over-filters.  This script prints, per query, the top-20 fused candidates'
dense scores and how many survive each candidate threshold.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

repo_root = Path(__file__).resolve().parents[2]  # paper-claw-master/ (backend/scripts/ -> .. -> ..)
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "backend" / "src"))

from backend.mentor_workflow.schemas import (  # noqa: E402
    IntentPacket,
    MentorConstraints,
    UserProfile,
)
from backend.mentor_workflow.dense_rag import DenseInternalMentorRag  # noqa: E402
from backend.services.mentor_semantic_retrieval import MentorSemanticIndex  # noqa: E402
from data_scripts.internal_mentor_rag import FileInternalMentorRag  # noqa: E402

rag_path = (repo_root / "data" / "ustc_mentor_rag.json").resolve()

dense = DenseInternalMentorRag(MentorSemanticIndex(rag_path), top_k=20)
lexical = FileInternalMentorRag(rag_path)

queries = ["强化学习", "天文学", "数据挖掘", "量子计算", "机器人"]

out = []
for q in queries:
    intent = IntentPacket(
        trace_id="t1", goal="find_mentors", confidence=1.0,
        raw_message=q, research_topics=[q], methods=[],
        application_domains=[], constraints=MentorConstraints(),
        user_profile=UserProfile(),
    )
    res = dense.retrieve(intent, [])
    # dense.retrieve sets retrieve_score in source_metadata (cosine*100)
    scores = [
        float(c.source_metadata.get("retrieve_score", 0.0)) / 100.0
        for c in res.candidates
    ]
    out.append(f"== {q} (dense top-20) ==")
    out.append("dense scores: " + " ".join(f"{s:.3f}" for s in scores))
    for thr in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55):
        n = sum(1 for s in scores if s >= thr)
        out.append(f"  thr={thr:.2f} -> {n} keep")
    out.append("")

out_path = Path(os.environ["TEMP"]) / "dense_threshold_sweep.txt"
out_path.write_text("\n".join(out), encoding="utf-8")
print("WROTE", out_path)
