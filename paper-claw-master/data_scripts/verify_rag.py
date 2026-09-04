"""RAG 库自检脚本（只读，不联网）。

对 ``data/ustc_mentor_rag.json`` 跑 4 项检查，每项打印 PASS/FAIL，最后给汇总：

  A. schema 合规    —— 每条 CandidateMentor / EvidenceRecord 能通过后端 pydantic
                       model_validate；后端不可 import 时降级为手写字段校验。
  B. 证据引用闭环   —— 每个候选的 evidence_refs 都能在 evidence 里找到，且
                       evidence.candidate_id 反向指回该候选；无悬空引用。
  C. 跳过外部源条件 —— 抽样"有研究方向+有证据"的导师，验证其证据含
                       identity_verified=true 且 mentor_role_verified≠False。
  D. 召回升单测     —— 用几个已知方向词跑 retrieve()，确认能召回对应导师。

用法：
  python data_scripts/verify_rag.py [--rag data/ustc_mentor_rag.json]

可在任何装了 httpx 的环境跑（schema 检查会自动降级）；在后端环境（装了
openai/pydantic）跑时 schema 检查走严格 model_validate。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG = REPO_ROOT / "data" / "ustc_mentor_rag.json"
DEFAULT_TRUTHSET = REPO_ROOT / "eval" / "mentor_queries.json"
DEFAULT_QUALITY_BASELINE = REPO_ROOT / "config" / "rag_quality_baseline.json"

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
    except Exception as exc:  # noqa: BLE001 - 后端依赖缺失时跳过，不算失败
        rep.add_skip("D. 召回升单测", f"环境缺后端依赖，跳过: {exc}")
        return

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

    rag = FileInternalMentorRag(rag_path)
    failed: list[str] = []
    for query, expected in test_cases:
        intent = IntentPacket(
            trace_id="verify-recall",
            goal=MentorGoal.find_mentors,
            research_topics=[query],
            confidence=1.0,
        )
        result = rag.retrieve(intent, [])
        names = {c.mentor_name for c in result.candidates}
        if expected not in names:
            failed.append(f"查'{query}'未召回{expected}")
    ok = not failed
    detail = f"{len(test_cases)} 个用例，失败 {len(failed)}"
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
)
_COVERAGE_NAVIGATION = (
    "总访问量", "日访问量", "网站访问量", "登录", "教学资源", "团队风采",
    "新闻动态", "组内相册", "其他栏目", "科研进展", "招生招聘", "我的相册",
    "教师博客", "扫描手机二维码", "欢迎您的访问",
)
_COVERAGE_BIBLIOGRAPHY = (
    "et al", "doi", "journal of", "sci adv", "angew chem", "adv mater",
    "ultramicroscopy", "pnas",
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

    def topic_is_garbage(topic: object) -> bool:
        text = str(topic or "")
        folded = text.casefold()
        return (
            any(m in text for m in _COVERAGE_BOILERPLATE)
            or any(m in text for m in _COVERAGE_NAVIGATION)
            or any(m in folded for m in _COVERAGE_BIBLIOGRAPHY)
        )

    garbage = sum(
        1 for c in candidates for t in (c.get("research_topics") or [])
        if topic_is_garbage(t)
    )
    bio_navigation = sum(
        1
        for c in candidates
        for line in str(c.get("source_metadata", {}).get("profile_bio") or "").splitlines()
        if line.strip() in _COVERAGE_NAVIGATION
    )
    if garbage:
        misses.append(f"研究方向含 {garbage} 条模板残留")
    if bio_navigation:
        misses.append(f"简介含 {bio_navigation} 条导航残留")

    detail = (
        f"方向 {topics_rate:.0%}，论文 {pubs_rate:.0%}，招生 {recruit_rate:.0%}"
        + (f"，方向垃圾 {garbage}" if garbage else "")
        + (f"，简介导航 {bio_navigation}" if bio_navigation else "")
    )
    if misses:
        rep.add_warn("E. 覆盖率门禁", "；".join(misses) + f"（{detail}）")
    else:
        rep.add("E. 覆盖率门禁", True, detail)


def check_retrieval_quality(rag_path: Path, rep: Report) -> None:
    """可证伪检索门禁：垃圾查询不得入榜；词法命中才算内部召回。"""
    # 直接执行本脚本时 sys.path[0] 是 data_scripts/，而 ``data_scripts``
    # 作为包需要其父目录在搜索路径中；补齐后该检查不再无故 SKIP。
    for path in (REPO_ROOT, REPO_ROOT / "backend" / "src"):
        as_text = str(path)
        if as_text not in sys.path:
            sys.path.insert(0, as_text)
    try:
        from data_scripts.internal_mentor_rag import FileInternalMentorRag
        from backend.mentor_workflow.schemas import IntentPacket, MentorGoal
    except Exception as exc:  # noqa: BLE001
        rep.add_skip("F. 检索质量", f"无法导入 retrieve: {exc}")
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


def check_provenance(candidates: list[dict], evidence: list[dict], rep: Report) -> None:
    """Hard invariants: pending paper leads can never become mentor facts."""
    profile_backfill = [
        e.get("evidence_id") for e in evidence
        if e.get("source_type") == "ustc_official_faculty_profile"
        and e.get("metadata", {}).get("topics_backfilled") is True
    ]
    unverified_paper_facts = [
        e.get("evidence_id") for e in evidence
        if any(field in str(e.get("metadata", {}).get("supports_fields", ""))
               for field in ("research_topics", "methods", "publications"))
        and "paper" in str(e.get("source_type", "")).casefold()
        and e.get("metadata", {}).get("identity_verified") is not True
    ]
    leaked_methods = [
        c.get("candidate_id") for c in candidates
        if c.get("methods") and c.get("source_metadata", {}).get("methods_verified") is not True
    ]
    legacy_untrusted_topics = [
        c.get("candidate_id") for c in candidates
        if int(c.get("source_metadata", {}).get("topics_source") or 0) == 2
    ]
    errors = profile_backfill + unverified_paper_facts + leaked_methods + legacy_untrusted_topics
    rep.add(
        "G. 证据溯源硬门禁",
        not errors,
        f"官网伪回填 {len(profile_backfill)}，未核验论文事实 {len(unverified_paper_facts)}，"
        f"未核验 methods 泄漏 {len(leaked_methods)}，旧 source=2 方向 {len(legacy_untrusted_topics)}",
    )


def check_truthset_anchors(evidence: list[dict], rep: Report, truthset: Path) -> None:
    if not truthset.exists():
        rep.add("H. 真值集证据锚", False, f"缺少 {truthset}")
        return
    spec = json.loads(truthset.read_text(encoding="utf-8"))
    official = [
        row for row in evidence
        if row.get("source_type") == "ustc_official_faculty_profile"
        and row.get("metadata", {}).get("identity_verified") is True
    ]
    missing: list[str] = []
    for query in spec.get("queries", []):
        for anchor in query.get("evidence_anchors", []):
            matched = any(
                row.get("candidate_id") == anchor.get("candidate_id")
                and row.get("source_uri") == anchor.get("source_uri")
                and all(
                    token.strip() in str(row.get("extracted_fact", ""))
                    for token in str(anchor.get("assertion", "")).split("；")
                    if token.strip()
                )
                for row in official
            )
            if not matched:
                missing.append(f"{query.get('id')}:{anchor.get('candidate_id')}")
    rep.add("H. 真值集证据锚", not missing, f"缺失/漂移 {len(missing)}" + (f"：{missing[:5]}" if missing else ""))


def check_quality_baseline(candidates: list[dict], evidence: list[dict], rep: Report, baseline_path: Path) -> None:
    pending = sum(
        e.get("metadata", {}).get("identity_review_status") == "pending"
        for e in evidence
    )
    trusted_topics = sum(
        int(c.get("source_metadata", {}).get("topics_source") or 0) in {1, 3}
        for c in candidates
    )
    if not baseline_path.exists():
        rep.add_warn("I. 可信覆盖/待审积压", f"无基线；可信方向 {trusted_topics}，待审论文实体 {pending}")
        return
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    min_trusted = int(baseline.get("min_trusted_topic_candidates", 0))
    max_pending_growth = int(baseline.get("max_pending_identity_records", pending))
    ok = trusted_topics >= min_trusted and pending <= max_pending_growth
    rep.add(
        "I. 可信覆盖/待审积压",
        ok,
        f"可信方向 {trusted_topics}（最低 {min_trusted}），待审 {pending}（最高 {max_pending_growth}）",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="自检 RAG 库")
    parser.add_argument("--rag", type=Path, default=DEFAULT_RAG)
    parser.add_argument("--truthset", type=Path, default=DEFAULT_TRUTHSET)
    parser.add_argument("--quality-baseline", type=Path, default=DEFAULT_QUALITY_BASELINE)
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
    check_retrieval_quality(args.rag, rep)
    check_provenance(candidates, evidence, rep)
    check_truthset_anchors(evidence, rep, args.truthset)
    check_quality_baseline(candidates, evidence, rep, args.quality_baseline)
    rep.summary()


if __name__ == "__main__":
    main()
