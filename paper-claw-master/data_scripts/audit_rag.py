"""RAG 库数据质量审计脚本（只读，不联网）。

对 ``data/ustc_mentor_rag.json`` 跑可复用的覆盖率体检，输出人类可读报告 + 可选结构化 JSON。
用于每次 re-build 后的质量门禁，比 verify_rag.py 的 E 项更细（分平台论文、email/bio、
英文名、垃圾残留、ID 一致性），并给出「raw 数据能支撑多少、库实际进多少」的落差。

用法：
  python data_scripts/audit_rag.py [--rag data/ustc_mentor_rag.json]
                                    [--raw data/ustc_mentors_raw.json]
                                    [--out data/audit_rag.json]

约束（与 data_scripts 其它脚本一致）：只依赖 stdlib；不联网；默认不写任何文件（除非 --out）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG = REPO_ROOT / "data" / "ustc_mentor_rag.json"
DEFAULT_RAW = REPO_ROOT / "data" / "ustc_mentors_raw.json"

_EMAIL_RE_BODY = r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"
_EMAIL_RE = re.compile(
    rf"\b{_EMAIL_RE_BODY}@{_EMAIL_RE_BODY}\.[A-Za-z0-9.-]+\.[A-Za-z]{{2,}}\b"
)
_EMAIL_BLACKLIST = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
    "@w3.org", "@example", "noreply", "no-reply",
}


def _fraction(n: int, d: int) -> float:
    return n / d if d else 0.0


def _pct(n: int, d: int) -> str:
    return f"{_fraction(n, d):.0%}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_platforms(c: dict) -> set[str]:
    val = c.get("source_metadata", {}).get("paper_platforms")
    if not val:
        return set()
    return {p.strip() for p in str(val).split(",") if p.strip()}


def extract_emails(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for email in _EMAIL_RE.findall(text or ""):
        low = email.lower()
        if any(bad in low for bad in _EMAIL_BLACKLIST):
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(email)
    return out


def _sm(c: dict, key: str) -> str:
    return c.get("source_metadata", {}).get(key, "")


def candidate_stats(candidates: list[dict]) -> dict:
    total = len(candidates)
    stats = {
        "total": total,
        "research_topics": 0,
        "methods": 0,
        "publications": 0,
        "projects": 0,
        "recruitment_status": 0,
        "homepage": 0,
        "english_name": 0,
        "profile_email": 0,
        "profile_bio": 0,
    }
    for c in candidates:
        if c.get("research_topics"):
            stats["research_topics"] += 1
        if c.get("methods"):
            stats["methods"] += 1
        if c.get("publications"):
            stats["publications"] += 1
        if c.get("projects"):
            stats["projects"] += 1
        if c.get("recruitment_status"):
            stats["recruitment_status"] += 1
        if c.get("homepage"):
            stats["homepage"] += 1
        if _sm(c, "english_name"):
            stats["english_name"] += 1
        if _sm(c, "profile_email"):
            stats["profile_email"] += 1
        if _sm(c, "profile_bio"):
            stats["profile_bio"] += 1
    return stats


def platform_paper_stats(candidates: list[dict]) -> dict:
    ct = Counter()
    with_pubs = 0
    for c in candidates:
        if c.get("publications"):
            with_pubs += 1
        for p in _split_platforms(c):
            ct[p] += 1
    return {"with_publications": with_pubs, "platform_coverage": dict(ct)}


_TOPIC_GARBAGE_MARKERS = (
        "版权所有", "©", "地址：", "联系地址", "邮编", "邮政编码", "手机版",
        "收藏本站", "设为首页", "English", "Copyright", "Contact information",
        "友情链接", "更新时间", "个人简介", "实验室简介", "学校简介", "代表性成果",
        "代表成果", "授课信息", "教学研究", "教学成果", "著作成果", "研究成果",
        "成果简介", "科研成果", "科技成果转化", "获奖信息", "招生信息",
        "访问量", "在线阅读链接",
        "欢迎点赞", "优秀实习生", "评审委员会", "谷歌学术引用",
        "Honors & Awards", "Social Affiliations",
)
_TOPIC_GARBAGE_EXACT = {
    "教学信息", "指导研究生及博士后", "在读研究生", "新闻", "新闻动态",
    "总访问量", "日访问量", "实验室概况", "研究兴趣",
    "主要研究方向但不局限于以下", "1）主要研究方向但不局限于以下",
}
_TOPIC_GARBAGE_PATTERNS = (
    re.compile(r"^中国科学技术大学.{0,30}(?:学院|实验室|中心)$"),
    re.compile(r"^中国科学院青年促进会(?:优秀)?会员"),
    re.compile(r"^[A-Za-z0-9＋+_-]{2,20}实验室$"),
    re.compile(r"(?:招收|招生|研究生课程|开设课程).{0,80}(?:博士|硕士|研究生|学生|课程)"),
    re.compile(r"^已在\s*(?:IEEE|ACM|Science|Nature)\b", re.I),
    re.compile(r"^(?:IEEE\s+Trans\..*|Pattern\s+Recognition|Science|Nature\s+Photonics|Physical\s+Review\s+Letters|ICIP\s+\d{4})$", re.I),
    re.compile(r"^\d{2}-\d{2}$"),
)


def topic_issues(candidates: list[dict]) -> list[dict]:
    """逐条返回确定污染与需人工复核项；不会把科研“导航”当站点导航。"""
    issues: list[dict] = []
    for c in candidates:
        for t in c.get("research_topics") or []:
            text = " ".join(str(t).split()).strip()
            category = None
            severity = None
            if (
                text in _TOPIC_GARBAGE_EXACT
                or any(m in text for m in _TOPIC_GARBAGE_MARKERS)
                or any(pattern.search(text) for pattern in _TOPIC_GARBAGE_PATTERNS)
                or re.search(r"https?://|\bDOI\s*:", text, re.I)
                or re.search(r"\b(?:Adv\. Mater|Angew\. Chem|Science)\b.{0,30}\b20\d{2}\b", text, re.I)
                or re.search(r"\b(?:I've been|I have been)\b.{0,40}\bprofessor\b", text, re.I)
            ):
                category, severity = "template_or_non_topic", "definite"
            elif len(text) > 80 or re.search(r"https?://|\bDOI\b", text, re.I):
                category, severity = "long_or_publication_like", "review"
            if category:
                issues.append({
                    "candidate_id": c.get("candidate_id"),
                    "mentor_name": c.get("mentor_name"),
                    "topic": text,
                    "category": category,
                    "severity": severity,
                })
    return issues


def bio_issues(candidates: list[dict]) -> list[dict]:
    markers = (
        "同专业博导", "同专业硕导", "总访问量", "日访问量", "扫描手机二维码",
        "版权所有", "网站访问量",
    )
    out: list[dict] = []
    for candidate in candidates:
        bio = str(_sm(candidate, "profile_bio") or "")
        hits = [marker for marker in markers if marker in bio]
        if hits:
            out.append({
                "candidate_id": candidate.get("candidate_id"),
                "mentor_name": candidate.get("mentor_name"),
                "markers": hits,
            })
    return out


def raw_potential(raw_path: Path | None) -> dict | None:
    if not raw_path or not raw_path.exists():
        return None
    recs = load_json(raw_path).get("records", [])
    verified = [r for r in recs if r.get("mentor_role_verified")]
    return {
        "total_records": len(recs),
        "verified_mentors": len(verified),
        "with_research_topics": sum(1 for r in verified if r.get("research_topics")),
        "with_english_name": sum(1 for r in verified if r.get("english_name")),
        "with_recruitment": sum(1 for r in verified if r.get("recruitment_status")),
        "with_profile_text": sum(1 for r in verified if (r.get("profile_text") or "").strip()),
        "excluded_records": len(recs) - len(verified),
    }


def excluded_role_review(raw_path: Path | None) -> list[dict]:
    if not raw_path or not raw_path.exists():
        return []
    recs = load_json(raw_path).get("records", [])
    out: list[dict] = []
    for record in recs:
        if record.get("mentor_role_verified"):
            continue
        profile_text = re.sub(
            r"[PM]同专业[博硕]导", "", str(record.get("profile_text") or "")
        )
        name = str(record.get("name") or "")
        role = r"(博士生导师|硕士生导师|博导|硕导)"
        title = r"(?:讲席教授|特任教授|副教授|教授|特任研究员|副研究员|研究员|正高级工程师)"
        match = None
        for pattern in (
            rf"{re.escape(name)}.{{0,150}}?{role}",
            rf"(?:现任|现为).{{0,100}}?{title}.{{0,20}}?{role}",
            rf"{title}[、，,\s]{{0,6}}{role}",
            rf"受聘{role}岗位",
            rf"(?:担任|聘为).{{0,50}}?{role}",
        ):
            match = re.search(pattern, profile_text, flags=re.DOTALL)
            if match:
                break
        latent_role = match.groups()[-1] if match else ""
        reason = (
            "recoverable_from_official_profile_text"
            if latent_role else "no_strong_mentor_role_in_stored_sources"
        )
        out.append({
            "faculty_id": str(record.get("faculty_id") or ""),
            "candidate_id": f"ustc_faculty_{record.get('faculty_id')}",
            "name": record.get("name") or "",
            "college": record.get("college") or record.get("unit") or "",
            "academic_title": record.get("academic_title") or "",
            "profile_url": record.get("profile_url") or "",
            "has_topics": bool(record.get("research_topics")),
            "has_recruitment": bool(record.get("recruitment_status")),
            "latent_role_token": latent_role,
            "exclusion_reason": reason,
            "review_status": "auto_recoverable" if latent_role else "pending",
            "proposed_confidence": 0.97 if latent_role else None,
        })
    return out


def id_consistency(candidates: list[dict]) -> dict:
    mismatched = 0
    for c in candidates:
        cid = c.get("candidate_id", "")
        fid = _sm(c, "ustc_faculty_id")
        if fid and str(cid) != f"ustc_faculty_{fid}":
            mismatched += 1
    return {"mismatched_id_suffix": mismatched}


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 覆盖审计")
    parser.add_argument("--rag", type=Path, default=DEFAULT_RAG)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--excluded-out", type=Path, default=None)
    args = parser.parse_args()

    if not args.rag.exists():
        print(f"找不到 RAG 库 {args.rag}")
        sys.exit(2)

    payload = load_json(args.rag)
    candidates = payload.get("candidates", [])
    evidence = payload.get("evidence", [])
    stats = candidate_stats(candidates)
    paper_stats = platform_paper_stats(candidates)
    issues = topic_issues(candidates)
    biography_issues = bio_issues(candidates)
    garbage = sum(1 for item in issues if item["severity"] == "definite")
    review_topics = sum(1 for item in issues if item["severity"] == "review")
    raw = raw_potential(args.raw)
    excluded = excluded_role_review(args.raw)
    if raw is not None:
        raw["profile_recoverable"] = sum(
            1 for item in excluded if item["review_status"] == "auto_recoverable"
        )
        raw["effective_verified_mentors"] = (
            raw["verified_mentors"] + raw["profile_recoverable"]
        )
    id_check = id_consistency(candidates)

    print("=" * 64)
    print(f"RAG 覆盖审计：{args.rag.name}")
    print(f"  导师 {stats['total']} · 证据 {len(evidence)} 条")
    print("-" * 64)
    rows = [
        ("research_topics", "研究方向"),
        ("methods", "研究方法"),
        ("publications", "代表论文"),
        ("recruitment_status", "招生信息"),
        ("english_name", "英文名"),
        ("profile_email", "email"),
        ("profile_bio", "bio(简介)"),
        ("projects", "项目"),
        ("homepage", "主页"),
    ]
    for key, label in rows:
        n = stats.get(key, 0)
        print(f"  {label:<12} {n:>4}/{stats['total']:<4}  {_pct(n, stats['total'])}")
    print("-" * 64)
    pc = paper_stats["platform_coverage"]
    if pc:
        for k, n in sorted(pc.items(), key=lambda kv: -kv[1]):
            print(f"  论文平台 {k:<9} {n}")
    else:
        print("  论文平台覆盖：无 paper_platforms 标记")
    if garbage:
        print(f"  方向垃圾残留：{garbage} 条（建议清理）")
    if review_topics:
        print(f"  方向待人工复核：{review_topics} 条")
    if biography_issues:
        print(f"  bio 模板残留：{len(biography_issues)} 位")
    if id_check["mismatched_id_suffix"]:
        print(f"  ID 后缀不一致：{id_check['mismatched_id_suffix']} 条")
    print("=" * 64)

    if raw:
        print("与 raw 数据的落差（raw 能支撑 → 库实际）:")
        gap_rows = [
            ("有效核验导师", raw["effective_verified_mentors"], stats["total"]),
            ("研究方向", raw["with_research_topics"], stats["research_topics"]),
            ("英文名", raw["with_english_name"], stats["english_name"]),
            ("招生", raw["with_recruitment"], stats["recruitment_status"]),
        ]
        for label, potential, actual in gap_rows:
            flag = "  [!] 落差大" if potential and _fraction(actual, potential) < 0.6 else ""
            print(f"  {label:<8} {actual:>4} / {potential}   {_pct(actual, potential)}{flag}")
        print("=" * 64)

    if args.out:
        report = {
            "rag": str(args.rag),
            "stats": stats,
            "paper_platforms": pc,
            "with_publications": paper_stats["with_publications"],
            "garbage_topics": garbage,
            "topic_issues": issues,
            "bio_issues": biography_issues,
            "id_consistency": id_check,
            "raw_potential": raw,
        }
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"已写入 {args.out}")

    if args.excluded_out:
        args.excluded_out.write_text(
            json.dumps({"count": len(excluded), "records": excluded}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已写入未核验导师审查表 {args.excluded_out}")


if __name__ == "__main__":
    main()
