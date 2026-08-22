from __future__ import annotations

import hashlib

from backend.schemas import ResolvedProviderConfig


class FixtureEmbeddingAdapter:
    def embed_texts(self, provider: ResolvedProviderConfig, texts: list[str]) -> list[list[float]]:
        dimension = int(provider.settings.get("dimension", 3))
        return [_embed_text(text, dimension) for text in texts]


def _embed_text(text: str, dimension: int) -> list[float]:
    normalized = text.lower()
    vectors = [0.0] * dimension
    keyword_buckets = {
        0: ("alpha", "retrieval", "rag", "evidence"),
        1: ("beta", "vision", "ocr", "image"),
        2: ("gamma", "citation", "reference", "bibliography"),
    }
    for index, keywords in keyword_buckets.items():
        if index < dimension:
            vectors[index] += sum(normalized.count(keyword) for keyword in keywords)
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    for index in range(dimension):
        vectors[index] += digest[index] / 2550.0
    norm = sum(value * value for value in vectors) ** 0.5
    return [value / norm for value in vectors] if norm else vectors
