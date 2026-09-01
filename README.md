# 科研导师推荐平台（"一〇七杯"算力与智能体开发大赛）

> 中国科学技术大学"一〇七杯"算力与智能体开发大赛 · 科研导师推荐平台。
> 本仓库为四人团队协作项目，分四个独立部分，各自有独立的文档与运行方式。
> **本文档是总入口，负责把四部分串起来**，并说明它们如何对接、当前接口状态与缺口。

---

## 一、仓库结构总览

```
code/
├── README.md                          ← 本文件（总入口，四部分导航与现状）
├── CLAUDE.md                          ← 供 Claude 编码助手使用的项目上下文
├── 启动项目.bat                        ← 一键启动主站（前后端 + 打开浏览器）
├── Code/                              【D · 前后端全栈网站】
│   ├── src/                           前端（React 18 + TS + AntD5 + Zustand + Vite + Three.js）
│   │   └── components/CloudGraph.tsx  3D 星云图组件（Three.js，渲染真实 715 导师）
│   ├── server/                        后端（Express + TS + better-sqlite3）
│   │   └── routes/cloud.ts            GET /api/cloud/graph（读 cloud_data.json 供云图）
│   └── package.json                   （含 three / @types/three 依赖）
├── paper-claw-master/                 【A · 多智能体后端  +  C · RAG 库与抓取】
│   ├── README.md                      （Paper Claw 全栈 App 配置/运行说明）
│   ├── backend/                       （A：FastAPI 多智能体后端）
│   │   └── MENTOR_WORKFLOW.md         （导师检索工作流架构/API 文档）
│   ├── data_scripts/                  （C：抓取与 RAG 构建脚本）
│   │   └── README.md                  （C 写的抓取与 RAG 构建流程文档）
│   └── data/                          （C 产出的 JSON 数据，含核心 RAG 库）
│       └── ustc_mentor_rag.json       当前进仓检索语料（180 导师 / 358 证据；星图仍用 cloud_data.json 的 715 节点）
├── cloud3d/                           【B · 3D 星图数据生成】
│   ├── build_cloud.py                 读 RAG 库 → 生成 cloud_data.json（坐标/配色）
│   └── cloud_data.json                银河盘可视化数据（主站后端 /api/cloud/graph 取用）
└── 项目规划/                          （仓库外同级目录，后端多智能体技术报告与演示）
```

> 同级目录 `../项目规划/` 还存有后端的技术报告与可运行演示脚本
> （`paper_claw_*技术报告.md`、`run_*demo.py` 等），属规划阶段产物。

---

## 二、四个部分分工与关系

| 角色 | 目录 | 交付物 | 一句话职责 |
|---|---|---|---|
| **D** | `Code/` | 前后端全栈网站 | 登录/主界面/检索台/收藏/云图/邮件/PDF/推荐，后端（导师类数据）以真实 RAG 填充 |
| **A** | `paper-claw-master/backend` | 多智能体检索后端 | 导师检索工作流，匹配/评分/证据/邮件/PDF 分析 |
| **C** | `paper-claw-master/data_scripts + data` | 导师抓取 + RAG 知识库 | 爬取官网/OpenAlex/S2/DBLP，组装 RAG 库，供 A/云图使用 |
| **B** | `cloud3d/` | 3D 研究星图 | 读 RAG 库生成银河系星图可视化 |

**数据流（核心）：**

```
[官网/论文平台] --C抓取--> paper-claw-master/data/ustc_mentor_rag.json (检索语料 180导师/358证据)
                                    │
        ┌───────────────────────────┼──────────────────────────────┐
        ▼                           ▼                              ▼
   [A后端] mentor_workflow      [B云图] build_cloud.py        [D 网站前端]
   InternalMentorRag.retrieve()  --> cloud_data.json            GET /api/advisors/:id 等
   → 匹配/评分/邮件/PDF          → 主站后端 /api/cloud/graph        （云图已接真实 715 节点）
                                 → CloudGraph.tsx(Three.js 渲染)     （检索走 180/358 语料）
```

