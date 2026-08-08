"""OpenAlex 论文抓取脚本（自包含，仅依赖 httpx）。

读取 ``data/ustc_mentors_raw.json`` 中每位导师的英文名，在 OpenAlex 解析其
作者实体（用 USTC 机构过滤消歧），再取该作者的代表论文（按被引量降序），
产出 ``data/ustc_mentor_papers.json``。

为什么是 OpenAlex 而非 Google Scholar：
- 有官方 API、稳定可复现，作者实体带 ``id`` 可消歧（Google Scholar 无官方
  API、反爬严格、作者难消歧）。
- 与项目现有论文链路（``backend/integrations/paper_sources/openalex.py``）同源。

设计要点：
- 机构 ID 固定为 USTC ``I126520041``（脚本启动时会自动复核一次）。
- 作者解析用 ``display_name.search:<英文名>`` + ``last_known_institutions.id:I126520041``
  双过滤；若英文名缺失或解析不到作者，记 warning 跳过。
- 每作者取 ``--max-papers`` 篇代表论文（默认 10），按 ``cited_by_count`` 降序。
- 容错 + 断点续抓：已有作者 ID 跳过；OpenAlex 限流（429）时退避重试。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "ustc_mentors_raw.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "ustc_mentor_papers.json"
DEFAULT_OVERRIDES = REPO_ROOT / "data" / "manual_overrides.json"

# 中科大在 OpenAlex 的机构 ID（启动时自动复核）。
USTC_OPENALEX_ID = "I126520041"
OPENALEX_BASE = "https://api.openalex.org"
USER_AGENT = "paper-claw mailto:paper-claw@example.com"


def _get(client: httpx.Client, path: str, params: dict, *, max_retries: int = 3) -> dict:
    """带 429 退避的 GET。"""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        response = client.get(path, params=params)
        if response.status_code == 429 and attempt < max_retries:
            wait = min(30, 2**attempt)
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    if last_exc:
        raise last_exc
    raise RuntimeError("OpenAlex request failed")


def verify_ustc_id(client: httpx.Client) -> str:
    """复核 USTC 机构 ID，返回 openalex.org/I... 形式的完整 ID。"""
    payload = _get(
        client,
        "/institutions",
        {"search": "University of Science and Technology of China", "per-page": 3},
    )
    for item in payload.get("results", []):
        if item.get("id", "").endswith(USTC_OPENALEX_ID):
            return item["id"]
    # 兜底：直接拼完整 ID。
    return f"https://openalex.org/{USTC_OPENALEX_ID}"


def resolve_author(
    client: httpx.Client, english_name: str, ustc_inst_id: str
) -> tuple[dict, bool] | None:
    """用英文名 + USTC 机构过滤解析作者实体。

    返回 (author, exact_match)；exact_match=False 表示只是模糊名命中，
    存在同名歧义风险，调用方应记 warning。无结果返回 None。
    """
    name = english_name.strip()
    if not name:
        return None
    params = {
        "filter": f"display_name.search:{name},last_known_institutions.id:{USTC_OPENALEX_ID}",
        "per-page": 10,
        "select": "id,display_name,display_name_alternatives,works_count,cited_by_count,"
        "last_known_institutions",
    }
    payload = _get(client, "/authors", params)
    results = payload.get("results", [])
    if not results:
        return None
    name_cf = name.casefold()
    # 1) 优先 display_name 精确匹配（忽略大小写）。
    for author in results:
        if (author.get("display_name") or "").casefold() == name_cf:
            return author, True
        # 别名精确匹配也算。
        for alt in author.get("display_name_alternatives", []) or []:
            if isinstance(alt, str) and alt.casefold() == name_cf:
                return author, True
    # 2) 退而求其次：display_name.search 的模糊命中（首条），标记为非精确。
    return results[0], False


def fetch_works(
    client: httpx.Client, author_openalex_id: str, *, max_papers: int
) -> list[dict]:
    """取某作者被引最高的 N 篇论文。author_openalex_id 形如 A5035816005。"""
    short_id = author_openalex_id.rsplit("/", 1)[-1]
    params = {
        "filter": f"author.id:{short_id}",
        "per-page": max(1, min(max_papers, 50)),
        "sort": "cited_by_count:desc",
        "select": "id,title,publication_year,cited_by_count,doi,type,"
        "primary_location,authorships",
    }
    payload = _get(client, "/works", params)
    works: list[dict] = []
    for item in payload.get("results", []):
        primary_location = item.get("primary_location") or {}
        source = (primary_location.get("source") or {})
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in item.get("authorships", [])
        ]
        authors = [a for a in authors if a]
        doi = item.get("doi")
        if isinstance(doi, str):
            doi = doi.removeprefix("https://doi.org/")
        works.append(
            {
                "openalex_id": item.get("id"),
                "title": item.get("title") or "Untitled",
                "year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
                "doi": doi,
                "type": item.get("type"),
                "venue": source.get("display_name"),
                "authors": authors,
                "landing_page_url": primary_location.get("landing_page_url"),
            }
        )
    return works


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
    # 用 faculty_id 建索引，方便断点续抓。
    return {
        str(record.get("faculty_id")): record
        for record in records
        if isinstance(record, dict) and record.get("faculty_id")
    }


def load_overrides(path: Path) -> dict[str, str | None]:
    """读取 data/manual_overrides.json 中本平台（OpenAlex）的手动裁决。

    返回 ``faculty_id -> openalex_author_id 或 None``。裁决值 null 表示
    "已裁定该平台的命中作者不是本人"，调用方应跳过；裁决值为 author 完整 ID
    （如 https://openalex.org/A...）时优先使用它代替自动解析。
    """
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, str | None] = {}
    for faculty_id, entry in payload.items():
        if isinstance(entry, dict) and "OpenAlex" in entry:
            value = entry["OpenAlex"]
            # 正常化：完整 URL -> 短 ID（如 A5035816005）。
            short = value.rsplit("/", 1)[-1] if isinstance(value, str) and value else None
            out[str(faculty_id)] = short
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取中科大导师的 OpenAlex 代表论文")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--overrides", type=Path, default=DEFAULT_OVERRIDES,
        help="手动裁决文件 manual_overrides.json（默认 data/manual_overrides.json）",
    )
    parser.add_argument("--max-papers", type=int, default=10, help="每位作者取多少篇 (默认 10)")
    parser.add_argument("--delay", type=float, default=1.0, help="每位作者间隔秒数 (默认 1)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--limit", type=int, default=0,
        help="只处理前 N 位导师 (0 表示全部)，用于小样",
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
    resolved = overridden_kept = overridden_dropped = 0

    with httpx.Client(
        base_url=OPENALEX_BASE, timeout=args.timeout,
        trust_env=False, headers={"User-Agent": USER_AGENT},
    ) as client:
        ustc_inst_id = verify_ustc_id(client)
        print(f"USTC OpenAlex 机构 ID: {ustc_inst_id}")
        for mentor in mentors:
            faculty_id = str(mentor.get("faculty_id"))
            en_name = mentor.get("english_name", "")
            name = mentor.get("name", "")
            # 断点续抓：已解析过且非空的跳过。
            if faculty_id in existing and existing[faculty_id].get("papers"):
                continue
            # 手动裁决优先：null = 已裁定非本人，跳过本平台的论文证据。
            if faculty_id in overrides and overrides[faculty_id] is None:
                overridden_dropped += 1
                warnings.append(
                    f"{name} (faculty_id={faculty_id}) 手动裁决 OpenAlex 命中非本人，跳过"
                )
                existing[faculty_id] = {
                    "faculty_id": faculty_id,
                    "name": name,
                    "english_name": en_name,
                    "openalex_author_id": None,
                    "papers": [],
                }
                continue
            if not en_name:
                warnings.append(f"{name} (faculty_id={faculty_id}) 无英文名，跳过")
                continue
            try:
                if faculty_id in overrides:
                    # 手动裁决指定了确定的作者 ID，直接抓取该作者的论文。
                    author_id = overrides[faculty_id]
                    papers = fetch_works(client, author_id, max_papers=args.max_papers)
                    existing[faculty_id] = {
                        "faculty_id": faculty_id,
                        "name": name,
                        "english_name": en_name,
                        "openalex_author_id": f"https://openalex.org/{author_id}",
                        "openalex_display_name": f"(manual override {author_id})",
                        "openalex_exact_match": True,
                        "openalex_works_count": None,
                        "openalex_cited_by_count": None,
                        "papers": papers,
                    }
                    overridden_kept += 1
                    if args.delay:
                        time.sleep(args.delay)
                    continue
                resolved_author = resolve_author(client, en_name, ustc_inst_id)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name} 作者解析失败: {type(exc).__name__}: {exc}")
                resolved_author = None
            if resolved_author is None:
                warnings.append(f"{name} ({en_name}) 未在 USTC 解析到 OpenAlex 作者")
                existing[faculty_id] = {
                    "faculty_id": faculty_id,
                    "name": name,
                    "english_name": en_name,
                    "openalex_author_id": None,
                    "papers": [],
                }
                continue
            author, exact_match = resolved_author
            openalex_author_id = author.get("id")
            if not exact_match:
                warnings.append(
                    f"{name} ({en_name}) OpenAlex 作者仅模糊命中 "
                    f"{author.get('display_name')} ({openalex_author_id})，"
                    f"存在同名歧义风险，论文可能归属他人"
                )
            try:
                papers = fetch_works(
                    client, openalex_author_id, max_papers=args.max_papers
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name} 论文抓取失败: {type(exc).__name__}: {exc}")
                papers = []
            existing[faculty_id] = {
                "faculty_id": faculty_id,
                "name": name,
                "english_name": en_name,
                "openalex_author_id": openalex_author_id,
                "openalex_display_name": author.get("display_name"),
                "openalex_exact_match": exact_match,
                "openalex_works_count": author.get("works_count"),
                "openalex_cited_by_count": author.get("cited_by_count"),
                "papers": papers,
            }
            resolved += 1
            tag = "" if exact_match else " [模糊命中]"
            print(
                f"  {name} ({en_name}) -> {openalex_author_id}, "
                f"{len(papers)} 篇论文{tag}"
            )
            if args.delay:
                time.sleep(args.delay)

    payload = {
        "run_date": date.today().isoformat(),
        "source": "openalex",
        "ustc_openalex_id": USTC_OPENALEX_ID,
        "mentor_count": len(mentors),
        "resolved_count": resolved,
        "warnings": warnings,
        "records": list(existing.values()),
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"\n完成：处理 {len(mentors)} 位导师，成功解析 {resolved} 位"
        f"（手动裁决保留 {overridden_kept} / 跳过 {overridden_dropped}），"
        f"写入 {args.output}"
    )
    if warnings:
        print(f"警告 {len(warnings)} 条（已写入 JSON 的 warnings 字段）")


if __name__ == "__main__":
    main()
