"""DBLP 论文抓取脚本（自包含，仅依赖 httpx）。

读取 ``data/ustc_mentors_raw.json`` 中每位导师的英文名，在 DBLP 解析其作者实体
（用 ``pid`` 消歧），再取该作者的出版物（按年份降序），产出
``data/ustc_mentor_papers_dblp.json``。

为什么加 DBLP（与 OpenAlex / S2 互补）：
- 公开免费 API（``dblp.org/.../api``），无需 key；DBLP PID 是稳定的作者标识。
- 计算机科学论文收录权威，对中科大 CS/AI/EE/网络空间安全学院尤其互补。
- 无被引量字段，故按年份取最近 N 篇（与 OpenAlex/S2 按被引取代表论文互补）。

设计要点（与 openalex_scraper.py 对齐，便于将来并入 build_rag）：
- 作者解析用 ``GET https://dblp.org/search/author/api?q=<name>&format=json&h=10``，
  解析 ``result.hits.hit[].info``：从 ``info.url`` 抽 pid（如 ``z/JinzheZeng``）；
  ``info.author`` 形如 "Jinzhe Zeng 0001"，去掉末尾序号后缀做精确名匹配。
- 论文用 ``GET https://dblp.org/pid/{pid}.xml``（XML 端点兼容所有 pid 格式，
  而 JSON 端点对数字 pid 如 ``254/2765`` 返回 404），解析
  ``<r>/<article|inproceedings>`` 的 ``<title>/<year>/<journal|booktitle>/<ee>``，
  按 ``year`` 降序取前 N。
- 容错 + 断点续抓：已有且非空 ``papers`` 跳过；429 退避重试。
- **暂不并入 RAG**：仅产出独立 JSON，留待人工裁决后统一合并。
- DBLP 仅覆盖 CS，命中集中在 CS/AI/EE 学院——预期行为，未命中者多为非 CS 学科。
"""

from __future__ import annotations

import argparse
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "ustc_mentors_raw.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "ustc_mentor_papers_dblp.json"
DEFAULT_OVERRIDES = REPO_ROOT / "data" / "manual_overrides.json"

DBLP_BASE = "https://dblp.org"
USER_AGENT = "Paper-Claw USTC mentor research (dblp)"

# DBLP info.author 形如 "Jinzhe Zeng 0001"，末尾 4 位数字是同名消歧序号。
_NAME_SUFFIX_RE = re.compile(r"\s+\d{4}$")


def _get_json(client: httpx.Client, url: str, params: dict | None = None, *, max_retries: int = 3) -> dict:
    """带 429 退避的 GET，返回 JSON（用于作者搜索 API）。"""
    for attempt in range(max_retries + 1):
        response = client.get(url, params=params)
        if response.status_code == 429 and attempt < max_retries:
            wait = min(30, 2**attempt)
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("DBLP request failed (rate limited)")


def _get_xml(client: httpx.Client, url: str, *, max_retries: int = 3) -> str:
    """带 429 退避的 GET，返回 XML 文本（用于论文端点）。"""
    for attempt in range(max_retries + 1):
        response = client.get(url)
        if response.status_code == 429 and attempt < max_retries:
            wait = min(30, 2**attempt)
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.text
    raise RuntimeError("DBLP request failed (rate limited)")


def _pid_from_url(url: str) -> str | None:
    """从 info.url（如 https://dblp.org/pid/z/JinzheZeng.html）抽 pid z/JinzheZeng。"""
    if not url:
        return None
    # 取 path 的 pid 段，去 .html。
    match = re.search(r"/pid/([^/]+/[^/]+?)(?:\.html)?$", url)
    return match.group(1) if match else None


def _normalize_name(value: str) -> str:
    """归一化 DBLP 作者名：去同名序号后缀、压空白、小写。"""
    return _NAME_SUFFIX_RE.sub("", value or "").strip().casefold()


