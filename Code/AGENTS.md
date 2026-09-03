# AGENTS.md — 【D】Code/ 网站全栈（详述）

> 本文件描述 D 模块代码现状，供所有 AI 编码助手共用。跨模块向导见根 `AGENTS.md`。
> **不含协作规则**（见根 `CLAUDE.md`）。数据基准：2026-08-21 通读。

D 是面向学生的全栈网站：登录、聊天检索导师、看详情/星图、收藏、生成联系邮件、PDF 分析、智能推荐。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | React 18.3 + TS 5.6 + AntD 5.22 + Zustand 5 + Vite 5 + Three.js 0.185 | 组件化 + 类型 + UI + 全局状态 + 3D |
| 后端 | Express 4.22 + TS + tsx 运行 | Node Web 服务 |
| 数据库 | better-sqlite3 `^13.0.3` | 文件型 `Code/data.db`（WAL） |
| 认证 | JWT（7 天）+ bcryptjs（cost 10） | 令牌 + 密码加密 |

`package.json` **无 `engines` 字段**；脚本 5 个：`dev`（concurrently 跑 vite + tsx）、`dev:frontend`、`dev:backend`、`build`（tsc -b + vite build）、`preview`。端口：前端 5173、后端 3001。

## 目录结构

```
Code/
├── server/
│   ├── index.ts            # Express 启动 + 路由挂载 + 全局中间件
│   ├── db.ts               # SQLite 建表/迁移（PRAGMA user_version，SCHEMA_VERSION=3）
│   ├── data/growthStore.ts # ★ Review PASS AgentRun 的成长状态写回门禁
│   ├── data/ragAdvisors.ts # ★ 活数据源：读 RAG JSON 建 byId Map（被多路由复用）
│   ├── stub/advisors.ts    # ✗ 8 条 mock（带 hIndex），已废弃，无路由引用
│   ├── middleware/auth.ts  # JWT 校验
│   ├── middleware/rateLimit.ts
│   └── routes/
│       ├── auth.ts         # 登录即注册
│       ├── agent.ts        # ★ SSE 检索代理 → A 后端（含 mapFinalMentor 缝合）
│       ├── advisors.ts     # 导师详情（真实 RAG）
│       ├── cloud.ts        # ★ 云图：读 cloud_data.json + 动态生成同域边
│       ├── email.ts        # 生成联系邮件（真实 RAG + 确定性模板）
│       ├── pdf.ts          # PDF 上传 + 分析（summary/keyPoints 由正文抽取，suggestedAdvisors 内容匹配）
│       ├── pdfText.ts      # PDF 文本抽取(unpdf) + 关键词分析/导师打分（被 pdf.ts 用）
│       ├── recommend.ts    # 智能推荐（真实 RAG，关键词命中打分）
│       ├── favorites.ts / history.ts / settings.ts / user.ts
├── src/
│   ├── App.tsx             # 路由 + AuthGuard/GuestGuard 守卫
│   ├── main.tsx / index.css
│   ├── pages/              # 14 个页面（Welcome/Search/Cloud/Advisor/Email/Compare/Pdf/Recommend/Profile/Settings/Favorites/Other）
│   ├── components/         # AdvisorCard/ChatWindow/CloudGraph/SortSelector/...
│   ├── services/           # ★ axios.ts + 各 API 客户端（agent.ts/advisor.ts/cloud.ts/...）
│   ├── stores/             # authStore/searchStore/settingsStore（Zustand）
│   └── types/              # 契约类型（search.ts 的 Advisor/CloudNode 等）
└── .env                    # JWT_SECRET/PORT/CORS_ORIGINS/MENTOR_AGENT_BASE_URL/...
```

## 后端数据库（5 表 + 2 索引）

`server/db.ts` 用 `PRAGMA user_version` 做版本迁移（`SCHEMA_VERSION=3`）；开库即设 `journal_mode=WAL`、`foreign_keys=ON`；DB 文件 `Code/data.db`。

| 表 | 用途 | 关键约束 |
|---|---|---|
| `users` | 用户 | `email UNIQUE`、`password_hash`（bcrypt）、`interests/skills` 存 JSON 字符串数组 |
| `favorites` | 收藏 | `UNIQUE(user_id, advisor_id)`、`FK(user_id→users) ON DELETE CASCADE` |
| `user_settings` | 设置 | `user_id UNIQUE NOT NULL`、`FK CASCADE`；4 字段 `bg_theme/bg_color/default_sort/card_density` |
| `search_history` | 检索历史 | `FK CASCADE`、索引 `idx_search_history_user(user_id, created_at DESC)` |
| `chat_history` | 对话历史 | `FK CASCADE`、索引 `idx_chat_history_session(user_id, session_id, created_at)` |
| `growth_state` | 科研成长 | `user_id` PK；导师/方向/论文 + `direction_hypotheses/verified_experiences/artifacts/research_tasks` 七类 JSON 状态；只由 Review PASS AgentRun 服务端写回；`SCHEMA_VERSION=3` |