四部分之间的数据都通过 **`candidate_id`**（如 `ustc_faculty_26275`）关联，应与前端 `Advisor.id` / 云图 `CloudNode.id` 保持一致。

---

## 三、各部分运行方式

> 以下每个部分的详细步骤见其自身文档（括号内标注）。这里只给速览。

Windows 用户首次使用先双击 `检查启动环境.bat`，它会跨安装路径检查并准备 Node.js、uv、Docker、依赖、数据库和迁移；日常再双击轻量的 `启动项目.bat`，浏览器会立即显示启动页并在服务就绪后自动进入平台。详细说明见 [`一键启动说明.md`](./一键启动说明.md)。

### 3.1 网站前端（D）—— `Code/`

- 环境：Node.js ≥ 18，npm。
- 配置：`cd Code && cp .env.example .env`（填 `JWT_SECRET`，后端端口默认 3001）。
- 依赖：`cd Code && npm install`。
- 启动：`npm run dev` → 前端 `http://localhost:5173`、后端 `http://localhost:3001`。
- 登录账号：任意邮箱 + 密码（≥6 位）即注册即登录。
- **当前状态**：云图已接真实 RAG 数据（`GET /api/cloud/graph`，715 导师）；检索已通过 D 代理接入 A 的真实后端（`MENTOR_AGENT_BASE_URL` 指向 :8000，未配置或 A 不可达时**不再回退 stub 导师**，直接报错）。邮件/推荐用语料 180/358，PDF 分析已用 `unpdf` 抽取正文生成 summary/keyPoints + 内容匹配推荐（非 stub）。

**网站功能清单**（登录即注册，任意邮箱 + 密码 ≥6 位）：检索工作台（SSE 流式 + 导师卡片）、历史记录、导师详情页、收藏夹（2~4 位批量对比）、邮件模板、PDF 分析、猜你喜欢、个人信息/偏好设置/注销账号、云图（3D 星云图）。

**备用命令与常见问题**：
- 分别启动：`npm run dev:frontend`（仅前端）/ `npm run dev:backend`（仅后端）；`tsx` 非自动 watch，改后端需重启。
- 生产构建：`npm run build`（tsc 检查 + Vite 打包到 `dist/`）→ `npm run preview`。
- 端口被占（EADDRINUSE :3001/:5173）：关掉占用进程，或用 `.env` 改 `PORT`。
- 重置数据库：删 `Code/data.db`（含 `-wal`/`-shm`），重启后端自动重建空库。
- 打包交给队友时排除：`Code/node_modules/`、`Code/data.db*`、`Code/.env`（`.env.example` 保留）。

详见：本 README 第三节其余部分 + 第四节（Code 的交付/接入细节已并入本总文档）。

### 3.2 多智能体后端（A）—— `paper-claw-master/backend`

- 环境：Python 3.12+、uv、Docker（PostgreSQL + pgvector）、Node.js 20+。
- **本机环境已就绪**（见第六节）：uv、Docker Desktop、pgvector DB、alembic 迁移均已完成，`/api/health` 已验证 OK。重开机器后只需：① 手动启动 Docker Desktop；② `cd paper-claw-master && docker compose up -d` 起 DB；③ 起后端（注意 `backend` 包源码在 `backend/src/`，须从该目录启动，否则 `No module named 'backend'`）：`cd paper-claw-master/backend/src && ../.venv/Scripts/python.exe -m uvicorn backend.api.app:create_app --factory --port 8000`（用 uv 亦可：在 `backend/` 下 `uv run --directory src uvicorn backend.api.app:create_app --factory --port 8000`）。
- 数据库：`docker compose up -d` 起 PostgreSQL（pgvector）。
- 依赖：项目根 `npm run setup`（装根/前端 npm + 用 uv 装后端 Python 依赖）。
- 配置：`cp .env.example .env`，填 API key **（导师工作流默认 `PAPER_CLAW_MENTOR_WORKFLOW_MODEL_REASONING_ENABLED=false`，可离线确定性运行，不填模型 key 也能跑）**。
- 启动：`npm run dev` → 后端 `http://localhost:8000`、前端 Vite。
- 测试：`python -m pytest backend/tests/mentor_workflow -q -p no:cacheprovider`。