def resolve_pid(client: httpx.Client, english_name: str) -> tuple[str, str, bool] | None:
    """用英文名解析 DBLP 作者 pid。

    返回 (pid, display_name, exact_match)；exact_match=False 表示只是模糊名命中
    （DBLP 同名靠 0001 序号区分，无序号的命中需人工确认），调用方应记 warning。
    无结果返回 None。
    """
    name = english_name.strip()
    if not name:
        return None
    url = f"{DBLP_BASE}/search/author/api"
    payload = _get_json(client, url, params={"q": name, "format": "json", "h": 10})
    result = payload.get("result") or {}
    hits = ((result.get("hits") or {}).get("hit")) or []
    if not hits:
        return None
    name_cf = name.casefold()
    candidates: list[tuple[str, str, bool]] = []
    for hit in hits:
        info = hit.get("info") or {}
        author = info.get("author") or ""
        url = info.get("url") or ""
        pid = _pid_from_url(url)
        if not pid:
            continue
        exact = _normalize_name(author) == name_cf
        candidates.append((pid, _NAME_SUFFIX_RE.sub("", author).strip(), exact))
    # 1) 优先精确名匹配。
    for pid, display, exact in candidates:
        if exact:
            return pid, display, True
    # 2) 退而求其次：首条候选，标记为非精确。
    pid, display, _ = candidates[0]
    return pid, display, False


