from __future__ import annotations

from backend.mentor_workflow.evidence import EvidenceLedger
from backend.mentor_workflow.schemas import (
    FinalMentorResult,
    FinalResult,
    IntentPacket,
    MentorGoal,
    ReviewStatus,
    WorkflowState,
)


class ResultComposerAgent:
    name = "result_composer_agent"

    def run(self, state: WorkflowState) -> FinalResult:
        if (
            state.review_decision is None
            or state.review_decision.status != ReviewStatus.pass_
        ):
            raise ValueError("Result composition requires a PASS review decision")
        if state.intent is None:
            raise ValueError("Result composition requires an IntentPacket")
        intent = state.intent
        ledger = EvidenceLedger(state.evidence_ledger)
        matches = {match.candidate_id: match for match in state.match_results}
        ordered_candidates = sorted(
            state.candidates,
            key=lambda candidate: (
                matches[candidate.candidate_id].ranking_position
                if candidate.candidate_id in matches
                else len(state.candidates) + 1,
                candidate.candidate_id,
            ),
        )
        mentor_results: list[FinalMentorResult] = []
        for candidate in ordered_candidates:
            invalid_refs = ledger.validate_candidate(candidate)
            if invalid_refs:
                raise ValueError(
                    f"Composer refused invalid evidence references: {invalid_refs}"
                )
            match = matches.get(candidate.candidate_id)
            if match is not None:
                invalid_refs = ledger.validate_match(match)
                if invalid_refs:
                    raise ValueError(
                        f"Composer refused invalid match evidence references: {invalid_refs}"
                    )
            mentor_results.append(
                FinalMentorResult(
                    candidate=candidate.model_copy(deep=True),
                    match=match.model_copy(deep=True) if match else None,
                )
            )
        evidence_refs = _unique(
            [
                reference
                for result in mentor_results
                for reference in result.candidate.evidence_refs
            ]
            + [
                reference
                for result in mentor_results
                if result.match
                for reference in result.match.evidence_refs
            ]
        )
        risks = _unique(
            [
                risk
                for result in mentor_results
                if result.match
                for risk in result.match.risks
            ]
        )
        uncertainty = _unique(
            [
                item
                for result in mentor_results
                if result.match
                for item in result.match.uncertainty
            ]
        )
        comparison = [
            f"#{result.match.ranking_position} {result.candidate.mentor_name}: {result.match.total_score:.2f}"
            for result in mentor_results
            if result.match is not None
        ]
        suggestions = _unique(intent.research_topics)
        email_draft = None
        if intent.goal == MentorGoal.generate_contact_email:
            if not mentor_results:
                raise ValueError(
                    "No approved mentor is available for contact email generation"
                )
            email_draft = _contact_email(mentor_results[0], intent)
        return FinalResult(
            trace_id=state.trace_id,
            goal=intent.goal,
            mentors=mentor_results,
            comparison_summary=comparison,
            research_direction_suggestions=suggestions,
            contact_email_draft=email_draft,
            evidence_refs=evidence_refs,
            risks=risks,
            uncertainty=uncertainty,
        )


def _contact_email(result: FinalMentorResult, intent: IntentPacket) -> str:
    mentor = result.candidate
    profile = intent.user_profile
    sender = profile.name or "[请填写姓名]"
    education = profile.education_level or "[请填写当前学历/年级]"
    background = "、".join(profile.background) or "[请填写与导师方向相关的学习背景]"
    interests = "、".join(mentor.research_topics) or "[请从已核验证据中选择研究方向]"
    publication = (
        mentor.publications[0] if mentor.publications else "[请从已核验证据中选择论文]"
    )
    return (
        f"主题：关于 {interests} 方向学习与研究机会的咨询\n\n"
        f"{mentor.mentor_name}老师您好：\n\n"
        f"我是{sender}，目前为{education}。我的相关背景包括：{background}。"
        f"我关注您已核验资料中的 {interests} 方向，其中包含《{publication}》。"
        "如果该资料与目前方向仍相关，我会先认真阅读并做好基础准备。\n\n"
        "如您方便，我希望进一步了解适合学生参与的研究准备与公开申请方式。"
        "本邮件未假设您的招生状态，具体信息以您的正式回复或公开通知为准。\n\n"
        f"感谢您的时间。\n{sender}"
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
