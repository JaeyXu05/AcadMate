from __future__ import annotations

import json

from backend.harness.contracts import RunCreate
from backend.harness.profile_skill import _generate_profile


def test_profile_generation_avoids_a_second_visible_wait_on_gateway_failure(monkeypatch):
    captured = {}

    def fake_generate_text(self, provider, messages):
        captured["provider"] = provider
        return json.dumps(
            {
                "summary": "用户已经形成计算机视觉兴趣，但仍需要用可复现实验补充独立研究证据。",
                "capabilities": [],
                "directions": [],
                "gaps": [],
                "next_actions": [
                    {
                        "action": "复现一个公开基线",
                        "deliverable": "代码与实验记录",
                        "acceptance_criteria": ["固定随机种子运行成功"],
                        "evidence_refs": [],
                    }
                ],
                "missing_information": ["尚无实验产物证据"],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(
        "backend.harness.profile_skill.OpenAICompatibleChatModelAdapter.generate_text",
        fake_generate_text,
    )
    request = RunCreate(
        message="生成科研画像",
        context={"profile": {"major": "计算机科学"}},
        llm_model="probe-model",
        llm_base_url="http://model.invalid/v1",
        llm_api_key="probe-secret",
    )

    _generate_profile(
        {"self_report": [{"source_ref": "profile:major", "value": "计算机科学"}], "reviewed_growth": {}, "reviewed_evidence_refs": []},
        ["profile:major"],
        request,
    )

    assert captured["provider"].model == "probe-model"
    assert captured["provider"].base_url == "http://model.invalid/v1"
    assert captured["provider"].api_key == "probe-secret"
    assert captured["provider"].settings["max_retries"] == 0
