"""Dense semantic retrieval over the curated mentor corpus.

This is the recall layer shared by mentor matching and PDF analysis.  It keeps
identity/evidence in the curated JSON corpus, but replaces lexical overlap with
multilingual dense embeddings.  Expensive mentor vectors are cached in-process.
"""

from __future__ import annotations

import json
import hashlib
import inspect
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.integrations.embeddings import FastEmbedEmbeddingAdapter
from backend.mentor_workflow.schemas import CandidateMentor, EvidenceRecord
from backend.mentor_workflow.topic_cleaning import clean_topics
from backend.schemas import ResolvedProviderConfig
from backend.services.providers import embedding_provider_from_settings


@dataclass(frozen=True)
class SemanticMentorHit:
    candidate: CandidateMentor
    score: float
    segment_indexes: list[int]


class MentorSemanticIndex:
    def __init__(
        self,
        rag_path: Path,
        *,
        provider: ResolvedProviderConfig | None = None,
        adapter: FastEmbedEmbeddingAdapter | None = None,
    ) -> None:
        self.rag_path = rag_path
        self.provider = provider or embedding_provider_from_settings()
        self.adapter = adapter or FastEmbedEmbeddingAdapter()
        if self.provider.provider != "local":
            raise ValueError(
                "Mentor semantic retrieval requires PAPER_CLAW_EMBEDDING_PROVIDER=local."
            )
        self._loaded = False
        self._candidates: list[CandidateMentor] = []
        self._evidence: list[EvidenceRecord] = []
        self._candidate_matrix: np.ndarray | None = None
        self._topic_matrix: np.ndarray | None = None

    @property
    def candidates(self) -> list[CandidateMentor]:
        self._ensure_loaded()
        return list(self._candidates)

    def evidence_for(self, candidate_ids: set[str]) -> list[EvidenceRecord]:
        self._ensure_loaded()
        return [item for item in self._evidence if item.candidate_id in candidate_ids]

    def search(self, segments: list[str], *, top_k: int = 20) -> list[SemanticMentorHit]:
        self._ensure_loaded()
        cleaned = [" ".join(text.split()) for text in segments if text and text.strip()]
        if not cleaned or not self._candidates:
            return []
        query_matrix = _normalized_matrix(
            self.adapter.embed_texts(self.provider, cleaned)
        )
        candidate_matrix = self._candidate_matrix
        if candidate_matrix is None or not len(candidate_matrix):
            return []
        topic_matrix = self._topic_matrix
        similarities = query_matrix @ candidate_matrix.T
        # 方向维度加权：见 _ensure_loaded 注释——整体多段文档混入院系/论文/方法
        # 泛词，会让"泛相关"导师的余弦分压过"精确方向"导师。这里只用整体分做召回，
        # 排序改用"方向相似度主导"的融合分，让研究方向精确命中的导师稳定排前。
        if topic_matrix is not None and len(topic_matrix):
            topic_similarities = query_matrix @ topic_matrix.T
        else:
            topic_similarities = None
        ranked: list[SemanticMentorHit] = []
        for candidate_index, candidate in enumerate(self._candidates):
            column = similarities[:, candidate_index]
            best = np.argsort(column)[::-1][: min(3, len(column))]
            best_scores = [float(column[index]) for index in best]
            # Max similarity protects a focused paragraph; a small top-k mean
            # contribution rewards support across several document passages.
            score = best_scores[0] * 0.8 + (sum(best_scores) / len(best_scores)) * 0.2
            if topic_similarities is not None:
                tcol = topic_similarities[:, candidate_index]
                tbest = np.argsort(tcol)[::-1][: min(3, len(tcol))]
                tbest_scores = [float(tcol[index]) for index in tbest]
                topic_score = tbest_scores[0] if tbest_scores else 0.0
                # 方向字段负责主题匹配；整体 profile 仅保留少量召回信号，
                # 避免院系名、论文池和泛 AI 词淹没精确方向。
                score = topic_score * 0.85 + score * 0.15
            ranked.append(
                SemanticMentorHit(
                    candidate=candidate,
                    score=score,
                    segment_indexes=[int(index) for index in best],
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.candidate.candidate_id))
        return ranked[: max(1, top_k)]

    def warm(self) -> None:
        """Materialize and cache both candidate and topic matrices."""
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        payload = json.loads(self.rag_path.read_text(encoding="utf-8"))
        self._candidates = [
            CandidateMentor.model_validate(item).model_copy(
                update={"research_topics": clean_topics(item.get("research_topics") or [])}
            )
            for item in payload.get("candidates", [])
            if isinstance(item, dict)
        ]
        self._evidence = [
            EvidenceRecord.model_validate(item)
            for item in payload.get("evidence", [])
            if isinstance(item, dict)
        ]
        fingerprint = self._fingerprint()
        self._candidate_matrix = self._load_cached_matrix(fingerprint, "candidate")
        if self._candidate_matrix is None:
            documents = [_candidate_document(candidate) for candidate in self._candidates]
            self._candidate_matrix = _normalized_matrix(
                self.adapter.embed_texts(self.provider, documents)
            )
            self._save_cached_matrix(fingerprint, self._candidate_matrix, "candidate")
        # 额外构建「纯研究方向」候选矩阵：研究方向字段单独 embed（不含院系/论文/
        # 方法等泛词），供 search 里对方向维度单算相似度、主导排序。这样既能保留
        # 整体文档的召回覆盖，又能让"研究方向精确命中"压过"论文里偶然出现的同义词"。
        # 方向文档极短、单次进程只构建一次，故不落盘缓存（整体矩阵已缓存，主体开销不重复）。
        topic_documents = [
            _candidate_topic_document(candidate) for candidate in self._candidates
        ]
        if any(topic_documents):
            self._topic_matrix = self._load_cached_matrix(fingerprint, "topic")
            if self._topic_matrix is None:
                self._topic_matrix = _normalized_matrix(
                    self.adapter.embed_texts(self.provider, topic_documents)
                )
                self._save_cached_matrix(fingerprint, self._topic_matrix, "topic")
        else:
            self._topic_matrix = None
        self._loaded = True

    def _fingerprint(self) -> str:
        settings = {
            key: self.provider.settings.get(key)
            for key in ("pooling", "normalize", "revision", "cache_dir")
        }
        adapter_source = inspect.getsource(type(self.adapter)).encode("utf-8")
        return hashlib.sha256(
            self.rag_path.read_bytes()
            + Path(__file__).read_bytes()
            + adapter_source
            + str(self.provider.model).encode("utf-8")
            + json.dumps(settings, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def _cache_path(self, kind: str) -> Path | None:
        raw = str(self.provider.settings.get("cache_dir") or "").strip()
        if not raw:
            return None
        model = re.sub(r"[^a-zA-Z0-9_.-]+", "_", self.provider.model or "model")
        return Path(raw) / f"paper_claw_mentor_index_{model}_{kind}.npz"

    def _load_cached_matrix(self, fingerprint: str, kind: str) -> np.ndarray | None:
        path = self._cache_path(kind)
        if path is None or not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as cached:
                if str(cached["fingerprint"].item()) != fingerprint:
                    return None
                matrix = np.asarray(cached["matrix"], dtype=np.float32)
            if matrix.shape[0] != len(self._candidates):
                return None
            return matrix
        except (OSError, ValueError, KeyError):
            return None

    def _save_cached_matrix(self, fingerprint: str, matrix: np.ndarray, kind: str) -> None:
        path = self._cache_path(kind)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp.npz")
        np.savez_compressed(temporary, fingerprint=fingerprint, matrix=matrix)
        temporary.replace(path)


def _candidate_document(candidate: CandidateMentor) -> str:
    fields = [
        f"导师：{candidate.mentor_name}",
        f"院系：{candidate.department or candidate.affiliation or ''}",
        "研究方向：" + "；".join(candidate.research_topics),
        "研究方法：" + "；".join(candidate.methods),
        "代表论文：" + "；".join(candidate.publications[:20]),
        "项目：" + "；".join(candidate.projects[:10]),
    ]
    # The retrieval model has a 512-token context.  Keep the strongest profile
    # signals and avoid spending first-run CPU on text the encoder truncates.
    return "\n".join(
        field for field in fields if field.split("：", 1)[-1].strip()
    )[:900]


def _candidate_topic_document(candidate: CandidateMentor) -> str:
    """纯研究方向文档：只拼 research_topics（+ methods 兜底），用于方向维度检索。

    与 _candidate_document 的整体文档分离：整体文档混入院系/论文/方法等泛词，
    会把"泛相关"导师压过"精确方向"导师；方向文档只保留方向词，让 search 里
    对方向维度单算的相似度能精确命中主题、主导排序。
    """
    topics = [t for t in candidate.research_topics if t and t.strip()]
    methods = [m for m in (candidate.methods or []) if m and m.strip()]
    parts = topics or methods
    if not parts:
        return ""
    return "研究方向：" + "；".join(parts[:16])


def _normalized_matrix(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError("Embedding adapter returned a non-matrix result.")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@lru_cache(maxsize=4)
def get_mentor_semantic_index(rag_path: Path) -> MentorSemanticIndex:
    """Reuse the in-memory mentor embeddings across PDF jobs in one process."""
    return MentorSemanticIndex(rag_path.resolve())