> **全库无任何 `hIndex` 列。**

## 关键 API（`server/routes/*`，除 `/auth/login` 外均需 `Authorization: Bearer <token>`）

### `POST /api/agent/chat` —— SSE 检索代理（D 的核心缝合点）

SSE 流式，限流 12/min/IP。D 作为代理转发给 A：

- **SSE 事件序列**（每条 `event:<t>\ndata:<JSON>\n\n`，payload 带 `type`）：`stage` 保留 A 的 `payload/evidence_refs/sender/receiver/timestamp`，并增加 `EVIDENCE_READY` 与成长写回事件；`thinking` 仅保留兼容。`result` 带 `run_id/review_status/evidence_refs`。
- **内部流程**：先 `POST {A}/api/runs`（`skill_id=mentor_match`）取 `trace_id` 或 `run_id`；失败则回退 `POST {A}/api/mentor-workflows`。再 `POST .../resume` → 轮询 `GET .../events`（去重后同时发 `stage` + `thinking`）+ `GET .../status` → `GET .../result`。
- **回退**：`MENTOR_AGENT_BASE_URL` 未配或 A 不可达 → **不返回 stub 导师**，SSE `error`。
- **阅读论文**：`POST /api/agent/read` `{candidate_id, growth}` → A Harness `skill_id=paper_qa` → 创建真实 Paper Claw `AgentRun` 并后台执行。D 轮询 Harness result；只有 run 成功、`RetrievalService` 返回 chunk 且答案按 `[chunk:id]` 引用证据时 Review PASS 并写回成长状态。论文检索仍不污染导师搜索。
- **★ `mapFinalMentor()` 字段映射**（D 侧缝合关键，真实字段→前端契约）：

  | 前端字段 | 来源 | 说明 |
  |---|---|---|
  | `id` | `candidate.candidate_id ?? String(index+1)` | 稳定 ID |
  | `name` | `candidate.mentor_name ?? '未知导师'` | 过滤掉 `'未知导师'` |
  | `title` | `candidate.source_metadata?.academic_title ?? ''` | 职称 |
  | `department` | `candidate.department ?? ''` | |
  | `tags` | `candidate.research_topics ?? []` | 研究方向 |
  | `papers` | `source_metadata.publication_total_count`，回退 `candidate.publications.length` | 论文总数；代表作只作展示 |
  | `matchScore` | `Math.round(match.total_score ?? 0)` | 匹配度 0~100 |
  | `explanation` | `match.rationale`（数组→换行拼接）| 匹配说明 |
  | `hIndex` | `undefined` | **始终置空** |

### 其余端点

| 端点 | 真实性 | 说明 |
|---|---|---|
| `POST /api/auth/login` | 真实 | 登录即注册（邮箱正则 + 密码 ≥6），路由限流 20/5min/IP，返回 `{token, user}` |
| `GET /api/advisors/:id` + `/explanation` | **真实 RAG** | RAG 不可用 503，id 不存在 404；详情 `matchScore:0`（无动态分）、`recentPapers=publications.slice(0,20)` 仅 title |
| `POST /api/email/generate` | **真实 RAG + 确定性模板** | 无 AI，返回 `{subject, body}` |
| `POST /api/upload/pdf` + `POST /api/pdf/analyze` | **真实** | 上传真实（multer + `%PDF-` 魔数 + ≤20MB + 30min TTL）；分析用 `unpdf` 抽正文 → summary/keyPoints 由内容生成，`suggestedAdvisors` 用「文档关键词 ↔ RAG research_topics/publications」命中打分（无命中回退论文数前 3） |
| `GET /api/recommend` | **真实 RAG** | 确定性关键词命中打分（`78+hits*6` 封顶 95；无命中 `55~72` 按 log2(papers)），取前 6 |
| `GET /api/cloud/graph` | 真实 | 读 `cloud3d/cloud_data.json` → 映射 `CloudNode`（`papers=pub_count`）→ 动态生成同域边（见下） |
| `/api/favorites` `/api/history` `/api/settings` `/api/user` | 真实 | 收藏/历史/设置/用户（profile GET/PUT；growth GET 只读，PUT 拒绝客户端直写；account DELETE 级联删） |

### `GET /api/cloud/graph` —— 云图数据组装

