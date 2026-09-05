# 科研导师推荐与科研伴学平台：真实代码逻辑全景

> 代码基线：2026-09-06。本文只描述当前可执行代码、配置、数据库结构、运行时数据与测试所体现的行为，不以历史说明文档为依据，也不描述开发过程。

## 1. 系统定位与事实边界

项目由两套 Web 界面、两个服务端存储域、一套导师数据流水线和一个星图数据生成器组成：

```text
用户浏览器
├─ Code：科研导师推荐主站（React）
│    └─ Express BFF
│         ├─ SQLite：用户域与产品功能状态
│         ├─ ustc_mentor_rag.json：导师详情与本地检索
│         └─ Paper Claw FastAPI：工作流、Harness、论文与报告能力
└─ paper-claw-master/frontend：Paper Claw 独立工作台（React）
     └─ Paper Claw FastAPI
          ├─ PostgreSQL：线程、运行、论文、证据、报告、任务
          └─ 文件存储：论文原件与解析制品

官网/论文平台
└─ data_scripts → ustc_mentor_rag.json
                        ├─ A 端导师检索
                        ├─ D 端本地检索、详情、推荐、邮件
                        └─ cloud3d → cloud_data.json → 主站 3D 星图
```

当前磁盘数据快照：

| 数据项 | 当前值 |
|---|---:|
| RAG 导师 | 972 |
| RAG 证据 | 1969 |
| 有 `research_topics` | 660（官网 597，论文标题推断 63） |
| 有 `publications` | 259 |
| 有 `methods` | 45 |
| 有 `recruitment_status` | 107 |
| 有 `profile_bio` / `profile_email` | 758 / 193 |
| 证据来源 | 官方目录 972、官方主页 630、OpenAlex 200、S2 150、DBLP 17 |
| 星图节点 | 972（classified 924，unclassified 48） |

运行时数据检查确认 RAG 与当前星图有 972 个共享导师 ID，缺失和孤立 ID 都是 0。

跨模块稳定主键是 `candidate_id`，格式为 `ustc_faculty_<faculty_id>`。它同时用于：

- RAG 的 `CandidateMentor.candidate_id`；
- A 端候选、匹配、证据和最终结果；
- D 端导师详情 URL、收藏、反馈、历史与成长记录；
- 星图节点 ID 与点击跳转。

## 2. 进程与启动顺序

### 2.1 默认进程

| 进程 | 默认地址 | 入口 | 作用 |
|---|---|---|---|
| 主站前端 | `127.0.0.1:5173` | `Code/src/main.tsx` | 用户登录、导师检索及科研伴学功能 |
| Express BFF | `127.0.0.1:3001` | `Code/server/index.ts` | 认证、用户数据、本地 RAG、A 端代理 |
| Paper Claw API | `127.0.0.1:8000` | `backend.api.app:create_app` | Agent、导师工作流、论文、报告、arXiv 任务 |
| PostgreSQL | `127.0.0.1:5432` | Docker Compose | Paper Claw 持久化与向量字段 |

`scripts/start-project.ps1` 是实际编排入口。它负责检查运行时、依赖和数据，启动 PostgreSQL、执行数据库迁移，再启动 A、D 和前端，并通过健康/就绪接口判断是否可服务。根目录批处理文件只是 PowerShell 编排器的便捷入口。

### 2.2 就绪语义

- Express `/api/health` 只报告进程、时间和 RAG 加载状态。
- Express `/api/ready` 要求 RAG 可读并且配置的 A 端探针成功；否则返回 503/degraded。
- FastAPI `/api/health` 是廉价存活检查，不访问数据库。
- FastAPI `/api/ready` 检查 PostgreSQL；仅在开启导师模型推理时把模型网关也作为硬依赖。
- FastAPI `/api/mentor-ready` 专门反映导师工作流是否可运行；默认确定性模式不要求模型。
- FastAPI `/api/chat-ready` 使用实际 API Key、Base URL 和模型名请求模型列表，而不是只检查环境变量是否存在。

FastAPI 启动时同时启动 arXiv 后台调度器；关闭时停止它。Express 启动后每 30 秒协调一次待补写成长记录，每 60 秒运行报告与计划提醒调度，并立即补跑错过发送时间的报告。

## 3. D：科研导师推荐主站

### 3.1 前端壳与会话

