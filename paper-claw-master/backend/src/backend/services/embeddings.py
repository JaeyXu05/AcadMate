from __future__ import annotations

import math

import tiktoken
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import DocumentChunk, ProcessedDocument
from backend.integrations.embeddings import EmbeddingAdapter, FixtureEmbeddingAdapter, OpenAICompatibleEmbeddingAdapter
from backend.schemas import ResolvedProviderConfig
from backend.services.providers import embedding_provider_from_settings


class EmbeddingService:
    def __init__(
        self,
        session: Session,
        adapters: dict[str, EmbeddingAdapter] | None = None,
        embedding_provider: ResolvedProviderConfig | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.adapters = adapters or {
            "fixture": FixtureEmbeddingAdapter(),
            "openai_compatible": OpenAICompatibleEmbeddingAdapter(),
            "openai": OpenAICompatibleEmbeddingAdapter(),
        }

    def embed_missing_chunks(self, paper_id: int, *, batch_size: int = 64) -> int:
        provider = self.embedding_provider or embedding_provider_from_settings()
        provider = _with_token_limited_inputs_provider(provider)
        adapter = self._adapter_for(provider)
        chunks = list(
            self.session.scalars(
                select(DocumentChunk)
                .join(ProcessedDocument)
                .where(
                    ProcessedDocument.paper_id == paper_id,
                    DocumentChunk.embedding.is_(None),
                )
                .order_by(DocumentChunk.chunk_index)
            )
        )
        embedded = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = adapter.embed_texts(provider, token_limited_texts(provider, [chunk.content_text for chunk in batch]))
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_model = provider.model or provider.name
                chunk.embedding_dimension = len(vector)
                embedded += 1
        self.session.flush()
        return embedded

    def embed_query(self, query: str) -> tuple[list[float], ResolvedProviderConfig]:
        provider = self.embedding_provider or embedding_provider_from_settings()
        provider = _with_token_limited_inputs_provider(provider)
        vector = self._adapter_for(provider).embed_texts(provider, token_limited_texts(provider, [query]))[0]
        return vector, provider

    def _adapter_for(self, provider: ResolvedProviderConfig) -> EmbeddingAdapter:
        adapter = self.adapters.get(provider.provider)
        if adapter is None:
            raise ValueError(f"No embedding adapter configured for provider {provider.provider!r}.")
        return adapter


def token_limited_texts(provider: ResolvedProviderConfig, texts: list[str]) -> list[str]:
    max_context_tokens = int(provider.settings.get("max_context_tokens", 8192))
    budget = max(1, math.floor(max_context_tokens * 0.9))
    encoding_name = str(provider.settings.get("tokenizer_encoding", "cl100k_base"))
    encoding = tiktoken.get_encoding(encoding_name)
    return [_truncate_to_tokens(text, encoding, budget) for text in texts]


def _truncate_to_tokens(text: str, encoding: tiktoken.Encoding, budget: int) -> str:
    tokens = encoding.encode(text)
    if len(tokens) <= budget:
        return text
    return encoding.decode(tokens[:budget])


def _with_token_limited_inputs_provider(provider: ResolvedProviderConfig) -> ResolvedProviderConfig:
    settings = dict(provider.settings or {})
    settings.setdefault("max_context_tokens", 8192)
    settings.setdefault("tokenizer_encoding", "cl100k_base")
    return provider.model_copy(update={"settings": settings})
