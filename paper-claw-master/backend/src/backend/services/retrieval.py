from __future__ import annotations

import math
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import DocumentChunk, ProcessedDocument
from backend.schemas import RetrievedChunk
from backend.services.embeddings import EmbeddingService

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


class RetrievalService:
    def __init__(self, session: Session, embedding_service: EmbeddingService | None = None) -> None:
        self.session = session
        self.embedding_service = embedding_service or EmbeddingService(session)

    def retrieve(self, paper_id: int, query: str, *, limit: int = 5) -> list[RetrievedChunk]:
        chunks = self._paper_chunks(paper_id)
        embedded_chunks = [chunk for chunk in chunks if chunk.embedding is not None]
        if embedded_chunks:
            try:
                query_vector, _ = self.embedding_service.embed_query(query)
            except Exception:
                return self.retrieve_lexical(paper_id, query, limit=limit)
            ranked = sorted(
                (
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        processed_document_id=chunk.processed_document_id,
                        content_text=chunk.content_text,
                        score=_cosine_similarity(query_vector, list(chunk.embedding)),
                        retrieval_mode="vector",
                        metadata={"chunk_key": chunk.chunk_key, "heading_path": chunk.heading_path_json},
                    )
                    for chunk in embedded_chunks
                ),
                key=lambda item: item.score,
                reverse=True,
            )
            return ranked[:limit]
        return self.retrieve_lexical(paper_id, query, limit=limit)

    def retrieve_lexical(self, paper_id: int, query: str, *, limit: int = 5) -> list[RetrievedChunk]:
        query_terms = set(_terms(query))
        ranked: list[RetrievedChunk] = []
        for chunk in self._paper_chunks(paper_id):
            chunk_terms = _terms(chunk.content_text)
            if not chunk_terms:
                continue
            overlap = sum(1 for term in chunk_terms if term in query_terms)
            if overlap == 0:
                continue
            score = overlap / math.sqrt(len(chunk_terms))
            ranked.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    processed_document_id=chunk.processed_document_id,
                    content_text=chunk.content_text,
                    score=score,
                    retrieval_mode="lexical",
                    metadata={"chunk_key": chunk.chunk_key, "heading_path": chunk.heading_path_json},
                )
            )
        return sorted(ranked, key=lambda item: item.score, reverse=True)[:limit]

    def _paper_chunks(self, paper_id: int) -> list[DocumentChunk]:
        return list(
            self.session.scalars(
                select(DocumentChunk)
                .join(ProcessedDocument)
                .options(selectinload(DocumentChunk.processed_document))
                .where(ProcessedDocument.paper_id == paper_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )


def _terms(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text)]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
