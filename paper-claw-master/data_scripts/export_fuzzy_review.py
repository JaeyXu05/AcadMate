"""导出多平台模糊命中导师的人工裁决对照表。

把各论文平台（OpenAlex / Semantic Scholar / DBLP）里所有模糊/非精确命中的导师，
连同其官网研究方向、命中作者实体和代表论文标题，导出成一份统一对照表，供人工裁决。

输出两种格式：
- ``data/fuzzy_review.md``  —— 人眼可读的 Markdown 表格 + 逐人详情，每平台一列。
- ``data/fuzzy_review.json`` —— 结构化，每条带空 ``verdict`` 待填。

裁决后可把结果写成 ``data/manual_overrides.json``（faculty_id -> platform:author_id 或 null），
供各 scraper 优先读取（长期方案，见 README）。

使用方式：
    # 自动读 data/ 下所有可用 papers JSON（默认）：
    python data_scripts/export_fuzzy_review.py

    # 只导出指定平台：
    python data_scripts/export_fuzzy_review.py --papers data/ustc_mentor_papers.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = REPO_ROOT / "data" / "ustc_mentors_raw.json"
DEFAULT_OVERRIDES = REPO_ROOT / "data" / "manual_overrides.json"

# 平台配置：文件路径、非精确命中的字段名、命名字段前缀、平台中文名。
_SOURCES: list[dict] = [
    {
        "path": REPO_ROOT / "data" / "ustc_mentor_papers.json",
        "fuzzy_field": "openalex_exact_match",
        "display_name": "openalex_display_name",
        "author_id": "openalex_author_id",
        "works_count": "openalex_works_count",
        "label": "OpenAlex",
        "cited_field": "cited_by_count",
    },
    {
        "path": REPO_ROOT / "data" / "ustc_mentor_papers_s2.json",
        "fuzzy_field": "s2_exact_match",
        "display_name": "s2_display_name",
        "author_id": "s2_author_id",
        "works_count": "s2_paper_count",
        "label": "Semantic Scholar",
        "cited_field": "cited_by_count",
    },
    {
        "path": REPO_ROOT / "data" / "ustc_mentor_papers_dblp.json",
        "fuzzy_field": "dblp_exact_match",
        "display_name": "dblp_display_name",
        "author_id": "dblp_pid",
        "works_count": "dblp_pub_count",
        "label": "DBLP",
        "cited_field": None,  # DBLP 无被引量
    },
]


def _load_papers(file: Path) -> dict[str, dict]:
    if not file.exists():
        return {}
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return {}
    return {
        str(rec.get("faculty_id")): rec
        for rec in records
        if isinstance(rec, dict) and rec.get("faculty_id")
    }


def _paper_summary(papers: list[dict], *, cited_field: str | None, limit: int = 2) -> str:
    """论文标题摘要（年+标题截断），用于 Markdown 表格列。"""
    if not papers:
        return "（无）"
    parts: list[str] = []
    for p in papers[:limit]:
        title = p.get("title") or "Untitled"

        # 去掉 HTML 标签。
        import re

        title = re.sub(r"<[^>]+>", "", title)
        if len(title) > 50:
            title = title[:47] + "..."
        parts.append(f"[{p.get('year')}] {title}")
    return " / ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="导出多平台模糊命中对照表")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument(
        "--papers", nargs="*", default=None,
        help="要导出的 papers JSON 路径（默认自动读 data/ 下所有可用）",
    )
    parser.add_argument("--md", type=Path, default=REPO_ROOT / "data" / "fuzzy_review.md")
    parser.add_argument("--json", type=Path, default=REPO_ROOT / "data" / "fuzzy_review.json")
    parser.add_argument("--manual-overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = parser.parse_args()

    if not args.raw.exists():
        print(f"缺少 {args.raw}，请先运行 ustc_scraper.py")
        return

    raw = {
        r["faculty_id"]: r
        for r in json.loads(args.raw.read_text(encoding="utf-8")).get("records", [])
    }
    manual_overrides = {}
    if args.manual_overrides.exists():
        loaded = json.loads(args.manual_overrides.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            manual_overrides = loaded

    # 决定用哪些 papers 源。
    if args.papers:
        sources = [
            {
                **next(s for s in _SOURCES if s["path"].name == Path(p).name),
                "path": Path(p),
            }
            for p in args.papers
        ]
    else:
        sources = [s for s in _SOURCES if s["path"].exists()]

    if not sources:
        print("无可用 papers JSON，请先运行论文抓取脚本")
        return

    # 所有尚未人工裁决的作者实体都要复核；exact_match 只是姓名相等，不能免审。
    all_ids: set[str] = set()
    papers_by_source: dict[str, dict[str, dict]] = {}
    for src in sources:
        recs = _load_papers(src["path"])
        papers_by_source[src["label"]] = recs
        for fid, rec in recs.items():
            mentor_override = manual_overrides.get(str(fid), {})
            if rec.get("papers") and src["label"] not in mentor_override:
                all_ids.add(fid)

    if not all_ids:
        print("所有平台作者实体均已裁决，无需导出")
        return

    # 按 name 排序。
    sorted_ids = sorted(all_ids, key=lambda fid: raw.get(fid, {}).get("name", ""))

    # 结构化记录（JSON）。
    records: list[dict] = []
    for fid in sorted_ids:
        mentor = raw.get(fid, {})
        rec: dict = {
            "faculty_id": fid,
            "name": mentor.get("name"),
            "english_name": mentor.get("english_name"),
            "department": mentor.get("college") or mentor.get("unit"),
            "official_topics": mentor.get("research_topics", []),
            "platforms": {},
            "verdict": "",  # 留空待人工填
        }
        for src in sources:
            pr = papers_by_source[src["label"]].get(fid)
            if pr is None or not pr.get("papers"):
                continue
            if src["label"] in manual_overrides.get(str(fid), {}):
                continue
            rec["platforms"][src["label"]] = {
                "display_name": pr.get(src["display_name"]),
                "author_id": pr.get(src["author_id"]),
                "works_count": pr.get(src["works_count"]),
                "name_exact_match": pr.get(src["fuzzy_field"]) is True,
                "papers": [
                    {
                        "year": p.get("year"),
                        "title": p.get("title"),
                        "cited": p.get(src["cited_field"]) if src["cited_field"] else None,
                    }
                    for p in pr.get("papers", [])
                ],
            }
        records.append(rec)

    # 输出 JSON。
    args.json.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Markdown 对照表。
    num_platforms = len(sources)
    lines: list[str] = [
        "# 多平台作者实体待审对照表",
        "",
        f"共 {len(records)} 位导师在至少一个平台上存在尚未裁决的作者实体。"
        "姓名精确相等也不能证明是同一人；请逐人核对机构、主页作者 ID、ORCID 与论文方向后填 verdict：",
        "`keep`（论文归属本人）/ `drop`（同名错配，丢弃）/ `uncertain`（需更多信息）。",
        f"平台：{'、'.join(s['label'] for s in sources)}。",
        "",
    ]
    # 表头：基础列 + 每平台 3 列。
    header = "| 导师 | 英文名 | 学院 | 官网方向 |"
    separator = "|---|---|---|---|"
    for src in sources:
        header += f" {src['label']}命中实体 | 论文数 | 样例标题 |"
        separator += "---|----|---|"
    lines.append(header)
    lines.append(separator)

    for rec in records:
        topics = "；".join(rec["official_topics"][:3]) or "（无）"
        row = (
            f"| {rec['name']} | {rec['english_name']} | {rec['department'] or ''} "
            f"| {topics} |"
        )
        for src in sources:
            plat = rec["platforms"].get(src["label"])
            if plat:
                papers = plat.get("papers", [])
                row += (
                    f" {plat['display_name']}"
                    + ("" if plat["works_count"] is None else f" ({plat['works_count']}篇)")
                    + f" | {len(papers)} | {_paper_summary(papers, cited_field=src.get('cited_field'))} |"
                )
            else:
                row += " — | — | — |"
        lines.append(row)

    # 逐人详情。
    lines.append("")
    lines.append("## 逐人详情")
    for rec in records:
        lines.append(
            f"\n### {rec['name']} ({rec['english_name']}) — {rec['department'] or ''}"
        )
        lines.append(f"- 官网方向: {rec['official_topics'] or '（无）'}")
        for src in sources:
            plat = rec["platforms"].get(src["label"])
            if plat:
                lines.append(f"- **{src['label']}**: {plat['display_name']} "
                             f"({plat['author_id']}"
                             + ("" if plat["works_count"] is None else f", {plat['works_count']}篇")
                             + ")")
                if plat["papers"]:
                    lines.append("  - 代表论文:")
                    for p in plat["papers"]:
                        cited_str = f" (cited {p['cited']})" if p.get("cited") is not None else ""
                        lines.append(f"    - [{p['year']}] {p['title']}{cited_str}")
            else:
                lines.append(f"- **{src['label']}**: 精确命中或未解析")
        lines.append(f"- **verdict**: {rec['verdict'] or '待填'}")

    args.md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 汇总打印。
    platform_breakdown = {}
    for rec in records:
        for src in sources:
            if src["label"] in rec["platforms"]:
                platform_breakdown[src["label"]] = platform_breakdown.get(src["label"], 0) + 1
    print(
        f"导出 {len(records)} 位作者实体待审导师 -> {args.md} + {args.json}"
    )
    for label, cnt in platform_breakdown.items():
        print(f"  {label}: {cnt}")
    print("请逐人核对照表填 verdict（keep/drop/uncertain）")


if __name__ == "__main__":
    main()
