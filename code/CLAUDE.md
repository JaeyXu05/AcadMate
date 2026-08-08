# CLAUDE.md — 项目上下文（给 Claude 编码助手）

本仓库是"科研导师推荐平台"四人协作项目（中科大"一〇七杯"算力与智能体开发大赛），
分四个独立部分，各自有独立文档。**接手任何任务前先读根目录 `README.md`**，它是总入口。

## 四部分速览

| 角色 | 目录 | 职责 | 自身文档 |
|---|---|---|---|
| D | `Code/` | 前后端全栈网站（React+Express+SQLite） | 契约/运行细节已并入根 `README.md`（§3 运行、§4.3 端点契约） |
| A | `paper-claw-master/backend` | FastAPI 多智能体检索后端 | `paper-claw-master/backend/MENTOR_WORKFLOW.md` |
| C | `paper-claw-master/data_scripts` + `data` | 导师抓取 + RAG 库构建 | `paper-claw-master/data_scripts/README.md` |
| B | `cloud3d/` | 3D 研究星图（Three.js） | `cloud3d/HANDOVER.md` |

## 关键数据事实

- **RAG 库**：`paper-claw-master/data/ustc_mentor_rag.json` — 715 导师 / 1523 证据，已构建成功。
  - candidate 字段：`candidate_id` / `mentor_name` / `department` / `research_topics`（仅 437/715）/
    `publications` / `homepage` / `recruitment_status` / `source_metadata.academic_title`（职称）。
  - candidate 与后端 schema 对齐（`backend/mentor_workflow/schemas.py` 的 `CandidateMentor`/`EvidenceRecord`）。
- **星图数据**：`cloud3d/cloud_data.json` — 715 节点，由 `cloud3d/build_cloud.py` 从 RAG 生成，
  含 `candidate_id/name/department/domain/color/lum/size/x/y/z/topics/pubs/homepage/recruitment`。
  通过 `candidate_id` 与 RAG、前端 Advisor.id 关联。
- **前端契约**：`Code/src/types/` 定义 `Advisor`/`CloudNode`/`AdvisorDetail` 等；D 已在
  `Code/src/services/` 预留字段映射位（组件零改动）。
- **ID 稳定性要求**：A 检索结果的 id、C 详情接口 `GET /api/advisors/:id`、B 云图 `CloudNode.id`
  三者必须一致，建议统一用 `candidate_id` 形态（如 `ustc_faculty_26275`）。

## 接口决策现状（已拍板，勿擅自改他人功能代码）

1. **hIndex** ✅ 已拍板：Type 里留可选 `hIndex` 备用，界面全用 `papers` 论文数展示（已去掉"H 指数"展示位与排序项）。
2. **matchScore / explanation** ✅ 已实现：由 A 检索流程动态计算，D 后端代理把 `MatchResult.total_score`/`rationale` 映射进 `Advisor`。
3. **检索接口形态** ✅ 已实现：前端保持 `POST /api/agent/chat`（SSE）契约不变；D 后端 `Code/server/routes/agent.ts` 作为代理，内部轮询 A 的 `/api/mentor-workflows`（非流式），把 `final_result.mentors[]`（candidate+match 嵌套）映射为扁平 `Advisor[]`。A 不可用时自动回退 stub。前端组件与 `services/agent.ts` 零改动。
4. **云图接口** ✅ 已解决：B 的 `cloud_data.json` 无 `edges` 边数据，只有同域星座连线；
   已在 `Code/server/routes/cloud.ts` 实现 `GET /api/cloud/graph`（按同域最近邻动态生成 `edges[]`），
   前端 `CloudGraph.tsx` 已集成真实 715 导师 Three.js 渲染。

> **D 协作铁律**：四人互不改别人的输出格式、也不改前端组件；真实字段与前端契约不符时，由 D 在
> service 层（`Code/src/services/`）或 D 的后端路由做字段映射"缝合"。检索代理（agent.ts 的
> `mapFinalMentor()`）正是这一条的应用。

## 环境

| 运行时 | 版本 | 备注 |
|---|---|---|
| Node.js | v24.18.0 | npm 11.16.0 |
| Python | 3.14.6（`py -3.14`） | 后端需 3.12+ |
| uv | 0.12.2 | 已装（`C:\Users\Danie\.local\bin\uv`） |
| Docker Desktop | 已装 | engine 需手动启动；pgvector DB 已起过，迁移完成 |

**A 后端环境本机已就绪**：uv + Docker Desktop + pgvector/pg16（`paper-claw-postgres`，:5432）+ alembic 迁移均完成，uvicorn 起后 `/api/health` OK。重开机后 Docker 不常驻，须手动启动 Desktop 再 `docker compose up -d`（详见根 `README.md` 第六节）。D `Code/.env` 的 `MENTOR_AGENT_BASE_URL` 已指向 :8000，A 不可达时 D 代理回退 stub。

## 协作铁律（D 的约定）

- 改动遵循 D 预留的映射位：真实数据字段与契约不符时，在 `Code/src/services/` 做 service 层映射，
  **不要让其他成员改输出格式，也不要改前端组件**。
- 介绍性/文档类文件（README、HANDOVER、接入说明、CLAUDE.md）可管理；功能代码勿动（除非用户明确要求）。