详见：[`README.md`](paper-claw-master/README.md)、[`backend/MENTOR_WORKFLOW.md`](paper-claw-master/backend/MENTOR_WORKFLOW.md)

### 3.3 RAG 数据（C）—— `paper-claw-master/data_scripts + data`

- 环境：Python 3.12+，脚本依赖仅 `httpx`（同时保证 `pydantic` 供 `internal_mentor_rag.py`）。
- 抓取（按需，均已产出过）：官网 `ustc_scraper.py` → OpenAlex `openalex_scraper.py` → S2 `semantic_scholar_scraper.py` → DBLP `dblp_scraper.py`。
- 组装：`python data_scripts/build_rag.py` → `data/ustc_mentor_rag.json`。
- 自检：`python data_scripts/verify_rag.py`（A/B/C/D 四项检查）。
- **当前状态**：RAG 库已构建成功（`build_rag_run2.log` / `verify_rag_run2.log` 通过），可直接使用。

详见：[`data_scripts/README.md`](paper-claw-master/data_scripts/README.md)

### 3.4 3D 星图（B）—— `cloud3d/`

> ✅ **已集成进主站**：3D 星图现在是主站前端 `Code/src/components/CloudGraph.tsx` 的一部分
> （Three.js 渲染真实 715 导师节点）。`cloud3d/` 只保留**数据生成**能力，不再需要独立的演示前端。

- 环境：Python（`py`）用于生成数据。
- 生成数据：`cd cloud3d && py build_cloud.py`（读 `../paper-claw-master/data/ustc_mentor_rag.json` → 生成 `cloud_data.json`）。
- 主站如何取用：后端 `GET /api/cloud/graph`（`Code/server/routes/cloud.ts`）读取该 `cloud_data.json`，
  映射为 `CloudNode` 并生成同域关系边，前端 CloudGraph 渲染。
- **当前状态**：`cloud_data.json` 已生成（715 节点），主站星图页已能浏览真实导师网络。
- 数据更新流程：RAG 库更新后 → 重跑 `build_cloud.py` → 重启主站后端即可。

---

## 四、四部分接口现状与缺口 ⚠️ 重点

四部分由四人分别完成，**数据字段与接口形态存在不一致**，需要统一决策。当前状态与建议如下（详细见各部分文档）：

### 4.1 前端需要的 `Advisor` 字段 vs RAG/后端实际字段

前端 `Code/src/types/search.ts` 定义 `Advisor`（`hIndex` 已改为可选，界面用 `papers` 展示）：
```ts
interface Advisor { id, name, title, department, tags[], hIndex?, papers, matchScore, explanation? }
```

| 前端字段 | RAG 数据（C） | 后端 A（MatchResult/CandidateMentor） | 结论 |
|---|---|---|---|
| `id` | `candidate_id` | `candidate.candidate_id` | ✅ 一致，建议统一用它 |
| `name` | `mentor_name` | `candidate.mentor_name` | ✅ 一致 |
| `title`(职称) | `source_metadata.academic_title` | `candidate.source_metadata.academic_title` | ✅ 有，需提取 |
| `department` | `department` | `candidate.department` | ✅ 一致 |
| `tags` | `research_topics`(仅 500/715) | `candidate.research_topics` | ✅ 有（部分缺，可用 methods 兜底） |
| `papers` | `len(publications)` / `openalex_works_count` | `candidate.publications` | ✅ 用 `len(publications)` |
| `hIndex` | ❌ **RAG 无** | ❌ **后端无此字段** | ✅ 已在 Type 留可选字段，界面不再展示，改用 `papers` |
| `matchScore` | ❌ 静态库无 | `match.total_score`(0-100) | ✅ 来自 A 检索时动态计算（代理映射） |
| `explanation` | `evidence.extracted_fact` 可拼 | `match.rationale` / `dimension_scores` | ✅ 用 A 的 rationale（代理里 join） |
| x/y/z 坐标 | ❌ | ❌ | ✅ 由 B `build_cloud.py` 单独生成 |

