# MENTOR_GUIDE.md — 【A】mentor_workflow 检索后端（详述）

> 本文件描述 A 模块代码现状，供所有 AI 编码助手共用。跨模块向导见根 `AGENTS.md`。
> **不含协作规则**（见根 `CLAUDE.md`）。数据基准：2026-08-21 通读。
>
> `MENTOR_WORKFLOW.md` 是工作流的高层说明，本文件是代码级详述；两者互补。若口径不一致，以本文件 + 代码为准。

A 是多智能体检索后端：接收学生研究兴趣，从内部 RAG（715 中科大导师）召回候选，经领域研究→证据审核→匹配评分，产出带 8 维打分的导师推荐。**默认确定性离线模式**，无需任何模型 key 即可跑通。

## 技术栈与配置

- **框架**：FastAPI + SQLAlchemy 2 + PostgreSQL(pgvector) + Pydantic 2 + alembic；`requires-python >=3.12`；src 布局（import `backend.*`）。依赖含 `deepagents`、`langchain-openai/deepseek`、`openai`、`pgvector`、`pymupdf`、`tiktoken`。
- **运行模式开关**：settings 字段 `mentor_workflow_model_reasoning_enabled`，环境变量 **`PAPER_CLAW_MENTOR_WORKFLOW_MODEL_REASONING_ENABLED`**（默认 **False** = 确定性离线）。
  - ⚠️ 旧文档/CLAUDE 简写为 `MODEL_REASONING_ENABLED`，**不准确**。默认模式无需模型 key。
  - 模型模式才需配 `PAPER_CLAW_CHAT_*`（`PAPER_CLAW_CHAT_MODEL` 必填）。
- **DB**：`docker compose up -d` 起 pgvector/pg16；`alembic upgrade head` 建表。单条迁移 `migrations/versions/0001_current_schema.py` 一次建好全部表（含 AgentRun/AgentRunEvent 等）。

## 目录结构（mentor_workflow 为主）

```
backend/src/backend/
├── settings.py                      # ★ 配置（mentor_workflow_model_reasoning_enabled 等）
├── mentor_workflow/                 # ★ 本模块核心
│   ├── orchestrator.py              # 9 阶段编排 + review loop
│   ├── schemas.py                   # ★ WorkflowStage(9)/ReviewStatus(5)/MatchDimensionScores(8)/MatchResult/CandidateMentor/EvidenceRecord
│   ├── state_store.py               # ★ 复用 AgentRun 表持久化（无新表）
│   ├── event_bus.py                 # 结构化事件
│   ├── evidence.py                  # EvidenceLedger 去重 + 5年时效 + 作者归属
│   ├── errors.py / research_tools.py / agentic_research.py
│   ├── ustc_sources.py              # USTC 官方源抓取 + mentor_candidate_id()
│   └── agents/
│       ├── intake.py                # ★ 意图理解 + goal 跳过规则（_enabled_agents）
│       ├── domain_research.py       # 领域专家
│       ├── composer.py              # result_composer
│       └── evaluation.py            # EvidenceReviewAgent（评审循环）
├── api/routers/mentor_workflows.py  # ★ 12 端点 + get_internal_mentor_rag 依赖注入
├── integrations/llm/openai_compatible.py  # ★ 仅 OpenAI 兼容 provider
└── （agents/ services/ tools/ 为旧 Paper-Claw 链路，未被本模块改动）
```

## 工作流与阶段（`WorkflowStage` 9 值）

`orchestrator.py` 的 `current_stage` 取自 `WorkflowStage` 枚举：

```
input_understanding → planning → domain_expert → mentor_research
→ matching → evidence_review → result_composer → completed（或 failed）
```

> **没有独立的 `candidate_screening` / `paper_evidence_assessment` 阶段**——那两步在模型模式下是 `mentor_research` 阶段**内部**子步骤。旧 `MENTOR_WORKFLOW.md` 的"标准路径"图是逻辑描述，不是字面 `current_stage` 取值。

