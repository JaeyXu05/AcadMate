"""Semantic Scholar 论文抓取脚本（自包含，仅依赖 httpx）。

读取 ``data/ustc_mentors_raw.json`` 中每位导师的英文名，在 Semantic Scholar
解析其作者实体（用 USTC 机构消歧），再取该作者的代表论文（按被引量降序），
产出 ``data/ustc_mentor_papers_s2.json``。

为什么加 Semantic Scholar（与 OpenAlex 互补）：
- 公开免费 API（``api.semanticscholar.org``），匿名约 1 req/s，申请免费 key 可提速。
- 作者实体带 ``authorId`` 可消歧，作者记录含 ``affiliations`` 可做机构匹配。
- 论文覆盖面与被引统计与 OpenAlex 互有补全，尤其偏 CS/AI/医学。

设计要点（与 openalex_scraper.py 对齐，便于将来并入 build_rag）：
- 作者解析用 ``GET /graph/v1/author/search?query=<name>``，limit=10；先找精确
  ``name`` 匹配（casefold）标 ``s2_exact_match=True``；否则按 ``affiliations``
  含 "University of Science and Technology of China" 优先，取首条标 ``False``。
- 论文用 ``GET /graph/v1/author/{authorId}/papers`` 取 ``limit=100``，客户端按
  ``citationCount`` 降序取前 N（该端点无服务端 sort）。
- 容错 + 断点续抓：已有且非空 ``papers`` 跳过；429 退避重试。
- **暂不并入 RAG**：仅产出独立 JSON，留待人工裁决后统一合并。
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "ustc_mentors_raw.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "ustc_mentor_papers_s2.json"
DEFAULT_OVERRIDES = REPO_ROOT / "data" / "manual_overrides.json"

S2_BASE = "https://api.semanticscholar.org/graph/v1"
USTC_NAME_TOKENS = ("university of science and technology of china", "ustc")
USER_AGENT = "Paper-Claw USTC mentor research (semantic_scholar)"


def _get(client: httpx.Client, path: str, params: dict, *, max_retries: int = 3) -> dict:
    """带 429 退避的 GET。S2 匿名限流较严，退避上限放宽到 30s。"""
    for attempt in range(max_retries + 1):
        response = client.get(path, params=params)
        if response.status_code == 429 and attempt < max_retries:
            wait = min(30, 2**attempt)
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("Semantic Scholar request failed (rate limited)")


def _has_ustc_affiliation(affiliations: object) -> bool:
    """author 的 affiliations 字段是否提到 USTC。"""
    if isinstance(affiliations, list):
        items = affiliations
    elif isinstance(affiliations, str):
        items = [affiliations]
    else:
        return False
    for item in items:
        if not isinstance(item, (str, dict)):
            continue
        text = item.get("name", "") if isinstance(item, dict) else str(item)
        text_cf = (text or "").casefold()
        if any(token in text_cf for token in USTC_NAME_TOKENS):
            return True
    return False


def resolve_author(
    client: httpx.Client, english_name: str
) -> tuple[dict, bool] | None:
    """用英文名解析 Semantic Scholar 作者实体。

    返回 (author, exact_match)；exact_match=False 表示只是模糊名命中（存在同名
    歧义风险），调用方应记 warning。无结果返回 None。优先选精确名匹配，其次
    affiliations 含 USTC 者。
    """
    name = english_name.strip()
    if not name:
        return None
    params = {
        "query": name,
        "fields": "name,affiliations,paperCount,citationCount,homepage",
        "limit": 10,
    }
    payload = _get(client, "/author/search", params)
    results = payload.get("data") or []
    if not results:
        return None
    name_cf = name.casefold()
    # 1) 优先精确名匹配（忽略大小写）。
    for author in results:
        if (author.get("name") or "").casefold() == name_cf:
            return author, True
    # 2) 其次 affiliations 含 USTC 者。
    for author in results:
        if _has_ustc_affiliation(author.get("affiliations")):
            return author, False
    # 3) 退而求其次：首条模糊命中，标记为非精确。
    return results[0], False


def fetch_papers(
    client: httpx.Client, author_id: str, *, max_papers: int
) -> list[dict]:
    """取某作者被引最高的 N 篇论文。S2 该端点无服务端 sort，客户端按 citationCount 降序。"""
    params = {
        "fields": "title,year,venue,citationCount,externalIds,authors",
        "limit": 100,
    }
    payload = _get(client, f"/author/{author_id}/papers", params)
    raw = payload.get("data") or []
    # 客户端按被引量降序，取前 max_papers。
    raw.sort(key=lambda p: (p.get("citationCount") or 0), reverse=True)
    papers: list[dict] = []
    for item in raw[:max_papers]:
        authors = [a.get("name", "") for a in item.get("authors", []) if isinstance(a, dict)]
        authors = [a for a in authors if a]
        external = item.get("externalIds") or {}
        doi = external.get("DOI")
        if isinstance(doi, str):
            doi = doi.removeprefix("https://doi.org/")
        papers.append(
            {
                "s2_paper_id": item.get("paperId"),
                "title": item.get("title") or "Untitled",
                "year": item.get("year"),
                "cited_by_count": item.get("citationCount", 0),
                "venue": item.get("venue"),
                "doi": doi,
                "authors": authors,
            }
        )
    return papers


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
        str(record.get("faculty_id")): record
        for record in records
        if isinstance(record, dict) and record.get("faculty_id")
    }


def load_overrides(path: Path) -> dict[str, str | None]:
    """读取 data/manual_overrides.json 中 Semantic Scholar 的手动裁决。

    ``faculty_id -> s2_author_id 或 None``。None 表示已裁定 S2 命中非本人，
    跳过；str 为确定的 S2 作者 ID，优先使用它代替自动解析。
    """
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, str | None] = {}
    for faculty_id, entry in payload.items():
        if isinstance(entry, dict) and "Semantic Scholar" in entry:
            out[str(faculty_id)] = entry["Semantic Scholar"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取中科大导师的 Semantic Scholar 代表论文")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--overrides", type=Path, default=DEFAULT_OVERRIDES,
        help="手动裁决文件 manual_overrides.json（默认 data/manual_overrides.json）",
    )
    parser.add_argument("--max-papers", type=int, default=10, help="每位作者取多少篇 (默认 10)")
    parser.add_argument("--delay", type=float, default=1.1, help="每位作者间隔秒数 (匿名建议 >=1，默认 1.1)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--limit", type=int, default=0,
        help="只处理前 N 位导师 (0 表示全部)，用于小样探针",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"找不到输入文件 {args.input}，请先运行 ustc_scraper.py")
        return

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    mentors = raw.get("records", []) if isinstance(raw, dict) else []
    if args.limit > 0:
        mentors = mentors[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing(args.output)
    overrides = load_overrides(args.overrides)
    warnings: list[str] = []
    resolved = exact_count = fuzzy_count = no_name = unresolved = 0
    overridden_kept = overridden_dropped = 0
    sample_papers: list[str] = []

    with httpx.Client(
        base_url=S2_BASE, timeout=args.timeout,
        trust_env=False, headers={"User-Agent": USER_AGENT},
    ) as client:
        for mentor in mentors:
            faculty_id = str(mentor.get("faculty_id"))
            en_name = mentor.get("english_name", "")
            name = mentor.get("name", "")
            # 断点续抓：已解析过且非空的跳过。
            if faculty_id in existing and existing[faculty_id].get("papers"):
                continue
            # 手动裁决优先：null = 已裁定 S2 命中非本人，跳过本平台的论文证据。
            if faculty_id in overrides and overrides[faculty_id] is None:
                overridden_dropped += 1
                warnings.append(
                    f"{name} (faculty_id={faculty_id}) 手动裁决 S2 命中非本人，跳过"
                )
                existing[faculty_id] = {
                    "faculty_id": faculty_id,
                    "name": name,
                    "english_name": en_name,
                    "s2_author_id": None,
                    "papers": [],
                }
                continue
            if not en_name:
                no_name += 1
                warnings.append(f"{name} (faculty_id={faculty_id}) 无英文名，跳过")
                continue
            try:
                if faculty_id in overrides:
                    # 手动裁决指定了确定的作者 ID，直接抓取该作者的论文。
                    s2_author_id = overrides[faculty_id]
                    papers = fetch_papers(client, s2_author_id, max_papers=args.max_papers)
                    existing[faculty_id] = {
                        "faculty_id": faculty_id,
                        "name": name,
                        "english_name": en_name,
                        "s2_author_id": s2_author_id,
                        "s2_display_name": f"(manual override {s2_author_id})",
                        "s2_exact_match": True,
                        "s2_paper_count": None,
                        "s2_cited_by_count": None,
                        "papers": papers,
                    }
                    overridden_kept += 1
                    if args.delay:
                        time.sleep(args.delay)
                    continue
                resolved_author = resolve_author(client, en_name)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name} 作者解析失败: {type(exc).__name__}: {exc}")
                resolved_author = None
            if resolved_author is None:
                unresolved += 1
                warnings.append(f"{name} ({en_name}) 未在 Semantic Scholar 解析到作者")
                existing[faculty_id] = {
                    "faculty_id": faculty_id,
                    "name": name,
                    "english_name": en_name,
                    "s2_author_id": None,
                    "papers": [],
                }
                continue
            author, exact_match = resolved_author
            s2_author_id = author.get("authorId")
            if not exact_match:
                warnings.append(
                    f"{name} ({en_name}) Semantic Scholar 作者仅模糊命中 "
                    f"{author.get('name')} ({s2_author_id})，存在同名歧义风险"
                )
            try:
                papers = fetch_papers(client, s2_author_id, max_papers=args.max_papers)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name} 论文抓取失败: {type(exc).__name__}: {exc}")
                papers = []
            existing[faculty_id] = {
                "faculty_id": faculty_id,
                "name": name,
                "english_name": en_name,
                "s2_author_id": s2_author_id,
                "s2_display_name": author.get("name"),
                "s2_exact_match": exact_match,
                "s2_paper_count": author.get("paperCount"),
                "s2_cited_by_count": author.get("citationCount"),
                "papers": papers,
            }
            resolved += 1
            if exact_match:
                exact_count += 1
            else:
                fuzzy_count += 1
            if len(sample_papers) < 2 and papers:
                sample_papers.append(f"{name}: [{papers[0]['year']}] {papers[0]['title']}")
            tag = "" if exact_match else " [模糊命中]"
            print(
                f"  {name} ({en_name}) -> {s2_author_id}, "
                f"{len(papers)} 篇论文{tag}"
            )
            if args.delay:
                time.sleep(args.delay)

    payload = {
        "run_date": date.today().isoformat(),
        "source": "semantic_scholar",
        "mentor_count": len(mentors),
        "resolved_count": resolved,
        "warnings": warnings,
        "records": list(existing.values()),
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # 可行性汇总。
    print(
        f"\n完成：处理 {len(mentors)} 位导师，解析 {resolved} 位"
        f"（精确 {exact_count} / 模糊 {fuzzy_count}，手动裁决保留 {overridden_kept}"
        f" / 跳过 {overridden_dropped}），未解析 {unresolved}，"
        f"无英文名 {no_name}，写入 {args.output}"
    )
    if sample_papers:
        print("样例论文:")
        for s in sample_papers:
            print(f"  - {s}")
    if warnings:
        print(f"警告 {len(warnings)} 条（已写入 JSON 的 warnings 字段）")


if __name__ == "__main__":
    main()
