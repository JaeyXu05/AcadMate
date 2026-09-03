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
            relation_judgements=list(state.relation_judgements),
        )


def _contact_email(result: FinalMentorResult, intent: IntentPacket) -> str:
    mentor = result.candidate
    profile = intent.user_profile
    sender = (profile.name or "").strip()
    education = (profile.education_level or "").strip()
    background = _email_phrases(profile.background, limit=5)
    skills = _email_phrases(profile.skills, limit=5)
    experiences = _email_phrases(profile.experiences, limit=3)
    interests = _email_phrases(mentor.research_topics, limit=4)
    direction = "、".join(interests) or "相关研究"
    publication = _short_email_text(mentor.publications[0]) if mentor.publications else ""
    understanding = _article_understanding(publication, interests, mentor.methods)

    personal_lines: list[str] = []
    if sender or education:
        identity = []
        if sender:
            identity.append(f"我是{sender}")
        if education:
            identity.append(f"目前为{education}")
        personal_lines.append("，".join(identity) + "。")
    if background:
        personal_lines.append(f"我的相关学习背景包括：{'、'.join(background)}。")
    if skills:
        personal_lines.append(f"目前我重点积累的能力包括：{'、'.join(skills)}。")
    if experiences:
        personal_lines.append(f"我曾接触或完成过{'、'.join(experiences)}，希望将这些积累继续用于严谨的科研训练。")
    if not sender and not education:
        personal_lines.insert(
            0,
            "【个人信息】（请填写姓名、学校、年级/专业，以及与申请研究相关的学习背景、技能或经历。）",
        )

    research_lines = [
        f"我近期持续关注您公开的{direction}研究，希望进一步理解这些方向背后的关键问题、研究方法与实际应用。"
    ]
    if publication:
        research_lines.append(
            f"我尤其关注您的代表性论文《{publication}》。{understanding}"
            "这让我认识到，严谨的问题建模、可靠的数据或实验设计，以及方法在真实科研场景中的可复现性同样重要。"
        )
    else:
        research_lines.append(
            "【论文与具体想法】（请补充导师的一篇代表性论文，并写下你对其研究问题、方法或结果的理解，以及希望进一步学习的问题。）"
        )
    research_lines.append(
        f"结合我对{direction}的兴趣，我希望从基础阅读、复现实验和细致的数据整理等工作做起，逐步形成对该研究方向的深入理解。"
    )
    research_lines.append(
        "如果您目前有适合学生参与的科研、实习或研究生申请机会，我非常希望有机会进入您的课题组/实验室，"
        "在您的指导下认真学习并承担力所能及的任务。若目前暂无合适名额，也恳请您在方便时指点我应当补充哪些知识与准备。"
    )

    sections = [
        f"主题：关于{direction}方向学习与研究机会的咨询",
        f"{mentor.mentor_name}老师您好：",
        *personal_lines,
        *research_lines,
        "本邮件未假设您的招生状态，具体信息以您的正式回复或公开通知为准。",
        "感谢您在百忙之中阅读这封邮件，期待有机会向您进一步请教。",
        "此致",
        "敬礼",
        sender or "【个人信息】",
    ]
    return "\n\n".join(sections)


def _article_understanding(title: str, topics: list[str], methods: list[str]) -> str:
    """用公开题目和已核验方向写出克制的理解，避免虚构论文细节。"""
    if not title:
        return ""
    lowered = title.lower()
    topic_text = "与".join(topics[:2]) or "相关科学问题"
    method_text = "、".join(_email_phrases(methods, limit=2))
    if "deep learning potential" in lowered or "deep potential" in lowered:
        return "从公开题目和研究方向看，我理解这项工作是把主动学习与深度学习势能模型结合起来，通过发现并补充有代表性的训练数据，提高模型对复杂原子或分子体系的可靠性与适用范围。"
    if "graph neural" in lowered or "gnn" in lowered:
        return f"从公开题目和研究方向看，我理解这项工作关注用图神经网络表达结构关系，并将这种结构化表示用于提升{topic_text}问题的建模能力。"
    if any(marker in lowered for marker in ("molecular dynamics", "reaction", "combustion", "chemical")):
        return f"从公开题目和研究方向看，我理解这项工作尝试将{method_text or '数据驱动的方法'}用于{topic_text}相关的动态过程分析，在保证计算效率的同时帮助理解复杂体系的演化规律。"
    if any(marker in lowered for marker in ("software", "toolkit", "framework", "platform", "generator", "dispatcher")):
        return f"从公开题目和研究方向看，我理解这项工作也重视把{topic_text}相关方法沉淀为可复用的软件、工具链或计算平台，从而支持后续研究稳定、可扩展地开展。"
    return f"从论文题目及公开资料呈现的信息看，我理解这项工作围绕{topic_text}展开，重点是将{method_text or '数据驱动的方法'}用于解决具体研究问题；这也让我对从问题定义、方法设计到实验验证的完整过程产生了兴趣。"


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
