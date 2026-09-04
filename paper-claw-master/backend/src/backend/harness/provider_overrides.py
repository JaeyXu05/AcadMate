"""Resolve the effective chat provider for a per-user Harness run.

The D application stores each logged-in user's own LLM credentials and sends
them as ``llm_*`` fields on ``RunCreate``.  Harness skills that only know the
global environment settings switch to this helper so a user who has configured
their own key/model actually uses it instead of the platform default.
"""

from __future__ import annotations

from backend.db.types import ProviderKind, ProviderName
from backend.harness.contracts import RunCreate
from backend.schemas import ProviderResolutionError, ResolvedProviderConfig
from backend.services.providers import chat_provider_from_settings
from backend.settings import get_settings


def provider_for_run(request: RunCreate) -> ResolvedProviderConfig:
    """Return the per-user provider when supplied, otherwise env settings."""
    user_model = (request.llm_model or "").strip()
    user_base_url = (request.llm_base_url or "").strip()
    user_api_key = (request.llm_api_key or "").strip()
    has_user_overrides = bool(user_model or user_base_url or user_api_key)
    if not has_user_overrides:
        return chat_provider_from_settings(get_settings())
    if not (user_model and user_base_url and user_api_key):
        raise ProviderResolutionError(
            "llm_override_incomplete",
            "用户 API 设置不完整：模型、Base URL 与 API Key 都必须填写。",
            {"model": user_model, "base_url": user_base_url, "has_api_key": bool(user_api_key)},
        )
    settings = get_settings()
    return ResolvedProviderConfig(
        id=0,
        name="settings-chat-user",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        base_url=user_base_url,
        model=user_model,
        api_key=user_api_key,
        temperature=settings.chat_temperature,
        settings={
            "max_tokens": settings.chat_max_tokens,
            "timeout": settings.chat_timeout_seconds,
            "max_retries": 0,
            **(settings.chat_extra_body or {}),
        },
    )