`Code/src/App.tsx` 使用 React Router、Ant Design 和懒加载页面。`/welcome` 只允许未登录用户访问；其余页面由 `AuthGuard` 包住并共享 `AppLayout`。应用启动后恢复本地 token 会话：

- API 返回 401 时清除登录态并跳转欢迎页；
- 网络/API 错误通过全局通知展示；
- 需要模型但用户未配置时，服务端返回 `API_SETTINGS_REQUIRED`，前端弹窗引导到 `/api-settings`；
- token 保存在 localStorage 或 sessionStorage，请求通过 Bearer JWT 发送。

实际页面：

| 路径 | 页面逻辑 |
|---|---|
| `/search` | 对话式导师搜索、SSE 活动、澄清续跑、结果卡片 |
| `/cloud` | 3D 导师星图、领域筛选、节点联动搜索/详情 |
| `/other` | 功能入口汇总 |
| `/profile` | 基本资料、兴趣、技能与成长状态展示 |
| `/settings` | 界面与产品设置 |
| `/api-settings` | 当前用户的模型 Base URL、模型和 API Key |
| `/favorites` | 收藏导师 |
| `/advisor/:id` | RAG 导师详情、证据、论文、匹配解释 |
| `/email` | 联系导师邮件生成、发送、发件箱/收件箱设置 |
| `/compare` | 已选导师比较 |
| `/pdf` | PDF 上传、单篇/多篇分析、后台任务历史 |
| `/recommend` | 基于真实用户记忆的猜你喜欢 |
| `/reports` | 周期报告、邮件投递和演示文稿生成 |
| `/plans` | 计划、完成反馈、智能拆解与提醒 |
| `/research` | 科研项目记录和项目内会话 |
| `/skills` | 用户自定义技能管理与校验 |
| `/integrations` | Zotero 连接、集合读取与同步 |

### 3.2 登录与账户

登录接口同时承担首次注册：邮箱不存在时使用 bcrypt（cost 10）写入密码哈希并初始化用户设置；已存在时校验密码。JWT 有效期 7 天。服务启动会拒绝空值、公开默认值或少于 16 字符的 `JWT_SECRET`。

账户数据接口负责资料、研究画像、API 设置、成长状态和注销。研究画像更新可进入 A 端 profile skill；成长状态不能被客户端直接任意覆盖，只能由经过审核的成长事件或内部写回路径更新。

用户模型 API Key 以 AES-256-GCM 加密后保存在 SQLite。密钥来自安全的 `MAIL_CREDENTIAL_KEY`，否则使用安全的 `JWT_SECRET` 派生；普通读取只返回“是否已保存”，只有 D 内部向 A 发起当前用户任务时才解密并注入覆盖值。历史默认密钥加密记录在成功读取后会自动迁移。

登录按 IP 每 5 分钟最多 20 次；Agent 路由按 IP 和路径每分钟最多 12 次。当前限流器是单进程内存实现，多实例部署不会共享计数。

## 4. 导师搜索的完整链路

### 4.1 前端状态

`searchStore` 保存当前对话、导师结果、排序、SSE 状态、分栏比例、会话 ID、待发送查询、工作流 `trace_id`、A 端 `run_id`、澄清状态、下一建议技能和附带 PDF ID。

同一搜索页会话复用 session 和 trace；收到澄清问题后，用户补充内容会续跑原工作流，而不是另开一轮。清空对话才重置这些标识。分栏比例单独保存在 localStorage，清空对话不重置布局偏好。

### 4.2 Express SSE 边界

前端调用 `POST /api/agent/chat`，Express 返回 SSE：

- `thinking`：面向用户的短进度；
- `stage`：兼容的阶段摘要；
- `event`：完整运行事件；
- `result`：导师数组或普通聊天结果；
- `summary`：最终文字；
- `done` / `error`：终态。

Express 把 A 端事件映射到主站阶段，并把事件写入 SQLite 的 mission/mission_events。事件持久化失败不会打断 SSE；客户端断开会停止继续向该响应写数据。

问候、感谢或明确要求“先聊聊/不要检索”的消息走 Paper Claw 通用聊天流，并要求当前用户已配置模型。其余消息进入导师检索。

### 4.3 首选 A 端、可审计的本地降级

当 A 端存活且就绪时，D 通过 Harness 创建 `mentor_match` run。D 只发送当前用户可信的 profile/growth 摘要、解析文档和用户模型覆盖，不把浏览器自报的成长字段当成可信事实。

