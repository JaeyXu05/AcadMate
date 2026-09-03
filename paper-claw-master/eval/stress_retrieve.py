"""Offline stress evaluation for the curated USTC mentor retriever.

Run from ``paper-claw-master`` with ``backend/.venv/Scripts/python.exe
eval/stress_retrieve.py``.  It writes a timestamped, inspectable JSON report
under ``eval/results`` and makes no network or database calls.
"""

from __future__ import annotations

import json
import sys
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
from data_scripts.internal_mentor_rag import FileInternalMentorRag  # noqa: E402


QUERIES = [
    ("vision_zh", "计算机视觉"),
    ("vision_en", "computer vision"),
    ("generative_ai", "生成式人工智能"),
    ("llm", "large language model"),
    ("reinforcement_learning", "强化学习"),
    ("multi_agent_rl", "多智能体强化学习"),
    ("nlp", "自然语言处理"),
    ("distributed", "分布式系统"),
    ("compiler", "编译器优化"),
    ("database", "数据库系统"),
    ("cybersecurity", "网络空间安全"),
    ("privacy", "隐私保护"),
    ("cryptography", "密码学"),
    ("quantum", "量子计算"),
    ("semiconductor", "半导体器件"),
    ("robotics", "机器人"),
    ("biomedical", "生物医学工程"),
    ("bioinformatics", "生物信息学"),
    ("drug_discovery", "药物发现"),
    ("materials", "材料科学"),
    ("chemical", "催化化学"),
    ("physics", "凝聚态物理"),
    ("math", "偏微分方程"),
    ("statistics", "贝叶斯统计"),
    ("and_query", "机器学习和网络安全"),
    ("nonsense", "不存在的方向xyz"),
    ("ambiguous", "AI"),
    ("natural_sentence", "我想做用大模型辅助医学文本分析的研究"),
]


def main() -> None:
    rag = FileInternalMentorRag(ROOT / "data" / "ustc_mentor_rag.json")
    expert = DynamicDomainExpertAgent()
    rows = []
    for query_id, query in QUERIES:
        contract = build_query_contract(query, [query])
        intent = IntentPacket(
            trace_id=f"stress-{query_id}",
            goal=MentorGoal.find_mentors,
            raw_message=query,
            research_topics=[query],
            query_contract=contract,
            confidence=1.0,
        )
        raw = rag.retrieve(intent, expert.run(intent))
        qualified = _enforce_query_boundary(raw, intent)
        rows.append(
            {
                "id": query_id,
                "query": query,
                "contract": contract.model_dump(mode="json"),
                "raw_count": len(raw.candidates),
                "qualified_count": len(qualified.candidates),
                "warnings": qualified.warnings,
                "raw_top10": [
                    {
                        "id": candidate.candidate_id,
                        "name": candidate.mentor_name,
                        "department": candidate.department,
                        "topics": candidate.research_topics[:4],
                        "score": candidate.source_metadata.get("retrieve_score"),
                        "hits": candidate.source_metadata.get("retrieve_hits"),
                    }
                    for candidate in raw.candidates[:10]
                ],
                "qualified": [
                    {
                        "id": candidate.candidate_id,
                        "name": candidate.mentor_name,
                        "department": candidate.department,
                        "topics": candidate.research_topics[:5],
                        "relevance": candidate.source_metadata.get("absolute_relevance"),
                        "match_type": candidate.source_metadata.get("match_type"),
                    }
                    for candidate in qualified.candidates
                ],
            }
        )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_candidates": len(rag._candidates),
        "query_count": len(rows),
        "rows": rows,
    }
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "retrieval_stress.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        names = ", ".join(item["name"] for item in row["qualified"][:3]) or "—"
        print(f"{row['id']:24} raw={row['raw_count']:2} qualified={row['qualified_count']}  {names}")
    print(out_path)


if __name__ == "__main__":
    main()
