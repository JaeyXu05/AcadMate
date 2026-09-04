"""Shared filters for USTC homepage template residue in research_topics."""

from __future__ import annotations

import re

BOILERPLATE_TOPIC_MARKERS = (
    "版权所有",
    "©",
    "地址：",
    "联系地址",
    "邮编",
    "邮政编码",
    "手机版",
    "收藏本站",
    "设为首页",
    "English",
    "Copyright",
    "Contact information",
    "友情链接",
    "更新时间",
    "个人简介",
    "实验室简介",
    "学校简介",
    "代表性成果",
    "代表成果",
    "授课信息",
    "教学研究",
    "教学成果",
    "著作成果",
    "研究成果",
    "成果简介",
    "科研成果",
    "科技成果转化",
    "获奖信息",
    "招生信息",
)
BOILERPLATE_TOPIC_EXACT = {
    "more", "gallery", "news", "vacancy",
    # Navigation, contact and venue labels occasionally leak from profile
    # pages into the direction list.  They are not research assertions.
    "联系我们", "contact us", "group", "icml", "ieee tie",
}
_POSTAL_CODE = re.compile(
    r"(?:邮\s*编|邮政编码).{0,12}\d{5,6}|^\d{6}$"
)
_YEAR_OR_VENUE = re.compile(r"^(?:19|20)\d{2}$|^ieee\s+[a-z.\s]+$", re.IGNORECASE)
_DANGLING_TOPIC_SENTENCE = re.compile(
    r"^(?:用于|应用于|通过|主要研究(?:体系)?包括|研究兴趣主要包括).{0,80}$"
)

# 「成果/项目/荣誉」句判别：与 data_scripts 的 ustc_scraper / build_rag 同源。
# 检索者加载库时（MentorSemanticIndex / FileInternalMentorRag）会再跑一次 clean_topics，
# 把 build 阶段漏网的项目/基金/获奖叙述从 research_topics 里摘掉，避免污染检索向量。
_ACHIEVEMENT_TOPIC_MARKERS = (
    "主持", "参与", "承担", "在研", "立项", "结题",
    "基金", "项目", "课题", "获", "奖", "荣誉", "评选",
    "基金资助", "课题资助", "项目资助", "人才项目", "人才计划",
    "国家自科", "国家自然科学", "国自然", "国家社科", "国家重点研发",
    "国家杰青", "杰青", "优青", "面上项目", "青年科学基金", "青年项目",
    "重点专项", "重大专项", "重大研究计划", "研究计划",
    "获奖", "荣获", "荣誉", "奖项", "入选", "学会优秀", "取得了",
    "发表", "论文", "专利", "授权", "著作", "出版",
    "案例入库", "案例", "担任", "主编", "编委",
)
_ACHIEVEMENT_SOFT_MARKERS = ("项目", "计划", "获奖", "论文")


def is_achievement_topic(topic: str) -> bool:
    """判断一个 topic 片段是否为成果/项目/荣誉叙述而非研究方向。"""
    text = " ".join(str(topic).split())
    if not text:
        return True
    hard = [m for m in _ACHIEVEMENT_TOPIC_MARKERS if m in text]
    if hard:
        return True
    soft = [m for m in _ACHIEVEMENT_SOFT_MARKERS if m in text]
    return len(soft) >= 2


def is_boilerplate_topic(topic: str) -> bool:
    text = " ".join(str(topic).split()).strip()
    if not text:
        return True
    if text.casefold() in BOILERPLATE_TOPIC_EXACT:
        return True
    if _POSTAL_CODE.search(text):
        return True
    if _YEAR_OR_VENUE.fullmatch(text) or _DANGLING_TOPIC_SENTENCE.match(text):
        return True
    return any(marker in text for marker in BOILERPLATE_TOPIC_MARKERS)


def clean_topics(values: list[str] | None, *, limit: int | None = None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        text = " ".join(str(raw).split()).strip()
        if not text or is_boilerplate_topic(text) or is_achievement_topic(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if limit is not None and len(cleaned) >= limit:
            break
    return cleaned
