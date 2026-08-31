"""Generate a fusion recall report for several probe queries.

Uses the full UnifiedMentorRetrieval facade (dense + lexical + no paper
gateway) so the numbers match what production would compute, minus the
paper-search side effects.  Writes UTF-8 output to a file (Windows console
is GBK-encoded, so printing Chinese to stdout garbles it).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

repo_root = Path(__file__).resolve().parents[2]  # paper-claw-master/
# data_scripts 是 namespace package（无 __init__.py），需把 repo_root 放 sys.path
# 让 `data_scripts.internal_mentor_rag` 可被导入；backend/src 放 src 布局包。
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "backend" / "src"))

from backend.mentor_workflow.schemas import (  # noqa: E402
    IntentPacket,
    MentorConstraints,
    UserProfile,
)
from backend.mentor_workflow.dense_rag import DenseInternalMentorRag  # noqa: E402
from backend.services.mentor_semantic_retrieval import MentorSemanticIndex  # noqa: E402
from backend.services.unified_mentor_retrieval import (  # noqa: E402
    UnifiedMentorRetrieval,
)
from data_scripts.internal_mentor_rag import FileInternalMentorRag  # noqa: E402

rag_path = (repo_root / "data" / "ustc_mentor_rag.json").resolve()

dense = DenseInternalMentorRag(MentorSemanticIndex(rag_path), top_k=20)
lexical = FileInternalMentorRag(rag_path)
facade = UnifiedMentorRetrieval(dense=dense, lexical=lexical, paper_gateway=None)

out_path = Path(os.environ["TEMP"]) / "fusion_report_mpnet.txt"

lines: list[str] = []
queries = ["强化学习", "天文学", "数据挖掘", "量子计算", "机器人"]
for q in queries:
    intent = IntentPacket(
        trace_id="t1",
        goal="find_mentors",
        confidence=1.0,
        raw_message=q,
        research_topics=[q],
        methods=[],
        application_domains=[],
        constraints=MentorConstraints(),
        user_profile=UserProfile(),
    )
    res = facade.retrieve(intent, [])
    lines.append(f"== {q} ({len(res.candidates)} cands) ==")
    for c in res.candidates[:15]:
        m = c.source_metadata
        lh = m.get("lexical_hits", 0)
        ds = m.get("dense_score", 0.0)
        dept = c.department or ""
        topics = " | ".join(c.research_topics[:2])
        lines.append(f"{lh}  {ds:.3f}  {c.mentor_name} / {dept} / {topics}")
    lines.append("")

out_path.write_text("\n".join(lines), encoding="utf-8")
print("WROTE", out_path)
