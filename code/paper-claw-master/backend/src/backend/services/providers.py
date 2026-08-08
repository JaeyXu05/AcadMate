from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import ProviderConfig
from backend.db.types import ProviderKind, ProviderName
from backend.schemas import ProviderResolutionError, ResolvedProviderConfig
from backend.settings import Settings, get_settings


def resolve_provider_config(session: Session, kind: str, name: str | None = None) -> ResolvedProviderConfig:
    statement = select(ProviderConfig).where(ProviderConfig.kind == kind, ProviderConfig.enabled.is_(True))
    if name is not None:
        statement = statement.where(ProviderConfig.name == name)
        provider_config = session.scalar(statement)
        if provider_config is None:
            raise ProviderResolutionError(
                "provider_not_found",
                f"No enabled provider config named {name!r} for kind {kind!r}.",
                {"kind": kind, "name": name},
            )
        return _to_resolved_provider(provider_config)

    default_statement = statement.where(ProviderConfig.is_default.is_(True)).order_by(ProviderConfig.id)
    provider_config = session.scalar(default_statement)
    if provider_config is None:
        provider_config = session.scalar(statement.order_by(ProviderConfig.id))
    if provider_config is None:
        raise ProviderResolutionError(
            "provider_not_found",
            f"No enabled provider config exists for kind {kind!r}.",
            {"kind": kind},
        )
    return _to_resolved_provider(provider_config)


def resolve_api_key(api_key_ref: str | None) -> str | None:
    if api_key_ref is None or not api_key_ref.strip():
        return None
    if api_key_ref.startswith("env:"):
        key = api_key_ref.removeprefix("env:")
        value = os.getenv(key)
        if value is None:
            raise ProviderResolutionError("api_key_missing", f"Environment variable {key!r} is not set.", {"api_key_ref": api_key_ref})
        return value
    return api_key_ref


def chat_provider_from_settings(settings: Settings | None = None) -> ResolvedProviderConfig:
    settings = settings or get_settings()
    if not settings.chat_model or not settings.chat_model.strip():
        raise ProviderResolutionError("chat_model_missing", "PAPER_CLAW_CHAT_MODEL is not set.")
    provider_settings: dict[str, object] = {"max_tokens": settings.chat_max_tokens, "timeout": settings.chat_timeout_seconds, "max_retries": settings.chat_max_retries}
    if settings.chat_extra_body is not None:
        provider_settings["extra_body"] = settings.chat_extra_body
    return ResolvedProviderConfig(
        id=0,
        name="settings-chat",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        base_url=settings.chat_base_url,
        model=settings.chat_model,
        api_key=settings.chat_api_key,
        temperature=settings.chat_temperature,
        settings=provider_settings,
    )


def embedding_provider_from_settings(settings: Settings | None = None) -> ResolvedProviderConfig:
    settings = settings or get_settings()
    if not settings.embedding_model or not settings.embedding_model.strip():
        raise ProviderResolutionError("embedding_model_missing", "PAPER_CLAW_EMBEDDING_MODEL is not set.")
    provider_settings: dict[str, object] = {
        "timeout": settings.embedding_timeout_seconds,
        "max_retries": settings.embedding_max_retries,
        "dimension": settings.embedding_dimension,
        "max_context_tokens": settings.embedding_max_context_tokens,
        "tokenizer_encoding": settings.tokenizer_encoding,
    }
    return ResolvedProviderConfig(
        id=0,
        name="settings-embedding",
        kind=ProviderKind.embedding.value,
        provider=ProviderName.openai_compatible.value,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key,
        settings=provider_settings,
    )


def _to_resolved_provider(provider_config: ProviderConfig) -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        id=provider_config.id,
        name=provider_config.name,
        kind=provider_config.kind,
        provider=provider_config.provider,
        base_url=provider_config.base_url,
        model=provider_config.model,
        api_key_ref=provider_config.api_key_ref,
        temperature=provider_config.temperature,
        settings=provider_config.settings_json or {},
    )
