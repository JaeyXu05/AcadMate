from __future__ import annotations

from backend.harness.contracts import RunCreate, SharedContext
from backend.harness.productivity_skill import (
    PlanCoachDraft,
    PlanMilestone,
    ProgressReportDraft,
    ReportAction,
    _humanize_report_draft,
    _fallback_report_draft,
    _normalize_report_action_dates,
    _render_progress_markdown,
    _review_report,
    _plan_snapshot,
    _parse_json_model,
    start_plan_coach,
)


def test_plan_snapshot_includes_bounded_personal_harness_summary():
    snapshot, refs = _plan_snapshot([], {}, {}, {
        "reviewed_artifacts": [{"evidence_refs": ["run:42"], "summary": "已阅读推荐系统论文"}],
    })
    assert snapshot["个人科研历史摘要"]["reviewed_artifacts"][0]["summary"] == "已阅读推荐系统论文"
    assert "run:42" in refs


def test_plan_output_normalizes_common_model_shape_drift():
    draft = _parse_json_model(
        """{
          "planning_summary": "当前计划目标较宽，建议先收敛为一次可验收的研究工作时段，再依据记录调整后续安排。",
          "capacity_assessment": "当前时间预算适合先完成一个 60 分钟的范围界定与资料整理阶段。",
          "personalization_basis": "使用了当前开放计划的时间预算与研究主题。",
          "milestones": [{
            "sequence": 1,
            "source_plan_id": "fallback",
            "title": "确定本阶段范围",
            "objective": "从当前计划中选择一个主题并写明本阶段边界。",
            "deliverable": "一份包含研究范围和关键问题的结构化笔记。",
            "acceptance_criteria": "计划文档包含明确范围和可验证的验收标准。",
            "priority": "medium",
            "estimated_minutes": 60,
            "start_at": null,
            "due_at": null,
            "reminder_at": null,
            "rationale": "先限定范围可以避免在一次工作时段中并行处理过多主题。",
            "evidence_refs": "plan:7"
          }],
          "risks": "当前资料不足时应避免把计划误写为已完成成果。"
        }""",
        PlanCoachDraft,
    )

    assert draft.personalization_basis == ["使用了当前开放计划的时间预算与研究主题。"]
    assert draft.milestones[0].source_plan_id is None
    assert draft.milestones[0].acceptance_criteria == ["计划文档包含明确范围和可验证的验收标准。"]
    assert draft.milestones[0].evidence_refs == ["plan:7"]
    assert draft.risks == ["当前资料不足时应避免把计划误写为已完成成果。"]


def test_report_humanizes_internal_terms_and_rejects_past_action_dates():
    draft = ProgressReportDraft(
        executive_summary="input_snapshot 显示本周期只有一项计划，尚未记录可核验的完成结果，因此不能据此推断已经完成科研工作。",
        progress_assessment="plan_records 中存在开放计划，但没有完成证据；下一步应围绕该计划形成最小可验收阶段。",
        next_actions=[
            ReportAction(
                action="完成当前计划的最小可验收阶段",
                rationale="避免在资料不足时扩展到未记录方向。",
                deliverable="一份结构化学习记录",
                acceptance_criteria=["限定一个主题", "记录三条要点"],
                target_date="2026-06-22",
            )
        ],
    )

    cleaned = _normalize_report_action_dates(
        _humanize_report_draft(draft),
        period_end="2026-09-03T23:59",
        current_time="2026-09-03T12:40",
    )
    markdown = _render_progress_markdown("科研日报", "daily", {
        "activity_events": 0,
        "dialogue_turns": 0,
        "completed_plans": 0,
        "pending_plans": 1,
        "matched_mentors": 0,
        "read_papers": 0,
    }, cleaned)

    assert "input_snapshot" not in markdown
    assert "plan_records" not in markdown
    assert "2026-09-03" in markdown
    assert "internal_field_leak" not in _review_report(markdown, cleaned)


def test_plan_coach_emits_applyable_milestones_from_model_draft(session, monkeypatch):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return PlanCoachDraft(
            planning_summary="当前总目标覆盖多个主题，60 分钟不足以完成，建议先完成推荐系统学习范围定义。",
            capacity_assessment="计划时间预算为 60 分钟，当前目标至少应拆分为多个阶段。",
            personalization_basis=["使用了当前开放计划的主题、截止时间和时间预算"],
            milestones=[
                PlanMilestone(
                    sequence=1,
                    source_plan_id=7,
                    title="确定推荐系统学习范围",
                    objective="只选择一个推荐系统基础主题完成第一轮学习。",
                    deliverable="一页推荐系统概念与问题清单。",
                    acceptance_criteria=["限定一个主题", "列出三条关键概念"],
                    priority="high",
                    estimated_minutes=45,
                    rationale="先收敛范围，避免将多个研究方向堆入一次工作时段。",
                    evidence_refs=["plan:7"],
                )
            ],
        ), {"agent": "plan_coach", "status": "completed", "model": "test-model"}

    monkeypatch.setattr("backend.harness.productivity_skill._generate_plan_draft", fake_generate)
    result = start_plan_coach(
        RunCreate(
            skill_id="plan_coach",
            message="请拆解当前科研计划",
            context=SharedContext(
                current_time="2026-09-03T12:40",
                timezone="Asia/Shanghai",
                plans=[{
                    "id": 7,
                    "title": "科研计划",
                    "description": "推荐系统、图推荐、EEG 与世界模型",
                    "status": "todo",
                    "priority": "high",
                    "estimated_minutes": 60,
                    "due_at": "2026-09-04T12:40",
                    "email_reminder": 1,
                }],
            ),
        ),
        session,
    )

    assert captured["current_time"] == "2026-09-03T12:40"
    artifact = result.artifact or {}
    assert artifact["generation"]["status"] == "completed"
    assert artifact["plan_drafts"][0]["deliverable"] == "一页推荐系统概念与问题清单。"
    assert artifact["plan_drafts"][0]["email_reminder"] == 1
    assert artifact["plan_drafts"][0]["reminder_at"] < artifact["plan_drafts"][0]["start_at"]


def test_report_fallback_keeps_plan_context_without_internal_field_leak():
    draft = _fallback_report_draft(
        [{
            "id": 1,
            "title": "科研计划",
            "status": "todo",
            "estimated_minutes": 60,
            "due_at": "2026-09-04T12:40",
        }],
        {},
        current_time="2026-09-03T12:40",
    )
    markdown = _render_progress_markdown("科研日报", "daily", {
        "activity_events": 0,
        "dialogue_turns": 0,
        "completed_plans": 0,
        "pending_plans": 1,
        "matched_mentors": 0,
        "read_papers": 0,
    }, draft)

    assert "科研计划" in markdown
    assert "plan:1" not in markdown
    assert "input_snapshot" not in markdown
