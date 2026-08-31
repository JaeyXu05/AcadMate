"""Email compose Skill: wrap ResultComposerAgent on an approved mentor_match thread."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.db.repositories import AgentRunRepository
from backend.db.types import RunStatus, WorkflowName
from backend.harness.contracts import RunCreate, RunCreated
from backend.harness.runtime import suggest_next_skill
from backend.mentor_workflow.schemas import MentorGoal, MentorWorkflowSupplement


def start_email_compose(request: RunCreate, session: Session, orchestrator, commit, run_id_of) -> RunCreated:
    growth = request.context.growth or {}
    candidate_id = request.context.candidate_id or ""
    trace_id = request.context.resume_trace_id or ""
    matched = [
        item
        for item in growth.get("matched_mentors") or []
        if isinstance(item, dict)
        and str(item.get("candidate_id") or item.get("id") or "") == candidate_id
        and str(item.get("review_status") or "PASS") == "PASS"
    ]
    evidence_refs = [
        str(ref)
        for item in matched
        for ref in (item.get("evidence_refs") or [])
        if str(ref)
    ]
    if not candidate_id:
        return _persist(
            session,
            request,
            RunStatus.waiting_for_user.value,
            "NEED_MORE_INPUT",
            [],
            {"error": "请指定导师 candidate_id", "retry": {"skill_id": "email_compose", "target": "mentor_match"}},
        )
    if not matched:
        return _persist(
            session,
            request,
            RunStatus.waiting_for_user.value,
            "NEED_MORE_INPUT",
            [],
            {
                "error": "尚未完成该导师的 Review PASS 匹配，无法生成初次联系邮件。",
                "retry": {"skill_id": "mentor_match", "target": "mentor_match"},
            },
        )
    if not trace_id:
        return _persist(
            session,
            request,
            RunStatus.waiting_for_user.value,
            "NEED_MORE_INPUT",
            evidence_refs,
            {
                "error": "缺少已通过审核的 mentor_match trace_id，请先完成导师匹配。",
                "retry": {"skill_id": "mentor_match", "target": "mentor_match"},
            },
        )

    try:
        state = orchestrator.supplement(
            trace_id,
            MentorWorkflowSupplement(
                message=request.message or "生成联系邮件",
                goal=MentorGoal.generate_contact_email,
            ),
        )
        commit()
    except Exception as exc:
        return _persist(
            session,
            request,
            RunStatus.failed.value,
            "FAILED",
            evidence_refs,
            {"error": f"Composer 失败：{exc}", "retry": {"skill_id": "email_compose", "target": "result_composer"}},
            trace_id=trace_id,
            mentor_run_id=run_id_of(trace_id),
        )

    draft = (
        state.final_result.contact_email_draft
        if state.final_result is not None
        else None
    )
    if not draft:
        return _persist(
            session,
            request,
            RunStatus.succeeded.value,
            "REVISE",
            evidence_refs,
            {
                "type": "contact_email",
                "candidate_id": candidate_id,
                "error": "Composer 未产出可审核草稿",
                "retry": {"skill_id": "email_compose", "target": "result_composer"},
            },
            trace_id=trace_id,
            mentor_run_id=run_id_of(trace_id),
        )
    subject, body = _split_draft(draft)
    if state.final_result is not None:
        evidence_refs = list(dict.fromkeys([
            *evidence_refs,
            *state.final_result.evidence_refs,
        ]))
    return _persist(
        session,
        request,
        RunStatus.succeeded.value,
        "PASS",
        evidence_refs,
        {
            "type": "contact_email",
            "candidate_id": candidate_id,
            "subject": subject,
            "body": body,
            "draft": draft,
            "approved": False,
        },
        trace_id=trace_id,
        mentor_run_id=run_id_of(trace_id),
    )


def email_compose_result(run_id: int, session: Session) -> RunCreated:
    from backend.db.models import AgentRun

    run = session.get(AgentRun, run_id)
    if run is None or run.workflow != WorkflowName.email_compose.value:
        raise ValueError("email AgentRun not found")
    output = dict(run.output_json or {})
    return RunCreated(
        run_id=str(run.id),
        skill_id="email_compose",
        status=run.status,
        trace_id=str((run.input_json or {}).get("metadata", {}).get("resume_trace_id") or "") or None,
        review_status=str(output.get("review_status") or "PENDING"),
        suggested_next_skill=output.get("suggested_next_skill"),
        evidence_refs=list(output.get("evidence_refs") or []),
        artifact=output.get("artifact"),
    )


def _persist(
    session: Session,
    request: RunCreate,
    status: str,
    review_status: str,
    evidence_refs: list[str],
    artifact: dict[str, Any],
    *,
    trace_id: str | None = None,
    mentor_run_id: int | None = None,
) -> RunCreated:
    run = AgentRunRepository(session).create(
        WorkflowName.email_compose.value,
        status=status,
        input_json={
            "message": request.message,
            "metadata": {
                "harness_skill_id": "email_compose",
                "candidate_id": request.context.candidate_id,
                "resume_trace_id": trace_id or request.context.resume_trace_id,
                "mentor_run_id": mentor_run_id,
            },
        },
        output_json={
            "review_status": review_status,
            "evidence_refs": evidence_refs,
            "suggested_next_skill": suggest_next_skill(request.context.growth),
            "artifact": artifact,
        },
        error_message=str(artifact.get("error") or "") or None,
    )
    session.commit()
    return RunCreated(
        run_id=str(run.id),
        skill_id="email_compose",
        status=status,
        trace_id=trace_id or request.context.resume_trace_id,
        review_status=review_status,
        suggested_next_skill=(
            suggest_next_skill(request.context.growth) if review_status == "PASS" else "email_compose"
        ),
        evidence_refs=evidence_refs,
        artifact=artifact,
    )


def _split_draft(draft: str) -> tuple[str, str]:
    text = draft.strip()
    if text.startswith("主题：") or text.startswith("主题:"):
        first, _, rest = text.partition("\n")
        subject = first.split("：", 1)[-1].split(":", 1)[-1].strip()
        return subject, rest.strip()
    return "研究生申请咨询", text
