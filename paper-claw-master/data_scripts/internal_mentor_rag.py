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
from backend.mentor_workflow.topic_cleaning import clean_topics as _clean_topics

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_PATH = REPO_ROOT / "data" / "ustc_mentor_rag.json"
# Keep a broad, deterministic candidate pool for the typed semantic boundary
# stage.  The workflow subsequently applies its evidence and relevance gates
# before returning at most five mentors to the UI.
DEFAULT_TOP_K = 80
HIT_BONUS = 1.5


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _contains(text: str, term: str) -> bool:
    t = _normalize(term)
    if not t:
        return False
    hay = _normalize(text)
    # 纯 ASCII 且极短（≤2 字符）的词做整词匹配，避免 "RL" 这类缩写在
    # "world"/"curl"/"RNA" 里被子串误命中；其余保留子串语义。
    if re.fullmatch(r"[a-z0-9]{1,2}", t):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", hay))
    return t in hay


def _high_coverage_cjk_match(values: list[str], term: str) -> bool:
    """Recall a near-normalised CJK label without accepting a vague overlap.

    This is deliberately recall-only.  The typed relation and evidence gates
    still decide qualification.  It helps labels such as ``常微分方程`` find a
    profile written as ``微分方程`` while rejecting ``随机过程`` vs ``随机图``.
    """

    query_chars = _CJK.findall(_normalize(term))
    if len(query_chars) < 3:
        return False
    query_units = set(query_chars)
    query_units.update(
        query_chars[index] + query_chars[index + 1]
        for index in range(len(query_chars) - 1)
    )
    query_bigrams = {unit for unit in query_units if len(unit) == 2}
    if not query_bigrams:
        return False
    for value in values:
        candidate_chars = _CJK.findall(_normalize(value))
        if len(candidate_chars) < 2:
            continue
        candidate_units = set(candidate_chars)
        candidate_units.update(
            candidate_chars[index] + candidate_chars[index + 1]
            for index in range(len(candidate_chars) - 1)
        )
        shared = query_units & candidate_units
        if (
            len(shared) / len(query_units) >= 0.6
            and query_bigrams & candidate_units
        ):
            return True
    return False


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
    dot = sum(weight * b[token] for token, weight in a.items() if token in b)
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
        self._candidates = []
        for record in payload.get("candidates", []):
            if not isinstance(record, dict):
                continue
            candidate = CandidateMentor.model_validate(record)
            self._candidates.append(
                candidate.model_copy(
                    update={
                        "research_topics": _clean_topics(candidate.research_topics),
                        "methods": _clean_topics(candidate.methods),
                    }
                )
            )
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

        scored: list[
            tuple[float, str, int, int, int, float, CandidateMentor]
        ] = []
        for index, candidate in enumerate(self._candidates):
            # 精确约束优先：名字或 ID 命中即召回。
            if mentor_filter and _normalize(candidate.mentor_name) not in mentor_filter:
                continue
            if candidate_filter and candidate.candidate_id not in candidate_filter:
                continue
            if not concepts and not mentor_filter and not candidate_filter:
                warnings.append("无检索条件，内部语料不召回全库")
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
            searchable_fields = [
                *candidate.research_topics,
                *candidate.methods,
                *candidate.publications,
                candidate.department or "",
            ]
            exact_hits = sum(
                1 for concept in concepts if _contains(haystack, concept)
            )
            fuzzy_hits = sum(
                1
                for concept in concepts
                if not _contains(haystack, concept)
                and _high_coverage_cjk_match(searchable_fields, concept)
            )
            hits = exact_hits + fuzzy_hits
            cosine = (
                _cosine_similarity(query_vector, self._candidate_vectors[index])
                if self._candidate_vectors
                else 0.0
            )
            # ``hits`` is only a small lexical tie-breaker.  Its semantics are
            # intentionally weaker than the TF-IDF score: domain expansion can
            # add broad aliases, which must not overwhelm a specific match.
            score = cosine * 100.0 + hits * HIT_BONUS
            # 无精确姓名/ID 时，hits=0 的余弦噪声不得入榜。
            if mentor_filter or candidate_filter or hits >= 1:
                scored.append(
                    (
                        score,
                        candidate.candidate_id,
                        hits,
                        exact_hits,
                        fuzzy_hits,
                        cosine,
                        candidate,
                    )
                )

        scored.sort(key=lambda item: (-item[0], -item[2], item[1]))
        kept: list[CandidateMentor] = []
        for (
            score,
            _candidate_id,
            hits,
            exact_hits,
            fuzzy_hits,
            cosine,
            candidate,
        ) in scored[:DEFAULT_TOP_K]:
            kept.append(
                candidate.model_copy(
                    deep=True,
                    update={
                        "source_metadata": {
                            **candidate.source_metadata,
                            "retrieve_hits": int(hits),
                            "retrieve_exact_hits": int(exact_hits),
                            "retrieve_fuzzy_hits": int(fuzzy_hits),
                            "retrieve_score": round(float(score), 4),
                            "retrieve_cosine": round(float(cosine), 6),
                        }
                    },
                )
            )

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