**编排**：`input_understanding`（意图 + 缺失字段判定）→ 若需澄清则 `CLARIFICATION_REQUIRED` 直接返回（不跑研究/匹配/编排）；否则 `planning`（按 goal 生成 enabled 步骤）→ `_run_review_loop`（`domain_expert → mentor_research → matching → evidence_review`，审核不过由 `RetryController` 决定返工目标并循环，带阶段/总上限检查）→ `result_composer` → `completed`。

**数据流**：`MentorWorkflowRequest` → `IntentPacket` → `TaskPlan` → `candidates`(`MentorResearchResult`) → `match_results`(`MatchResult[]`) → `ReviewDecision` → `FinalResult{mentors:[{candidate, match}]}`。

**目标(goal)跳过规则**（`agents/intake.py::_enabled_agents`）：

| goal | 跑哪些 |
|---|---|
| `find_mentors` | 全流程 |
| `inspect_mentor` | 跳过 domain_expert 与 matching |
| `compare_mentors` | 跳过 domain_expert |
| `generate_contact_email` / `follow_up_question` | 只跑 result_composer（复用已通过审核的状态） |

输入不足 → `CLARIFICATION_REQUIRED`，不跑研究/匹配。

## 证据纪律与审核（`ReviewStatus` 5 值）

- 证据必须带 `metadata.identity_verified=true`、`mentor_role_verified=true`、`supports_fields`，否则独立评审返回 `RESEARCH_AGAIN`。
- **`ReviewStatus`**：`PASS / REVISE / RESEARCH_AGAIN / NEED_MORE_INPUT / FAILED`（5 值；py 成员 `pass_`→值 `"PASS"`）。
- `EvidenceReviewAgent` 顺序检查：意图完整性 → 候选存在 → 证据引用闭环 → 字段是否被证据支持 → 候选有无研究方向 → 证据时效（`stale` 即 >5 年）→ 匹配一致性（仅 find/compare）。任一不过返回对应决策。
- `EvidenceLedger` 按 `(source_uri, candidate_id, content_hash)` 去重；`content_hash = sha256(source_type+source_uri+candidate_id+extracted_fact+locator)`。
- **论文 5 年时效规则**（`_freshness_from_year`/`_paper_freshness`）：current=≤2yr、recent=≤5yr、stale=>5yr（丢弃）。**作者归属校验** `_paper_author_matches`：论文绝不用于证明导师身份（只有 `identity_verified=True` 的官方目录证据才能）。

## 状态持久化（复用旧表，无新表）

**复用 `AgentRun` / `AgentRunEvent`，不加任何 mentor 专属表**：

| 存什么 | 存哪 |
|---|---|
| 完整 `WorkflowState` | `AgentRun.output_json` |
| 请求 `request` | `AgentRun.input_json` |
| `trace_id` | `AgentRun.deepagent_run_id` |
| 判别 | `workflow="mentor_search"` |
| 事件 | `AgentRunEvent.payload_json` |
| 元信息 | `metadata_json = {"mentor_workflow":true, ...}` |

**乐观锁**：`state_version`（JSON 内字段）+ `with_for_update()` 行锁 + 创建时 `pg_advisory_xact_lock(hashtextextended(trace_id,0))`。单条 alembic 迁移建全部表，无 mentor-workflow 专属迁移。

## 模型层与评分

- **Provider 抽象仅 OpenAI 兼容**（`integrations/llm/openai_compatible.py` 用 `openai` SDK 的 `chat.completions.create`；base_url/model/api_key 可配，经 `chat_provider_from_settings` 读 `PAPER_CLAW_CHAT_*`）。**无原生 Anthropic/Google 适配器**。模型模式需 `PAPER_CLAW_CHAT_MODEL`。
- **`MatchDimensionScores` 8 维**（全库 schema 无 hIndex）：

  ```
  research_topic_match / method_match / application_match / recent_activity
  / student_background_fit / constraint_satisfaction / recruitment_fit
  / evidence_completeness
  ```

  `total_score = mean_score()`（0~100）。
