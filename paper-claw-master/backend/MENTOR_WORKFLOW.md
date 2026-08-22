# 导师检索后端工作流

## 现有架构映射

| 需求 | 现有代码 | 本次接入 |
| --- | --- | --- |
| 后端入口 | `backend.api.app:create_app` | 注册 `/api/mentor-workflows` 路由；旧路由保持不变 |
| 旧聊天/Agent | `backend.agents.runner`、DeepAgents 主 Agent 与论文子 Agent | 不改旧聊天链路；导师检索使用专用、可审计的结构化编排 |
| 模型层 | 运行时 OpenAI-compatible 配置与 Provider 服务 | 默认模式可离线确定性执行；可选模型模式做项目归类、候选初筛、论文判读和语义匹配，不硬编码厂商 |
| 工具与 RAG | 论文目录、搜索、解析、Embedding、Retrieval、报告服务 | 生产链使用“内部中科大 RAG → USTC 相关学院广召回 → 模型初筛 → 入围候选 arXiv/OpenAlex → 证据审核”；原论文服务保持原样 |
| 状态与事件 | `AgentRun`、`AgentRunEvent`、线程与消息表 | `SqlAlchemyStateStore` 把类型化状态写入现有 `AgentRun.output_json`，事件写入现有事件表，无新表 |
| 测试替换 | 项目原有 pytest fixtures | `InMemoryStateStore`、`InMemoryEventBus` 和 `MentorResearchTool` Protocol 支持完全离线 Mock |

当前部署范围默认是中国科学技术大学。导师名单和导师身份只接受中科大官方教师主页系统及其挂出的中科大个人主页作为外部权威来源；论文不会把论文作者自动升级为导师。确定性模式只在官方方向缺失时补论文，模型模式对语义初筛入围者逐人尝试论文检索。证据必须用 `metadata.identity_verified=true`、`metadata.mentor_role_verified=true` 和 `metadata.supports_fields` 明确标注支持范围，否则独立评审返回 `RESEARCH_AGAIN`，不会输出正常推荐。

## 中科大优先数据源链

```text
内部中科大导师 RAG（预留 Protocol/FastAPI 依赖接口）
  ↓ 未命中、候选不完整或身份未核验
中科大官方教师高级搜索 + 相关学院广召回
  ↓
教师库挂出的 faculty.ustc.edu.cn 个人主页
  ↓ 模型模式：全池语义初筛；默认模式：缺方向候选
原 Paper-Claw arXiv/OpenAlex 论文搜索
```

- `InternalMentorRag` 是内部整理库的稳定接口；默认 `NullInternalMentorRag` 不伪造数据。
- `get_internal_mentor_rag` 是 FastAPI 注入点，接库时无需修改 Agent、工作流或 API。
- `UstcOfficialMentorSource` 负责官方导师身份、学院、职称、导师角色、主页和公开研究方向。
- `MissingDirectionPaperEnricher` 只补 `research_topics`、`methods` 和 `publications`。
- `AgenticPaperResearchEnricher` 对模型初筛入围者检索论文，并由结构化模型判断论文实际方向和项目迁移关系。
- 论文补全要求作者可归属、查询概念明确命中且论文不超过五年；论文证据不承担导师身份验证。
- 生产 HTTP 适配器固定 HTTPS 和 `*.ustc.edu.cn`，检查重定向主机、响应类型与响应大小。

## 工作流

标准路径为（对应 `WorkflowStage` 的 9 个值）：

```text
input_understanding
-> planning
-> domain_expert
-> mentor_research          （其中模型模式下含候选初筛 Candidate Screening、论文判读 Paper Evidence Assessment 两个子步骤）
-> matching
-> evidence_review
-> result_composer
-> completed
（异常 / 输入缺失另有 failed / clarification_required）
```

目标化跳过规则：

- `inspect_mentor` 跳过领域扩展和排序，只调研指定导师、审核证据并编排结果。
- `compare_mentors` 跳过候选方向扩展，直接调研并比较指定候选。
- `generate_contact_email` 和 `follow_up_question` 只复用当前工作流已通过审核的状态。
- 输入不足时状态为 `CLARIFICATION_REQUIRED`，不执行研究、匹配或结果编排。

独立评审只返回枚举决策：`PASS`、`REVISE`、`RESEARCH_AGAIN`、`NEED_MORE_INPUT` 或 `FAILED`。返工控制器根据失败检查返回领域、研究、匹配、输入或编排节点，并同时执行阶段上限与总上限检查。

