"""Model-backed, evidence-bounded research profile generation.

The model writes the readable assessment. Deterministic code owns the source
packet, evidence boundary and validation so a self-description can never be
silently presented as reviewed research experience.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from backend.db.repositories import AgentRunRepository
from backend.db.types import RunStatus, WorkflowName
from backend.harness.contracts import RunCreate, RunCreated
from backend.harness.provider_overrides import provider_for_run
from backend.integrations.llm.openai_compatible import OpenAICompatibleChatModelAdapter
from backend.settings import get_settings

ResearchLevel = Literal[
    "seen",
    "understood",
    "implemented",
    "reproduced",
    "debugged",
    "experimented",
    "innovated",
    "unknown",
]
EvidenceStatus = Literal["self_reported", "reviewed", "unknown"]


class ProfileCapability(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    level: ResearchLevel = "unknown"
    assessment: str = Field(min_length=1, max_length=320)
    evidence_status: EvidenceStatus = "unknown"
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class ProfileDirection(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    status: Literal["interest", "hypothesis", "supported", "unknown"] = "unknown"
    rationale: str = Field(min_length=1, max_length=320)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class ProfileGap(BaseModel):
    gap: str = Field(min_length=1, max_length=220)
    why_it_matters: str = Field(min_length=1, max_length=320)
    evidence_refs: list[str] = Field(default_factory=list, max_length=6)


class ProfileAction(BaseModel):
    action: str = Field(min_length=1, max_length=220)
    deliverable: str = Field(min_length=1, max_length=240)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=4)
    evidence_refs: list[str] = Field(default_factory=list, max_length=6)


class ResearchProfileDraft(BaseModel):
    summary: str = Field(min_length=30, max_length=900)
    capabilities: list[ProfileCapability] = Field(default_factory=list, max_length=10)
    directions: list[ProfileDirection] = Field(default_factory=list, max_length=8)
    gaps: list[ProfileGap] = Field(default_factory=list, max_length=6)
    next_actions: list[ProfileAction] = Field(min_length=1, max_length=5)
    missing_information: list[str] = Field(default_factory=list, max_length=8)


def start_profile_analyze(request: RunCreate, session: Session) -> RunCreated:
    snapshot, allowed_refs = _source_packet(request.context.profile, request.context.growth)
    if not snapshot["self_report"] and not any(snapshot["reviewed_growth"].values()):
        return _persist(
            session,
            request,
            status=RunStatus.waiting_for_user.value,
            review_status="NEED_MORE_INPUT",
            evidence_refs=[],
            artifact={
                "type": "research_profile",
                "error": "请先填写专业、研究方向、技能或个人简介；没有输入时不能生成科研画像。",
                "missing_information": ["专业或院系", "研究兴趣", "已有技能或科研经历"],
            },
        )

    try:
        draft, generation = _generate_profile(snapshot, allowed_refs, request)
        draft = _restrict_evidence(
            draft,
            set(allowed_refs),
            set(snapshot["reviewed_evidence_refs"]),
        )
        failed_checks = _review_profile(draft)
    except Exception as exc:  # noqa: BLE001 - persist an auditable model failure
        return _persist(
            session,
            request,
            status=RunStatus.failed.value,
            review_status="FAILED",
            evidence_refs=allowed_refs,
            artifact={
                "type": "research_profile",
                "error": f"科研画像模型生成失败：{type(exc).__name__}: {exc}",
                "generation": {"agent": "research_profile_agent", "status": "failed"},
            },
        )

    used_refs = _collect_output_refs(draft)
    review_status = "PASS" if not failed_checks else "REVISE"
    artifact = {
        "type": "research_profile",
        **draft.model_dump(mode="json"),
        "evidence_refs": used_refs,
        "generated_at": datetime.now(UTC).isoformat(),
        "generation": generation,
        "review_status": review_status,
        "failed_checks": failed_checks,
        "limitations": [
            "自述技能仅标记为 self_reported，不等同于通过审核的科研能力。",
            "平台未记录的线下经历保持 unknown，不由模型补写。",
        ],
    }
    return _persist(
        session,
        request,
        status=RunStatus.succeeded.value,
        review_status=review_status,
        evidence_refs=used_refs,
        artifact=artifact,
    )


def profile_analyze_result(run_id: int, session: Session) -> RunCreated:
    from backend.db.models import AgentRun

    run = session.get(AgentRun, run_id)
    if run is None or run.workflow != WorkflowName.profile_analyze.value:
        raise ValueError("profile_analyze AgentRun not found")
    output = dict(run.output_json or {})
    return RunCreated(
        run_id=str(run.id),
        skill_id="profile_analyze",
        status=run.status,
        review_status=str(output.get("review_status") or "PENDING"),
        evidence_refs=list(output.get("evidence_refs") or []),
        artifact=output.get("artifact"),
    )


def _source_packet(profile: dict[str, Any], growth: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    self_report: list[dict[str, Any]] = []
    allowed: list[str] = []
    reviewed_refs: list[str] = []
    profile_fields = {
        "education": [profile.get("grade"), profile.get("major")],
        "interests": profile.get("interests"),
        "skills": profile.get("skills"),
        "bio": profile.get("bio"),
    }
    for field, raw in profile_fields.items():
        value = _compact(raw)
        if not _has_meaningful_value(value):
            continue
        ref = f"profile:{field}"
        allowed.append(ref)
        self_report.append({"source_ref": ref, "field": field, "value": value, "evidence_status": "self_reported"})

    reviewed_growth: dict[str, list[dict[str, Any]]] = {}
    for section in (
        "matched_mentors",
        "read_papers",
        "verified_experiences",
        "artifacts",
        "research_tasks",
        "direction_hypotheses",
    ):
        rows: list[dict[str, Any]] = []
        values = growth.get(section) or []
        for index, raw in enumerate(values[:10] if isinstance(values, list) else []):
            if not isinstance(raw, dict):
                continue
            item_id = str(raw.get("id") or raw.get("candidate_id") or raw.get("paper_id") or index + 1)
            source_ref = f"growth:{section}:{item_id}"
            refs = [str(ref) for ref in raw.get("evidence_refs") or [] if str(ref)]
            allowed.extend([source_ref, *refs])
            is_reviewed = raw.get("review_status") == "PASS" or bool(refs)
            if is_reviewed:
                reviewed_refs.extend([source_ref, *refs])
            rows.append(
                {
                    "source_ref": source_ref,
                    "record": _compact(raw),
                    "evidence_refs": refs,
                    "evidence_status": "reviewed" if is_reviewed else "platform_record",
                }
            )
        reviewed_growth[section] = rows

    directions = _compact(growth.get("directions") or [])
    if directions:
        allowed.append("growth:directions")
        reviewed_growth["directions"] = [{"source_ref": "growth:directions", "record": directions, "evidence_status": "platform_record"}]
    return {
        "self_report": self_report,
        "reviewed_growth": reviewed_growth,
        "reviewed_evidence_refs": list(dict.fromkeys(reviewed_refs)),
    }, list(dict.fromkeys(allowed))


def _generate_profile(
    snapshot: dict[str, Any],
    allowed_refs: list[str],
    request: RunCreate,
) -> tuple[ResearchProfileDraft, dict[str, Any]]:
    settings = get_settings()
    provider = provider_for_run(request).model_copy(deep=True)
    provider.settings = {
        **provider.settings,
        "max_tokens": min(settings.chat_max_tokens, 1800),
        # The DeepSeek-class model can spend 20-60s producing a structured
        # profile.  The old 22s cap turned valid slow responses into false
        # timeouts, so keep the provider-configured budget (120s by default)
        # instead of inventing a shorter local ceiling.
        "timeout": float(provider.settings.get("timeout") or settings.chat_timeout_seconds),
        "max_retries": 0,
        "response_format": {"type": "json_object"},
        # DeepSeek v4 defaults to emitting a long reasoning_content before the
        # JSON; when reasoning exhausts the token budget, content stays empty
        # and structural validation fails. The profile task is a bounded JSON
        # generation, so disable hidden thinking for a stable structured reply.
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    system = """
你是科研画像 Agent。你的任务是把用户自述与平台已审核记录组织成自然、克制、可行动的中文科研画像。

