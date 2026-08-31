from __future__ import annotations

from typing import Any

import httpx
from openai import OpenAI

from backend.schemas import ResolvedProviderConfig
from backend.services.providers import resolve_api_key


class OpenAICompatibleChatModelAdapter:
    def __init__(self, client: Any | None = None) -> None:
        self.client = client
        self._http_client: httpx.Client | None = None
        self._openai_clients: dict[tuple[str | None, str | None, int], OpenAI] = {}

    def generate_text(
        self, provider: ResolvedProviderConfig, messages: list[dict]
    ) -> str:
        if self.client is not None:
            client = self.client
        else:
            # The desktop environment may export a stale HTTP(S)_PROXY pointing
            # at a local port.  The configured OpenAI-compatible endpoint is
            # reachable directly, so do not let process-global proxy variables
            # silently turn a valid API key into an SSL/connection failure.
            if self._http_client is None:
                self._http_client = httpx.Client(trust_env=False)
            api_key = provider.api_key or resolve_api_key(provider.api_key_ref)
            try:
                configured_retries = provider.settings.get("max_retries")
                max_retries = max(0, int(2 if configured_retries is None else configured_retries))
            except (TypeError, ValueError):
                max_retries = 0
            client_key = (provider.base_url, api_key, max_retries)
            client = self._openai_clients.get(client_key)
            if client is None:
                client = OpenAI(
                    api_key=api_key,
                    base_url=provider.base_url,
                    http_client=self._http_client,
                    max_retries=max_retries,
                )
                self._openai_clients[client_key] = client
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
