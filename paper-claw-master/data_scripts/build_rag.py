"""组装 RAG 库：清洗官网资料并聚合多平台论文，生成工作流 RAG 记录。

读取 ``data/ustc_mentors_raw.json``（官网导师）和各论文平台的
（OpenAlex ``ustc_mentor_papers.json`` / S2 ``ustc_mentor_papers_s2.json`` /
DBLP ``ustc_mentor_papers_dblp.json``）论文，为每位导师生成：

- 一条 ``CandidateMentor``（含 ``candidate_id`` / ``mentor_name`` / ``affiliation`` /
  ``department`` / ``research_topics`` / ``methods`` / ``publications`` /
  ``homepage`` / ``recruitment_status`` / ``evidence_refs`` / ``source_metadata``）。
- 1~N 条 ``EvidenceRecord``：
    1. 身份证据（官方教师目录）：``identity_verified=true``、
       ``mentor_role_verified=true``、``supports_fields=affiliation,department,homepage``。
    2. 主页方向证据（若解析到研究方向/方法/招生）。
    3. 各论文平台证据：仅作者确认记录可支持候选字段；待审核记录保留为
       ``pending_review``，但不得污染论文、方法或方向。

构建时还会清除页面导航/访问计数/栏目标题等模板噪声，严格识别官方主页中的
导师身份语句，并按 DOI、平台 ID、规范化标题跨平台去重。论文总量与代表作数量
分别写入 ``source_metadata``，避免把截取的代表作列表误当成论文总数。

输出 ``data/ustc_mentor_rag.json``，结构::

    {
      "candidates": [ CandidateMentor dict, ... ],
      "evidence":   [ EvidenceRecord dict, ... ],
      "source_chain": ["internal_ustc_rag"],
      "warnings": [...],
      "generated_at": "..."
    }

该文件即 ``InternalMentorRag`` 适配器加载的库。字段与
``backend/mentor_workflow/schemas.py`` 的 ``CandidateMentor`` / ``EvidenceRecord``
以及 ``tests/mentor_workflow/test_ustc_sources.py`` 的
``_verified_internal_result`` 样板对齐，保证能跳过外部官方源。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = REPO_ROOT / "data" / "ustc_mentors_raw.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "ustc_mentor_rag.json"
DEFAULT_ROLE_OVERRIDES = REPO_ROOT / "data" / "mentor_role_overrides.json"
DEFAULT_PAPER_OVERRIDES = REPO_ROOT / "data" / "manual_overrides.json"
DEFAULT_PAPER_SOURCES = {
    "openalex": REPO_ROOT / "data" / "ustc_mentor_papers.json",
    "s2": REPO_ROOT / "data" / "ustc_mentor_papers_s2.json",
    "dblp": REPO_ROOT / "data" / "ustc_mentor_papers_dblp.json",
}

USTC_AFFILIATION = "中国科学技术大学"
USTC_FACULTY_SEARCH_PAGE = (
    "https://faculty.ustc.edu.cn/search.jsp?urltype=tree.TreeTempUrl&wbtreeid=1016"
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_id(faculty_id: str) -> str:
    return f"ustc_faculty_{faculty_id}"


def _author_key(value: str) -> str:
    """归一化作者名用于匹配：去标点、小写。"""
    import re

    return re.sub(r"[^a-z0-9一-鿿]", "", value.casefold())


def _keyword_in_title(keyword: str, title: str) -> bool:
    """Match ASCII keywords on word boundaries while keeping CJK matching simple."""
    folded = (title or "").casefold()
    term = keyword.casefold().strip()
    if not term:
        return False
    if re.search(r"[a-z0-9]", term):
        pattern = re.escape(term).replace(r"\ ", r"[\s\-]+")
        if term in {"electrochemi", "cryptograph", "metallurg"}:
            return re.search(rf"(?<![a-z0-9]){pattern}[a-z]*(?![a-z0-9])", folded) is not None
        return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", folded) is not None
    return term in folded


def _paper_methods(titles: str | list[str]) -> list[str]:
    """从论文标题保守抽取方法；列表输入要求至少两篇论文支持。"""
    values = [titles] if isinstance(titles, str) else [str(item or "") for item in titles]
    if isinstance(titles, str):
        return [method for method in _METHOD_KEYWORDS if _keyword_in_title(method, values[0])]
    return [
        method
        for method in _METHOD_KEYWORDS
        if sum(_keyword_in_title(method, title) for title in values) >= 2
    ]


# 论文标题 → 研究方向标签 的保守词典（中英双语子串命中）。
# build 时当某导师官网没抓到 research_topics 但论文标题明确含该领域时，用它回填
# 一个规范化研究方向，避免这类导师因"无方向"在检索/云图里被埋没。
# 关键词用小写子串匹配，命中即视为该方向成立（论文标题是强证据，非模板残留）。
_PAPER_TOPIC_LEXICON: list[tuple[str, str]] = [
    # (命中子串, 回填方向标签)  —— 子串须区分度高，避免"AI/学习"这类泛词误打。
    ("reinforcement learning", "强化学习"),
    ("deep learning", "深度学习"),
    ("machine learning", "机器学习"),
    ("neural network", "神经网络"),
    ("computer vision", "计算机视觉"),
    ("natural language processing", "自然语言处理"),
    ("large language model", "大语言模型"),
    ("graph neural", "图神经网络"),
    ("diffusion model", "扩散模型"),
    ("transformer", "Transformer 模型"),
    ("quantum", "量子计算"),
    ("spintronic", "自旋电子学"),
    ("topological", "拓扑物态"),
    ("semiconductor", "半导体材料"),
    ("photocatalysis", "光催化"),
    ("electrocatalysis", "电催化"),
    ("battery", "电池储能"),
    ("energy storage", "能量存储"),
    ("hydrogen", "氢能与燃料电池"),
    ("carbon", "碳材料"),
    ("solar cell", "太阳能电池"),
    ("perovskite", "钙钛矿材料"),
    ("optoelectronic", "光电器件"),
    ("photonic", "光子学"),
    ("optical", "光学"),
    ("laser", "激光物理"),
    ("biomedical", "生物医学"),
    ("cancer", "肿瘤医学"),
    ("drug", "药物设计"),
    ("bioinformatics", "生物信息学"),
    ("genome", "基因组学"),
    ("protein", "蛋白质结构"),
    ("cell", "细胞生物学"),
    ("microbiome", "微生物组"),
    ("climate", "气候变化"),
    ("atmospheric", "大气科学"),
    ("ocean", "海洋科学"),
    ("geophysical", "地球物理"),
    ("seismic", "地震学"),
    ("planetary", "行星科学"),
    ("fluid", "流体力学"),
    ("turbulence", "湍流"),
    ("aerodynamic", "空气动力学"),
    ("combustion", "燃烧与推进"),
    ("mechanical", "力学"),
    ("structural", "结构力学"),
    ("macromolecular", "高分子"),
    ("polymer", "高分子"),
    ("nano", "纳米材料"),
    ("catalyst", "催化化学"),
    ("organic", "有机化学"),
    ("inorganic", "无机化学"),
    ("electrochemi", "电化学"),
    ("material", "材料科学"),
    ("metallurg", "金属材料"),
    ("high-entropy", "高熵合金"),
    ("robotics", "机器人学"),
    ("robot", "机器人"),
    ("autonomous", "自主系统"),
    ("control", "控制理论与工程"),
    ("signal processing", "信号处理"),
    ("multimedia", "多媒体"),
    ("speech", "语音处理"),
    ("3d vision", "三维视觉"),
    ("knowledge graph", "知识图谱"),
    ("recommender", "推荐系统"),
    ("federated learning", "联邦学习"),
    ("adversarial", "对抗鲁棒性"),
    ("cryptograph", "密码学"),
    ("security", "网络安全"),
    ("privacy", "隐私保护"),
    ("blockchain", "区块链"),
    ("cloud computing", "云计算"),
    ("distributed", "分布式系统"),
    ("high performance computing", "高性能计算"),
    ("fpga", "FPGA 与体系结构"),
    ("computer architecture", "计算机体系结构"),
    ("soc", "集成电路"),
    ("signal integrity", "电磁兼容"),
]

# 单独命中时歧义过高，不能据此把论文标题反推成导师研究方向。例如 control 既可能
# 是控制理论，也可能只是实验对照；cell/material/security 等同理。保留词典映射供
# 后续人工/组合证据使用，但自动回填与跨语言作者消歧均跳过这些词。
_AMBIGUOUS_PAPER_TOPIC_KEYWORDS = {
    "carbon", "organic", "optical", "cell", "material", "control", "security",
    "robot", "mechanical", "structural", "distributed", "autonomous",
    # These terms are valid paper vocabulary but too broad to infer a
    # professor's primary direction from title-only evidence.  In particular,
    # quantum is not synonymous with quantum computing and a cancer/ocean
    # mention can be merely an application or dataset.
    "quantum", "hydrogen", "cancer", "ocean", "combustion", "transformer",
}


def _paper_topics_from_titles(titles: list[str]) -> list[str]:
    """从论文标题保守回填研究方向标签；命中领域词典即返回对应标签，去重保序。

    只在 titles 非空时调用，且调用方仅在该导师 research_topics 为空时才回填，
    因此它绝不会覆盖官网已抓到的研究方向。
    """
    hit: list[str] = []
    seen: set[str] = set()
    one_paper_ok = {
        "reinforcement learning", "computer vision", "natural language processing",
        "large language model", "graph neural", "diffusion model", "bioinformatics",
        "knowledge graph", "recommender", "federated learning", "signal processing",
        "cloud computing", "high performance computing", "computer architecture",
        "signal integrity", "soc",
    }
    for keyword, label in _PAPER_TOPIC_LEXICON:
        support = sum(_keyword_in_title(keyword, title) for title in titles)
        minimum = 1 if keyword in one_paper_ok else 2
        if support >= minimum and label not in seen:
            seen.add(label)
            hit.append(label)
    return hit[:6]


def _strip_html(value: str) -> str:
    """去掉 OpenAlex 标题里残留的 <sub>/<sup> 等标签。"""
    import re

    return re.sub(r"<[^>]+>", "", value).strip()


# ---------------------------------------------------------------------------
# 从官网个人主页 profile_text 抽取富信息（bio / email / 办公地点 / 毕业院校）。
# 此前 build 完全丢弃 profile_text，导致详情页 bio/contact 与更多方向全部缺失。
# 这些是纯文本富信息，抽取结果写入 source_metadata（标量 dict，符合 schema），
# 不改 CandidateMentor schema、不改 A/C 输出格式；D 侧 ragAdvisors.ts 读键拼接。
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*@[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\.[A-Za-z]{2,}"
)
_EMAIL_BLACKLIST = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
    "@w3.org", "@example", "noreply", "no-reply",
)


def _extract_email(text: str) -> str | None:
    """从个人主页正文抽取首个可信 email（过滤图片/站务噪声）。"""
    for email in _EMAIL_RE.findall(text or ""):
        low = email.lower()
        if any(bad in low for bad in _EMAIL_BLACKLIST):
            continue
        return email
    return None


# 基本信息区里以「中文标签 + 冒号」出现的键值行，不属于 bio 正文。
_BIO_KEY_VALUE_LABELS = (
    "教师英文名称", "电子邮箱", "邮箱", "E-mail", "Email", "职务",
    "办公地点", "办公地址", "毕业院校", "联系电话", "电话", "传真",
    "职称", "学历", "学位", "通讯地址", "办公室", "主页", "Homepage",
    "个人主页", "个人网站",
)

# 个人主页顶部/底部的站务噪声整行或整段匹配，bio 里直接丢弃。
_BIO_NOISE_LINES = {
    "首页", "科学研究", "教学信息", "团队成员", "获奖信息",
    "招生信息", "导航", "登录", "English", "教师个人主页",
    "查看更多", "【查看更多】", "暂无内容", "网站访问量",
}
_BIO_NOISE_SUBSTRINGS = (
    "扫描手机二维码", "手机扫描二维码", "即可访问本教师主页", "欢迎您的访问",
    "您是第", "位访客", "开通时间", "访问量", "手机版",
)
_BIO_SECTION_HEADINGS = {
    "基本信息", "个人信息", "其他联系方式", "联系方式", "教育经历", "工作经历",
    "社会兼职", "研究方向", "研究领域", "科研项目", "论文成果", "代表性论文",
    "教学信息", "教学资源", "学生信息", "团队成员", "我的相册", "教师博客",
    "其他栏目", "获奖信息", "招生信息", "语种", "专利", "更多",
}
_BIO_ROLE_ONLY = re.compile(
    r"^(?:博士生导师|硕士生导师|博导|硕导|教授|副教授|特任教授|研究员|"
    r"副研究员|特任研究员|特任副研究员|正高级工程师|个人信息Personal Information)$"
)
_BIO_INTRO_HINT = re.compile(
    r"(?:现任|现为|目前|主要从事|主要研究|研究方向|获得.{0,20}(?:博士|学位)|"
    r"毕业于|任职于|教授|研究员|导师|I\s|My\s)",
    re.IGNORECASE,
)


def _extract_bio(profile_text: str, name: str, max_len: int = 600) -> str | None:
    """定位并抽取导师简介段，而不是把整页清洗后机械截取前 600 字。"""
    text = (profile_text or "").strip()
    if not text:
        return None

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        if _is_boilerplate_topic(line):
            continue
        if line in _BIO_NOISE_LINES:
            continue
        if line in _BIO_SECTION_HEADINGS or _BIO_ROLE_ONLY.fullmatch(line):
            lines.append(line)  # 保留章节边界，选段时使用。
            continue
        if any(marker in line for marker in _BIO_NOISE_SUBSTRINGS):
            continue
        # 标题面包屑「中国科学技术大学 曾晋哲--曾晋哲--首页」这类含 "--" 的标题行。
        if "--" in line and (name in line or "首页" in line):
            continue
        # 同专业博导/硕导的英文占位「P同专业博导」「M同专业硕导」。
        if re.search(r"同专业[博硕]导", line):
            continue
        if re.fullmatch(r"[|、，,\s]+", line):
            continue
        if re.fullmatch(r"[0-9a-f]{80,}", line, re.I):
            continue
        # 「标签:值」键值行跳过（邮箱哈希/办公地点等）与未知标签。
        if re.match(r"^[^：:]{1,10}[:：]", line):
            label = re.split(r"[:：]", line, maxsplit=1)[0].strip()
            if any(kw in label for kw in _BIO_KEY_VALUE_LABELS):
                continue
            continue  # 其它「标签:值」行同样非散文，一并丢弃
        lines.append(line)

    # 优先找“姓名 + 介绍性语句”；其次找不含姓名但有明确任职/研究叙述的长句。
    start = next(
        (i for i, line in enumerate(lines) if name in line and len(line) >= 20 and _BIO_INTRO_HINT.search(line)),
        None,
    )
    if start is None:
        start = next(
            (i for i, line in enumerate(lines) if len(line) >= 30 and _BIO_INTRO_HINT.search(line)),
            None,
        )
    if start is None:
        return None

    selected: list[str] = []
    for line in lines[start : start + 5]:
        if selected and (line in _BIO_SECTION_HEADINGS or _BIO_ROLE_ONLY.fullmatch(line)):
            break
        if line in _BIO_SECTION_HEADINGS or _BIO_ROLE_ONLY.fullmatch(line):
            continue
        if re.search(r"https?://|\bDOI\s*:", line, re.I):
            continue
        selected.append(line)
        if sum(len(item) for item in selected) >= max_len:
            break
    bio = "\n".join(selected).strip()
    if not bio:
        return None
    if len(bio) > max_len:
        bio = bio[:max_len].rstrip("，,；;、 \t")
    if len(bio) < 20:
        return None
    return bio


def _extract_office(profile_text: str) -> str | None:
    m = re.search(r"(?:办公地点|办公地址)[:：]?\s*([^\n]{2,60})", profile_text or "")
    return " ".join(m.group(1).split()).strip() if m else None


def _extract_graduated_from(profile_text: str) -> str | None:
    m = re.search(r"(?:毕业院校)[:：]?\s*([^\n]{2,60})", profile_text or "")
    return " ".join(m.group(1).split()).strip() if m else None



_METHOD_KEYWORDS = [
    "deep learning", "reinforcement learning", "neural network",
    "transformer", "graph neural", "convolutional", "diffusion model",
    "large language model", "contrastive learning", "self-supervised",
]

# 与 ustc_scraper._BOILERPLATE_TOPIC_MARKERS 同源：build 时对已抓取的
# research_topics 再做一次清理，即使跳过重抓也能去掉模板残留污染。
_BOILERPLATE_TOPIC_MARKERS = (
    "版权所有",
    "©",
    "地址：",
    "联系地址",
    "邮编",
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
    "邮政编码",
    "手机版",
)
_BOILERPLATE_TOPIC_EXACT = {
    "more", "gallery", "news", "vacancy",
    "联系我们", "contact us", "group", "icml", "ieee tie",
}
_POSTAL_CODE_TOPIC = re.compile(r"(?:邮\s*编|邮政编码).{0,12}\d{5,6}|^\d{6}$")
_YEAR_OR_VENUE_TOPIC = re.compile(r"^(?:19|20)\d{2}$|^ieee\s+[a-z.\s]+$", re.IGNORECASE)
_DANGLING_TOPIC_SENTENCE = re.compile(
    r"^(?:用于|应用于|通过|主要研究(?:体系)?包括|研究兴趣主要包括).{0,80}$"
)

# 已在 2026-08-24 成品库中实际出现的中文站点栏目/访问计数。只收录无歧义的
# 整项值，避免误杀“导航与制导”“视觉导航”等真实科研方向。
_DIRTY_TOPIC_EXACT = {
    "教学信息", "指导研究生及博士后", "在读研究生", "新闻", "新闻动态",
    "总访问量", "日访问量", "实验室概况", "研究兴趣",
    "主要研究方向但不局限于以下", "1）主要研究方向但不局限于以下",
}
_DIRTY_TOPIC_PATTERNS = (
    re.compile(r"^(?:总|日)?访问量(?:[:：]?\s*\d+)?$"),
    re.compile(r"^中国科学技术大学.{0,30}(?:学院|实验室|中心)$"),
    re.compile(r"^中国科学院青年促进会(?:优秀)?会员"),
    re.compile(r"^[A-Za-z0-9＋+_-]{2,20}实验室$"),
)
_TOPIC_SENTENCE_NOISE = re.compile(
    r"(?:招收|招生|研究生课程|开设课程|在线阅读链接|访问量|新闻动态|会员（?\d{4}|"
    r"欢迎(?:点赞|关注)|诚邀|优秀实习生|评审委员会|谷歌学术引用|"
    r"Honors\s*&\s*Awards|Social Affiliations|adjunct\s+(?:assistant\s+)?professor)",
    re.IGNORECASE,
)
_TOPIC_LINK_OR_PAPER = re.compile(
    r"(?:https?://|\bDOI\s*:|^[“\"‘'].{25,}[”\"’'](?:[,，.]|\s*$)|"
    r"\b(?:Adv\. Mater|Angew\. Chem|Science|Ultramicroscopy)\b.{0,40}(?:\b20\d{2}\b|\b\d{1,4}\s*(?:[,(:]|$)))",
    re.IGNORECASE,
)

# 「成果/项目/荣誉」句判别：与 ustc_scraper._is_achievement_topic 同源。
# raw 已抓取的 research_topics 里混有项目/基金/获奖叙述（方向段后内联、无换行），
# 离线重跑 build 时也必须二次过滤，否则污染照旧进入检索向量。
_ACHIEVEMENT_TOPIC_MARKERS = (
    "主持", "参与", "承担", "在研", "立项", "结题",
    "基金", "项目", "课题", "获", "奖", "荣誉", "评选",
    "基金资助", "课题资助", "项目资助", "人才项目", "人才计划",
    "国家自科", "国家自然科学", "国家自然科学", "国自然", "国家社科", "国家重点研发",
    "国家杰青", "杰青", "优青", "面上项目", "青年科学基金", "青年项目",
    "重点专项", "重大专项", "重大研究计划", "研究计划",
    "获奖", "荣获", "荣誉", "奖项", "入选", "学会优秀", "取得了",
    "发表", "论文", "专利", "授权", "著作", "出版",
    "案例入库", "案例", "担任", "主编", "编委",
)
_ACHIEVEMENT_SOFT_MARKERS = ("项目", "计划", "获奖", "论文")


def _is_achievement_topic(topic: str) -> bool:
    text = " ".join(str(topic).split())
    if not text:
        return True
    hard = [m for m in _ACHIEVEMENT_TOPIC_MARKERS if m in text]
    if hard:
        return True
    soft = [m for m in _ACHIEVEMENT_SOFT_MARKERS if m in text]
    return len(soft) >= 2


def _is_boilerplate_topic(topic: str) -> bool:
    if topic.casefold() in _BOILERPLATE_TOPIC_EXACT:
        return True
    if _POSTAL_CODE_TOPIC.search(topic):
        return True
    if _YEAR_OR_VENUE_TOPIC.fullmatch(topic) or _DANGLING_TOPIC_SENTENCE.match(topic):
        return True
    return any(marker in topic for marker in _BOILERPLATE_TOPIC_MARKERS)


def _clean_profile_topic(topic: object) -> str | None:
    """规范化单条官网方向；仅删除可证实的站点/履历噪声，保留科研“导航”。"""
    text = " ".join(str(topic or "").split()).strip(" []()（）.。:：-*；;")
    if not text:
        return None
    text = re.sub(r"^\d+[)）.、]\s*", "", text).strip()
    text = re.sub(r"^(?:主要)?研究方向(?:包括|为|但不局限于以下)?\s*[:：]?\s*", "", text)
    if not text or text in _DIRTY_TOPIC_EXACT:
        return None
    if _is_boilerplate_topic(text) or _is_achievement_topic(text):
        return None
    if any(pattern.search(text) for pattern in _DIRTY_TOPIC_PATTERNS):
        return None
    if _TOPIC_SENTENCE_NOISE.search(text):
        return None
    if _TOPIC_LINK_OR_PAPER.search(text):
        return None
    if re.fullmatch(r"\d{2}-\d{2}", text):
        return None
    if re.fullmatch(
        r"(?:IEEE\s+Trans\..*|Pattern\s+Recognition|Science|Nature\s+Photonics|"
        r"Physical\s+Review\s+Letters|ICIP\s+\d{4})",
        text,
        re.IGNORECASE,
    ):
        return None
    if re.match(r"^已在\s*(?:IEEE|ACM|Science|Nature)\b", text, re.IGNORECASE):
        return None
    if re.search(r"\b(?:I've been|I have been)\b.{0,40}\bprofessor\b", text, re.I):
        return None
    return text


def _profile_mentor_role(name: str, profile_text: str) -> str | None:
    """从官方主页正文提取强导师身份陈述，排除“同专业博导”等推荐组件。"""
    text = re.sub(r"[PM]同专业[博硕]导", "", profile_text or "")
    role = r"(博士生导师|硕士生导师|博导|硕导)"
    title = r"(?:讲席教授|特任教授|副教授|教授|特任研究员|副研究员|研究员|正高级工程师)"
    patterns = (
        rf"{re.escape(name)}.{{0,150}}?{role}",
        rf"(?:现任|现为).{{0,100}}?{title}.{{0,20}}?{role}",
        rf"(?:现任|现为|作为)\s*{role}",
        rf"(?:职务|主要任职)[：:].{{0,80}}?{role}",
        rf"(?:^|\n)\s*{role}[、，,\s]{{1,8}}{title}",
        rf"(?:^|\n)\s*{role}.{{0,30}}?{title}",
        rf"(?:中国科学技术大学|中科大).{{0,80}}?{role}",
        rf"(?:仪器科学与技术|学科点).{{0,30}}?{role}",
        rf"{title}[、，,\s]{{0,6}}{role}",
        rf"受聘{role}岗位",
        rf"(?:担任|聘为).{{0,50}}?{role}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            # role 是每个表达式最后一个捕获组。
            return match.groups()[-1]
    return None


def _normalize_token(value: str) -> str:
    """归一化方向词/标题词用于重叠判断：小写、去标点空白。"""
    import re

    return re.sub(r"[^a-z0-9一-鿿]", "", value.casefold())


def _has_cjk(text: str) -> bool:
    """是否含中文字符。"""
    return bool(__import__("re").search(r"[一-鿿]", text))


def _direction_consistency(
    topics: list[str], titles: list[str]
) -> str:
    """判断官网方向与论文标题的方向一致性，返回三态：

    - "overlap"      : 有明确重叠信号（方向词作为子串命中标题），可信。
    - "mismatch"     : 方向词与标题同语言却无任何重叠，强烈疑似同名错配，应丢弃。
    - "uncertain"    : 跨语言（如中文方向 vs 英文标题）无法用子串判定，保留但存疑。
    - "no_topics"    : 导师无官网方向，无从对比，保留。
    """
    if not topics:
        return "no_topics"
    title_blob = " ".join(_normalize_token(t) for t in titles)
    topics_cjk = any(_has_cjk(t) for t in topics)
    titles_cjk = any(_has_cjk(t) for t in titles)
    for topic in topics:
        token = _normalize_token(topic)
        if len(token) >= 2 and token in title_blob:
            return "overlap"
    # 使用已有中英领域词典搭桥；宽泛词不得独立证明方向一致。
    for keyword, label in _PAPER_TOPIC_LEXICON:
        if keyword in _AMBIGUOUS_PAPER_TOPIC_KEYWORDS or keyword not in " ".join(titles).casefold():
            continue
        normalized_label = _normalize_token(label)
        if any(
            normalized_label in _normalize_token(topic)
            or _normalize_token(topic) in normalized_label
            for topic in topics
            if len(_normalize_token(topic)) >= 2
        ):
            return "overlap"
    # 无子串重叠：仅当方向词与标题同语言时才判错配；跨语言降级存疑。
    if topics_cjk and not titles_cjk:
        return "uncertain"
    if not topics_cjk and titles_cjk:
        return "uncertain"
    return "mismatch"


def _source_platform(record: dict) -> str:
    """从论文记录推断来源平台（openalex / s2 / dblp）。"""
    if record.get("openalex_author_id") is not None:
        return "openalex"
    if record.get("s2_author_id") is not None:
        return "s2"
    if record.get("dblp_pid") is not None:
        return "dblp"
    return "unknown"


def _source_display_key(record: dict) -> str:
    """论文记录用来生成 evidence source_uri / source_type 的键。"""
    return (
        record.get("openalex_author_id")
        or record.get("s2_author_id")
        or record.get("dblp_pid")
        or ""
    )


def _source_match_flag(record: dict) -> bool | None:
    """该平台作者是否精确命中（OpenAlex/S2/DBLP 各自的 exact_match 字段）。"""
    if record.get("openalex_author_id") is not None:
        return record.get("openalex_exact_match")
    if record.get("s2_author_id") is not None:
        return record.get("s2_exact_match")
    if record.get("dblp_pid") is not None:
        return record.get("dblp_exact_match")
    return None


_PLATFORM_OVERRIDE_KEYS = {
    "openalex": "OpenAlex",
    "s2": "Semantic Scholar",
    "dblp": "DBLP",
}
_PLATFORM_AUTHOR_ID_KEYS = {
    "openalex": "openalex_author_id",
    "s2": "s2_author_id",
    "dblp": "dblp_pid",
}


def _normalized_author_id(value: object) -> str:
    return str(value or "").strip().casefold().removeprefix("https://openalex.org/")


def _paper_identity_status(
    faculty_id: str,
    source: dict,
    manual_overrides: dict[str, dict[str, object]],
) -> tuple[str, str]:
    """Return verified/pending/rejected; exact name equality is not verification."""
    platform = _source_platform(source)
    override_key = _PLATFORM_OVERRIDE_KEYS.get(platform, platform)
    mentor_overrides = manual_overrides.get(str(faculty_id), {})
    if override_key not in mentor_overrides:
        return "pending", "no_manual_or_strong_identity_verification"
    approved = mentor_overrides.get(override_key)
    if approved is None:
        return "rejected", "manual_override_rejected"
    actual = source.get(_PLATFORM_AUTHOR_ID_KEYS.get(platform, ""))
    if _normalized_author_id(approved) == _normalized_author_id(actual):
        return "verified", "manual_override_author_id"
    return "rejected", "manual_override_points_to_different_author"


def _source_papers(record: dict) -> list[dict]:
    papers = record.get("papers") or []
    # 过滤无标题/空标题的条目，避免污染 publications。
    out = []
    for paper in papers:
        if isinstance(paper, dict) and _strip_html(paper.get("title") or ""):
            out.append(paper)
    return out


def _source_total_count(record: dict) -> int | None:
    for key in ("openalex_works_count", "s2_paper_count", "dblp_pub_count"):
        value = record.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


def _source_citation_count(record: dict) -> int | None:
    for key in ("openalex_cited_by_count", "s2_cited_by_count"):
        value = record.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


def _normalized_doi(value: object) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text)


def _paper_keys(paper: dict) -> list[str]:
    keys: list[str] = []
    doi = _normalized_doi(paper.get("doi"))
    if doi:
        keys.append(f"doi:{doi}")
    for field in ("openalex_id", "s2_paper_id", "dblp_key"):
        value = str(paper.get(field) or "").strip().casefold()
        if value:
            keys.append(f"{field}:{value}")
    title = _strip_html(paper.get("title") or "")
    normalized_title = re.sub(r"[^a-z0-9一-鿿]", "", title.casefold())
    if normalized_title:
        keys.append(f"title:{normalized_title}")
    return keys


def _dedupe_papers(papers: list[dict]) -> list[dict]:
    """按 DOI → 平台 ID → 规范化标题跨平台去重，保留首次出现的记录。"""
    seen: set[str] = set()
    out: list[dict] = []
    for paper in papers:
        keys = _paper_keys(paper)
        if not keys or any(key in seen for key in keys):
            continue
        seen.update(keys)
        out.append(paper)
    return out


def _cross_platform_author_conflict(source: dict, all_sources: list[dict]) -> bool:
    """识别“姓名精确但作者实体明显分裂”的 S2/DBLP 记录。

    OpenAlex 查询带 USTC 机构约束，作为离线交叉核验锚点。其它平台若与其代表作
    没有 DOI/规范化标题交集，且作品总数不足 OpenAlex 的四分之一，先降为待审核。
    """
    platform = _source_platform(source)
    if platform == "openalex" or _source_match_flag(source) is not True:
        return False
    anchor = next(
        (
            item for item in all_sources
            if _source_platform(item) == "openalex" and _source_match_flag(item) is True
        ),
        None,
    )
    if not anchor:
        return False
    anchor_papers = _source_papers(anchor)
    source_papers = _source_papers(source)
    if not anchor_papers or not source_papers:
        return False
    anchor_keys = {
        key for paper in anchor_papers for key in _paper_keys(paper)
        if key.startswith(("doi:", "title:"))
    }
    source_keys = {
        key for paper in source_papers for key in _paper_keys(paper)
        if key.startswith(("doi:", "title:"))
    }
    if anchor_keys & source_keys:
        return False
    anchor_total = _source_total_count(anchor)
    source_total = _source_total_count(source)
    return bool(
        anchor_total is not None
        and source_total is not None
        and anchor_total >= 20
        and source_total * 4 < anchor_total
    )


def build_mentor(
    mentor: dict,
    paper_sources: list[dict],
    paper_overrides: dict[str, object] | None = None,
) -> tuple[dict, list[dict], list[str]] | None:
    """为单个导师生成 (candidate_dict, evidence_list, warnings)；非导师返回 None。

    ``paper_sources`` 是该导师在 OpenAlex / S2 / DBLP 各平台的论文记录列表，
    可以多源同时存在；build 时按来源逐平台做方向一致性过滤并合并去重。
    ``paper_overrides`` 是该导师经人工裁决的平台→作者 ID；``null`` 表示拒绝，
    与当前来源 ID 一致的非空值表示确认。
    """
    faculty_id = str(mentor.get("faculty_id"))
    name = mentor.get("name", "")
    if not faculty_id or not name:
        return None
    profile_text = mentor.get("profile_text") or ""
    profile_role = _profile_mentor_role(name, profile_text)
    if not mentor.get("mentor_role_verified") and not profile_role:
        return None

    candidate_id = _candidate_id(faculty_id)
    evidence: list[dict] = []
    warnings: list[str] = []

    # 从官网个人主页富文本抽取 bio / email / 办公地点 / 毕业院校（此前完全被丢弃）。
    profile_email = _extract_email(profile_text)
    profile_bio = _extract_bio(profile_text, name)
    profile_office = _extract_office(profile_text)
    profile_graduated_from = _extract_graduated_from(profile_text)
    if not profile_email and "@" in profile_text:
        warnings.append(f"{name} 官网个人主页存在邮箱但为非明文（站方加密），未抽取到 email")

    # 1) 身份证据：官方教师目录。
    role = mentor.get("mentor_role") or profile_role or ""
    identity_fact = (
        f"中科大官方教师系统列出{name}，单位为"
        f"{mentor.get('college') or mentor.get('unit') or USTC_AFFILIATION}"
        + (f"，导师类型为{role}" if role else "")
        + "。"
    )
    role_verification_source = (
        mentor.get("mentor_role_verification_source")
        or (
            "official_directory_fields"
            if mentor.get("mentor_role_verified") and mentor.get("mentor_role")
            else "official_profile_text_strong"
        )
    )
    identity_confidence = 0.99 if role_verification_source == "official_directory_fields" else 0.97
    identity = {
        "evidence_id": f"ev_{candidate_id}_identity",
        "candidate_id": candidate_id,
        "source_type": "ustc_official_faculty_directory",
        "source_uri": USTC_FACULTY_SEARCH_PAGE,
        "title": f"中国科学技术大学教师个人主页：{name}",
        "extracted_fact": identity_fact,
        "locator": f"teacherData[a={faculty_id}]",
        "retrieved_at": _utcnow_iso(),
        "freshness": "current",
        "confidence": identity_confidence,
        "metadata": {
            "identity_verified": True,
            "mentor_role_verified": True,
            "supports_fields": "affiliation,department,homepage",
            "ustc_faculty_id": faculty_id,
            "source_priority": "official",
            "mentor_role_verification_source": role_verification_source,
        },
    }
    evidence.append(identity)

    # 2) 主页方向（官网解析，先去模板/版权污染）：最终 research_topics 在
    #    处理论文回填后确定（见下方 _finalize_topics），此处仅做源中的初值。
    topics_from_profile = _dedupe(
        cleaned
        for topic in (mentor.get("research_topics") or [])
        if (cleaned := _clean_profile_topic(topic)) is not None
    )
    recruitment = mentor.get("recruitment_status")

    # 3) 论文证据：合并 OpenAlex / S2 / DBLP 各来源代表论文，逐平台做方向
    #    一致性过滤后统一去重，补 publications / methods / 论文证据。
    publication_records: list[dict] = []
    paper_methods: list[str] = []
    kept_platforms: list[str] = []
    reviewed_platforms: list[str] = []
    paper_source_metadata: dict[str, str | int | float | bool] = {}
    trusted_total_counts: list[tuple[int, str]] = []
    for source in paper_sources:
        platform = _source_platform(source)
        if platform == "unknown":
            continue
        papers = _source_papers(source)
        # 用途：补 publications（去 HTML 标签）。
        titles = [_strip_html(p.get("title") or "") for p in papers]
        titles = [t for t in titles if t]
        # 方向一致性过滤：作者仅模糊命中（exact_match=False）时，用官网研究方向
        # 与命中论文标题对比，按一致性三态处理：
        #   mismatch   —— 同语言却无重叠，强烈疑似同名错配，丢弃该平台论文证据。
        #   uncertain  —— 跨语言无法子串判定（如中文方向 vs 英文论文），保留
        #                  论文证据但记 warning，留待人工裁决。
        #   overlap    —— 有重叠信号，保留。
        exact_match = _source_match_flag(source)
        override_key = {
            "openalex": "OpenAlex", "s2": "Semantic Scholar", "dblp": "DBLP",
        }.get(platform, platform)
        has_manual_override = override_key in (paper_overrides or {})
        manual_author_id = (paper_overrides or {}).get(override_key)
        manual_id_matches = (
            has_manual_override
            and manual_author_id is not None
            and str(manual_author_id).strip().casefold()
            == str(_source_display_key(source)).strip().casefold()
        )
        consistency = _direction_consistency(topics_from_profile, titles) if titles else "no_papers"
        cross_platform_conflict = _cross_platform_author_conflict(source, paper_sources)
        if has_manual_override:
            author_match_status = "confirmed" if manual_id_matches else "rejected"
        else:
            author_match_status = (
                "confirmed" if exact_match is True and not cross_platform_conflict
                else "pending_review"
            )
        warning = None
        if has_manual_override and manual_author_id is None:
            warning = f"{name} {platform} 作者实体经人工复核判定为错配，已丢弃"
        elif has_manual_override and not manual_id_matches:
            warning = (
                f"{name} {platform} 人工指定作者 {manual_author_id} 与当前抓取实体"
                f" {_source_display_key(source)} 不同；请重跑该平台抓取，本次先丢弃"
            )
        elif manual_id_matches:
            warning = f"{name} {platform} 作者实体经人工复核确认"
        elif cross_platform_conflict:
            warning = (
                f"{name} {platform} 虽姓名精确命中，但与 USTC 约束的 OpenAlex 代表作无交集，"
                "且作者作品总数差异过大，降为待审核证据，不参与候选字段回填"
            )
        elif exact_match is False and titles:
            if consistency == "mismatch":
                author_match_status = "rejected"
                warning = (
                    f"{name} {platform} 作者仅模糊命中 "
                    f"{_source_display_key(source)}，且其论文标题与官网研究方向"
                    f"({topics_from_profile[:3]})同语言却无重叠，判定为同名错配，丢弃论文证据"
                )
            else:
                warning = (
                    f"{name} {platform} 作者仅模糊命中 "
                    f"{_source_display_key(source)}，官网方向为{topics_from_profile[:3]}、"
                    f"方向一致性={consistency}，论文仅保留为待审核证据，不参与候选字段回填"
                    f"（见 export_fuzzy_review.py）"
                )
        elif exact_match is None:
            warning = (
                f"{name} {platform} 作者命中缺少 exact_match 标志，"
                "论文仅保留为待审核证据，不参与候选字段回填"
            )
        if warning:
            warnings.append(warning)
        if author_match_status == "rejected":
            continue
        reviewed_platforms.append(platform)

        source_total = _source_total_count(source)
        source_citations = _source_citation_count(source)
        paper_source_metadata[f"{platform}_representative_count"] = len(papers)
        if source_total is not None:
            paper_source_metadata[f"{platform}_publication_total"] = source_total
        if source_citations is not None:
            paper_source_metadata[f"{platform}_citation_total"] = source_citations
        paper_source_metadata[f"{platform}_author_match_status"] = author_match_status
        if exact_match is not None:
            paper_source_metadata[f"{platform}_author_match_exact"] = exact_match

        # 只有精确匹配的作者论文进入 CandidateMentor。待审核论文保留 EvidenceRecord，
        # 但不能影响检索、methods、研究方向回填或前端论文数。
        if author_match_status == "confirmed":
            publication_records.extend(papers)
            kept_platforms.append(platform)
            if source_total is not None:
                trusted_total_counts.append((source_total, platform))
        if not papers:
            continue
        # 论文 EvidenceRecord（每平台一条，evidence_id 带平台后缀避免冲突）。
        paper_evidence = {
            "evidence_id": f"ev_{candidate_id}_papers_{platform}",
            "candidate_id": candidate_id,
            "source_type": f"{platform}_paper_metadata",
            "source_uri": _source_display_key(source),
            "title": f"{name} 的 {platform} 代表论文",
            "extracted_fact": (
                f"{name}在{platform}解析到作者实体{_source_display_key(source)}，"
                f"代表论文包括：{'；'.join(titles[:5])}。"
            ),
            "locator": f"{platform} works (sorted by relevance)",
            "retrieved_at": _utcnow_iso(),
            "freshness": "recent",
            "confidence": 0.9 if author_match_status == "confirmed" else 0.45,
            "metadata": {
                "identity_verified": False,
                "mentor_role_verified": False,
                "supports_fields": (
                    "research_topics,methods,publications"
                    if author_match_status == "confirmed" else ""
                ),
                "source_platform": platform,
                "source_priority": "paper_supplement",
                "retrieved_representative_count": len(papers),
                "author_match_status": author_match_status,
                "direction_consistency": consistency,
                "cross_platform_conflict": cross_platform_conflict,
                "manual_author_override": has_manual_override,
            },
        }
        if exact_match is not None:
            paper_evidence["metadata"]["author_match_exact"] = exact_match
        if source_total is not None:
            paper_evidence["metadata"]["source_publication_total"] = source_total
        if source_citations is not None:
            paper_evidence["metadata"]["source_citation_total"] = source_citations
        # 保留来源 ID 到 metadata，便于回溯。
        for src_key in ("openalex_author_id", "s2_author_id", "dblp_pid"):
            if source.get(src_key) is not None:
                paper_evidence["metadata"][src_key] = source.get(src_key)
        evidence.append(paper_evidence)

    # 最终研究方向：官网没抓到方向（或方向全被模板过滤掉）但有论文时，
    # 用论文标题保守回填领域标签，避免这类导师在检索/云图里被埋没。
    publication_records = _dedupe_papers(publication_records)
    publications = [_strip_html(p.get("title") or "") for p in publication_records]
    backfilled_topics: list[str] = []
    if not topics_from_profile and publications:
        backfilled_topics = _paper_topics_from_titles(publications)
        if backfilled_topics:
            warnings.append(
                f"{name} 官网未抓到研究方向，已从论文标题回填 "
                f"{len(backfilled_topics)} 个方向：{'；'.join(backfilled_topics)}"
            )
    topics = [*topics_from_profile, *backfilled_topics]

    paper_methods = _paper_methods(" ".join(publications))

    # 2b) 主页方向证据：在论文回填确定 topics 之后再构建（若官网有方向/招生，
    #     或本次回填出方向），并把 research_topics 纳入其 supports_fields。
    if topics_from_profile or recruitment:
        supported: list[str] = []
        facts: list[str] = []
        if topics_from_profile:
            supported.append("research_topics")
            facts.append(f"研究方向包括：{'；'.join(topics_from_profile)}")
        if recruitment:
            supported.append("recruitment_status")
            facts.append(f"招生信息：{recruitment}")
        profile = {
            "evidence_id": f"ev_{candidate_id}_profile",
            "candidate_id": candidate_id,
            "source_type": "ustc_official_faculty_profile",
            "source_uri": mentor.get("profile_url", ""),
            "title": f"{name}的中科大官方个人主页",
            "extracted_fact": f"{name}官方个人主页；" + "；".join(facts) + "。",
            "locator": "研究方向/研究领域/个人简介",
            "retrieved_at": _utcnow_iso(),
            "freshness": "current",
            "confidence": 0.98,
            "metadata": {
                "identity_verified": True,
                "mentor_role_verified": True,
                "supports_fields": ",".join(supported),
                "ustc_faculty_id": faculty_id,
                "source_priority": "official_profile",
                # 标记该研究方向是否由论文回填，便于审计与后续人工校正。
                "topics_backfilled": bool(backfilled_topics),
            },
        }
        evidence.append(profile)

    evidence_refs = [e["evidence_id"] for e in evidence]
    # methods 仅来自论文标题的关键词命中（保守，不做推断），去重保序。
    seen: set[str] = set()
    merged_methods: list[str] = []
    for m in paper_methods:
        k = m.casefold()
        if k and k not in seen:
            seen.add(k)
            merged_methods.append(m)

    # source_metadata 只允许标量(str/int/float/bool)，None 值会触发 schema 校验失败，
    # 故富信息抽不到时不落键（保持精炼）。
    source_metadata = {
        "ustc_faculty_id": faculty_id,
        "english_name": mentor.get("english_name", ""),
        "academic_title": mentor.get("academic_title", ""),
        "mentor_role": role,
        # A 后端 CandidateMentor.source_metadata 仅允许标量(str/int/float/bool)，
        # 故把平台列表序列化为逗号分隔字符串（如 "openalex,s2,dblp"），避免 RAG 校验失败。
        "paper_platforms": ",".join(kept_platforms),
        "paper_review_platforms": ",".join(reviewed_platforms),
        "representative_publication_count": len(publications),
        # 1 = 官网抓到，2 = 论文回填，0 = 无方向。供云图/检索区分数据来源。
        "topics_source": 2 if backfilled_topics else (1 if topics_from_profile else 0),
        # 从官网个人主页富文本抽取的展示用富信息（D 侧详情页 bio/contact/recruiting 读取）。
        "profile_bio": profile_bio,
        "profile_email": profile_email,
        "profile_office": profile_office,
        "profile_graduated_from": profile_graduated_from,
        **paper_source_metadata,
    }
    if trusted_total_counts:
        publication_total_count, publication_count_source = max(trusted_total_counts)
        source_metadata["publication_total_count"] = publication_total_count
        source_metadata["publication_count_source"] = publication_count_source
    source_metadata = {k: v for k, v in source_metadata.items() if v is not None}

    candidate = {
        "candidate_id": candidate_id,
        "mentor_name": name,
        "affiliation": USTC_AFFILIATION,
        "department": mentor.get("college") or mentor.get("unit") or None,
        "research_topics": topics,
        "methods": merged_methods,
        "publications": publications,
        "projects": [],
        "homepage": mentor.get("profile_url") or None,
        "recruitment_status": recruitment,
        "evidence_refs": evidence_refs,
        "missing_fields": [],
        "source_metadata": source_metadata,
        "updated_at": _utcnow_iso(),
    }
    # 计算 missing_fields（与后端 _candidate_missing_fields 一致）。
    candidate["missing_fields"] = _missing_fields(candidate)
    return candidate, evidence, warnings


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        k = v.casefold()
        if k and k not in seen:
            seen.add(k)
            out.append(v)
    return out


def _missing_fields(candidate: dict) -> list[str]:
    fields = {
        "affiliation": candidate.get("affiliation"),
        "department": candidate.get("department"),
        "research_topics": candidate.get("research_topics"),
        "methods": candidate.get("methods"),
        "projects": candidate.get("projects"),
        "homepage": candidate.get("homepage"),
        "recruitment_status": candidate.get("recruitment_status"),
    }
    return [name for name, value in fields.items() if not value]


def main() -> None:
    parser = argparse.ArgumentParser(description="组装中科大导师 RAG 库")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument(
        "--papers", type=Path, action="append", default=[],
        help="论文源 JSON 路径，可多次指定以合并多平台（默认读取 "
        "ustc_mentor_papers.json / _s2 / _dblp 三个）。兼容旧单文件用法。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--role-overrides", type=Path, default=DEFAULT_ROLE_OVERRIDES)
    parser.add_argument("--paper-overrides", type=Path, default=DEFAULT_PAPER_OVERRIDES)
    args = parser.parse_args()

    if not args.raw.exists():
        print(f"找不到官网数据 {args.raw}，请先运行 ustc_scraper.py")
        return
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    mentors = raw.get("records", []) if isinstance(raw, dict) else []
    role_overrides: dict[str, dict] = {}
    if args.role_overrides.exists():
        override_payload = json.loads(args.role_overrides.read_text(encoding="utf-8"))
        role_overrides = override_payload.get("verified", {})
    paper_overrides: dict[str, dict[str, object]] = {}
    if args.paper_overrides.exists():
        override_payload = json.loads(args.paper_overrides.read_text(encoding="utf-8"))
        if isinstance(override_payload, dict):
            paper_overrides = {
                str(key): value for key, value in override_payload.items()
                if isinstance(value, dict)
            }

    # 论文源：未显式给 --papers 时用默认三平台；否则用显式列表（可多次）。
    paper_paths: list[Path] = args.papers or list(DEFAULT_PAPER_SOURCES.values())
    papers_by_faculty: dict[str, list[dict]] = {}
    for p in paper_paths:
        if not p.exists():
            continue
        papers_payload = json.loads(p.read_text(encoding="utf-8"))
        for rec in papers_payload.get("records", []) if isinstance(papers_payload, dict) else []:
            if isinstance(rec, dict) and rec.get("faculty_id"):
                # 跨平台通过 openalex/s2/dblp 字段区分，聚合到同一导师下。
                papers_by_faculty.setdefault(str(rec["faculty_id"]), []).append(rec)

    candidates: list[dict] = []
    evidence: list[dict] = []
    warnings: list[str] = []
    skipped_non_mentor = 0
    for mentor in mentors:
        faculty_id = str(mentor.get("faculty_id"))
        mentor = dict(mentor)
        override = role_overrides.get(faculty_id)
        if isinstance(override, dict) and override.get("mentor_role"):
            mentor.update({
                "mentor_role": override["mentor_role"],
                "mentor_role_verified": True,
                "mentor_role_verification_source": "official_profile_refresh",
            })
        paper_sources = papers_by_faculty.get(faculty_id, [])
        result = build_mentor(mentor, paper_sources, paper_overrides.get(faculty_id))
        if result is None:
            skipped_non_mentor += 1
            continue
        candidate, ev, mentor_warnings = result
        candidates.append(candidate)
        evidence.extend(ev)
        warnings.extend(mentor_warnings)

    payload = {
        "generated_at": _utcnow_iso(),
        "run_date": date.today().isoformat(),
        "source_chain": ["internal_ustc_rag"],
        "mentor_count": len(candidates),
        "evidence_count": len(evidence),
        "skipped_non_mentor": skipped_non_mentor,
        "warnings": warnings,
        "candidates": candidates,
        "evidence": evidence,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"完成：{len(candidates)} 位导师，{len(evidence)} 条证据，"
        f"跳过非导师 {skipped_non_mentor} 位，写入 {args.output}"
    )
    # 打印有论文的导师数与有研究方向数，便于核对。
    with_papers = sum(1 for c in candidates if c.get("publications"))
    with_topics = sum(1 for c in candidates if c.get("research_topics"))
    print(f"  含论文证据: {with_papers} 位；含研究方向: {with_topics} 位")
    dropped = [w for w in warnings if "同名错配" in w]
    if dropped:
        print(f"  方向一致性过滤丢弃 {len(dropped)} 条模糊命中论文证据")


if __name__ == "__main__":
    main()