### 4.2 接口决策现状

1. **`hIndex` 缺失** ✅ **已拍板**：前端 Type 保留可选 `hIndex` 备用，界面全部用 `papers`（论文数）展示，去掉了"H 指数"展示位与排序项。将来 A/C 若能采集真实 H 指数可随时加回。

2. **`matchScore` / `explanation` 来源** ✅ **已实现**：这两项由 A 的检索流程动态计算，`Code/server/routes/agent.ts` 代理已把 `MatchResult.total_score` / `rationale` 映射进 `Advisor`。

3. **检索接口形态** ✅ **已实现（D 代理轮询）**：前端走 `POST /api/agent/chat`（SSE：结构化 `stage` 透传 `payload/evidence_refs`，并兼容 `thinking/result/summary/done/error`）。D 先尝试 A 的 `POST /api/runs`（skill `mentor_match`），失败则回退 `POST /api/mentor-workflows`，再 resume → 轮询 events/status → review/evidence/result。`MENTOR_AGENT_BASE_URL` 未配置或 A 连不上时**不回退王某某等 stub 导师**。详情页「阅读其论文」经 Harness 创建真实 Paper Claw `AgentRun`，使用 `RetrievalService` 取 chunk；只有 run 成功且回答引用检索证据时才 Review PASS 并服务端写回成长状态。

4. ~~**云图接口形态（B/C）**~~ ✅ **已解决并完成集成**：后端 `GET /api/cloud/graph`（`Code/server/routes/cloud.ts`）读取 `cloud_data.json`，映射为 `CloudNode` 并动态生成同域关系边（`same-field`），前端 `CloudGraph.tsx` 已改为真实 Three.js 渲染 715 导师节点。云图数据不再走 mock。**不要把星图 715 改成 180。**

> 上述字段映射均按 **D 的协作铁律**收在 D 侧（`Code/server/routes/agent.ts` 的 `mapFinalMentor()`），A/C 输出格式零改动、前端组件零改动。

### 4.3 各协作端点的详细契约（D 侧已定，供 A/C 联调）

> **通用约定**：API 前缀 `/api`；除登录外均需 `Authorization: Bearer <token>`；错误统一 `{message}`；前端契约在 `Code/src/types/`，服务层映射在 `Code/src/services/` 与 D 后端路由。D 已把每个协作功能的真实数据在服务层/路由层缝合，保持前端契约不变（`server/stub/advisors.ts` 为废弃的旧 mock，勿用）。

**① 检索对话 `POST /api/agent/chat`**（SSE 流式；D 后端代理接入 A；A 不可用时返回错误，不回退 stub）：
`SSE` 事件序列（每条 `event: <type>\ndata: <JSON>\n\n`）：`stage`（审核/返工等）与 `thinking`（旧契约，可多次）→ `result`（`{type:'result', advisors:Advisor[], suggested_next_skill?}`）→ `summary` → `done`/`error`。

**② 邮件模板 `POST /api/email/generate`**：`{advisor_id:string}` → `{subject:string, body:string}`。

**③ PDF 分析 `POST /api/upload/pdf` + `POST /api/pdf/analyze`**：上传 `multipart` 字段 `file`（PDF ≤20MB）→ `{upload_id, filename}`；分析 `{upload_id}` → `{summary, keyPoints[], suggestedAdvisors:Advisor[]}`。

