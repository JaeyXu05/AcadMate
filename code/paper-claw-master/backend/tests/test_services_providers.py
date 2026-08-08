from __future__ import annotations

import pytest

from backend.db.models import ProviderConfig
from backend.db.types import ProviderKind, ProviderName
from backend.schemas import ProviderResolutionError
from backend.services.providers import chat_provider_from_settings, embedding_provider_from_settings, resolve_api_key, resolve_provider_config
from backend.settings import REPO_ROOT, Settings


def add_provider(session, **values):
    provider = ProviderConfig(**values)
    session.add(provider)
    session.flush()
    return provider


def test_resolve_default_provider(session):
    add_provider(
        session,
        name="fallback-chat",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        model="fallback-model",
        is_default=False,
    )
    default = add_provider(
        session,
        name="default-chat",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        base_url="https://example.invalid/v1",
        model="default-model",
        api_key_ref="env:PAPER_CLAW_TEST_KEY",
        temperature=0.1,
        is_default=True,
        settings_json={"timeout": 30},
    )

    resolved = resolve_provider_config(session, ProviderKind.chat.value)

    assert resolved.id == default.id
    assert resolved.name == "default-chat"
    assert resolved.base_url == "https://example.invalid/v1"
    assert resolved.settings == {"timeout": 30}


def test_resolve_explicit_provider_ignores_other_defaults(session):
    add_provider(
        session,
        name="default-chat",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        model="default-model",
        is_default=True,
    )
    explicit = add_provider(
        session,
        name="named-chat",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        model="named-model",
        is_default=False,
    )

    resolved = resolve_provider_config(session, ProviderKind.chat.value, name="named-chat")

    assert resolved.id == explicit.id
    assert resolved.model == "named-model"


def test_resolve_provider_ignores_disabled_configs(session):
    add_provider(
        session,
        name="disabled-chat",
        kind=ProviderKind.chat.value,
        provider=ProviderName.openai_compatible.value,
        enabled=False,
        is_default=True,
    )

    with pytest.raises(ProviderResolutionError) as exc_info:
        resolve_provider_config(session, ProviderKind.chat.value)

    assert exc_info.value.error.code == "provider_not_found"


def test_resolve_api_key_from_env(monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_TEST_KEY", "secret-value")

    assert resolve_api_key("env:PAPER_CLAW_TEST_KEY") == "secret-value"


def test_resolve_api_key_missing_env():
    with pytest.raises(ProviderResolutionError) as exc_info:
        resolve_api_key("env:PAPER_CLAW_MISSING_TEST_KEY")

    assert exc_info.value.error.code == "api_key_missing"


def test_settings_default_storage_root():
    settings = Settings()

    assert REPO_ROOT.name == "paper-claw"
    assert settings.data_dir == REPO_ROOT / "data"
    assert settings.storage_root == REPO_ROOT / "data" / "files"


def test_settings_load_model_environment(monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "openai:gpt-test")
    monkeypatch.setenv("PAPER_CLAW_CHAT_API_KEY", "chat-secret")
    monkeypatch.setenv("PAPER_CLAW_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("PAPER_CLAW_CHAT_RATE_LIMITER_REQUESTS_PER_SECOND", "1.5")
    monkeypatch.setenv("PAPER_CLAW_CHAT_RATE_LIMITER_CHECK_EVERY_N_SECONDS", "0.2")
    monkeypatch.setenv("PAPER_CLAW_CHAT_RATE_LIMITER_MAX_BUCKET_SIZE", "7")
    monkeypatch.setenv("PAPER_CLAW_CHAT_EXTRA_BODY", '{"thinking": {"type": "disabled"}}')
    monkeypatch.setenv("PAPER_CLAW_EMBEDDING_MODEL", "embed-test")
    monkeypatch.setenv("PAPER_CLAW_EMBEDDING_DIMENSION", "1536")
    monkeypatch.setenv("PAPER_CLAW_LOCAL_OCR_MODEL", "ocr-test")
    monkeypatch.setenv("PAPER_CLAW_LLAMA_PARSE_VERSION", "v2")

    settings = Settings()

    assert settings.chat_model == "openai:gpt-test"
    assert settings.chat_api_key == "chat-secret"
    assert settings.chat_base_url == "https://chat.example/v1"
    assert settings.chat_rate_limiter_requests_per_second == 1.5
    assert settings.chat_rate_limiter_check_every_n_seconds == 0.2
    assert settings.chat_extra_body["thinking"] == {"type": "disabled"}
    assert settings.chat_rate_limiter_max_bucket_size == 7
    assert settings.embedding_model == "embed-test"
    assert settings.embedding_dimension == 1536
    assert settings.local_ocr_model == "ocr-test"
    assert settings.llama_parse_version == "v2"


def test_settings_derived_providers(monkeypatch):
    monkeypatch.setenv("PAPER_CLAW_CHAT_MODEL", "openai:gpt-test")
    monkeypatch.setenv("PAPER_CLAW_CHAT_API_KEY", "chat-secret")
    monkeypatch.setenv("PAPER_CLAW_CHAT_EXTRA_BODY", '{"thinking": {"type": "disabled"}}')
    monkeypatch.setenv("PAPER_CLAW_EMBEDDING_MODEL", "embed-test")
    monkeypatch.setenv("PAPER_CLAW_EMBEDDING_API_KEY", "embed-secret")
    monkeypatch.setenv("PAPER_CLAW_EMBEDDING_DIMENSION", "12")
    settings = Settings()

    chat = chat_provider_from_settings(settings)
    embedding = embedding_provider_from_settings(settings)

    assert chat.name == "settings-chat"
    assert chat.model == "openai:gpt-test"
    assert chat.api_key == "chat-secret"
    assert chat.settings["extra_body"]["thinking"] == {"type": "disabled"}
    assert embedding.name == "settings-embedding"
    assert embedding.model == "embed-test"
    assert embedding.api_key == "embed-secret"
    assert embedding.settings["dimension"] == 12
