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


def boilerplate_garbage(candidates: list[dict]) -> int:
    """研究方向里残留的模板垃圾污染（自包含判定，避免依赖后端包）。"""
    markers = (
        "版权所有", "©", "地址：", "联系地址", "邮编", "邮政编码", "手机版",
        "收藏本站", "设为首页", "English", "Copyright", "Contact information",
        "友情链接", "更新时间", "个人简介", "实验室简介", "学校简介", "代表性成果",
        "代表成果", "授课信息", "教学研究", "教学成果", "著作成果", "研究成果",
        "成果简介", "科研成果", "科技成果转化", "获奖信息", "招生信息",
    )
    n = 0
    for c in candidates:
        for t in c.get("research_topics") or []:
            if any(m in t for m in markers):
                n += 1
    return n


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
    }


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
    args = parser.parse_args()

    if not args.rag.exists():
        print(f"找不到 RAG 库 {args.rag}")
        sys.exit(2)

    payload = load_json(args.rag)
    candidates = payload.get("candidates", [])
    evidence = payload.get("evidence", [])
    stats = candidate_stats(candidates)
    paper_stats = platform_paper_stats(candidates)
    garbage = boilerplate_garbage(candidates)
    raw = raw_potential(args.raw)
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
    if id_check["mismatched_id_suffix"]:
        print(f"  ID 后缀不一致：{id_check['mismatched_id_suffix']} 条")
    print("=" * 64)

    if raw:
        print("与 raw 数据的落差（raw 能支撑 → 库实际）:")
        gap_rows = [
            ("核验导师", raw["verified_mentors"], stats["total"]),
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
            "id_consistency": id_check,
            "raw_potential": raw,
        }
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"已写入 {args.out}")


if __name__ == "__main__":
    main()