- **`MatchResult`** 字段：`candidate_id, total_score, dimension_scores, rationale:list[str], negative_factors, risks, uncertainty, evidence_refs, ranking_position`。
- **数据源链**：内部 RAG（`get_internal_mentor_rag` 注入 `data_scripts.internal_mentor_rag.FileInternalMentorRag`，离线 TF-IDF：`score = cosine*100 + hits*3`；失败回退 `NullInternalMentorRag` → 走 USTC 官方源）→ USTC 官方源（`*.ustc.edu.cn`，强制 HTTPS、重定向主机复检、响应类型/≤2MB 大小校验）→ 论文补全。
- **两种 enricher**：确定性 `MissingDirectionPaperEnricher`（只补缺方向候选）/ 模型 `AgenticPaperResearchEnricher`（语义初筛入围者逐人查论文，`min_relevance_score=35` 阈值）。

## API（12 端点，均 `/api/mentor-workflows`）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/` | 创建（`execute_immediately=false` 可只建不跑） |
| GET | `/{trace_id}` | 全状态 |
| GET | `/{trace_id}/status` | 轮询状态 |
| GET | `/{trace_id}/events` | 结构化事件 |
| GET | `/{trace_id}/candidates` | 候选 |
| GET | `/{trace_id}/matches` | 匹配 |
| GET | `/{trace_id}/evidence` | 证据 |
| GET | `/{trace_id}/audit` | 模型模式安全/工具轨迹 |
| GET | `/{trace_id}/review` | 评审决定 |
| GET | `/{trace_id}/result` | 最终结果 |
| POST | `/{trace_id}/input` | 补充输入 |
| POST | `/{trace_id}/resume` | 继续 |

**依赖注入缝**：`get_internal_mentor_rag`（router dep）把仓库根注入 `sys.path`，导入 `data_scripts.internal_mentor_rag.FileInternalMentorRag`，加载 `data/ustc_mentor_rag.json`；任何失败 → `NullInternalMentorRag`（回退官方 USTC 源）。`internal_mentor_rag.py` 的 `retrieve()` 用离线 TF-IDF（CJK 整词 + bigram、峰值归一 TF、`idf=log(N/(1+df))`、`score=cosine*100+hits*3`）。

## 与 D 的对接

D 的 `Code/server/routes/agent.ts` 作为代理：`POST /api/mentor-workflows`（`execute_immediately:false`）取 `trace_id` → `POST .../resume` → 轮询 `GET .../events`+`/status` → `GET .../result`，把 `final_result.mentors[]`（candidate+match 嵌套）经 `mapFinalMentor()` 映射为扁平 `Advisor[]`。字段映射见 `Code/AGENTS.md`。

## 与旧 Paper-Claw 链路的关系

旧 Paper-Claw 链路（`agents/`/`services/`/`tools/` 的 DeepAgents 对话/论文 QA/报告）**未被 mentor_workflow 改动**；mentor_workflow 仅复用其 `AgentRun` 表、`PaperSearchService` 与 chat provider，并新注册 `mentor_workflows` 路由。

## Harness 接入

- `POST /api/runs` 统一接收 `mentor_match` 与 `paper_qa` Skill。Mentor Skill 仍包装 `MentorWorkflowOrchestrator`。
- Paper Skill 会把导师语料中的论文映射到 Paper catalog，调用原 `submit_agent_message()` 创建真实 `workflow=paper_qa` 的 `AgentRun`，再由原 `execute_agent_run()` 后台运行 Paper Claw 多智能体。
- `GET /api/runs/{run_id}/harness-result` 使用 `RetrievalService` 读取该论文的 chunk。仅当 AgentRun 为 `succeeded`、检索结果非空、最终回答含真实 `[chunk:<id>]` 引用时返回 `review_status=PASS`；无 chunk 为 `RESEARCH_AGAIN`，未引用为 `REVISE`。
- Harness 只负责适配、状态路由和审核结果契约，不直接调用模型；论文向量/词法检索仍由 `RetrievalService` 完成。

## 测试

`backend/tests/mentor_workflow/`：`test_intake_planning` / `test_research_matching_review` / `test_composer` / `test_agentic_research` / `test_runtime_failures` / `test_schemas_state` / `test_ustc_sources` / `test_integration`；`tests/api/test_mentor_workflows_api.py`；`tests/test_mentor_workflow_state_store_db.py`。运行：`uv run pytest`（DB 测试需 pgvector 起）。
