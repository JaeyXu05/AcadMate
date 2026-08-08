from __future__ import annotations

from typing import Any

from openai import OpenAI

from backend.schemas import ResolvedProviderConfig
from backend.services.providers import resolve_api_key


class OpenAICompatibleEmbeddingAdapter:
    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def embed_texts(self, provider: ResolvedProviderConfig, texts: list[str]) -> list[list[float]]:
        client = self.client or OpenAI(api_key=provider.api_key or resolve_api_key(provider.api_key_ref), base_url=provider.base_url)
        kwargs = {"model": provider.model, "input": texts, "timeout": provider.settings.get("timeout")}
        if provider.settings.get("dimension") is not None:
            kwargs["dimensions"] = provider.settings["dimension"]
        response = client.embeddings.create(**kwargs)
        return [list(item.embedding) for item in response.data]
