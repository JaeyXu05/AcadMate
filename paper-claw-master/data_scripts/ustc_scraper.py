"""USTC 官方教师库抓取脚本（自包含，仅依赖 httpx）。

遍历 9 个重点学院，调用中科大官方教师高级搜索 AJAX 端点，分页拉满每个学院的
导师列表，再抓取每位教师的官方个人主页，解析研究方向 / 导师角色 / 招生信息，
仅保留导师角色已核验的教师，产出 ``data/ustc_mentors_raw.json``。

实现说明：网关参数、URL 白名单校验和主页解析逻辑均忠实移植自后端
``backend/src/backend/mentor_workflow/ustc_sources.py`` 的
``HttpxUstcFacultyGateway`` / ``HttpxUstcProfileFetcher`` /
``parse_ustc_faculty_profile``，保证抓到的字段与工作流预期一致；但脚本本身
不 import 后端包，避免拖入 openai/langchain 等重型依赖，任何装了 httpx 的
Python 3.12+ 环境都能直接跑。

特性：
- 断点续抓：输出 JSON 中已有的 ``faculty_id`` 自动跳过。
- 容错：搜索分页、主页抓取、主页解析每步独立 try/except，记 warning 跳过。
- 限速：``--max-per-college`` 限制每学院抓取条数，``--delay`` 控制主页请求间隔。
- 全校模式：``--all-colleges`` 用空 ``collegeid`` 单流分页拉取全校所有教学单位
  （后端约定 ``USTC_ALL_TEACHING_UNITS_ID=""`` 即"全部教学单位"），每条记录自带
  ``collegeName`` 归属，不会因跨学院扫描丢失学院信息。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data" / "ustc_mentors_raw.json"

USTC_AFFILIATION = "中国科学技术大学"
USTC_FACULTY_SEARCH_PAGE = (
    "https://faculty.ustc.edu.cn/search.jsp?urltype=tree.TreeTempUrl&wbtreeid=1016"
)
USTC_FACULTY_SEARCH_ENDPOINT = (
    "https://faculty.ustc.edu.cn/system/resource/tsites/advancesearch.jsp"
)
# 与后端 USTC_COLLEGE_IDS 一致：9 个重点学院。
USTC_COLLEGE_IDS = {
    "数学科学学院": "1002",
    "信息科学技术学院": "1014",
    "计算机科学与技术学院": "1019",
    "人工智能与数据科学学院": "1155",
    "网络空间安全学院": "1154",
    "软件学院": "1023",
    "科技商学院、管理学院": "1010",
    "管理学院": "1010",
    "未来技术学院": "1280",
}
# 与后端 USTC_ALL_TEACHING_UNITS_ID 一致：空串表示"全部教学单位"。
USTC_ALL_TEACHING_UNITS_ID = ""
USER_AGENT = "Paper-Claw USTC mentor research"


# ---------------------------------------------------------------------------
# 官方搜索网关（移植自后端 HttpxUstcFacultyGateway）
# ---------------------------------------------------------------------------


def _required_ustc_url(value: str) -> str:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("USTC source URL must use HTTP or HTTPS")
    if hostname != "ustc.edu.cn" and not hostname.endswith(".ustc.edu.cn"):
        raise ValueError("USTC source URL must stay under an official ustc.edu.cn host")
    return re.sub(r"^http://", "https://", value.strip(), flags=re.IGNORECASE)


def _clean_text(value: object) -> str:
    return " ".join(html.unescape(str(value or "")).replace("\xa0", " ").split())


def _safe_int(value: object, default: int) -> int:
    if not isinstance(value, str | int):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _faculty_id_from_url(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.casefold().encode()).hexdigest()[:16]


def _faculty_record(payload: dict) -> dict | None:
    name = _clean_text(payload.get("showName") or payload.get("name"))
    profile_url = _https_url(_clean_text(payload.get("url")))
    if not name or not profile_url:
        return None
    try:
        _required_ustc_url(profile_url)
    except ValueError:
        return None
    faculty_id = _clean_text(payload.get("a")) or _faculty_id_from_url(profile_url)
    college = _clean_text(payload.get("collegeName")).replace("&nbsp;", " ") or _clean_text(
        payload.get("unit")
    )
    graduate_tutor_role = _clean_text(payload.get("gtutor"))
    doctoral_tutor_role = _clean_text(payload.get("doctorTutor"))
    mentor_role = "、".join(r for r in (doctoral_tutor_role, graduate_tutor_role) if r)
    mentor_role_verified = bool(graduate_tutor_role or doctoral_tutor_role)
    return {
        "faculty_id": faculty_id,
        "name": name,
        "english_name": _clean_text(payload.get("ename")),
        "college": college,
        "unit": _clean_text(payload.get("unit")),
        "academic_title": _clean_text(payload.get("prorank")),
        "graduate_tutor_role": graduate_tutor_role,
        "doctoral_tutor_role": doctoral_tutor_role,
        "mentor_role": mentor_role,
        "mentor_role_verified": mentor_role_verified,
        "profile_url": profile_url,
    }


def _https_url(value: str) -> str:
    return re.sub(r"^http://", "https://", value.strip(), flags=re.IGNORECASE)


def faculty_search(
    client: httpx.Client,
    *,
    college_id: str = "",
    page_index: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int, int]:
    """调用官方 AJAX 端点，返回 (记录列表, 总页数, 总记录数)。"""
    params: dict[str, str | int] = {
        "collegeid": college_id,
        "disciplineid": "0",
        "enrollid": "0",
        "pageindex": max(1, page_index),
        "pagesize": max(1, min(page_size, 50)),
        "rankid": "",
        "degreeid": "0",
        "honorid": "",
        "pinyin": "",
        "profilelen": "100",
        "teacherName": "",
        "searchDirection": "",
        "viewmode": "8",
        "viewid": "1066239",
        "siteOwner": "2006639312",
        "viewUniqueId": "1066239",
        "showlang": "zh_CN",
        "ispreview": "false",
        "basenum": "0",
        "ellipsis": "...",
        "alignright": "false",
        "productType": "0",
        "tutorType": "",
    }
    response = client.get(USTC_FACULTY_SEARCH_ENDPOINT, params=params)
    response.raise_for_status()
    _required_ustc_url(str(response.url))
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("USTC faculty search returned a non-object response")
    raw_records = payload.get("teacherData")
    if not isinstance(raw_records, list):
        raise ValueError("USTC faculty search returned no teacherData list")
    records = [
        record
        for item in raw_records
        if isinstance(item, dict) and (record := _faculty_record(item)) is not None
    ]
    total_pages = max(1, _safe_int(payload.get("totalpage"), 1))
    total_records = max(0, _safe_int(payload.get("totalnum"), 0))
    return records, total_pages, total_records


# ---------------------------------------------------------------------------
# 个人主页抓取 + 解析（移植自后端 HttpxUstcProfileFetcher / parse_ustc_faculty_profile）
# ---------------------------------------------------------------------------


def fetch_profile(client: httpx.Client, url: str, *, max_bytes: int = 2_000_000) -> str:
    safe_url = _required_ustc_url(url)
    response = client.get(safe_url)
    response.raise_for_status()
    _required_ustc_url(str(response.url))
    content_type = response.headers.get("content-type", "").casefold()
    if "html" not in content_type:
        raise ValueError("USTC faculty profile did not return HTML")
    if len(response.content) > max_bytes:
        raise ValueError("USTC faculty profile exceeded the response size limit")
    return response.text


class _VisibleTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "br", "div", "p", "li", "section", "article",
        "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [
            " ".join(html.unescape(line).split())
            for line in "".join(self.parts).splitlines()
        ]
        return "\n".join(line for line in lines if line)


def _visible_text(profile_html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(profile_html)
    return parser.text()


# 站点导航/版权/模板的"研究方向"污染词：抓取时被误当作研究方向的非方向文本。
# 命中即整条丢弃（不拆成部分），避免污染检索与云图 domain 分类。
# 注意：不含"研究方向/研究领域"这类也会出现在合法描述句里（如"研究方向涉及…"）
# 的泛词——那类前缀已由 _research_topics 的正则剥掉，这里只管明确无歧义的模板残留。
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
# 完全等于这些片段的短词也不构成研究方向（多为模板残留）。
_BOILERPLATE_TOPIC_EXACT = {"more", "gallery", "news", "vacancy"}
_POSTAL_CODE_TOPIC = re.compile(r"(?:邮\s*编|邮政编码).{0,12}\d{5,6}|^\d{6}$")

# 「成果/项目/荣誉」句判别标记：导师个人主页的「研究方向」段常紧跟一段
# 论文/项目/获奖叙述（如「主持/参与国家自然科学基金…」「在研项目」「多项竞赛中获奖」）。
# 这些是成果句而非研究方向（方向是名词短语），内联在方向段后、无换行，stop_markers
# 拦不住，必须在切分后逐片段筛掉，避免污染检索向量与云图 domain 分类。
_ACHIEVEMENT_TOPIC_MARKERS = (
    "主持", "参与", "承担", "在研", "立项", "结题",
    "基金", "项目", "课题", "计划", "基金资助",
    "课题资助", "项目资助", "人才项目", "人才计划",
    "国家自科", "国家自然科学", "国自然", "国家社科", "国家重点研发",
    "国家杰青", "杰青", "优青", "面上项目", "青年科学基金", "青年项目",
    "重点专项", "重大专项", "重大研究计划", "研究计划",
    "获奖", "荣获", "获得", "获", "荣誉", "奖项", "入选", "学会优秀",
    "取得了",
    "发表", "论文", "专利", "授权", "著作", "出版",
    "案例入库", "案例", "担任", "主编", "编委",
)
# 这些词单独出现过于泛，必须搭配其它成果词才判定为成果句，避免误杀合法方向。
_ACHIEVEMENT_SOFT_MARKERS = ("项目", "计划", "获奖", "论文")


def _is_achievement_topic(topic: str) -> bool:
    """判断一个 topic 片段是否为成果/项目/荣誉叙述而非研究方向。

    方向是名词短语（如"计算机视觉"、"强化学习"），成果句带动作/基金/荣誉词
    （如"主持国家自然科学基金青年项目"、"ISCAS 2023 竞赛获奖"）。命中硬标记
    直接判成果；命中软标记（"项目/计划/获奖/论文"）需再搭配至少一个其它成果
    信号（动词/基金/荣誉），降低对"储能项目"这类含"项目"的方向的误杀。
    """
    text = " ".join(str(topic).split())
    if not text:
        return True
    hard = [m for m in _ACHIEVEMENT_TOPIC_MARKERS if m in text]
    if hard:
        return True
    soft = [m for m in _ACHIEVEMENT_SOFT_MARKERS if m in text]
    return len(soft) >= 2



def _is_boilerplate_topic(topic: str) -> bool:
    lowered = topic.casefold()
    if lowered in _BOILERPLATE_TOPIC_EXACT:
        return True
    if _POSTAL_CODE_TOPIC.search(topic):
        return True
    return any(marker in topic for marker in _BOILERPLATE_TOPIC_MARKERS)


def _split_topics(value: str) -> list[str]:
    cleaned = re.sub(
        r"(?:社会兼职|团队成员|教育经历|工作经历|科研项目|论文成果).*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"[、，,；;|•·]|\s{2,}", cleaned)
    result: list[str] = []
    for part in parts:
        topic = re.sub(r"^\[?\d+\]?[.)、]?\s*", "", part)
        topic = topic.strip(" []()（）.。:：-*")
        if (
            2 <= len(topic) <= 120
            and "暂无内容" not in topic
            and topic.casefold() not in {"research focus", "research interests"}
            and not _is_boilerplate_topic(topic)
            and not _is_achievement_topic(topic)
        ):
            result.append(topic)
    return result


def _research_topics_all(text: str) -> list[str]:
    values: list[str] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    stop_markers = (
        "社会兼职", "团队成员", "教育经历", "工作经历", "科研项目",
        "论文成果", "招生信息", "学生信息", "个人信息", "联系方式",
        "其他联系方式", "社会服务", "获奖信息",
    )
    label_pattern = re.compile(
        r"^(?:主要)?(?:研究方向|研究领域)"
        r"(?:\s*Research (?:Focus|Interests?|Areas?))?"
        r"\s*(?:包括|为)?\s*[:：]?\s*",
        flags=re.IGNORECASE,
    )
    english_label_pattern = re.compile(
        r"^Research (?:Focus|Interests?|Areas?)\s*[:：]?\s*",
        flags=re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        content = label_pattern.sub("", line)
        content = english_label_pattern.sub("", content)
        if content != line and content:
            values.extend(_split_topics(content))
            continue
        if not label_pattern.search(line) and not english_label_pattern.search(line):
            continue
        for following in lines[index + 1 : index + 9]:
            if any(marker in following for marker in stop_markers) or re.search(
                r"(?:欢迎|招收|招生).{0,60}(?:博士|硕士|研究生|本科生|学生)",
                following,
            ):
                break
            values.extend(_split_topics(following))
    for pattern in (
        r"主要研究方向包括\s*([^\n。]{2,400})",
        r"主要从事\s*([^\n。]{2,300}?)(?:的研究|研究)",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            values.extend(_split_topics(match.group(1)))
    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = " ".join(value.split()).casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(value)
    # Cleaning and de-duplication happen before the safety cap.  This prevents
    # navigation/citation fragments from occupying all 20 retained slots.
    cleaned = [
        value for value in unique
        if not re.search(r"(?:https?://|\bdoi\b|网站访问量|总访问量|扫描手机二维码)", value, re.I)
        and value not in {"研究方向", "研究领域", "论文成果", "科研项目", "教学资源"}
    ]
    return cleaned


def _research_topics(text: str) -> list[str]:
    """Public compatibility wrapper with the audited 20-topic safety cap."""
    return _research_topics_all(text)[:20]


def _recruitment_status(text: str) -> str | None:
    for line in text.splitlines():
        normalized = " ".join(line.split())
        if re.search(
            r"(?:欢迎|招收|招生).{0,60}(?:博士|硕士|研究生|本科生|学生)",
            normalized,
        ):
            return normalized[:300]
    return None


def _role_verified_from_text(text: str) -> bool:
    return any(token in text for token in ("博士生导师", "硕士生导师", "博导", "硕导"))


# ---------------------------------------------------------------------------
# 主抓取流程
# ---------------------------------------------------------------------------


def load_existing(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return {}
    return {
        str(record.get("faculty_id") or record.get("profile_url")): record
        for record in records
        if isinstance(record, dict)
    }


def _process_record(
    client: httpx.Client,
    record: dict,
    *,
    delay: float,
    warnings: list[str],
    scope_label: str,
) -> tuple[dict | None, bool]:
    """抓取并解析单条搜索记录的个人主页。

    返回 ``(enriched_record_or_None, is_mentor)``：非导师返回 ``(None, False)``，
    主页抓取失败但仍核验为导师的返回带空 profile_text 的记录。
    """
    profile_text = ""
    research_topics: list[str] = []
    extracted_topics: list[str] = []
    recruitment_status: str | None = None
    try:
        profile_html = fetch_profile(client, record["profile_url"])
        profile_text = _visible_text(profile_html)
        extracted_topics = _research_topics_all(profile_text)
        research_topics = extracted_topics[:20]
        recruitment_status = _recruitment_status(profile_text)
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f"[{scope_label}] {record['name']} 主页抓取/解析失败: "
            f"{type(exc).__name__}: {exc}"
        )
    role_verified = bool(
        record["mentor_role_verified"] or _role_verified_from_text(profile_text)
    )
    if not role_verified:
        return None, False
    record.update(
        {
            "research_topics": research_topics,
            "topics_extracted_count": len(extracted_topics),
            "topics_truncated": len(extracted_topics) > 20,
            "recruitment_status": recruitment_status,
            "profile_text": profile_text,
            "affiliation": USTC_AFFILIATION,
        }
    )
    if delay:
        time.sleep(delay)
    return record, True


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取中科大官方教师库导师数据")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"输出 JSON 路径 (默认 {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--max-per-college", type=int, default=200,
        help="每个学院最多抓取多少条导师 (默认 200，0 表示不限制)；"
        "--all-colleges 模式下忽略",
    )
    parser.add_argument(
        "--max-total", type=int, default=0,
        help="全校模式下的全局抓取上限 (0 表示不限制)；仅 --all-colleges 生效",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="每次主页请求间隔秒数 (默认 0.5)",
    )
    parser.add_argument(
        "--timeout", type=float, default=15.0,
        help="官方端点请求超时秒数 (默认 15)",
    )
    parser.add_argument(
        "--colleges", nargs="*", default=None,
        help="只抓指定学院名 (默认全部 9 个)，例如 --colleges 人工智能；"
        "与 --all-colleges 互斥",
    )
    parser.add_argument(
        "--all-colleges", action="store_true",
        help="全校模式：用空 collegeid 单流分页拉取所有教学单位（含 9 学院之外的）",
    )
    args = parser.parse_args()

    if args.all_colleges and args.colleges:
        print("--all-colleges 与 --colleges 互斥，请二选一")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing(args.output)
    headers = {"User-Agent": USER_AGENT}
    warnings: list[str] = []
    max_per_college = args.max_per_college if args.max_per_college > 0 else 10**9
    max_total = args.max_total if args.max_total > 0 else 10**9

    new_count = 0
    mode = "all_colleges" if args.all_colleges else "key_colleges"
    with httpx.Client(
        follow_redirects=True, timeout=args.timeout, trust_env=False, headers=headers
    ) as client:
        if args.all_colleges:
            # 全校单流：空 collegeid 拉取所有教学单位，记录自带 collegeName 归属。
            print("=== 全校模式：抓取所有教学单位 (collegeid='') ===")
            collected = 0
            skipped_non_mentor = 0
            page_index = 1
            while collected < max_total:
                try:
                    page_records, total_pages, total_records = faculty_search(
                        client, college_id=USTC_ALL_TEACHING_UNITS_ID,
                        page_index=page_index, page_size=20,
                    )
                except Exception as exc:  # noqa: BLE001
                    warnings.append(
                        f"[all-colleges] 第 {page_index} 页搜索失败: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    break
                if not page_records:
                    break
                print(
                    f"  第 {page_index}/{total_pages} 页，本页 {len(page_records)} 条"
                    f"（共 {total_records} 条）"
                )
                for record in page_records:
                    if collected >= max_total:
                        break
                    key = str(record["faculty_id"])
                    if key in existing:
                        continue
                    enriched, is_mentor = _process_record(
                        client, record, delay=args.delay,
                        warnings=warnings, scope_label="all-colleges",
                    )
                    if not is_mentor:
                        skipped_non_mentor += 1
                        continue
                    existing[key] = enriched
                    collected += 1
                    new_count += 1
                if page_index >= total_pages:
                    break
                page_index += 1
            print(
                f"  全校新增 {collected} 位导师，跳过非导师 {skipped_non_mentor} 位，"
                f"累计 {len(existing)} 位"
            )
        else:
            colleges = USTC_COLLEGE_IDS
            if args.colleges:
                colleges = {
                    name: cid
                    for name, cid in USTC_COLLEGE_IDS.items()
                    if any(wanted in name for wanted in args.colleges)
                }
            if not colleges:
                print(f"未匹配到任何学院，可用学院: {list(USTC_COLLEGE_IDS)}")
                return
            for college_name, college_id in colleges.items():
                print(f"=== 抓取学院: {college_name} (id={college_id}) ===")
                collected = 0
                skipped_non_mentor = 0
                page_index = 1
                while collected < max_per_college:
                    try:
                        page_records, total_pages, total_records = faculty_search(
                            client, college_id=college_id,
                            page_index=page_index, page_size=20,
                        )
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(
                            f"[{college_name}] 第 {page_index} 页搜索失败: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        break
                    if not page_records:
                        break
                    for record in page_records:
                        if collected >= max_per_college:
                            break
                        key = str(record["faculty_id"])
                        if key in existing:
                            continue
                        enriched, is_mentor = _process_record(
                            client, record, delay=args.delay,
                            warnings=warnings, scope_label=college_name,
                        )
                        if not is_mentor:
                            skipped_non_mentor += 1
                            continue
                        existing[key] = enriched
                        collected += 1
                        new_count += 1
                    if page_index >= total_pages:
                        break
                    page_index += 1
                print(
                    f"  本学院新增 {collected} 位导师，跳过非导师 {skipped_non_mentor} 位，"
                    f"累计 {len(existing)} 位"
                )

    payload = {
        "run_date": date.today().isoformat(),
        "source": "ustc_official_faculty_directory + ustc_official_faculty_profile",
        "mode": mode,
        "college_count": len(USTC_COLLEGE_IDS),
        "record_count": len(existing),
        "warnings": warnings,
        "records": list(existing.values()),
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"\n完成：共 {len(existing)} 位导师（本次新增 {new_count}），写入 {args.output}"
    )
    if warnings:
        print(f"警告 {len(warnings)} 条（已写入 JSON 的 warnings 字段）")


if __name__ == "__main__":
    main()