A 成功后，D 轮询运行与事件，取得导师工作流结果，再将 A 的嵌套 `candidate + match + evidence` 映射成主站扁平 `Advisor`：

- ID、姓名、职称、院系、主页、方向和方法来自候选；
- 展示分数使用工作流综合分，主题绝对相关性保留在 score breakdown；
- 论文数只接受已核验来源元数据，不把截断的代表作数组长度伪装成论文总数；
- 证据引用去重后随结果返回；
- 最后再次执行最低分、DIRECT/ADJACENT 关系和正主题分门禁。

若 A 未配置、未就绪或调用超时，而本地 RAG 可用，D 使用同一条原始查询运行本地确定性检索。它不是“随便取全库 Top-K”：查询会先拆成不可丢失的概念契约，再执行候选级证据绑定、绝对阈值和矛盾检查。没有合格导师时返回 `NO_MATCH` 与可放宽诊断，不用无关候选补满数量。

若 A 与本地 RAG 都不可用，SSE 返回明确错误，不生成虚构导师。

### 4.4 结果写回

审核通过的导师结果会写入：

- 搜索历史与会话展示；
- mission 及事件回放；
- run artifact；
- 成长状态中的导师、方向、证据和后续研究任务。

成长写回要求数值型 A 端 run ID。写回暂时失败时进入 `pending_growth_writes`，后台协调器按锁、尝试次数和错误信息重试，避免把 trace ID 当作 run ID 或静默丢失结果。

## 5. A：导师工作流

### 5.1 请求和状态

`MentorWorkflowRequest` 接收自然语言、显式目标、主题、方法、应用领域、约束、用户画像、项目、解析文档、星图交互轨迹和原始证据引用。目标包括找导师、查看导师、比较导师、生成联系邮件和追问。

完整状态由 `WorkflowState` 保存，通过 `SqlAlchemyStateStore` 持久化到 PostgreSQL，并带 `state_version` 做版本化提交。每个阶段发出包含 sender、receiver、payload、证据引用和状态版本的事件。

状态枚举只有九个：

```text
input_understanding → planning → domain_expert → mentor_research
→ matching → evidence_review → result_composer → completed
                                                  └→ failed
```

“候选筛选”和“论文证据评估”是研究/审核内部动作，不是独立 WorkflowStage。

### 5.2 输入理解

输入理解会：

1. 归一化明确的搜索动词错字和命令外壳；
2. 识别院系、导师姓名、招生、本科生友好、理论偏好等约束；
3. 把当前查询与历史背景分开；历史兴趣只能参与背景适配，不能替换本轮检索主题；
4. 构造 `QueryContract`，保留 raw、semantic、canonical query、必保概念、扩展词、排除的泛化词、概念角色和 AND/OR 逻辑；
5. 对“图学习导师”等短主题与“张凯导师/王小明博导”等姓名表达分别处理；
6. 缺少主题或比较对象时进入 `CLARIFICATION_REQUIRED`，返回具体问题而不继续猜测。

### 5.3 规划、领域判断和检索

PlanningAgent 根据目标生成启用/跳过的步骤和执行模式。领域专家输出结构化领域判断，供召回与评分使用。

导师研究通过统一检索门面执行：

- 首选 `MentorSemanticIndex` 的多语种稠密召回；
- 稠密组件不可用时使用 `FileInternalMentorRag` 的受控关键词/TF-IDF 召回；
- RAG 整体不可用时才进入官方 USTC 教师源；
- 候选缺研究方向时，可经 PostgreSQL 论文库或直接 arXiv/OpenAlex 网关补齐已归属论文证据；
- Retrieval Manager 允许增加别名和子领域作召回词，但不会改写原始 QueryContract；
- 第一轮质量门失败才执行受控 fallback，所有尝试、覆盖度、关系判断和警告进入审计状态。

默认 `mentor_workflow_model_reasoning_enabled=false`，导师检索、领域判断、匹配和审核均可确定性运行。开启后，领域判断、论文研究和匹配替换为结构化模型推理，同时仍受 schema、证据和审核门控制。

### 5.4 候选、证据与匹配

候选必须至少有绑定到自身的证据。证据记录包含来源类型、URI、标题、抽取事实、支持字段、实体核验、来源层级、时效、置信度、查询相关性和 DIRECT/ADJACENT/IDENTITY 支持类型。