硬约束：
1. 只能使用 source_packet；禁止补写学校、项目、论文、奖项、技能熟练度或研究成果。
2. 严格区分 self_reported 与 reviewed。自述技能可以描述为“用户填写”，不能写成已验证能力。
3. 能力层级只允许 seen、understood、implemented、reproduced、debugged、experimented、innovated、unknown。证据不足时必须选 unknown，不能向上猜测。
4. 所有 evidence_refs 必须来自 allowed_evidence_refs。没有依据时用空数组并在 missing_information 说明。
5. summary 要像导师给学生的简洁反馈，不要复述字段，不要使用“根据您提供的信息”等模板套话。
6. gaps 与 next_actions 要具体，行动必须包含交付物和可核验验收标准，禁止“多读论文、继续学习、提升能力”等空话。
7. 输出中文，不输出思维链，只返回符合 required_json_schema 的 JSON 对象，不要 Markdown 代码围栏。
""".strip()
    payload = {
        "allowed_evidence_refs": allowed_refs,
        "source_packet": snapshot,
        "required_json_schema": ResearchProfileDraft.model_json_schema(),
    }
    raw = OpenAICompatibleChatModelAdapter().generate_text(
        provider,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "请生成科研画像。\n" + json.dumps(payload, ensure_ascii=False)},
        ],
    )
    draft = _parse_json_model(raw)
    return draft, {
        "agent": "research_profile_agent",
        "status": "completed",
        "config_source": "environment_chat_config",
        "provider": provider.provider,
        "model": provider.model,
        "base_host": urlparse(provider.base_url or "").hostname,
        "timeout_seconds": provider.settings["timeout"],
        "max_retries": 0,
    }


def _parse_json_model(raw: str) -> ResearchProfileDraft:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        return ResearchProfileDraft.model_validate_json(cleaned)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"科研画像模型输出未通过结构校验：{exc}") from exc


def _restrict_evidence(
    draft: ResearchProfileDraft,
    allowed: set[str],
    reviewed: set[str],
) -> ResearchProfileDraft:
    cleaned = draft.model_copy(deep=True)
    for item in [*cleaned.capabilities, *cleaned.directions, *cleaned.gaps, *cleaned.next_actions]:
        item.evidence_refs = list(dict.fromkeys(ref for ref in item.evidence_refs if ref in allowed))
    for capability in cleaned.capabilities:
        if not capability.evidence_refs:
            capability.level = "unknown"
            capability.evidence_status = "unknown"
        elif any(ref in reviewed for ref in capability.evidence_refs):
            capability.evidence_status = "reviewed"
        elif all(ref.startswith("profile:") for ref in capability.evidence_refs):
            capability.level = "unknown"
            capability.evidence_status = "self_reported"
        else:
            capability.level = "unknown"
            capability.evidence_status = "unknown"
    return cleaned


def _review_profile(draft: ResearchProfileDraft) -> list[str]:
    failed: list[str] = []
    if not draft.next_actions:
        failed.append("next_actions_missing")
    if any(not item.acceptance_criteria for item in draft.next_actions):
        failed.append("acceptance_criteria_missing")
    if not draft.missing_information and any(item.level == "unknown" for item in draft.capabilities):
        failed.append("unknown_without_missing_information")
    return failed


def _collect_output_refs(draft: ResearchProfileDraft) -> list[str]:
    return list(dict.fromkeys(
        ref
        for item in [*draft.capabilities, *draft.directions, *draft.gaps, *draft.next_actions]
        for ref in item.evidence_refs
    ))


def _compact(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return str(value)[:240]
    if isinstance(value, dict):
        return {str(key): _compact(item, depth + 1) for key, item in list(value.items())[:16]}
    if isinstance(value, list):
        return [_compact(item, depth + 1) for item in value[:12]]
    if isinstance(value, str):
        return value.strip()[:700]
    return value


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_meaningful_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    return True


def _persist(
    session: Session,
    request: RunCreate,
    *,
    status: str,
    review_status: str,
    evidence_refs: list[str],
    artifact: dict[str, Any],
) -> RunCreated:
    run = AgentRunRepository(session).create(
        WorkflowName.profile_analyze.value,
        status=status,
        input_json={"message": request.message, "metadata": {"harness_skill_id": "profile_analyze"}},
        output_json={"review_status": review_status, "evidence_refs": evidence_refs, "artifact": artifact},
        error_message=str(artifact.get("error") or "") or None,
    )
    session.commit()
    return RunCreated(
        run_id=str(run.id),
        skill_id="profile_analyze",
        status=status,
        review_status=review_status,
        evidence_refs=evidence_refs,
        artifact=artifact,
    )
