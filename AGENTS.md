# AGENTS.md — 科研导师推荐平台（全 Agent 共用向导）

> 本文件是给**所有 AI 编码助手**（Claude / Codex / Dash / 其它）的统一项目入口。
> **只讲项目内容与代码现状，不含协作规则**——协作规则见仓库根 `CLAUDE.md` 的"协作铁律"章节，需用户批准后才会写进文档。
>
> - 想看代码级全景汇总 → 根目录 `项目全景梳理报告.md`。
> - 想看某模块细节 → 下表"细节文档"列指向的文件。
> - 数据基准：2026-08-21 通读；RAG 库以磁盘 `paper-claw-master/data/ustc_mentor_rag.json`（generated_at 2026-08-08）为准。

---

## 一句话

学生登录网站 → 输入研究兴趣 → A 多智能体从当前进仓 **180** 位导师中匹配打分 → 展示卡片 / 详情 / 收藏 / 邮件；3D 星图仍渲染 **715** 节点快照。

## 四模块分工

| 角色 | 目录 | 职责 | 细节文档 | 技术栈 |
|---|---|---|---|---|
| **D** | `Code/` | 前后端全栈网站 | `Code/AGENTS.md` | React 18 + Express + SQLite |
| **A** | `paper-claw-master/backend` | 多智能体检索后端 | `paper-claw-master/backend/MENTOR_GUIDE.md` | FastAPI + PostgreSQL(pgvector) |
| **C** | `paper-claw-master/data_scripts` + `data` | 导师抓取 + RAG 库构建 | `paper-claw-master/data_scripts/AGENTS.md` | httpx + 离线 TF-IDF |
| **B** | `cloud3d/` | 3D 星图数据生成 | `cloud3d/AGENTS.md` | 纯 Python 数据脚本 |

> 注意：`cloud3d/` 现在只是**数据生成**模块（`build_cloud.py` → `cloud_data.json`）；真正的 3D 渲染前端在 D 的 `Code/src/components/CloudGraph.tsx`。HANDOVER.md 描述的演示前端已删除。

## 跨模块主键：candidate_id

`candidate_id`（形如 `ustc_faculty_26275`）是每位导师的唯一 ID，四模块共享：

- **生成**：C 的 `build_rag.py::_candidate_id(faculty_id) = f"ustc_faculty_{faculty_id}"`；A 的 `ustc_sources.py::mentor_candidate_id(name, faculty_id=...)` 在有 faculty_id 时产出同一形态。
- **一致性要求**：A 检索结果 `id` ⇔ C 知识库 `candidate_id` ⇔ D `GET /api/advisors/:id` ⇔ B `CloudNode.id` 必须相同。改动 ID 形态需四处同步。

## 核心数据事实（核对磁盘 JSON，非文档）

> **口径拆分**：当前进仓检索语料 `paper-claw-master/data/ustc_mentor_rag.json` 为 **180 导师 / 358 证据**。下表与 `cloud3d/cloud_data.json` 仍是星图用的 **715 / 1580** 原快照，不要把星图改成 180。

RAG 库历史全量快照（星图 `cloud_data.json` 据此生成，generated_at 以星图文件为准）：

| 项 | 值 |
|---|---|
| 导师数 | **715** |
| 证据数 | **1580**（旧文档写 1523 是上一版 `.bak`，已过时） |
| 有 `research_topics` | **500 / 715**（434 来自官网 profile + 66 论文标题回填） |
| 有 `publications` | 231 / 715 |
| 有 `methods` | 39 / 715 |
| 有 `recruitment_status` | 78 / 715 |
| 有 `source_metadata.academic_title` | 708 / 715 |
| `homepage`/`department`/`affiliation` | 100% |
| `source_chain` | `["internal_ustc_rag"]` |
| `topics_source` 分布 | 0 无方向 215 / 1 来自 profile 434 / 2 论文回填 66 |
| 证据按 `source_type` | 身份 715 + profile 514 + openalex 128 + s2 214 + dblp 9 = 1580 |

candidate 字段：`candidate_id / mentor_name / affiliation / department / research_topics / methods / publications / projects / homepage / recruitment_status / evidence_refs / missing_fields / source_metadata{ustc_faculty_id, english_name, academic_title, mentor_role, paper_platforms, topics_source}`，全部与 A 后端 schema（`mentor_workflow/schemas.py` 的 `CandidateMentor`/`EvidenceRecord`）对齐。

## 数据流总览

```
[官网/论文平台] --C抓取--> data/ustc_mentor_rag.json (检索 180/358；星图快照仍为 715/1580)
                                    │
        ┌───────────────────────────┼────────────────────────────┐
        ▼                           ▼                            ▼
   [A] mentor_workflow          [B] cloud_data.json(715)     [D] ragAdvisors.ts
   retrieve→匹配/评分/邮件/PDF   → /api/cloud/graph            读检索语料→详情/邮件/推荐
        │                           CloudGraph 715 节点        检索经D代理接A
        └── D /api/agent/chat 先 POST /api/runs，失败再 mentor-workflows ──┘
```