匹配先计算主题绝对相关性并淘汰 UNRELATED/低阈值候选，再形成八维记录：主题、方法、应用、近期活跃度、学生背景、约束、招生、证据完整度。排序以主题分为基础；只有用户明确要求且候选字段已验证时，方法、应用和约束才按有限权重调整顺序。缺失字段保持中性，不制造优势或惩罚。

### 5.5 独立审核与返工

EvidenceReviewAgent 检查：

- 意图是否完整；
- candidate/match 引用是否存在且归属正确；
- 身份和已填字段是否有显式证据支持；
- 是否存在无研究方向候选；
- 活跃证据是否过时；
- 结果是否达到绝对阈值、关系类型和查询相关证据要求；
- 论文记录和论文计数字段是否矛盾。

审核可以 PASS、REVISE、RESEARCH_AGAIN、NEED_MORE_INPUT 或 FAILED。RetryController 只重跑审核指定的 input/domain/research/matching/composer 段，并受总重试上限约束。无候选但检索和证据逻辑正常时视为可解释的 `NO_MATCH`，不是系统异常。

ResultComposer 只组合审核后的候选、匹配、证据、风险、不确定性和诊断。工作流提供同步创建/续跑接口，也提供 async 创建、补充输入、状态、事件、候选、匹配、证据、审计、审核和最终结果读取接口。

## 6. Paper Claw 通用 Agent 与 Harness

### 6.1 通用 Agent

通用 Agent 以 Thread → Message → AgentRun → AgentRunEvent 为主线。新消息会创建或复用线程、落用户消息和 run，再由 LangGraph/Deep Agents 流式运行。服务同时消费 `messages` 和 `updates`：可见文字作为 chunk 返回，可持久化工具/状态更新写成事件。

运行可能处于 pending、running、waiting_for_user、succeeded、partial、failed 或 cancelled：

- 工具要求确认时保存 interrupt payload 并进入 waiting_for_user；
- approval 接口可批准、编辑或取消，并从同一个 checkpoint 恢复；
- 客户端取消会更新运行状态，执行循环在流边界检查取消；
- 成功后写 assistant message 和最终 output；
- 异常会回滚当前事务、写失败事件和错误摘要；
- 长期停在 running 的旧运行会被识别为 stale。

### 6.2 Harness Skills

`POST /api/runs` 是 D 调用 A 的统一技能入口。共享上下文只允许用户 ID、查询、可信 profile/growth、候选/文档/论文 ID、页文本、报告周期、计划和审计摘要；原始 API Key 位于独立覆盖字段，不写入共享审计上下文。

当前技能包括：

- `mentor_match`：包装上述导师工作流；
- `paper_qa`：围绕已选导师/论文检索片段并回答，产出阅读证据和成长补丁；
- `pdf_analyze`：PDF 页级语义召回、可选模型结构化重排、导师匹配与证据审核；
- `email_compose`：基于导师与学生已核验信息写邮件；
- `profile_update`：结构化研究画像；
- `research_task` / `direction_explore`：研究方向和下一任务；
- `progress_report`：周期成长报告；
- `plan_coach`：计划拆解与容量建议。

`/api/runs/next-skill` 根据成长状态确定下一步：已匹配但未读论文优先 paper_qa；已有论文阅读但无联系邮件时建议 email_compose；存在上传未分析 PDF 时建议 pdf_analyze。该判断是确定性映射，不调用模型。

## 7. 论文、PDF、报告和科研伴学

### 7.1 论文库

Paper Claw 的论文域区分 Paper、外部 identifier、source record、原始 artifact、paper-artifact 关联、采集任务、解析任务、解析事件、解析文档、处理后文档、section、chunk 和 reference。搜索源由 factory 选择 arXiv/OpenAlex；确认候选后才正式写入论文及其来源记录。

上传制品后可执行页面摄取。解析器支持 TeX source、LlamaParse 和本地 OCR 等适配器；清洗后形成章节与 chunk，embedding 服务写向量供语义检索。报告证据可以指向 chunk、reference 或 paper，从而保留引用来源。

### 7.2 主站 PDF

主站只接收 20 MB 以内 PDF，并同时检查扩展名/MIME 与 `%PDF-` 魔数。文件按内容哈希持久化到用户文档目录，SQLite 保存归属和解析状态。

