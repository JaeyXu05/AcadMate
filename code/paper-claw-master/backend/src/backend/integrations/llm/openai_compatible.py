from __future__ import annotations

from typing import Any

from openai import OpenAI

from backend.schemas import ResolvedProviderConfig
from backend.services.providers import resolve_api_key


class OpenAICompatibleChatModelAdapter:
    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def generate_text(
        self, provider: ResolvedProviderConfig, messages: list[dict]
    ) -> str:
        client = self.client or OpenAI(
            api_key=provider.api_key or resolve_api_key(provider.api_key_ref),
            base_url=provider.base_url,
        )
        kwargs: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": provider.temperature,
            "max_tokens": provider.settings.get("max_tokens"),
            "timeout": provider.settings.get("timeout"),
        }
        if provider.settings.get("extra_body") is not None:
            kwargs["extra_body"] = provider.settings["extra_body"]
        if provider.settings.get("response_format") is not None:
            kwargs["response_format"] = provider.settings["response_format"]
        response = client.chat.completions.create(**kwargs)
        if not response.choices:
            raise RuntimeError("Chat model returned no choices.")
        return str(response.choices[0].message.content or "")
