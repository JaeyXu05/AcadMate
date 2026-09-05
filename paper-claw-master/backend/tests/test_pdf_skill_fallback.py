from __future__ import annotations

import httpx
from openai import APIConnectionError

from backend.harness.contracts import RunCreate
from backend.harness.pdf_skill import PdfResearchAnalysis, _rerank_with_model
from backend.schemas import ResolvedProviderConfig


def test_pdf_rerank_falls_back_when_configured_gateway_is_unreachable(monkeypatch):
    provider = ResolvedProviderConfig(
        id=0,
        name="test-chat",
        kind="chat",
        provider="openai_compatible",
        base_url="https://unreachable.invalid/v1",
        model="test-model",
        api_key="test-key",
        temperature=0.0,
        settings={"timeout": 1, "max_retries": 0},
    )
    expected = PdfResearchAnalysis(
        document_summary="local fallback",
        research_directions=[],
        methods=[],
        decisions=[],
    )
    monkeypatch.setattr("backend.harness.pdf_skill.provider_for_run", lambda request: provider)
    monkeypatch.setattr(
        "backend.harness.pdf_skill.OpenAICompatibleChatModelAdapter.generate_text",
        lambda self, provider, messages: (_ for _ in ()).throw(
            APIConnectionError(request=httpx.Request("POST", provider.base_url or "https://invalid"))
        ),
    )
    monkeypatch.setattr(
        "backend.harness.pdf_skill._rerank_without_model",
        lambda request, passages, hits: expected,
    )

    result = _rerank_with_model(
        RunCreate(skill_id="pdf_analyze", message="analyze", context={}),
        [{"passage_id": "p1-1", "page": 1, "text": "multimodal model"}],
        [],
    )

    assert result is expected
