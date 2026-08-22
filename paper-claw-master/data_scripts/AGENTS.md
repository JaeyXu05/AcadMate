# AGENTS.md — 【C】data_scripts + data 抓取与 RAG 组装（详述）

> 本文件描述 C 模块代码现状，供所有 AI 编码助手共用。跨模块向导见根 `AGENTS.md`。
> **不含协作规则**（见根 `CLAUDE.md`）。数据基准：2026-08-21 通读。
>
> ⚠️ 旧文档 `data_scripts/README.md` 部分过时（检查项数、S2/DBLP 是否并入），以本文件为准。

C 负责从中科大官网 + 三大学术论文平台抓取导师信息，组装成与 A 后端 schema 对齐的 RAG 知识库 `data/ustc_mentor_rag.json`（715 导师 / 1580 证据）。**全部脚本自包含，仅依赖 `httpx`，不 import 后端**——可独立运行。

## 目录结构

```
paper-claw-master/
├── data_scripts/
│   ├── ustc_scraper.py            # ★ 中科大官网教师库
│   ├── openalex_scraper.py        # OpenAlex 论文
│   ├── semantic_scholar_scraper.py# Semantic Scholar 论文
│   ├── dblp_scraper.py            # DBLP 论文
│   ├── build_rag.py               # ★ 聚合三平台 → 组装 RAG JSON
│   ├── internal_mentor_rag.py     # ★ FileInternalMentorRag（A 依赖注入用的离线检索）
│   ├── verify_rag.py              # ★ 5 项检查 A–E
│   └── export_fuzzy_review.py     # 三平台模糊命中对照（供人工裁决）
└── data/
    ├── ustc_mentor_rag.json       # ★ 成品 RAG（715/1580/500，generated 2026-08-08）
    ├── ustc_mentor_rag.json.bak   # 旧版（1523/437，已过时）
    ├── ustc_mentors_raw.json      # 官网原始
    ├── ustc_mentor_papers{,_s2,_dblp}.json  # 三平台论文
    ├── build_rag_run2.log / verify_rag_run2.log  # ✗ 过期（2026-07-28，描述 1300 证据的更早构建）
    ├── fuzzy_review.md / fuzzy_review.json
    └── manual_overrides.json      # 人工裁决结果，各 scraper 重跑优先读
```

## 抓取脚本（4 个，仅依赖 httpx）

| 脚本 | 数据源 | 要点 |
|---|---|---|
| `ustc_scraper.py` | 中科大官网教师库 | 9 个重点学院 ID + `--all-colleges` 全校（`USTC_ALL_TEACHING_UNITS_ID=""`）；断点续抓；研究方向截断 20 条；输出 `data/ustc_mentors_raw.json` |
| `openalex_scraper.py` | OpenAlex | USTC 机构 ID `I126520041`；按被引取代表论文 → `ustc_mentor_papers.json` |
| `semantic_scholar_scraper.py` | Semantic Scholar | 匿名 ~1 req/s（默认 `--delay 1.1`）；按被引取 → `ustc_mentor_papers_s2.json` |
| `dblp_scraper.py` | DBLP | XML 端点 `/pid/{pid}.xml`（兼容数字 pid）；按年份取 → `ustc_mentor_papers_dblp.json` |

## `build_rag.py` —— RAG 组装

- **聚合 OpenAlex + S2 + DBLP 三平台论文**（⚠️ 旧 README 说 S2/DBLP"暂不并入"，**实际 `build_rag.py` 默认已并入三平台**，README §5 已更正，但各 scraper docstring 仍写旧文案）。
- **三态方向一致性过滤**：同语言无重叠 → 丢；跨语言 → 留 + warning；有重叠/无方向 → 留。
- 为每位导师生成 `CandidateMentor` + 1~5 条 `EvidenceRecord`（身份 / profile / 每平台论文各一条）。
- **`candidate_id = ustc_faculty_{faculty_id}`**——四模块共享主键，在此生成。
- **论文标题回填研究方向**：68 词 lexicon，至多 6 条，标 `topics_source=2`（这是 500/715 有方向中 66 条的来源）。
- 输出结构 `{candidates, evidence, source_chain:["internal_ustc_rag"], ...}`，字段与后端 `schemas.py` 对齐。

## `internal_mentor_rag.py` —— 离线检索（A 依赖注入用）

`FileInternalMentorRag` 实现 `InternalMentorRag.retrieve()`，**离线 TF-IDF**（无外部服务）：

- 分词：CJK 整词 + bigram
- TF 峰值归一；`idf = log(N/(1+df))`
- **`score = cosine*100 + hits*3`**（余弦相似 ×100 + 命中数 ×3）

A 的 `get_internal_mentor_rag` 依赖注入会加载此类；任何失败回退 `NullInternalMentorRag`（走 USTC 官方源）。

## `verify_rag.py` —— 5 项检查 A–E（不是 4 项）

⚠️ 旧 README 说"4 项检查"，实为 **5 项**：

| 项 | 检查 | 失败处理 |
|---|---|---|
| A | schema 合规 | |
| B | 证据引用闭环 | |
| C | 跳过外部源条件 | |
| D | 召回升单测 | 后端依赖缺失则 **SKIP** |
| E | 覆盖率软门禁 | **WARN，不影响退出码** |

## `export_fuzzy_review.py` —— 人工裁决辅助

导出三平台模糊/非精确命中对照表（`fuzzy_review.md`/`.json`）供人工裁决；裁决写入 `manual_overrides.json`，各 scraper 重跑时优先读。

## RAG 库真实计数（核对磁盘 JSON）

| 项 | 值 |
|---|---|
| 导师 / 证据 | **715 / 1580** |
| 有 `research_topics` | **500**（434 profile + 66 论文回填 `topics_source=2`） |
| 有 `publications` | 231 |
| 有 `methods` | 39 |
| 有 `recruitment_status` | 78 |
| 有 `academic_title` | 708 |
| `homepage`/`department`/`affiliation` | 100% |
| 证据按 `source_type` | 身份 715 + profile 514 + openalex 128 + s2 214 + dblp 9 = 1580 |
| `source_chain` | `["internal_ustc_rag"]` |
| `topics_source` 分布 | 0 无 215 / 1 profile 434 / 2 回填 66 |
| `candidate_id` 形态 | 全部 `^ustc_faculty_\d+$` |

## 字段对齐

`candidate_id / mentor_name / source_metadata.academic_title / research_topics` 等全部与后端 schema（`backend/mentor_workflow/schemas.py` 的 `CandidateMentor`/`EvidenceRecord`）一致——这是 A 能直接消费 RAG 的前提，改字段需同步 A schema。

## C 模块文档坑（务必留意）

- 两个 run2 日志（`build_rag_run2.log`/`verify_rag_run2.log`）**已过期**（mtime 2026-07-28，描述 1300 证据的更早构建），**不代表当前库**。
- `.bak` 文件（1523 证据 / 437 有方向 / 无 `topics_source`）是上一版；当前 JSON（1580/500/有 `topics_source`）更新。旧文档的 1523/437 描述的是 `.bak`。
- S2/DBLP 各自脚本 docstring 仍写"暂不并入 RAG"，但 `build_rag.py` 默认已并入三平台。

## 验证计数的一句话命令

```bash
py -c "import json; d=json.load(open('paper-claw-master/data/ustc_mentor_rag.json',encoding='utf-8')); print(len(d['candidates']), d['mentor_count'], len(d['evidence']), d['evidence_count'])"
# 预期: 715 715 1580 1580
```
