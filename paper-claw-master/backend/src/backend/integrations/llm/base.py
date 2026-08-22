from __future__ import annotations

from typing import Protocol

from backend.schemas import ResolvedProviderConfig


class ChatModelAdapter(Protocol):
    def generate_text(self, provider: ResolvedProviderConfig, messages: list[dict]) -> str:
        ...