def fetch_papers(client: httpx.Client, pid: str, *, max_papers: int) -> list[dict]:
    """取某 pid 的出版物（XML），按年份降序取前 N。DBLP 无被引量字段。

    DBLP XML 结构（已验证）：::

        <dblpperson name="..." pid="254/2765">
          <r>
            <article key="journals/...">
              <title>...</title><year>2025</year>
              <journal>J. Chem. Inf. Model.</journal>
              <ee>https://doi.org/10.1021/...</ee>
            </article>
          </r>
          <r>
            <inproceedings key="conf/...">
              <title>...</title><year>2024</year>
              <booktitle>NeurIPS 2024</booktitle>
              <ee>https://doi.org/10.1007/...</ee>
            </inproceedings>
          </r>
        </dblpperson>
    """
    xml_text = _get_xml(client, f"{DBLP_BASE}/pid/{pid}.xml")
    root = ET.fromstring(xml_text)
    raw_items: list[tuple[int, dict]] = []
    for r_elem in root.findall("r"):
        pub_elem = r_elem.find("./article") or r_elem.find("./inproceedings") or r_elem.find("./incollection") or r_elem.find("./www")
        if pub_elem is None:
            continue

        def _el(tag: str) -> str | None:
            child = pub_elem.find(tag)
            return child.text.strip() if child is not None and child.text else None

        year_str = _el("year")
        try:
            year = int(year_str) if year_str else 0
        except (TypeError, ValueError):
            year = 0

        venue = _el("journal") or _el("booktitle") or _el("venue")
        doi = None
        for ee in pub_elem.findall("ee"):
            if ee.text and "doi.org" in ee.text:
                doi = ee.text.strip().removeprefix("https://doi.org/")
                break
        title = _el("title") or "Untitled"
        if title and title.endswith("."):
            title = title[:-1]

        raw_items.append(
            (
                year,
                {
                    "dblp_key": pub_elem.get("key"),
                    "title": title,
                    "year": year_str,
                    "venue": venue,
                    "type": pub_elem.tag,
                    "doi": doi,
                    "url": _el("url"),
                },
            )
        )

    raw_items.sort(key=lambda it: it[0], reverse=True)
    return [item for _, item in raw_items[:max_papers]]


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
    """读取 data/manual_overrides.json 中 DBLP 的手动裁决。

    ``faculty_id -> dblp_pid 或 None``。None 表示已裁定 DBLP 命中非本人，跳过；
    str（如 ``z/JinzheZeng``）为确定的 DBLP pid，优先使用它代替自动解析。
    """
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, str | None] = {}
    for faculty_id, entry in payload.items():
        if isinstance(entry, dict) and "DBLP" in entry:
            out[str(faculty_id)] = entry["DBLP"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取中科大导师的 DBLP 代表论文")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--overrides", type=Path, default=DEFAULT_OVERRIDES,
        help="手动裁决文件 manual_overrides.json（默认 data/manual_overrides.json）",
    )
    parser.add_argument("--max-papers", type=int, default=10, help="每位作者取多少篇 (默认 10)")
    parser.add_argument("--delay", type=float, default=0.5, help="每位作者间隔秒数 (默认 0.5，礼貌限速)")
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
        timeout=args.timeout, trust_env=False, headers={"User-Agent": USER_AGENT},
    ) as client:
        for mentor in mentors:
            faculty_id = str(mentor.get("faculty_id"))
            en_name = mentor.get("english_name", "")
            name = mentor.get("name", "")
            # 断点续抓：已解析过且非空的跳过。
            if faculty_id in existing and existing[faculty_id].get("papers"):
                continue
            # 手动裁决优先：null = 已裁定 DBLP 命中非本人，跳过本平台的论文证据。
            if faculty_id in overrides and overrides[faculty_id] is None:
                overridden_dropped += 1
                warnings.append(
                    f"{name} (faculty_id={faculty_id}) 手动裁决 DBLP 命中非本人，跳过"
                )
                existing[faculty_id] = {
                    "faculty_id": faculty_id,
                    "name": name,
                    "english_name": en_name,
                    "dblp_pid": None,
                    "papers": [],
                }
                continue
            if not en_name:
                no_name += 1
                warnings.append(f"{name} (faculty_id={faculty_id}) 无英文名，跳过")
                continue
            try:
                if faculty_id in overrides:
                    # 手动裁决指定了确定的 DBLP pid，直接抓取该作者的论文。
                    pid = overrides[faculty_id]
                    papers = fetch_papers(client, pid, max_papers=args.max_papers)
                    existing[faculty_id] = {
                        "faculty_id": faculty_id,
                        "name": name,
                        "english_name": en_name,
                        "dblp_pid": pid,
                        "dblp_display_name": f"(manual override {pid})",
                        "dblp_exact_match": True,
                        "dblp_pub_count": None,
                        "papers": papers,
                    }
                    overridden_kept += 1
                    if args.delay:
                        time.sleep(args.delay)
                    continue
                resolved_pid = resolve_pid(client, en_name)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name} 作者解析失败: {type(exc).__name__}: {exc}")
                resolved_pid = None
            if resolved_pid is None:
                unresolved += 1
                warnings.append(f"{name} ({en_name}) 未在 DBLP 解析到作者（可能非 CS 学科）")
                existing[faculty_id] = {
                    "faculty_id": faculty_id,
                    "name": name,
                    "english_name": en_name,
                    "dblp_pid": None,
                    "papers": [],
                }
                continue
            pid, display, exact_match = resolved_pid
            if not exact_match:
                warnings.append(
                    f"{name} ({en_name}) DBLP 作者仅模糊命中 {display} ({pid})，"
                    f"存在同名歧义风险"
                )
            try:
                papers = fetch_papers(client, pid, max_papers=args.max_papers)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name} 论文抓取失败: {type(exc).__name__}: {exc}")
                papers = []
            existing[faculty_id] = {
                "faculty_id": faculty_id,
                "name": name,
                "english_name": en_name,
                "dblp_pid": pid,
                "dblp_display_name": display,
                "dblp_exact_match": exact_match,
                # 不额外发请求取总数；如需可单独拉 /pid/{pid}.json 统计。
                "dblp_pub_count": None,
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
                f"  {name} ({en_name}) -> {pid}, {len(papers)} 篇{tag}"
            )
            if args.delay:
                time.sleep(args.delay)

    payload = {
        "run_date": date.today().isoformat(),
        "source": "dblp",
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
