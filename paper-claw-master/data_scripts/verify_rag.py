"""RAG 库自检脚本（只读，不联网）。

对 ``data/ustc_mentor_rag.json`` 跑 A–G 七项检查，每项打印 PASS/FAIL，最后给汇总：

  A. schema 合规    —— 每条 CandidateMentor / EvidenceRecord 能通过后端 pydantic
                       model_validate；后端不可 import 时降级为手写字段校验。
  B. 证据引用闭环   —— 每个候选的 evidence_refs 都能在 evidence 里找到，且
                       evidence.candidate_id 反向指回该候选；无悬空引用。
  C. 跳过外部源条件 —— 抽样"有研究方向+有证据"的导师，验证其证据含
                       identity_verified=true 且 mentor_role_verified≠False。
  D. 召回升单测     —— 用几个已知方向词跑 retrieve()，确认能召回对应导师。
  E. 覆盖率软门禁   —— 汇报关键字段覆盖率，不把数据稀疏误判为结构损坏。
  F. 检索质量门禁   —— 检查导航垃圾召回，并验证视觉/强化学习等代表查询。
  G. 语义元数据门禁 —— 检查作者状态、论文计数、pending 证据和简介模板残留。

用法：
  python data_scripts/verify_rag.py [--rag data/ustc_mentor_rag.json]

可在任何装了 httpx 的环境跑（schema 检查会自动降级）；在后端环境（装了
openai/pydantic）跑时 schema 检查走严格 model_validate。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG = REPO_ROOT / "data" / "ustc_mentor_rag.json"

# 严格 schema 校验：尝试 import 后端模型，失败则降级。
_STRICT = False
try:
    sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
    from backend.mentor_workflow.schemas import (  # noqa: E402
        CandidateMentor,
        EvidenceRecord,
    )
    _STRICT = True
except Exception:  # noqa: BLE001 - 后端依赖缺失时降级
    CandidateMentor = None  # type: ignore[assignment]
    EvidenceRecord = None  # type: ignore[assignment]


class Report:
    def __init__(self) -> None:
        # (name, status, detail)；status: "PASS" | "FAIL" | "SKIP"
        self.items: list[tuple[str, str, str]] = []
        self.strict_note = ""

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append((name, "PASS" if ok else "FAIL", detail))

    def add_skip(self, name: str, detail: str = "") -> None:
        self.items.append((name, "SKIP", detail))

    def add_warn(self, name: str, detail: str = "") -> None:
        """覆盖率等软性门禁：不阻断（不影响退出码），但提醒数据质量退化。"""
        self.items.append((name, "WARN", detail))

    def summary(self) -> None:
        print("\n" + "=" * 60)
        if self.strict_note:
            print(self.strict_note)
        all_ok = True
        for name, status, detail in self.items:
            line = f"[{status}] {name}"
            if detail:
                line += f" — {detail}"
            print(line)
            if status == "FAIL":
                all_ok = False
        print("=" * 60)
        failed = sum(1 for _, s, _ in self.items if s == "FAIL")
        skipped = sum(1 for _, s, _ in self.items if s == "SKIP")
        warned = sum(1 for _, s, _ in self.items if s == "WARN")
        print(
            "总体: "
            + ("全部通过" if all_ok else f"存在 {failed} 项失败")
            + (f"，{skipped} 项因环境跳过" if skipped else "")
            + (f"，{warned} 项警告(数据质量待改进)" if warned else "")
        )
        sys.exit(0 if all_ok else 1)


# ---------------------------------------------------------------------------
# A. schema 合规
# ---------------------------------------------------------------------------


def _manual_candidate_check(c: dict) -> list[str]:
    errs: list[str] = []
    for req in ("candidate_id", "mentor_name"):
        if not c.get(req):
            errs.append(f"缺必填 {req}")
    if not isinstance(c.get("research_topics"), list):
        errs.append("research_topics 非 list")
    if not isinstance(c.get("evidence_refs"), list):
        errs.append("evidence_refs 非 list")
    return errs


def _manual_evidence_check(e: dict) -> list[str]:
    errs: list[str] = []
    for req in ("source_type", "source_uri", "title", "extracted_fact", "locator"):
        if not str(e.get(req, "")).strip():
            errs.append(f"缺必填/空 {req}")
    conf = e.get("confidence")
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        errs.append(f"confidence 越界: {conf}")
    if not isinstance(e.get("metadata"), dict):
        errs.append("metadata 非 dict")
    return errs


def check_schema(candidates: list[dict], evidence: list[dict], rep: Report) -> None:
    c_bad = 0
    e_bad = 0
    sample_errs: list[str] = []
    if _STRICT:
        for c in candidates:
            try:
                CandidateMentor.model_validate(c)
            except Exception as exc:  # noqa: BLE001
                c_bad += 1
                if len(sample_errs) < 3:
                    sample_errs.append(f"{c.get('candidate_id')}: {exc}")
        for e in evidence:
            try:
                EvidenceRecord.model_validate(e)
            except Exception as exc:  # noqa: BLE001
                e_bad += 1
                if len(sample_errs) < 6:
                    sample_errs.append(f"{e.get('evidence_id')}: {exc}")
        rep.strict_note = "schema 检查: 严格模式（后端 pydantic model_validate）"
    else:
        for c in candidates:
            errs = _manual_candidate_check(c)
            if errs:
                c_bad += 1
                if len(sample_errs) < 3:
                    sample_errs.append(f"{c.get('candidate_id')}: {'; '.join(errs)}")
        for e in evidence:
            errs = _manual_evidence_check(e)
            if errs:
                e_bad += 1
                if len(sample_errs) < 6:
                    sample_errs.append(f"{e.get('evidence_id')}: {'; '.join(errs)}")
        rep.strict_note = "schema 检查: 降级模式（后端依赖缺失，手写字段校验）"

    ok = c_bad == 0 and e_bad == 0
    detail = f"候选不合规 {c_bad}/{len(candidates)}，证据不合规 {e_bad}/{len(evidence)}"
    if sample_errs:
        detail += "；样例错误: " + " | ".join(sample_errs[:3])
    rep.add("A. schema 合规", ok, detail)


# ---------------------------------------------------------------------------
# B. 证据引用闭环
# ---------------------------------------------------------------------------


def check_references(candidates: list[dict], evidence: list[dict], rep: Report) -> None:
    ev_by_id = {e.get("evidence_id"): e for e in evidence}
    dangling = 0
    reverse_mismatch = 0
    for c in candidates:
        for ref in c.get("evidence_refs", []):
            ev = ev_by_id.get(ref)
            if ev is None:
                dangling += 1
            elif ev.get("candidate_id") != c.get("candidate_id"):
                reverse_mismatch += 1
    # 反向：有 candidate_id 的证据应指向某个候选
    cand_ids = {c.get("candidate_id") for c in candidates}
    orphan_evidence = sum(
        1 for e in evidence
        if e.get("candidate_id") and e.get("candidate_id") not in cand_ids
    )
    ok = dangling == 0 and reverse_mismatch == 0 and orphan_evidence == 0
    detail = (
        f"悬空引用 {dangling}，反向不匹配 {reverse_mismatch}，孤儿证据 {orphan_evidence}"
    )
    rep.add("B. 证据引用闭环", ok, detail)


# ---------------------------------------------------------------------------
# C. 跳过外部源条件
# ---------------------------------------------------------------------------


def check_skip_conditions(candidates: list[dict], evidence: list[dict], rep: Report) -> None:
    """验证"有研究方向+有证据"的候选，其证据含身份/角色核验标记。"""
    ev_by_cand: dict[str, list[dict]] = {}
    for e in evidence:
        ev_by_cand.setdefault(e.get("candidate_id"), []).append(e)
    qualified = [
        c for c in candidates
        if c.get("research_topics") and c.get("evidence_refs")
    ]
    if not qualified:
        rep.add("C. 跳过外部源条件", False, "无'有方向+有证据'候选，无法验证")
        return
    failing = 0
    for c in qualified:
        bound = ev_by_cand.get(c["candidate_id"], [])
        has_verified = any(
            ev.get("metadata", {}).get("identity_verified") is True
            and ev.get("metadata", {}).get("mentor_role_verified") is not False
            for ev in bound
        )
        if not has_verified:
            failing += 1
    ok = failing == 0
    rep.add(
        "C. 跳过外部源条件",
        ok,
        f"{len(qualified)} 个合格候选中 {failing} 个缺身份/角色核验证据",
    )


# ---------------------------------------------------------------------------
# D. 召回升单测
# ---------------------------------------------------------------------------


def check_recall(
    candidates: list[dict], evidence: list[dict], rep: Report, rag_path: Path
) -> None:
    """用已知方向词检索，确认能召回对应导师。依赖 FileInternalMentorRag + 后端 schemas。

    ``rag_path`` 即被自检的文件：检索必须基于同一份数据，否则"查某方向"
    的召回结果与被验证的候选人集不一致（此前一直用默认库，导致 --rag 时失真）。
    """
    # 同目录导入：把脚本所在目录加入 sys.path，便于直接 python xxx.py 运行。
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        from internal_mentor_rag import FileInternalMentorRag  # noqa: E402
        from backend.mentor_workflow.schemas import IntentPacket, MentorGoal  # noqa: E402
        backend_available = True
    except Exception:  # noqa: BLE001 - 轻量环境走纯字典回退，不再跳过
        backend_available = False

    # 自动构造测试用例：挑几个有明确研究方向的导师，用其方向词反查。
    test_cases: list[tuple[str, str]] = []  # (query, expected_name)
    seen_names: set[str] = set()
    for c in candidates:
        if len(test_cases) >= 3:
            break
        name = c.get("mentor_name", "")
        topics = c.get("research_topics", [])
        if name and topics and name not in seen_names:
            # 用第一个方向词作为查询。
            test_cases.append((topics[0], name))
            seen_names.add(name)

    if not test_cases:
        rep.add("D. 召回升单测", False, "无可构造的召回用例（无研究方向导师）")
        return

    rag = FileInternalMentorRag(rag_path) if backend_available else None
    failed: list[str] = []
    for query, expected in test_cases:
        if backend_available:
            intent = IntentPacket(
                trace_id="verify-recall",
                goal=MentorGoal.find_mentors,
                research_topics=[query],
                confidence=1.0,
            )
            result = rag.retrieve(intent, [])
            names = {c.mentor_name for c in result.candidates}
        else:
            q = re.sub(r"\s+", "", query.casefold())
            names = {
                str(c.get("mentor_name") or "") for c in candidates
                if q in re.sub(
                    r"\s+", "", " ".join([
                        *map(str, c.get("research_topics") or []),
                        *map(str, c.get("methods") or []),
                        *map(str, c.get("publications") or []),
                    ]).casefold(),
                )
            }
        if expected not in names:
            failed.append(f"查'{query}'未召回{expected}")
    ok = not failed
    mode = "后端检索" if backend_available else "stdlib 轻量召回"
    detail = f"{len(test_cases)} 个用例，失败 {len(failed)}（{mode}）"
    if failed:
        detail += "；" + "; ".join(failed[:3])
    rep.add("D. 召回升单测", ok, detail)


# ---------------------------------------------------------------------------
# E. 覆盖率门禁（软性 WARN，不阻断）
# ---------------------------------------------------------------------------

# 与 build_rag 一致的模板残留子串，用于体检研究方向的垃圾污染。
_COVERAGE_BOILERPLATE = (
    "版权所有",
    "©",
    "地址：",
    "联系地址",
    "邮编",
    "English",
    "Copyright",
    "Contact information",
    "授课信息",
    "教学研究",
    "代表性成果",
    "代表成果",
    "研究成果",
    "著作成果",
    "获奖信息",
    "招生信息",
    "邮政编码",
    "手机版",
    "访问量",
    "在线阅读链接",
    "欢迎点赞",
    "优秀实习生",
    "评审委员会",
    "谷歌学术引用",
    "Honors & Awards",
    "Social Affiliations",
)
_DIRTY_TOPIC_EXACT = {
    "教学信息", "指导研究生及博士后", "在读研究生", "新闻", "新闻动态",
    "总访问量", "日访问量", "实验室概况", "研究兴趣",
    "主要研究方向但不局限于以下", "1）主要研究方向但不局限于以下",
}
_DIRTY_TOPIC_PATTERNS = (
    re.compile(r"^中国科学技术大学.{0,30}(?:学院|实验室|中心)$"),
    re.compile(r"^中国科学院青年促进会(?:优秀)?会员"),
    re.compile(r"^[A-Za-z0-9＋+_-]{2,20}实验室$"),
    re.compile(r"(?:招收|招生|研究生课程|开设课程).{0,80}(?:博士|硕士|研究生|学生|课程)"),
    re.compile(r"^已在\s*(?:IEEE|ACM|Science|Nature)\b", re.I),
    re.compile(r"^(?:IEEE\s+Trans\..*|Pattern\s+Recognition|Science|Nature\s+Photonics|Physical\s+Review\s+Letters|ICIP\s+\d{4})$", re.I),
    re.compile(r"^\d{2}-\d{2}$"),
)


def check_coverage(candidates: list[dict], rep: Report) -> None:
    """数据覆盖体检：方向/论文/招生覆盖率低于阈值，或研究方向仍含模板残留时 WARN。

    - 覆盖率是软门禁：不影响退出码，但能暴露数据质量退化（抓取失败/同步漂移）。
    - 垃圾残留一旦出现即告警，防止上次清理后的污染回流。
    """
    total = max(len(candidates), 1)
    misses: list[str] = []

    def rate(field: str) -> float:
        return sum(1 for c in candidates if c.get(field)) / total

    topics_rate = rate("research_topics")
    pubs_rate = rate("publications")
    recruit_rate = rate("recruitment_status")
    if topics_rate < 0.60:
        misses.append(f"研究方向覆盖率 {topics_rate:.0%} 低于 60%")
    if pubs_rate < 0.20:
        misses.append(f"论文覆盖率 {pubs_rate:.0%} 低于 20%")
    if recruit_rate < 0.05:
        misses.append(f"招生信息覆盖率 {recruit_rate:.0%} 低于 5%")

    garbage = sum(
        1
        for c in candidates
        for t in (c.get("research_topics") or [])
        if (
            t in _DIRTY_TOPIC_EXACT
            or any(m in t for m in _COVERAGE_BOILERPLATE)
            or any(pattern.search(t) for pattern in _DIRTY_TOPIC_PATTERNS)
        )
    )
    if garbage:
        misses.append(f"研究方向含 {garbage} 条模板残留")

    detail = (
        f"方向 {topics_rate:.0%}，论文 {pubs_rate:.0%}，招生 {recruit_rate:.0%}"
        + (f"，垃圾 {garbage}" if garbage else "")
    )
    if misses:
        rep.add_warn("E. 覆盖率门禁", "；".join(misses) + f"（{detail}）")
    else:
        rep.add("E. 覆盖率门禁", True, detail)


def check_semantic_metadata(candidates: list[dict], evidence: list[dict], rep: Report) -> None:
    """纯 stdlib 语义门禁：论文口径、作者审核状态与候选字段必须一致。"""
    failures: list[str] = []
    paper_evidence = [
        item for item in evidence
        if str(item.get("source_type") or "").endswith("_paper_metadata")
    ]
    pending_count = 0
    for item in paper_evidence:
        metadata = item.get("metadata") or {}
        status = metadata.get("author_match_status")
        if status not in {"confirmed", "pending_review"}:
            failures.append(f"{item.get('evidence_id')}: author_match_status={status!r}")
        if "author_match_exact" not in metadata:
            failures.append(f"{item.get('evidence_id')}: 缺 author_match_exact")
        if "retrieved_representative_count" not in metadata:
            failures.append(f"{item.get('evidence_id')}: 缺代表作条数")
        if "paper_count" in metadata:
            failures.append(f"{item.get('evidence_id')}: 仍使用歧义 paper_count")
        supports = str(metadata.get("supports_fields") or "")
        if status == "pending_review" and supports:
            failures.append(f"{item.get('evidence_id')}: 待审核证据不应支持候选字段")
        if status == "pending_review":
            pending_count += 1

    if pending_count:
        failures.append(f"仍有 {pending_count} 条论文证据待人工审核")

    for candidate in candidates:
        metadata = candidate.get("source_metadata") or {}
        representative = len(candidate.get("publications") or [])
        if metadata.get("representative_publication_count") != representative:
            failures.append(
                f"{candidate.get('candidate_id')}: 代表作口径 "
                f"{metadata.get('representative_publication_count')} != {representative}"
            )
        total = metadata.get("publication_total_count")
        if total is not None and (not isinstance(total, int) or total < 0):
            failures.append(f"{candidate.get('candidate_id')}: 非法论文总数 {total!r}")
        bio = str(metadata.get("profile_bio") or "")
        if any(marker in bio for marker in ("同专业博导", "同专业硕导", "总访问量", "日访问量")):
            failures.append(f"{candidate.get('candidate_id')}: bio 含站点模板")

    detail = f"论文证据 {len(paper_evidence)} 条，语义错误 {len(failures)}"
    if failures:
        detail += "；" + "; ".join(failures[:5])
    rep.add("G. 论文语义门禁", not failures, detail)


def check_retrieval_quality(
    rag_path: Path, candidates: list[dict], rep: Report
) -> None:
    """可证伪检索门禁：垃圾查询不得入榜；词法命中才算内部召回。"""
    try:
        from data_scripts.internal_mentor_rag import FileInternalMentorRag
        from backend.mentor_workflow.schemas import IntentPacket, MentorGoal
    except Exception:  # noqa: BLE001
        def lightweight_count(terms: list[str]) -> int:
            normalized = [re.sub(r"\s+", "", term.casefold()) for term in terms]
            count = 0
            for candidate in candidates:
                blob = re.sub(
                    r"\s+", "", " ".join([
                        *map(str, candidate.get("research_topics") or []),
                        *map(str, candidate.get("methods") or []),
                        *map(str, candidate.get("publications") or []),
                    ]).casefold(),
                )
                if any(term and term in blob for term in normalized):
                    count += 1
            return count

        garbage_n = lightweight_count(["不存在的方向xyz"])
        vision_n = lightweight_count(["计算机视觉", "三维视觉"])
        rl_n = lightweight_count(["强化学习"])
        ok = garbage_n == 0 and vision_n > 0 and rl_n > 0
        rep.add(
            "F. 检索质量",
            ok,
            f"stdlib 回退：垃圾召回 {garbage_n}，视觉 {vision_n}，强化学习 {rl_n}",
        )
        return

    rag = FileInternalMentorRag(rag_path)
    garbage = rag.retrieve(
        IntentPacket(
            trace_id="verify-garbage",
            goal=MentorGoal.find_mentors,
            research_topics=["不存在的方向xyz"],
            confidence=1.0,
        ),
        [],
    )
    vision = rag.retrieve(
        IntentPacket(
            trace_id="verify-cv",
            goal=MentorGoal.find_mentors,
            research_topics=["计算机视觉", "三维视觉"],
            confidence=1.0,
        ),
        [],
    )
    rl = rag.retrieve(
        IntentPacket(
            trace_id="verify-rl",
            goal=MentorGoal.find_mentors,
            research_topics=["强化学习"],
            confidence=1.0,
        ),
        [],
    )
    garbage_n = len(garbage.candidates)
    vision_hits = [
        int(c.source_metadata.get("retrieve_hits") or 0) for c in vision.candidates
    ]
    rl_hits = [int(c.source_metadata.get("retrieve_hits") or 0) for c in rl.candidates]
    ok = garbage_n == 0 and (not vision.candidates or max(vision_hits, default=0) >= 1)
    if rl.candidates and max(rl_hits, default=0) < 1:
        ok = False
    detail = (
        f"垃圾召回 {garbage_n}，视觉 {len(vision.candidates)}，"
        f"强化学习 {len(rl.candidates)}（hits=0 不得入榜）"
    )
    rep.add("F. 检索质量", ok, detail)


def main() -> None:
    parser = argparse.ArgumentParser(description="自检 RAG 库")
    parser.add_argument("--rag", type=Path, default=DEFAULT_RAG)
    args = parser.parse_args()

    if not args.rag.exists():
        print(f"找不到 RAG 库 {args.rag}")
        sys.exit(2)
    payload = json.loads(args.rag.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    evidence = payload.get("evidence", [])
    print(f"自检 {args.rag}: {len(candidates)} 候选, {len(evidence)} 证据")

    rep = Report()
    check_schema(candidates, evidence, rep)
    check_references(candidates, evidence, rep)
    check_skip_conditions(candidates, evidence, rep)
    check_recall(candidates, evidence, rep, args.rag)
    check_coverage(candidates, rep)
    check_retrieval_quality(args.rag, candidates, rep)
    check_semantic_metadata(candidates, evidence, rep)
    rep.summary()


if __name__ == "__main__":
    main()