**④ 猜你喜欢 `GET /api/recommend`**：→ `{recommendations:Advisor[], basedOn:string[]}`。

**⑤ 导师详情 `GET /api/advisors/:id` + `explanation`**（C 接）：详情返回 `AdvisorDetail`（`Advisor` + `bio/contact/recentPapers/recruiting`）；explanation 返回 `{explanation}`。

**导师详情/检索的对象类型 `Advisor`**（`Code/src/types/search.ts`）：
```ts
{ id, name, title, department, tags[], hIndex?, papers, matchScore, explanation? }
```
`id` 必须跨端一致：A 检索结果 `id` ⇔ C 知识库导师 `id` ⇔ `GET /api/advisors/:id` 接受的 id。

---

## 五、给新接手者 / Claude 的阅读顺序

1. 读本 README（四部分导航与现状）+ 根目录 `CLAUDE.md`（项目上下文速览）。
2. 前端：`Code/` 的 `src/`、`server/`（当前实现；运行步骤见 README 第三节）。
   - `Code/` 不再单独维护接入说明——云图已集成，检索/邮件/推荐契约即时同步在本节第四节。
3. 后端：`paper-claw-master/README.md`（后端 App 配置运行）+ `paper-claw-master/backend/MENTOR_WORKFLOW.md`（工作流与 API）。
4. 数据：`paper-claw-master/data_scripts/README.md`（抓取与 RAG 构建）。
5. 云图数据：README 第三节 3.4 + `cloud3d/build_cloud.py`（生成 `cloud_data.json` 的算法）。

---

## 六、环境速查（本机已确认的运行时）

| 运行时 | 版本 | 位置 / 备注 |
|---|---|---|
| Node.js | v24.18.0 | 全局 npm 11.16.0 |
| Python | 3.14.6（`py -3.14`） | 系统（后端需 3.12+） |
| uv | ✅ 0.12.2 | `%USERPROFILE%\.local\bin\uv`（亦可 `py -m uv`） |
| Docker Desktop | ✅ 已安装（engine 需手动启动） | `C:\Program Files\Docker\Docker\resources\bin\docker.exe` |
| PostgreSQL + pgvector | ✅ 已通过 Docker 启动过 | `paper-claw-master/docker-compose.yml`：`pgvector/pgvector:pg16`，容器 `paper-claw-postgres`，端口 5432 |
| conda | ❌ 未安装 | （C 脚本不强制） |

**当前 A 后端运行状态**：A 的多智能体后端需本机启动（Docker pgvector + uvicorn）。**注意 Docker Desktop 不会随开机自动常驻**，重开会话后若 A 连不上（`.env` 里 `MENTOR_AGENT_BASE_URL` 指向的 :8000 不通），先手动启动 Docker Desktop 并 `cd paper-claw-master && docker compose up -d`，再起 uvicorn。D 网站此时**不会**回退 stub 导师，检索会提示无法连接。

> 启动步骤详细见第三节 3.2（A 部分）。

### ⚠️ 已知踩坑：Node.js 24 + better-sqlite3

`Code/package.json` 原先锁定 `better-sqlite3@^13.0.2`。**在 Node.js 24（ABI 137）下该版本没有预编译二进制，会触发 node-gyp 从源码编译，若未装 Visual Studio C++ Build Tools 会直接失败**（`npm install` 报 `gyp ERR! find VS`）。

> ✅ **已修复**：将 `better-sqlite3` 升到 `^13.0.3`（含 Node 24 的 win32-x64 预编译二进制），`npm install` 无需 VS 工具链即可通过，运行验证正常。

其他成员若在 Node 24 上装依赖报错，先检查 `package.json` 里的 `better-sqlite3` 版本是否为 `^13.0.3`（或更高）。

> 功能性文件仅此一处为让项目在 Node 24 上可运行而做的依赖版本调整；其余介绍性文件（README/接入说明/交接文档）仅作归档与新总 README、CLAUDE.md 的补充，功能代码未改动。