单篇和 2–20 篇合并分析都创建独立后台 job，浏览器离开页面不会取消。文本提取后按最大页数与字符预算做均匀采样，避免只保留论文头尾。D 将页号和文本发送到 A 的 `pdf_analyze`：

1. A 把正文切为带页码 passage；
2. 多语种向量索引召回导师；
3. 有模型时进行结构化语义重排；未配置模型时只对“模型缺失”采用本地语义重排，其他配置错误会明确失败；
4. 匹配必须达到绝对分数并引用真实 PDF 页；
5. 再补充导师官方身份/方向证据；
6. 只有 Review PASS 才写主站分析摘要、要点、导师结果和成长事件。

扫描件、加密 PDF、无正文、无有效导师或模型结构错误不会按文件名或词频伪造结果。

### 7.3 邮件

导师联系邮件由固定场景模板生成，使用导师 RAG、学生 profile、已核验论文阅读和推荐记忆。邮件地址优先使用 RAG 的已抽取主页邮箱。SMTP/IMAP 设置按用户保存，密码加密；发送先写 outbox，再尝试投递，失败保留尝试次数与错误以供重试。收件箱读取通过 IMAP 完成。

### 7.4 报告、演示文稿与计划

进度报告按日/周/月区间聚合成长事件、会话和计划。A 端 `progress_report` 成功时保存模型生成与审计信息；不可用时使用明确标记的本地事实摘要。报告可排队发送邮件，也可创建 presentation job，由 Node 调用 `Code/server/services/ppt_builder.py` 生成可下载文件。Windows 启动器把 A 端锁定虚拟环境的 Python 路径注入 D 进程，该环境显式包含 `python-pptx`，因此新机器不依赖碰巧存在的全局 Python 包。

计划支持父子关系、顺序、优先级、起止时间、预计/实际投入、交付物、验收标准、执行笔记、完成时间和提醒。完成计划必须填写实际结果与投入时间，并写成长事件。`plan_coach` 以个人可信摘要的 fingerprint 做缓存；A 不可用时返回明确标记的本地拆解，不冒充模型成功。提醒调度器通过 outbox 去重发送。

### 7.5 研究项目、会话、技能和 Zotero

- 研究项目保存标题、目标、状态及项目上下文；
- 主站 Conversations 在项目/页面 surface 下保存会话、目标和消息，消息流可调用 A 的通用 Agent；
- 自定义技能支持创建、编辑、结构校验、启用和禁用；
- Zotero 集成验证 library/key、读取 collections、同步条目到本地 integration_items，并可断开和清除凭据。

## 8. 个性化推荐与导师详情

导师详情直接从当前 RAG 映射，展示个人信息、研究方向、方法、代表作、主页、招生状态及证据。匹配解释只有在用户已有相关匹配 artifact 时才带本轮分数与理由；不会为未搜索过的导师编造个性化分数。

猜你喜欢的信号来自：近期搜索、长期成长方向和收藏导师方向，权重分别为 1.2、1.0、0.6，同一词只保留较高权重。系统排除已收藏和明确 dislike 的导师，只允许官网方向或有完整已核验论文来源链的方向进入候选池。

每个记忆信号独立检索并合并候选，最终推荐分由绝对相关性 80%、画像覆盖 12%、证据质量 5%、已核验论文支持 3% 组成。默认返回 6 位、最多 12 位；优先限制同一院系最多 2 位，数量不足才回填。推荐解释指出使用了哪类记忆、主题关系和最强证据。

## 9. 星图

`cloud3d/build_cloud.py` 每次从当前 RAG 重建 `cloud_data.json`，不抓网也不修改源 RAG。它以 department、research_topics 和 methods 的关键词得分把导师分入 10 个宏观领域或 unknown：

- 领域质心使用内外双轨；
- 簇内按 candidate_id 排序后用黄金角低差异序列排布，结果可复现；
- y 轴只添加确定性波动形成厚度；
- 节点携带主题、方法、代表作、主页、招生、分类得分、颜色、亮度和大小；
- meta 给出 schema version、导师/证据/领域数、图例、相机范围和四臂背景参数。

Express `/api/cloud/graph` 读取该文件并转换为前端 `CloudData`。真正的 Three.js/React 渲染在主站 `CloudGraph.tsx`；`cloud3d` 本身只是数据生成模块。

## 10. 数据生产与质量门

`data_scripts` 的真实生产链如下：

