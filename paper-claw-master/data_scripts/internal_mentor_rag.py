"""InternalMentorRag 适配器：加载抓取好的 RAG 库并实现 retrieve()。

这是把 ``data/ustc_mentor_rag.json`` 接入工作流的粘合层。实现
``backend.mentor_workflow.ustc_sources.InternalMentorRag`` 协议的 ``retrieve``，
返回符合 schema 的 ``MentorResearchResult``（含 ``CandidateMentor`` +
``EvidenceRecord``）。

匹配策略（轻量、离线、可复现）：
- 若 intent 显式指定 ``mentor_names`` 或 ``candidate_ids``，按名字/ID 精确召回。
- 否则用 intent 的 research_topics / methods / application_domains +
  domain_judgements 的 search_concepts 做关键词命中，命中即召回，按命中数排序。
- 返回的候选都带 ``identity_verified=true`` 的身份证据，source_chain 标
  ``internal_ustc_rag``，从而让工作流在内部库完整命中时跳过外部官方源。

接入方式（最小改动）：把 ``backend/api/routers/mentor_workflows.py`` 的
``get_internal_mentor_rag`` 改为::

    from data_scripts.internal_mentor_rag import FileInternalMentorRag

    def get_internal_mentor_rag() -> InternalMentorRag:
        return FileInternalMentorRag()  # 默认加载 data/ustc_mentor_rag.json

或在测试里直接 ``FileInternalMentorRag()`` 传给 ``UstcMentorResearchTool``。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from backend.mentor_workflow.schemas import (
    CandidateMentor,
    DomainJudgement,
    EvidenceRecord,
    IntentPacket,
    MentorGoal,
    MentorResearchResult,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_PATH = REPO_ROOT / "data" / "ustc_mentor_rag.json"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _contains(text: str, term: str) -> bool:
    t = _normalize(term)
    return bool(t and t in _normalize(text))


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


# ---- 轻量稀疏向量检索（离线、确定性、无外部模型）----
# 用词法 TF 向量 + 中文二元组 + 英文词元构建每个候选的语义向量，查询时算余弦相似度，
# 与传统子串命中数做混合打分。这样"深度强化学习"可命中含 "Reinforcement Learning" 的导师，
# 也更好地区分命中质量，取代纯子串计数排序。
_CJK = re.compile(r"[一-鿿]")


def _tokens(text: str) -> list[str]:
    """把一段文本切成可比较的词元：英文词 + 中文整短语 + 中文二元组。"""
    value = text.casefold()
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9][a-z0-9\-\.]*", value):
        if len(word) >= 2:
            tokens.append(word)
    chars = _CJK.findall(value)
    if chars:
        # 整段中文短语作为一个词元（保留完整方向名语义），再加滑动二元组提升模糊匹配
        tokens.append("".join(chars))
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i + 1])
    return tokens


def _term_vector(text: str) -> Counter[str]:
    """TF 词频向量（归一化到最大词频=1），用作离线嵌入，无需外部模型。"""
    counts = Counter(_tokens(text))
    if not counts:
        return counts
    peak = max(counts.values())
    return Counter({token: count / peak for token, count in counts.items()})


def build_idf(corpus: list[Counter[str]]) -> dict[str, float]:
    """根据候选语料统计文档频次，返回 token -> IDF 权重。

    常见词元（如"学习""化学"这类二元组）跨大量候选出现，IDF 小；只在个别
    候选出现的整段中文短语/专有词元，IDF 大。用在离线向量里降低泛词噪声。
    """
    total = max(len(corpus), 1)
    doc_freq: Counter[str] = Counter()
    for vector in corpus:
        doc_freq.update(vector.keys())
    return {
        token: math.log(total / (1.0 + freq))
        for token, freq in doc_freq.items()
    }


def _weighted_vector(
    vector: Counter[str], idf: dict[str, float]
) -> dict[str, float]:
    """用 IDF 加权 TF 向量：权重 = 归一化 TF * IDF。"""
    return {
        token: weight * idf.get(token, 0.0)
        for token, weight in vector.items()
    }


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """两个加权 TF 向量的余弦相似度。"""
    if not a or not b:
        return 0.0
    dot = sum(weight for token, weight in a.items() if token in b)
    if dot <= 0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class FileInternalMentorRag:
    """从 JSON 文件加载的内部导师 RAG。实现 InternalMentorRag 协议。"""

    def __init__(self, rag_path: Path | str | None = None) -> None:
        self.rag_path = Path(rag_path) if rag_path else DEFAULT_RAG_PATH
        self._loaded = False
        self._candidates: list[CandidateMentor] = []
        self._evidence: list[EvidenceRecord] = []
        self._load_warnings: list[str] = []
        # 每个候选的离线 TF*IDF 词向量（按 _candidates 下标对齐），供混合检索用。
        self._candidate_vectors: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.rag_path.exists():
            self._load_warnings.append(
                f"内部 RAG 文件不存在: {self.rag_path}，"
                f"请先运行 data_scripts/ustc_scraper.py + openalex_scraper.py + build_rag.py"
            )
            return
        payload = json.loads(self.rag_path.read_text(encoding="utf-8"))
        self._evidence = [
            EvidenceRecord.model_validate(record)
            for record in payload.get("evidence", [])
            if isinstance(record, dict)
        ]
        self._candidates = [
            CandidateMentor.model_validate(record)
            for record in payload.get("candidates", [])
            if isinstance(record, dict)
        ]
        # 预计算候选向量：合并研究方向/方法/论文/学院/姓名，一次算好供后续查询复用。
        # 先按全库统计 IDF（降常见二元组噪声），再逐候选做 TF*IDF 加权。
        raw_vectors = [
            _term_vector(
                " ".join(
                    [
                        candidate.mentor_name,
                        " ".join(candidate.research_topics),
                        " ".join(candidate.methods),
                        " ".join(candidate.publications),
                        candidate.department or "",
                    ]
                )
            )
            for candidate in self._candidates
        ]
        self._idf = build_idf(raw_vectors)
        self._candidate_vectors = [
            _weighted_vector(vector, self._idf)
            for vector in raw_vectors
        ]

    def retrieve(
        self,
        intent: IntentPacket,
        domain_judgements: list[DomainJudgement],
    ) -> MentorResearchResult:
        self._ensure_loaded()
        warnings = list(self._load_warnings)
        if not self._candidates:
            return MentorResearchResult(
                warnings=warnings or ["内部 RAG 无可用导师记录"],
                source_chain=["internal_ustc_rag"],
            )

        concepts = _unique(
            [
                *intent.research_topics,
                *intent.methods,
                *intent.application_domains,
                *[
                    concept
                    for judgement in domain_judgements
                    for concept in judgement.search_concepts
                ],
            ]
        )
        mentor_filter = {
            _normalize(name) for name in intent.constraints.mentor_names
        }
        candidate_filter = set(intent.constraints.candidate_ids)

        # 查询向量：把 research_topics/methods/application_domains + 领域同义词
        # 合并成一条查询文本，与候选向量算语义相似度（离线、确定性）。
        query_vector = _weighted_vector(_term_vector(" ".join(concepts)), self._idf)

        scored: list[tuple[float, str, int, CandidateMentor]] = []
        for index, candidate in enumerate(self._candidates):
            # 精确约束优先：名字或 ID 命中即召回。
            if mentor_filter and _normalize(candidate.mentor_name) not in mentor_filter:
                continue
            if candidate_filter and candidate.candidate_id not in candidate_filter:
                continue
            if not concepts and not mentor_filter and not candidate_filter:
                # 无任何检索条件时，返回全部（让上层兜底排序）。
                scored.append((0.0, "", 0, candidate))
                continue
            haystack = " ".join(
                [
                    candidate.mentor_name,
                    " ".join(candidate.research_topics),
                    " ".join(candidate.methods),
                    " ".join(candidate.publications),
                    candidate.department or "",
                ]
            )
            # 词法：命中查询里的若干概念（子串归一化匹配）。
            hits = sum(1 for concept in concepts if _contains(haystack, concept))
            # 语义：查询向量与候选向量的余弦相似度。
            cosine = (
                _cosine_similarity(query_vector, self._candidate_vectors[index])
                if self._candidate_vectors
                else 0.0
            )
            # 混合：语义为主、词法兜底，保证纯子串命中（含精确约束）也能排到。
            score = cosine * 100.0 + hits * 3.0
            # 保留精确命中标识方便调试与稳定性（原逻辑同等条件即可召回）。
            if hits > 0 or score > 0.0 or mentor_filter or candidate_filter:
                scored.append((score, candidate.candidate_id, hits, candidate))

        # 先按混合分降序，同分再按词法命中数，最后按 candidate_id 保证稳定排序。
        scored.sort(key=lambda item: (-item[0], -item[2], item[1]))
        kept = [candidate for _, _, _, candidate in scored]

        # 只回传与召回候选绑定的证据，避免账本里塞无关记录。
        kept_ids = {candidate.candidate_id for candidate in kept}
        evidence = [
            record
            for record in self._evidence
            if record.candidate_id in kept_ids
        ]

        # 内部库的身份/导师角色均已核验、且带研究方向 → 视为完整命中，
        # unresolved_candidate_ids 留空，工作流据此跳过外部官方源。
        unresolved = [
            candidate.candidate_id
            for candidate in kept
            if not candidate.research_topics or not candidate.evidence_refs
        ]
        return MentorResearchResult(
            candidates=kept,
            evidence=evidence,
            warnings=warnings,
            used_fallback=False,
            source_chain=["internal_ustc_rag"],
            unresolved_candidate_ids=unresolved,
        )


def main() -> None:
    """命令行自检：打印库统计并用示例 intent 试跑一次 retrieve()。"""
    rag = FileInternalMentorRag()
    rag._ensure_loaded()
    print(f"RAG 文件: {rag.rag_path}")
    print(f"候选导师: {len(rag._candidates)} 位")
    print(f"证据记录: {len(rag._evidence)} 条")
    if rag._load_warnings:
        print("警告:", rag._load_warnings)
        return
    # 示例检索：强化学习 / reinforcement learning。
    sample_intent = IntentPacket(
        trace_id="rag-selfcheck",
        goal=MentorGoal.find_mentors,
        research_topics=["强化学习", "reinforcement learning"],
        methods=["reinforcement learning"],
        confidence=1.0,
    )
    result = rag.retrieve(sample_intent, [])
    print(f"\n示例检索 '强化学习' -> {len(result.candidates)} 位导师")
    for candidate in result.candidates[:5]:
        print(f"  - {candidate.mentor_name} ({candidate.department}): {candidate.research_topics[:3]}")


if __name__ == "__main__":
    main()
