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
                    evidence=[
                        record.model_copy(deep=True)
                        for reference in _unique([
                            *candidate.evidence_refs,
                            *(match.evidence_refs if match else []),
                        ])
                        if (record := ledger.get(reference)) is not None
                        and record.candidate_id == candidate.candidate_id
                    ],
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
            query_contract=intent.query_contract,
            retrieval_attempts=list(state.retrieval_attempts),
            quality_status="PASS" if mentor_results else "NO_MATCH",
            coverage_report=dict(state.coverage_report),
            no_match_diagnostics=(
                {
                    key: state.coverage_report[key]
                    for key in (
                        "retrieved_candidate_count",
                        "qualified_candidate_count",
                        "zeroed_at_stage",
                        "missing_concepts",
                        "relaxation_options",
                    )
                    if key in state.coverage_report
                }
                if not mentor_results
                else {}
            ),
            relation_judgements=list(state.relation_judgements),
        )


def _contact_email(result: FinalMentorResult, intent: IntentPacket) -> str:
    mentor = result.candidate
    profile = intent.user_profile
    sender = profile.name or "[请填写姓名]"
    education = profile.education_level or "[请填写当前学历/年级]"
    background = "、".join(_email_phrases(profile.background, limit=5)) or "[请填写与导师方向相关的学习背景]"
    interests = "、".join(_email_phrases(mentor.research_topics, limit=3)) or "[请从已核验证据中选择研究方向]"
    publication = _short_email_text(mentor.publications[0]) if mentor.publications else "[请从已核验证据中选择论文]"
    return (
        f"主题：关于 {interests} 方向学习与研究机会的咨询\n\n"
        f"{mentor.mentor_name}老师您好：\n\n"
        f"我是{sender}，目前为{education}。我的相关背景包括：{background}。"
        f"我近期正在了解您公开的 {interests} 研究方向，并注意到公开资料中有《{publication}》。"
        "我希望先从公开资料开始学习，并进一步确认适合自己的研究切入点。\n\n"
        "如您方便，我希望进一步了解适合学生参与的研究准备与公开申请方式。"
        "本邮件未假设您的招生状态，具体信息以您的正式回复或公开通知为准。\n\n"
        f"感谢您的时间。\n{sender}"
    )


def _short_email_text(value: str, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit].rstrip("，。；、 ")


def _email_phrases(values: list[str], *, limit: int) -> list[str]:
    """Keep concise research labels and discard scraped recruitment boilerplate."""
    blocked = (
        "招生", "课程", "资料", "链接", "开源", "欢迎", "出版", "全套",
        "书籍", "研究生", "考核", "在线", "http://", "https://", "@",
    )
    phrases: list[str] = []
    for raw in values:
        text = _short_email_text(raw, limit=60)
        if not text or len(text) > 48 or any(marker in text for marker in blocked):
            continue
        if text not in phrases:
            phrases.append(text)
        if len(phrases) >= limit:
            break
    return phrases


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