1. `ustc_scraper.py` 从中科大官方教师搜索接口取得 faculty_id、院系、主页并解析可见正文、研究方向、角色、邮箱和招生信息；
2. OpenAlex、Semantic Scholar、DBLP 抓取器按英文名、机构和人工 override 解析作者并取得代表作；
3. 模糊作者命中可导出人工复核表，人工结论写 override，不直接污染正式候选；
4. `build_rag.py` 只让身份确认的论文支持 publications/methods/topics，按 DOI、平台 ID 和规范化标题跨平台去重；
5. 官网方向优先；官网缺方向时，只有高特异性论文词且达到支持篇数才受控回填。当前构建把这类标题推断标为 `topics_source=2`，可用于展示和星图，但 A/D 的标准导师检索不会把它当作已核验方向事实；只有官网 `source=1` 或另有完整推断证据链的 `source=3` 才能通过可信方向门；
6. 每位入库导师必须有官方身份/角色链，候选字段生成对应 evidence_refs 和 missing_fields；
7. `verify_rag.py` 检查 schema、引用完整性、跳过条件、召回样例、覆盖率、语义元数据和检索质量；
8. `audit_rag.py` 输出覆盖、论文平台、主题噪声、bio、排除角色和 ID 一致性统计。

RAG 顶层包含 candidates、evidence、source_chain、warnings 和生成时间。候选核心字段与 A 的 Pydantic schema 对齐；论文平台的总论文数与截取的代表作列表严格分开。

## 11. 两个数据库与文件边界

### 11.1 D 的 SQLite

SQLite 保存用户产品状态，不保存 A 的论文知识图谱。主要表族：

- `users`、`user_settings`、`email_accounts`；
- `favorites`、`advisor_feedback`、`search_history`、`chat_history`；
- `growth_state`、`growth_events`、`run_artifacts`、`pending_growth_writes`；
- `missions`、`mission_events`；
- `research_documents`、`pdf_analysis_jobs`；
- `report_preferences`、`progress_reports`、`presentation_jobs`；
- `plans`、`email_outbox`、`productivity_run_cache`；
- `research_projects`、`conversations`、`conversation_goals`、`conversation_messages`；
- `custom_skills`、`integration_accounts`、`integration_items`、`paper_search_sessions`。

迁移按版本顺序执行；新增列使用列存在性检查，旧数据库可就地升级。所有用户域查询都带 user_id，避免跨用户读取。

### 11.2 A 的 PostgreSQL

PostgreSQL 保存：

- threads/messages、agent_runs/agent_run_events、memories；
- papers、identifiers、source_records；
- artifacts、paper_artifacts、acquisition_jobs；
- parse_jobs/events、parsed_documents、processed_documents、sections、chunks、references；
- search_sessions/candidates；
- reports/report_evidence；
- provider_configs；
- arXiv daily config、subscriptions、papers、paper-subscription links、harvest jobs 和 query windows。

Repository 层封装查询与状态转移，Service 层编排检索、采集、解析、embedding、报告和任务，API Router 只做 HTTP 校验和调用边界。

### 11.3 文件

- RAG 和抓取中间数据位于 `paper-claw-master/data`；
- A 的原始论文/解析制品位于配置的 storage root；
- D 上传的 PDF 位于 `Code/data/documents`，SQLite 记录内容哈希和所有权；
- 生成的 PPT 位于 D 的受控输出目录；
- 星图运行时文件是 `cloud3d/cloud_data.json`。

## 12. Paper Claw 独立前端

这套前端不是主站的旧副本，而是直接查看 A 端内部对象的工作台。它没有 React Router，而由 `App.tsx` 内的 activePage 切换：

- Chat：线程、消息、运行、持久化事件、审批/取消；
- Papers：论文归档、详情、解析状态、设为 active paper；
- Reports：报告列表、阅读、删除和跳回论文；
- Memory：长期记忆读取；
- Tasks：arXiv 日更配置、订阅、测试查询、历史回采和窗口状态；
- Settings：运行时/provider 设置。

选中的 thread、active run 保存在 localStorage；run 运行中每 2.2 秒轮询，成功但 assistant message 尚未落库时以 700 ms 轮询线程。终态触发全局刷新；waiting_for_user 展示决策面板。

## 13. 失败与降级原则

当前代码遵循以下实际边界：