四模块通过 `candidate_id` 关联。检索走"前端 SSE → D 代理 → 轮询 A 非流式"链路（见 `Code/AGENTS.md`）。

## 环境

| 运行时 | 版本 | 备注 |
|---|---|---|
| Node.js | v24.18.0 | npm 11.16.0；D 全栈 |
| Python | 3.14.6（`py -3.14`） | A 后端需 3.12+；C/B 纯脚本 |
| uv | 0.12.2 | A 后端依赖管理 |
| Docker | 已装 | A 的 pgvector/pg16（`paper-claw-postgres`，:5432）；engine 需手动启动 |

各模块启动方式见各自文档与根 `README.md`。

## ⚠️ 务必留意的坑（说明性文档已过时，以代码 + 磁盘数据为准）

| # | 旧文档写法 | 代码/数据实际 |
|---|---|---|
| 1 | 证据 1523 / 有方向 437 | **1580 / 500**（当前 JSON） |
| 2 | A 模型开关 `MODEL_REASONING_ENABLED` | 实为 `PAPER_CLAW_MENTOR_WORKFLOW_MODEL_REASONING_ENABLED`，默认 False（确定性） |
| 3 | `cloud3d/cloud_data.json` 有 `legend`/可用 | ✅ 已重跑 `py build_cloud.py` 重生成（`legend[10]`/`domain_count:10`/`arms:4`，旧备份 `.bak_old`） |
| 4 | D 导师详情/邮件/推荐是 [STUB] | **均为真实 RAG**（`server/data/ragAdvisors.ts`）；`stub/advisors.ts` 已废弃；✅ PDF summary/keyPoints 也已改为真实内容（`server/routes/pdfText.ts`） |
| 5 | 有 hIndex 展示/排序 | **全链路无 hIndex**：schema 无列、`mapFinalMentor` 置 `undefined`、UI 只显示 `papers`+`matchScore` |
| 6 | 工作流含独立 `candidate_screening`/`paper_evidence_assessment` 阶段 | `WorkflowStage` 仅 9 值；那两步是 `mentor_research` 内部子步骤 |
| 7 | 星图 6 臂、`best_arm_t()`、半径 205→470 | 当前 `build_cloud.py`：**N_ARMS=4**、半径 250→460、3+3+2+2 分臂；`CloudGraph.tsx` 的 `arms:6` 仅背景装饰 |

## 旧文档状态

`README.md`、`CLAUDE.md`、`cloud3d/HANDOVER.md`、`paper-claw-master/backend/MENTOR_WORKFLOW.md`、`paper-claw-master/data_scripts/README.md` 部分内容已过时（见上表）。本套 AGENTS 文档与 `项目全景梳理报告.md` 已按代码校正；接手时以本套 + 代码为准。

---

## 协作铁律

> 本节是项目**治理约定**，与上文的"项目内容"分开。不新增规则，只把团队已拍板的约定讲清楚。各 AI 助手（Claude / Codex / Dash / 其它）均须遵守。

### 铁律一：各守输出格式，互不改对方的输出格式与前端组件

- 每人各有输出格式契约：A 的检索结果 schema、C 的 RAG 字段、B 的 `cloud_data.json` 结构、D 的前端组件。
- **不要改别人的输出格式，也不要改 D 的前端组件**（`Code/src/components/`、`Code/src/pages/`）。
- 此条**双向**：A/C/B 各自保持自己的 schema 稳定且与后端 `backend/mentor_workflow/schemas.py` 对齐，**不要为迁就前端而改自己的输出格式**；前端侧的差异由 D 负责缝合（见铁律二）。

### 铁律二：字段不符时，由 D 在 service 层 / 后端路由做映射"缝合"

- 真实数据字段与前端契约不一致时，**由 D 负责**在以下两处之一做字段映射，而不是让别人改输出格式或改前端：
  - service 层：`Code/src/services/`
  - D 的后端路由：`Code/server/routes/`
- 典型应用：检索代理 `Code/server/routes/agent.ts` 的 `mapFinalMentor()`，把 A 返回的嵌套 `candidate+match` 映射成扁平 `Advisor[]`。后续类似情况照此办理。

### 铁律三：文档可管，功能代码勿擅改

- **文档类文件可自由管理**：`README.md`、`HANDOVER.md`、接入说明、`CLAUDE.md`、`AGENTS.md` 及 `项目全景梳理报告.md`。
- **勿动本任务所属模块以外的功能代码**，除非用户明确要求跨模块改动。各模块功能代码（D 前后端、A 后端、C 脚本、B 生成脚本）各有归属，跨模块改动需用户点头。

### 附：ID 稳定性（跨模块一致性，非可选项）

- `candidate_id`（形如 `ustc_faculty_26275`）在四处必须一致：A 检索结果 `id` ⇔ C 详情接口 `GET /api/advisors/:id` ⇔ B 云图 `CloudNode.id` ⇔ RAG `candidate_id`。
- 改动 ID 形态需四处同步，否则关联断裂。
> 注：此项原属"关键数据事实"，因其直接约束四人如何协同（一人改 ID 需四人同步），提升至此。
