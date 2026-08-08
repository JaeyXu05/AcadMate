from __future__ import annotations

from typing import Protocol

from backend.schemas import ResolvedProviderConfig


class EmbeddingAdapter(Protocol):
    def embed_texts(self, provider: ResolvedProviderConfig, texts: list[str]) -> list[list[float]]:
        ...