- 存活不等于就绪，数据库、RAG、A 端和模型分别报告；
- 模型不是默认导师检索的必需项，但普通聊天、邮件智能能力、报告增强等功能按用户配置决定；
- A 端失败时只有导师搜索具备等价查询约束的本地 RAG 降级；PDF 等要求证据审核的功能不会静默伪造成功；
- 无匹配是结构化业务结果，不用低相关候选补位；
- 缺失字段保持缺失，未知招生状态、论文数和方法不推断；
- 外部论文只在作者/机构身份确认后支持导师事实；
- 所有成长写回要求审核状态、来源 run/skill 和证据引用；
- 邮件、报告、计划等异步动作通过 outbox/job/cache 表保留可重试状态。

## 14. 异机部署边界

仓库自带的是单台 Windows 主机的可复现开发/演示部署链路。批处理从自身位置推导仓库路径，不依赖用户名或盘符；环境准备按 `Code/package-lock.json` 和 `paper-claw-master/backend/uv.lock` 安装依赖，创建本机 `.env` 与随机 JWT 密钥，启动本机 Docker PostgreSQL、执行 Alembic 迁移并预热本地 embedding 索引。A、D、Vite 和 PostgreSQL 都绑定 `127.0.0.1`，所以把完整仓库复制或克隆到另一台 Windows 电脑后可重新准备并运行，但默认不会向局域网或公网暴露。仓库没有提供等价的 Linux/macOS 一键脚本或完整应用 Docker 镜像；非 Windows 部署需要自行按同一进程和环境变量契约编排。

迁移现有实例时，源码本身不等于完整业务状态。必须另外迁移 `Code/data.db` 及其 WAL、`Code/data`、`Code/generated`、`paper-claw-master/data/files`、两份 `.env`，以及 Compose 管理的 PostgreSQL volume。Compose project name 由仓库绝对路径计算，同一台机器移动仓库目录会得到新的 volume 名；若要保留旧 A 端数据，应先做 PostgreSQL 备份/恢复，不能假定新目录自动挂载旧卷。`JWT_SECRET` 或邮件凭据加密密钥改变后，既有登录 token 或已保存密文不能继续按原值解密。

当前代码没有提供公网生产发布所需的静态前端托管、TLS/反向代理、服务守护、集中日志、共享文件存储或跨实例任务协调。Express 的限流器、报告/提醒调度与部分运行协调是进程内实现，SQLite 和本地文件也是单机边界；因此不能把多个 D 实例直接并排启动并声称等价。SMTP/IMAP、Zotero、arXiv/OpenAlex、模型网关和首次本地模型下载仍受目标机器网络、凭据及第三方可用性约束。

## 15. 当前验证基线

| 范围 | 结果 |
|---|---|
| 主站 TypeScript 前端与 Express 服务端类型检查 | 通过 |
| 主站生产构建 | 通过 |
| 主站测试 | 43/43 通过 |
| Paper Claw 独立前端类型检查与生产构建 | 通过 |
| Paper Claw 独立前端测试 | 4/4 通过 |
| 导师工作流测试 | 92/92 通过 |
| Paper Claw 后端完整测试（Docker PostgreSQL） | 366/366 通过；28 分 15 秒 |
| 星图测试 | 5/5 通过 |
| 数据质量测试 | 5/5 通过 |
| RAG 自检 | A–G 全部通过；972 candidates / 1969 evidence |
| 跨模块运行时数据 | 972 个共享 candidate_id，通过 |
| Windows 启动预检、真实服务启动与新用户烟测 | 通过；注册、画像、推荐、428 API 门、合并 PDF、PPT 导出均验证 |

完整后端测试没有失败，但输出了三类兼容性警告：FastAPI `on_event` 已被官方标记为未来弃用；两个导师工作流 API 测试中的 `freshness="unknown"` 测试值触发 Pydantic 枚举序列化提示；当前 FastEmbed 版本提示多语种 MPNet 模型已从 CLS pooling 改为 mean pooling。这些警告不影响本次通过结论，但升级 FastAPI、Pydantic 或 FastEmbed 时需要复核。

主站构建仍会提示 CloudPage 相关 chunk 约 591 kB；这是 3D 页面加载性能提示，不改变上述业务行为。SMTP/IMAP、Zotero、arXiv/OpenAlex 和模型网关的在线成功还取决于用户凭据、网络与第三方服务状态。
