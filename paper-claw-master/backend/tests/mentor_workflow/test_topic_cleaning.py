from __future__ import annotations

from backend.mentor_workflow.schemas import MatchDimensionScores
from backend.mentor_workflow.topic_cleaning import clean_topics, is_boilerplate_topic


def test_boilerplate_topics_include_postal_code_and_mobile_nav():
    assert is_boilerplate_topic("邮政编码：230026")
    assert is_boilerplate_topic("手机版")
    assert is_boilerplate_topic("230026")
    assert not is_boilerplate_topic("微分方程动力学")
    assert not is_boilerplate_topic("推荐系统")


def test_clean_topics_drops_homepage_template_residue():
    cleaned = clean_topics(
        [
            "微分方程动力学",
            "邮政编码：230026",
            "手机版",
            "微分方程动力学",
            "动力系统",
        ]
    )
    assert cleaned == ["微分方程动力学", "动力系统"]


def test_mean_score_is_research_topic_match_not_eight_way_average():
    scores = MatchDimensionScores(
        research_topic_match=13.17,
        method_match=50,
        application_match=50,
        recent_activity=100,
        student_background_fit=50,
        constraint_satisfaction=100,
        recruitment_fit=50,
        evidence_completeness=100,
    )
    assert scores.mean_score() == 13.17
