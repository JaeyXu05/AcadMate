"""组装 RAG 库：把官网 + OpenAlex 数据合成符合工作流 schema 的记录。

读取 ``data/ustc_mentors_raw.json``（官网导师）和各论文平台的
（OpenAlex ``ustc_mentor_papers.json`` / S2 ``ustc_mentor_papers_s2.json`` /
DBLP ``ustc_mentor_papers_dblp.json``）论文，为每位导师生成：

- 一条 ``CandidateMentor``（含 ``candidate_id`` / ``mentor_name`` / ``affiliation`` /
  ``department`` / ``research_topics`` / ``methods`` / ``publications`` /
  ``homepage`` / ``recruitment_status`` / ``evidence_refs`` / ``source_metadata``）。
- 2~3 条 ``EvidenceRecord``：
    1. 身份证据（官方教师目录）：``identity_verified=true``、
       ``mentor_role_verified=true``、``supports_fields=affiliation,department,homepage``。
    2. 主页方向证据（若解析到研究方向/方法/招生）。
    3. 论文证据（若 OpenAlex 解析到论文）：``supports_fields=research_topics,methods,publications``。

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
DEFAULT_MANUAL_OVERRIDES = REPO_ROOT / "data" / "manual_overrides.json"
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
    """Boundary-aware bilingual phrase matching (``soc`` must not match social)."""
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


def _paper_methods(titles: list[str]) -> list[str]:
    """Only keep a method supported by at least two distinct verified papers."""
    hits = {
        method: sum(_keyword_in_title(method, title) for title in titles)
        for method in _METHOD_KEYWORDS
    }
    return [method for method in _METHOD_KEYWORDS if hits[method] >= 2]


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
    "查看更多", "暂无内容", "网站访问量",
}
_BIO_NAVIGATION_LINES = {
    "研究领域", "研究方向", "论文成果", "论文发表", "论文发表", "论文列表",
    "代表性论文", "专利", "科研项目", "教学资源", "学生信息", "我的相册",
    "教师博客", "其他栏目", "语种", "语言选择", "基本信息", "个人信息",
    "联系方式", "其他联系方式", "社会兼职", "学术交流情况", "研究团队",
    "研究论文", "科研项目", "教育经历", "工作经历", "招聘信息", "招生招聘",
    "科研队伍", "科研进展", "文章发表", "组内相册", "中文主页", "研究组快讯",
    "新闻动态", "团队风采",
    "暑期学校", "招生要求", "教学案例", "出版书籍", "企业咨询",
    "Home", "Research", "Publications", "Activities",
}
_BIO_SECTION_BOUNDARIES = {"教育经历", "工作经历", "社会兼职", "学术兼职"}
_BIO_ENGLISH_SECTION_BOUNDARIES = (
    "education background", "work experience", "social affiliations", "academic affiliations",
)
_BIO_NOISE_SUBSTRINGS = (
    "扫描手机二维码", "手机扫描二维码", "即可访问本教师主页", "欢迎您的访问",
    "您是第", "位访客", "开通时间", "访问量", "手机版",
)


def _extract_bio(profile_text: str, name: str, max_len: int = 600) -> str | None:
    """从个人主页正文抽一段可读的导师简介（去导航/键值/footer）。

    策略：按行清洗，去掉站点导航、QR 码提示、访客计数字样、底部版权、
    「标签:值」键值行与标题面包屑，保留含导师姓名的连贯散文段落。
    """
    text = (profile_text or "").strip()
    if not text:
        return None

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        # 履历、任职与社会兼职不是导师简介；在第一个结构化章节前截断，
        # 防止简介被大段简历和站点栏目淹没。
        compact = re.sub(r"[\s|]+", "", line).casefold()
        if line in _BIO_SECTION_BOUNDARIES or any(
            phrase in compact for phrase in _BIO_ENGLISH_SECTION_BOUNDARIES
        ):
            break
        if _is_boilerplate_topic(line):
            continue
        if line in _BIO_NOISE_LINES or line in _BIO_NAVIGATION_LINES:
            continue
        if compact in {re.sub(r"[\s|]+", "", item).casefold() for item in _BIO_NAVIGATION_LINES}:
            continue
        if any(
            marker in compact
            for marker in (
                "personalinformation", "othercontactinformation", "researchfocus",
                "同专业博导", "同专业硕导", "researchteam", "researchnews",
            )
        ):
            continue
        if any(marker in line for marker in _BIO_NOISE_SUBSTRINGS):
            continue
        # 标题面包屑「中国科学技术大学 曾晋哲--曾晋哲--首页」这类含 "--" 的标题行。
        if "--" in line and (name in line or "首页" in line):
            continue
        # 同专业博导/硕导的英文占位「P同专业博导」「M同专业硕导」。
        if re.fullmatch(r"[PM]同专业[博硕]导", line):
            continue
        if line == name or re.fullmatch(rf"{re.escape(name)}\s*\([^)]{{1,20}}\)", line):
            continue
        if re.fullmatch(r"(?:博士生导师|硕士生导师|教授|副教授|研究员|副研究员|特任教授)", line):
            continue
        if line in {"|", ">", ">>"}:
            continue
        if re.fullmatch(r"-?\s*(?:19|20)\d{2}[./-]\d{1,2}(?:[./-]\d{1,2})?", line):
            continue
        if line.startswith(("○ 热烈欢迎", "○ 诚挚欢迎", "○ 热烈祝贺", "恭喜")):
            continue
        # 「标签:值」键值行跳过（邮箱哈希/办公地点等）与未知标签。
        if re.match(r"^[^：:]{1,10}[:：]", line):
            label = re.split(r"[:：]", line, maxsplit=1)[0].strip()
            if any(kw in label for kw in _BIO_KEY_VALUE_LABELS):
                continue
            continue  # 其它「标签:值」行同样非散文，一并丢弃
        lines.append(line)

    cleaned = "\n".join(lines)
    # 底部版权 footer 之后的内容截断。
    cleaned = re.split(r"(?:版权所有|Copyright|©)\s*©?[0-9]*", cleaned)[0].strip()
    if not cleaned:
        return None

    bio = cleaned
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
_OFFICIAL_METHOD_LEXICON = [
    ("强化学习", "强化学习"),
    ("reinforcement learning", "reinforcement learning"),
    ("图神经网络", "图神经网络"),
    ("graph neural network", "graph neural network"),
    ("gnn", "graph neural network"),
    ("深度学习", "深度学习"),
    ("deep learning", "deep learning"),
    ("机器学习", "机器学习"),
    ("machine learning", "machine learning"),
    ("神经网络", "神经网络"),
    ("neural network", "neural network"),
    ("transformer", "Transformer"),
    ("扩散模型", "扩散模型"),
    ("diffusion model", "diffusion model"),
    ("大语言模型", "大语言模型"),
    ("large language model", "large language model"),
    ("对比学习", "对比学习"),
    ("contrastive learning", "contrastive learning"),
    ("自监督", "自监督学习"),
    ("self-supervised", "self-supervised learning"),
]


def _official_methods_from_topics(topics: list[str]) -> list[str]:
    methods: list[str] = []
    for keyword, label in _OFFICIAL_METHOD_LEXICON:
        if any(_keyword_in_title(keyword, topic) for topic in topics):
            methods.append(label)
    return _dedupe(methods)

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
_BOILERPLATE_TOPIC_EXACT = {"more", "gallery", "news", "vacancy"}
_POSTAL_CODE_TOPIC = re.compile(r"(?:邮\s*编|邮政编码).{0,12}\d{5,6}|^\d{6}$")

# 官网个人主页的栏目导航、访问计数和论文列表有时会被抓取器误当成研究方向。
# 这些规则只排除可明确判定为页面结构/引文碎片的内容；正常的中英文研究表述保留。
_NAVIGATION_TOPIC_EXACT = {
    "登录", "首页", "研究方向", "研究领域", "科研进展", "教学资源", "团队风采",
    "新闻动态", "组内相册", "其他栏目", "招生招聘", "招生信息", "论文成果",
    "论文发表", "论文发表", "代表性论文", "代表性成果", "科研项目", "项目成果",
    "学生信息", "我的相册", "教师博客", "个人主页", "基本信息", "联系方式",
    "教育经历", "工作经历", "社会兼职", "语种", "语言选择", "中文主页",
    "总访问量", "日访问量", "网站访问量", "访问量", "浏览量", "团队成员",
}
_NAVIGATION_TOPIC_MARKERS = (
    "总访问量", "日访问量", "网站访问量", "您是第", "扫描手机二维码",
    "欢迎访问", "点击查看", "在线阅读链接", "http://", "https://",
)
_BIBLIOGRAPHY_TOPIC_MARKERS = (
    "et al", "doi", "vol.", "pp.", "paper no.", "journal of ",
    "adv. mater", "angew.", "sci adv", "nat ", "pnas", "ultramicroscopy",
)
_BIBLIOGRAPHY_TOPIC_RE = re.compile(
    r"\b(?:J\s*(?:Am|Phys|Chem)|Nat(?:ure)?\b|Angew(?:andte)?\b|"
    r"Adv(?:anced)?\b|Sci\s+Adv\b|PNAS\b|Macromolecules\b|Ultramicroscopy\b)",
    re.IGNORECASE,
)
_DATE_ONLY_TOPIC = re.compile(r"(?:(?:19|20)\d{2}(?:[-./]\d{1,2}){0,2}|\d{1,2}[-./]\d{1,2})$")
_BIBLIOGRAPHY_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_LATIN_NAME_FRAGMENT = re.compile(r"^[A-Z][a-z]{1,20}$")
_BIBLIOGRAPHY_IDENTIFIER = re.compile(r"^(?:e\d{4,}|\d{4,})$", re.IGNORECASE)
_ROLE_OR_ADMISSION_TOPIC = re.compile(
    r"(?:博士生导师|硕士生导师|招收(?:硕士|博士|研究生)|欢迎.*(?:报考|加入|联系))"
)
_METHOD_OR_CV_TOPIC = re.compile(
    r"^(?:使用|采用|利用|通过|借助)|(?:辅助图像处理|仿真模拟等?手段|等方法(?:开展|进行)|实验手段)"
)
_NON_TOPIC_CREDENTIAL = re.compile(
    r"(?:实习生|评审|职务|Fellow|Distinguished Paper|Best Paper|获奖|人才计划)",
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
    "获奖", "荣获", "荣誉", "奖项", "入选", "学会优秀", "取得了", "人才", "学者",
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
    return any(marker in topic for marker in _BOILERPLATE_TOPIC_MARKERS)


def _clean_topic(topic: object, mentor_name: str) -> str | None:
    """保守清洗官网方向条目，丢弃导航、计数器及参考文献碎片。

    原始页面把栏目、访问统计和部分论文列表与研究方向混在同一文本块时，
    scraper 会按分隔符切成短条目。这里在最终 RAG 出口再次过滤，保证已有
    原始数据重建时也不会重新污染检索语料。
    """
    text = " ".join(str(topic or "").replace("\u200b", "").split()).strip(" ，,；;、|：:．.")
    if not text:
        return None
    # 去除列表编号；不改正文，避免损失诸如“3D 视觉”里的数字。
    text = re.sub(r"^(?:\[?\d{1,2}\]?|[①-⑳])\s*[.、)）]\s*", "", text)
    normalized = text.casefold()
    if not text or normalized in _NAVIGATION_TOPIC_EXACT:
        return None
    if _DATE_ONLY_TOPIC.fullmatch(text):
        return None
    if _is_boilerplate_topic(text) or _is_achievement_topic(text):
        return None
    if any(marker.casefold() in normalized for marker in _NAVIGATION_TOPIC_MARKERS):
        return None
    # 单独的人名、导师身份与招生文案不是研究主题。
    if text == mentor_name or _LATIN_NAME_FRAGMENT.fullmatch(text) or _BIBLIOGRAPHY_IDENTIFIER.fullmatch(text):
        return None
    if _ROLE_OR_ADMISSION_TOPIC.search(text):
        return None
    if _METHOD_OR_CV_TOPIC.search(text) or _NON_TOPIC_CREDENTIAL.search(text):
        return None
    if len(text) > 120:
        return None
    # 引文标题本身不是“研究方向”。有期刊/作者格式、或年份与论文格式并存时排除。
    bibliography_marker = any(marker in normalized for marker in _BIBLIOGRAPHY_TOPIC_MARKERS)
    if bibliography_marker or _BIBLIOGRAPHY_TOPIC_RE.search(text) or (
        _BIBLIOGRAPHY_YEAR.search(text)
        and ("." in text or "," in text or "(" in text or ")" in text)
    ):
        # 研究方向后接“近年在某期刊发表”等引文时，保留引文前的完整主题句；
        # 若本身就是期刊名/论文标题，则没有可保留的前缀，直接丢弃。
        prefix = re.split(r"[。；;]", text, maxsplit=1)[0].strip()
        if prefix and prefix != text and not _BIBLIOGRAPHY_TOPIC_RE.search(prefix):
            return _clean_topic(prefix, mentor_name)
        return None
    return text


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
    """Return verified/pending/rejected; exact name equality is never verification."""
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


def _source_metrics(record: dict) -> dict[str, int | float]:
    """提取论文平台已抓到的作者级统计，供候选记录展示和审计。

    ``publications`` 只保存代表论文标题，长度不能代表作者总论文数。平台返回的
    works/paper/pub count 与 cited-by count 是独立、可验证的原始统计，之前在组装时
    被丢弃；保留为 source_metadata 标量键，不改变 CandidateMentor schema。
    """
    keys = (
        "openalex_works_count", "openalex_cited_by_count",
        "s2_paper_count", "s2_cited_by_count", "dblp_pub_count",
    )
    out: dict[str, int | float] = {}
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            out[key] = value
    return out


def build_mentor(
    mentor: dict,
    paper_sources: list[dict],
    manual_overrides: dict[str, dict[str, object]] | None = None,
) -> tuple[dict, list[dict], list[str]] | None:
    """为单个导师生成 (candidate_dict, evidence_list, warnings)；非导师返回 None。

    ``paper_sources`` 是该导师在 OpenAlex / S2 / DBLP 各平台的论文记录列表，
    可以多源同时存在；build 时按来源逐平台做方向一致性过滤并合并去重。
    """
    faculty_id = str(mentor.get("faculty_id"))
    name = mentor.get("name", "")
    if not faculty_id or not name:
        return None
    if not mentor.get("mentor_role_verified"):
        return None

    candidate_id = _candidate_id(faculty_id)
    manual_overrides = manual_overrides or {}
    evidence: list[dict] = []
    warnings: list[str] = []

    # 从官网个人主页富文本抽取 bio / email / 办公地点 / 毕业院校（此前完全被丢弃）。
    profile_text = mentor.get("profile_text") or ""
    profile_email = _extract_email(profile_text)
    profile_bio = _extract_bio(profile_text, name)
    profile_office = _extract_office(profile_text)
    profile_graduated_from = _extract_graduated_from(profile_text)
    if not profile_email and "@" in profile_text:
        warnings.append(f"{name} 官网个人主页存在邮箱但为非明文（站方加密），未抽取到 email")

    # 1) 身份证据：官方教师目录。
    role = mentor.get("mentor_role", "")
    identity_fact = (
        f"中科大官方教师系统列出{name}，单位为"
        f"{mentor.get('college') or mentor.get('unit') or USTC_AFFILIATION}"
        + (f"，导师类型为{role}" if role else "")
        + "。"
    )
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
        "confidence": 0.99,
        "metadata": {
            "identity_verified": True,
            "mentor_role_verified": True,
            "supports_fields": "affiliation,department,homepage",
            "ustc_faculty_id": faculty_id,
            "source_priority": "official",
        },
    }
    evidence.append(identity)

    # 2) 主页方向（官网解析，先去模板/版权污染）：最终 research_topics 在
    #    处理论文回填后确定（见下方 _finalize_topics），此处仅做源中的初值。
    topics_from_profile = _dedupe([
        cleaned
        for topic in (mentor.get("research_topics") or [])
        if (cleaned := _clean_topic(topic, name))
    ])
    official_methods = _official_methods_from_topics(topics_from_profile)
    recruitment = mentor.get("recruitment_status")
    # 搜索页标题有时被误识别为招生信息，例如“某某--欢迎访问…--首页”。
    if recruitment and any(marker in recruitment for marker in _NAVIGATION_TOPIC_MARKERS):
        recruitment = None

    # 3) 论文证据：合并 OpenAlex / S2 / DBLP 各来源代表论文，逐平台做方向
    #    一致性过滤后统一去重，补 publications / methods / 论文证据。
    publications: list[str] = []
    paper_methods: list[str] = []
    kept_platforms: list[str] = []
    pending_platforms: list[str] = []
    platform_counts: dict[str, int] = {}
    source_metrics: dict[str, int | float] = {}
    for source in paper_sources:
        papers = _source_papers(source)
        if not papers:
            continue
        platform = _source_platform(source)
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
        identity_status, identity_reason = _paper_identity_status(
            faculty_id, source, manual_overrides
        )
        drop_reason = None
        uncertain_reason = None
        consistency = _direction_consistency(topics_from_profile, titles) if titles else "no_titles"
        if identity_status == "rejected":
            drop_reason = (
                f"{name} {platform} 作者实体被人工裁决拒绝或与裁决 ID 不一致，"
                "丢弃该平台论文证据"
            )
        elif identity_status == "pending" and consistency == "mismatch":
            drop_reason = (
                f"{name} {platform} 作者待核验，且论文标题与官网方向同语言无重叠，"
                "作为疑似同名错配丢弃"
            )
        elif identity_status == "pending" and titles:
            uncertain_reason = (
                f"{name} {platform} 作者实体待核验（exact_match={exact_match}），"
                f"一致性={consistency}；论文只进入待审队列，不建立导师事实"
            )
        if drop_reason:
            warnings.append(drop_reason)
            continue
        if uncertain_reason:
            warnings.append(uncertain_reason)
        if identity_status == "verified":
            publications.extend(titles)
            kept_platforms.append(platform)
            platform_counts[platform] = platform_counts.get(platform, 0) + 1
            source_metrics.update(_source_metrics(source))
        else:
            pending_platforms.append(platform)
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
            "confidence": 0.98 if identity_status == "verified" else 0.45,
            "metadata": {
                "identity_verified": identity_status == "verified",
                "mentor_role_verified": False,
                "supports_fields": (
                    "research_topics,methods,publications"
                    if identity_status == "verified"
                    else "candidate_paper_leads"
                ),
                "source_platform": platform,
                "source_priority": "paper_supplement",
                "paper_count": len(papers),
                "identity_review_status": identity_status,
                "identity_review_reason": identity_reason,
                "name_exact_match": exact_match is True,
                "direction_consistency": consistency,
            },
        }
        # 保留来源 ID 到 metadata，便于回溯。
        for src_key in ("openalex_author_id", "s2_author_id", "dblp_pid"):
            if source.get(src_key) is not None:
                paper_evidence["metadata"][src_key] = source.get(src_key)
        paper_evidence["metadata"].update(_source_metrics(source))
        evidence.append(paper_evidence)

    # 最终研究方向：官网没抓到方向（或方向全被模板过滤掉）但有论文时，
    # 用论文标题保守回填领域标签，避免这类导师在检索/云图里被埋没。
    publications = _dedupe(publications)
    backfilled_topics: list[str] = []
    if not topics_from_profile and publications:
        backfilled_topics = _paper_topics_from_titles(publications)
        if backfilled_topics:
            warnings.append(
                f"{name} 官网未抓到研究方向，已从论文标题回填 "
                f"{len(backfilled_topics)} 个方向：{'；'.join(backfilled_topics)}"
            )
    topics = [*topics_from_profile, *backfilled_topics]

    paper_methods = _paper_methods(publications)

    # 2b) 官网证据只陈述官网事实，绝不混入论文推断方向。
    if topics_from_profile or recruitment:
        supported: list[str] = []
        facts: list[str] = []
        if topics_from_profile:
            supported.append("research_topics")
            facts.append(f"研究方向包括：{'；'.join(topics_from_profile)}")
        if official_methods:
            supported.append("methods")
            facts.append(f"官网方向明确提及方法：{'；'.join(official_methods)}")
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
                "topics_backfilled": False,
            },
        }
        evidence.append(profile)

    # 已核验论文推断方向使用独立证据，不能伪装成官网事实。
    if backfilled_topics:
        evidence.append({
            "evidence_id": f"ev_{candidate_id}_verified_paper_topics",
            "candidate_id": candidate_id,
            "source_type": "verified_paper_topic_inference",
            "source_uri": mentor.get("profile_url", ""),
            "title": f"{name}的已核验论文方向推断",
            "extracted_fact": f"由已核验作者论文支持的方向：{'；'.join(backfilled_topics)}。",
            "locator": "verified paper titles / controlled lexicon",
            "retrieved_at": _utcnow_iso(),
            "freshness": "recent",
            "confidence": 0.8,
            "metadata": {
                "identity_verified": True,
                "mentor_role_verified": True,
                "supports_fields": "research_topics",
                "source_priority": "verified_paper_inference",
                "topics_backfilled": True,
            },
        })

    evidence_refs = [e["evidence_id"] for e in evidence]
    # methods 仅来自论文标题的关键词命中（保守，不做推断），去重保序。
    seen: set[str] = set()
    merged_methods: list[str] = []
    for m in [*official_methods, *paper_methods]:
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
        "pending_paper_platforms": ",".join(_dedupe(pending_platforms)),
        # 1 = 官网抓到，2 = 论文回填，0 = 无方向。供云图/检索区分数据来源。
        "topics_source": 3 if backfilled_topics else (1 if topics_from_profile else 0),
        "methods_verified": bool(merged_methods),
        "paper_identity_verified": bool(kept_platforms),
        "topics_extracted_count": int(mentor.get("topics_extracted_count") or len(mentor.get("research_topics") or [])),
        "topics_truncated": bool(mentor.get("topics_truncated", False)),
        # 从官网个人主页富文本抽取的展示用富信息（D 侧详情页 bio/contact/recruiting 读取）。
        "profile_bio": profile_bio,
        "profile_email": profile_email,
        "profile_office": profile_office,
        "profile_graduated_from": profile_graduated_from,
        # 作者级总论文/被引统计（仅精确匹配平台），与 publications 的代表论文列表互补。
        **source_metrics,
    }
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


def _dedupe(values: list[str]) -> list[str]:
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
    parser.add_argument(
        "--manual-overrides", type=Path, default=DEFAULT_MANUAL_OVERRIDES,
        help="人工作者实体裁决（默认 data/manual_overrides.json）",
    )
    args = parser.parse_args()

    if not args.raw.exists():
        print(f"找不到官网数据 {args.raw}，请先运行 ustc_scraper.py")
        return
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    mentors = raw.get("records", []) if isinstance(raw, dict) else []
    manual_overrides: dict[str, dict[str, object]] = {}
    if args.manual_overrides.exists():
        loaded_overrides = json.loads(args.manual_overrides.read_text(encoding="utf-8"))
        if isinstance(loaded_overrides, dict):
            manual_overrides = {
                str(key): value
                for key, value in loaded_overrides.items()
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
        paper_sources = papers_by_faculty.get(faculty_id, [])
        result = build_mentor(mentor, paper_sources, manual_overrides)
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