## 数据、事件与证据

`backend.mentor_workflow.schemas` 定义 `IntentPacket`、`TaskPlan`、`AgentMessage`、`EvidenceRecord`、`CandidateMentor`、`MatchResult`、`ReviewDecision`、`RetryRecord` 和 `WorkflowState`。

状态写入必须通过 `StateStore`，每次关键更新进行乐观版本检查并递增 `state_version`。`EvidenceLedger` 对来源、候选与内容哈希去重，并检查候选/匹配引用是否存在且绑定正确。独立评审还检查导师身份和所有已填候选字段是否被证据明确支持。结果编排器只接受 `PASS` 状态，不会新增导师、修改分数或删除不确定性。

日志只记录 trace、Agent、阶段、事件、版本、耗时、状态和错误类型；不记录密钥、完整 PDF/网页正文或模型内部推理。

## API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/mentor-workflows` | 创建任务；`execute_immediately=false` 可只创建不运行 |
| GET | `/api/mentor-workflows/{trace_id}` | 完整类型化状态 |
| GET | `/api/mentor-workflows/{trace_id}/status` | 稳定轮询状态与当前阶段 |
| GET | `/api/mentor-workflows/{trace_id}/events` | 结构化事件 |
| GET | `/api/mentor-workflows/{trace_id}/candidates` | 候选导师 |
| GET | `/api/mentor-workflows/{trace_id}/matches` | 匹配结果 |
| GET | `/api/mentor-workflows/{trace_id}/evidence` | 必要证据摘录与元数据 |
| GET | `/api/mentor-workflows/{trace_id}/audit` | 安全 Context、模型准备、候选初筛、语义评估和工具轨迹 |
| GET | `/api/mentor-workflows/{trace_id}/review` | 独立评审决定 |
| GET | `/api/mentor-workflows/{trace_id}/result` | 已审核最终结果 |
| POST | `/api/mentor-workflows/{trace_id}/input` | 补充输入并继续 |
| POST | `/api/mentor-workflows/{trace_id}/resume` | 继续已创建/等待的任务 |

生产依赖默认使用现有 SQLAlchemy Session；FastAPI 的 `get_internal_mentor_rag` 可替换为内部导师库实现，`get_mentor_workflow_runtime` 可在测试中替换为内存运行时。旧 `/api/agent/messages`、线程、论文、报告和任务 API 的请求/响应语义未改变，前端不需要立即修改。

## 需求—代码—测试映射

| 能力 | 代码路径 | 离线测试 |
| --- | --- | --- |
| 输入与计划 | `mentor_workflow/agents/intake.py` | `test_intake_planning.py` |
| 动态专家与研究 | `mentor_workflow/agents/domain_research.py` | `test_research_matching_review.py` |
| 中科大官方源、个人主页、内部 RAG 和论文补全 | `mentor_workflow/ustc_sources.py`、`mentor_workflow/research_tools.py` | `test_ustc_sources.py` |
| 模型项目分析、候选初筛、论文判读和语义匹配 | `mentor_workflow/agentic_research.py` | `test_agentic_research.py` |
| 匹配、审核、返工 | `mentor_workflow/agents/evaluation.py` | `test_research_matching_review.py` |
| 结果与邮件 | `mentor_workflow/agents/composer.py` | `test_composer.py` |
| 状态、事件、证据 | `state_store.py`、`event_bus.py`、`evidence.py` | `test_schemas_state.py`、`test_runtime_failures.py`、`test_mentor_workflow_state_store_db.py` |
| 端到端流程 | `mentor_workflow/orchestrator.py` | `test_integration.py` |
| HTTP API | `api/routers/mentor_workflows.py` | `api/test_mentor_workflows_api.py` |

## 本地检查

项目声明的标准后端测试入口为 pytest。使用已安装的 Python 3.12 环境执行：

```powershell
python -m pytest backend/tests/mentor_workflow backend/tests/api/test_mentor_workflows_api.py -q -p no:cacheprovider
```

当前本次改动相关结果为 `74 passed, 1 warning`；mypy 检查 17 个源文件通过。数据库回归测试仍按项目原夹具要求使用 PostgreSQL 数据库 `paper_claw_test`。离线测试使用假网关，不访问外部模型、官方网页或远程向量服务；另有真实模型端到端 JSON/HTML 与中科大官方源烟测，位于项目根目录同级的 `项目规划` 文件夹。