- 读 `cloud3d/cloud_data.json`，映射为 `CloudNode`（`papers=pub_count`）。
- **动态生成同域边** `buildEdges`：按 `domain` 分组，每人连**同域内最近邻 1 条**（1-最近邻，非 k 近邻），`MAX_PER_DOMAIN=400`，`relation:"same-field"`，`weight=max(0.1, 1-dist/400)`。
- 返回 `{nodes, edges, meta:{title, mentor_count, domain_count, legend, camera}}`。
- 读 `data.meta.legend` —— **磁盘 cloud_data.json 是旧文件、缺 `legend`**，会返回 `legend:[]`、`domain_count:0`，需重生成（见根 AGENTS.md 坑 #3）。

## 数据源真相（纠正旧文档把多处标成 [STUB]）

- **`server/stub/advisors.ts`（8 条 mock，带 hIndex）已废弃**——无任何活动路由引用。`agent.ts` **不再**内联 stub 导师。
- **`server/data/ragAdvisors.ts` 才是活数据源**：读 `paper-claw-master/data/ustc_mentor_rag.json`，按 `candidate_id` 建 `byId` Map。被 `advisors/email/pdf/recommend/index`（健康检查）使用。
- 因此**导师详情 / 邮件 / 推荐 / 健康检查 / PDF（summary+keyPoints+推荐）均为真实数据**；检索仅在 A 不可达时回退 mock。

## 前端结构与展示字段

- **路由**（`App.tsx`，`AuthGuard`/`GuestGuard` 守卫）：`/welcome`（落地，GuestGuard）→ 登录后 `/search`（首页）、`/cloud`、`/other`、`/profile`、`/settings`、`/favorites`、`/advisor/:id`、`/email`、`/compare`、`/pdf`、`/recommend`。
- **状态**：`authStore`（token 存 localStorage/sessionStorage，7 天）、`searchStore`（聊天历史/结果/排序/分屏比 0.45，localStorage 持久化分屏）、`settingsStore`（4 主题预设 + 自定义色 + 排序 + 密度 + 语言，同步后端）。
- **展示字段**：界面全用 `papers`（论文数）+ `matchScore`（匹配度），**全程无 hIndex**。`AdvisorCard`/`AdvisorDetailPage`/`ComparePage` 显示论文数+匹配度；`SortSelector` 排序项 = `匹配度/工号/论文数/院系`（无 hIndex 排序）。`Advisor.hIndex?` 在 `types/search.ts` 留可选字段备用，但 `mapFinalMentor`/`toAdvisorDetail`/`toLightAdvisor` 均不赋值；只有废弃的 stub/mock 数据带 hIndex 值。
- **`CloudGraph.tsx`**（Three.js，591 行）：`InstancedMesh` + 自定义 `ShaderMaterial`（billboard + 呼吸脉动），背景装饰用 `SPIRAL={r_in:170, r_out:540, turns:1.4, arms:6}` 画旋臂星尘/星云/中央亮核（**此 `arms:6` 仅为背景装饰，与 B 的 `build_cloud.py` 节点布局 `N_ARMS=4` 无关**）。节点坐标用 `cloud_data.json` 预计算值，组件不复算。交互：拖拽/缩放/自动缓旋、悬停浮卡、点击选中（按边高亮邻居）。
- **契约类型**：`Code/src/types/` 定义 `Advisor`/`CloudNode`/`AdvisorDetail` 等；`Code/src/services/` 是预留字段映射位（组件零改动）。`Advisor` 关键字段：`id/name/title/department/tags[]/hIndex?/papers/matchScore/explanation?`。`SseEventType = 'thinking'|'result'|'summary'|'done'|'error'|'stage'`；`SortBy = 'match'|'staffId'|'papers'|'department'`。

> 说明：检索/详情当前读 972/1969 RAG；Welcome 页静态统计和 715 节点云图仍是历史展示快照，不应当作当前检索库口径。

## .env 变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `JWT_SECRET` | — | ≥16 字符且非默认，启动校验 |
| `PORT` | 3001 | 后端端口 |
| `CORS_ORIGINS` | `http://localhost:5173` | |
| `MENTOR_AGENT_BASE_URL` | （指向 A 的 :8000） | 空/不可达 → 检索报错，不回退 stub |
| `MENTOR_AGENT_TIMEOUT_MS` | 180000 | |
| `MENTOR_AGENT_POLL_MS` | 1200 | 轮询 A 间隔 |

## 已知缺口

- hIndex 全链路无数据（已去展示）；当前 304 位导师无 `research_topics`，另有 2 位导师身份因证据不足未进仓。
- `CloudGraph.tsx` 背景装饰 `arms:6` 与 B 布局 `N_ARMS=4` 不一致（仅观感，可择机统一）。
