"""Deterministic research-task and direction-explore Skills."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.db.repositories import AgentRunRepository
from backend.db.types import RunStatus, WorkflowName
from backend.harness.contracts import RunCreate, RunCreated
from backend.harness.runtime import suggest_next_skill


def start_direction_explore(request: RunCreate, session: Session) -> RunCreated:
    growth = request.context.growth or {}
    matched = [item for item in growth.get("matched_mentors") or [] if isinstance(item, dict)]
    if not matched:
        return _persist(
            session,
            WorkflowName.direction_explore.value,
            "direction_explore",
            RunStatus.waiting_for_user.value,
            "NEED_MORE_INPUT",
            request,
            [],
            {"error": "还没有通过审核的匹配导师，无法形成有证据的方向假设。"},
        )
    hypotheses = []
    evidence_refs: list[str] = []
    for mentor in matched:
        for tag in mentor.get("tags") or []:
            refs = [str(item) for item in (mentor.get("evidence_refs") or []) if str(item)]
            if not refs:
                continue
            evidence_refs.extend(refs)
            hypotheses.append(
                {
                    "id": f"direction:{str(tag).strip().lower()}",
                    "direction": tag,
                    "status": "supported",
                    "mentor_id": mentor.get("id"),
                    "evidence_refs": refs,
                }
            )
    evidence_refs = list(dict.fromkeys(evidence_refs))
    review = "PASS" if hypotheses else "REVISE"
    return _persist(
        session,
        WorkflowName.direction_explore.value,
        "direction_explore",
        RunStatus.succeeded.value,
        review,
        request,
        evidence_refs,
        {
            "type": "direction_explore",
            "direction_hypotheses": hypotheses,
            "research_tasks": [
                {
                    "id": f"research-question:{item.get('mentor_id')}",
                    "title": f"把方向「{item.get('direction')}」写成可验证研究问题",
                    "status": "pending",
                    "acceptance_criteria": ["至少引用 2 个论文证据片段", "写出假设与最小验证步骤"],
                    "evidence_refs": item.get("evidence_refs") or [],
                }
                for item in hypotheses[:3]
            ] if review == "PASS" else [],
        },
    )


def start_research_task(request: RunCreate, session: Session) -> RunCreated:
    growth = request.context.growth or {}
    task_id = request.context.task_id or ""
    pending = [
        item
        for item in growth.get("research_tasks") or []
        if isinstance(item, dict) and item.get("status") in {"pending", "in_progress"}
    ]
    task = next((item for item in pending if str(item.get("id") or "") == task_id), pending[0] if pending else None)
    allowed = {
        str(ref)
        for paper in growth.get("read_papers") or []
        if isinstance(paper, dict)
        for ref in (paper.get("evidence_refs") or [])
        if str(ref)
    }
    cited = [
        token
        for token in _cited_refs(request.message)
        if token in allowed
    ]
    if not allowed:
        return _persist(
            session,
            WorkflowName.research_task.value,
            "research_task",
            RunStatus.waiting_for_user.value,
            "NEED_MORE_INPUT",
            request,
            [],
            {"error": "还没有通过审核的论文证据，无法执行研究任务。"},
        )
    if len(cited) < 2 or len(request.message.strip()) < 12:
        return _persist(
            session,
            WorkflowName.research_task.value,
            "research_task",
            RunStatus.succeeded.value,
            "REVISE",
            request,
            cited,
            {
                "error": "研究任务需要至少引用 2 条已读论文 Evidence，并写出可验证问题。",
                "retry": {"skill_id": "research_task", "target": "paper_evidence"},
            },
        )
    completed = {
        **(task or {}),
        "id": (task or {}).get("id") or f"research-question:{request.context.candidate_id or 'open'}",
        "status": "completed",
        "statement": request.message.strip(),
        "evidence_refs": cited,
    }
    return _persist(
        session,
        WorkflowName.research_task.value,
        "research_task",
        RunStatus.succeeded.value,
        "PASS",
        request,
        cited,
        {"type": "research_task", "research_tasks": [completed]},
    )


def skill_result(run_id: int, session: Session, workflow: str, skill_id: str) -> RunCreated:
    from backend.db.models import AgentRun

    run = session.get(AgentRun, run_id)
    if run is None or run.workflow != workflow:
        raise ValueError(f"{skill_id} AgentRun not found")
    output = dict(run.output_json or {})
    return RunCreated(
        run_id=str(run.id),
        skill_id=skill_id,
        status=run.status,
        review_status=str(output.get("review_status") or "PENDING"),
        suggested_next_skill=output.get("suggested_next_skill"),
        evidence_refs=list(output.get("evidence_refs") or []),
        artifact=output.get("artifact"),
    )


def _cited_refs(message: str) -> list[str]:
    import re

    return re.findall(r"(paper_chunk:\d+:\d+|ustc_[a-z0-9_]+|document:[^\s,，]+)", message)


def _persist(
    session: Session,
    workflow: str,
    skill_id: str,
    status: str,
    review_status: str,
    request: RunCreate,
    evidence_refs: list[str],
    artifact: dict[str, Any],
) -> RunCreated:
    run = AgentRunRepository(session).create(
        workflow,
        status=status,
        input_json={"message": request.message, "metadata": {"harness_skill_id": skill_id}},
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
        skill_id=skill_id,
        status=status,
        review_status=review_status,
        suggested_next_skill=(
            suggest_next_skill(request.context.growth) if review_status == "PASS" else skill_id
        ),
        evidence_refs=evidence_refs,
        artifact=artifact,
    )
