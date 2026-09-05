
107 → Open Research｜355+ 黑客松 / Agent 项目如何改变了我的思维方式

107 CUP → OPEN SOURCE / RESEARCH AGENT / HACKATHON STUDY

  看完 355+ 个项目之后，
我为什么不想只做一个“导师匹配平台”了

这份报告不是功能规划，也不是把我的聊天压成十个概念。它记录的是一段真正发生过的思维变化：我从一个已经能工作的导师搜索原型出发，连续看了 GitHub 高关注 Agent、ETHGlobal、LabLab、Devpost、Hacker News、ModelScope、Hugging Face 等平台上的数百个项目，又继续追它们的演示、作者自述、获奖结果、社区讨论和后续产品化。越看，我越发现：真正优秀的团队并不是“比别人多接了一个模型”，而是在重新定义用户到底在完成什么任务、系统到底替用户承担什么责任、结果为什么值得相信，以及为什么别人愿意继续使用和扩展它。

**355+**第一轮跨平台候选项目；其中 100 个 2024+ 高关注 GitHub 项目、173 个 ETHGlobal 项目，以及 Devpost / LabLab / HN / ModelScope / HF 等候选。

**3 轮认知重构**从“加功能”到“重构 Agent 产品”，再到“寻找一个值得长期做成开源项目的原创母题”。

**1 个目标升级**一〇七杯仍然重要，但现在希望比赛版本只是第一个公开 Demo，而不是项目的终点。

**最终问题**不是“还能加什么 Agent”，而是“什么东西值得陌生开发者 star、fork、写插件、贡献研究包与任务轨迹”。

**这次调研最重要的结果：**我没有找到一个“照抄就行”的冠军方案。相反，上百个项目互相矛盾的成功经验，逐步逼着我把自己的系统从“导师推荐 + 多 Agent”推成一个更完整的命题：**一个能够理解人的科研状态、计算人与目标之间的差距、生成可执行 Research Mission、要求证据验证、允许人实时干预，并让人和 Agent 在每次任务后都发生可积累变化的开放科研系统。**

[01 起点](#origin)[02 355+ 项目怎么查](#survey)[03 第一轮冲击](#shock1)[04 获奖项目改变标准](#shock2)[05 生产项目纠偏](#prod)[06 多团队模拟评审](#debate)[07 思路演变](#evolution)[08 最终母题](#thesis)[09 十个原创方向](#ideas)[10 代码落地](#landing)[11 Demo](#demo)[12 开源生态](#opensource)[13 路线](#roadmap)

01 / WHERE WE STARTED

## 我最初其实已经有一个“能展示”的项目，但它还没有一个足够强的理由让人记住

最初的一〇七项目并不是空白原型。前端已经有导师搜索、导师详情、推荐、收藏、对比、邮件生成、PDF 分析和 3D 星图；后端也已经不是一个简单的 LLM wrapper，而是一条完整的多 Agent 工作流：输入理解、规划、动态领域专家、导师研究、候选筛选、论文证据、匹配、独立审核、结果合成。更关键的是，后端已经有类型化状态、EvidenceLedger、ReviewDecision、RetryRecord、Event Bus、Resume 等机制。

当时我觉得的问题

页面还可以更丰富，Agent 还可以更明显，输入还可以加语音、图片，3D 星图还可以更酷，最好再接 Browser Agent、Memory、MCP。沿着这个方向继续做，当然能把 Demo 变得更热闹。

后来才发现的问题

这些能力几乎都已经在大量 2024–2026 黑客松作品和开源 Agent 项目里出现。单独增加语音、Browser、Memory、Agent Crew 或 3D，已经很难构成“为什么一定要做这个项目”的核心理由。

[IMG_BASE64 #1 内嵌图片已省略]

**当前原型截图。** 这版系统已经具有完整产品雏形，但从外部看仍然更像“导师信息平台 + Chat + 工具页面”。真正强的 Evidence / Review / Retry / Resume 等后端机制没有转化成用户能理解的产品语言。

这也是我后来反复不满意的根源。每次讨论时我都能再加一个“不错的功能”，但越加越容易变成一个技术清单：

多 Agent
+ RAG
+ PDF
+ 语音
+ Browser
+ 3D
+ Memory
+ MCP
+ 邮件
+ 推荐
────────────────────
= 功能很多
≠ 一个有自己观点的项目

于是目标发生了第一次变化：我开始暂停修 bug，也暂停继续堆页面，先去看别人到底是怎么赢、怎么获得开发者关注、怎么在几分钟 Demo 里让评委记住，以及哪些项目在黑客松之后还能继续生长。

02 / HOW THE SURVEY CHANGED

## 我查的不是“Agent 项目排行榜”，而是不同团队解决问题的方式

第一轮我做了一个很大的候选池：355 条原始案例。GitHub 主池集中在 2024 年以后、高社区关注的 Agent 项目；黑客松池覆盖 ETHGlobal、LabLab、Devpost、Devfolio；产品/社区信号又补了 Hacker News、Product Hunt、Hugging Face Spaces、ModelScope，以及国内开发者社区。这个数量本身没有学术统计意义，它的作用是帮助我避开“只看三五个熟悉项目就开始设计”的局限。

#### 代码社区

Browser Use、OpenHands、Agent Zero、PydanticAI、VoltAgent、Graphiti、12-Factor Agents、Microsoft Agent Framework、Agent-S、RD-Agent……重点看 architecture、README、issue/discussion、后续版本。

#### 黑客松档案

ETHGlobal、Devpost、LabLab 等。重点不只看“用了什么技术”，还看 2–4 分钟 Demo 怎么讲、获了什么奖、作者如何解释创新点、项目是不是只为 sponsor prize 拼装。

#### 程序员社区

Hacker News 等。这里最有价值的是质疑：为什么不用普通脚本？多 Agent 是否真的必要？trace 怎么调？成本如何？这些问题往往比项目自己的 README 更能暴露设计弱点。

### 后来我的精读方式也变了

一开始我记录的是“项目名称 / 功能 / 可以借鉴什么”。这很快变得不够。第二轮开始，我要求一个项目至少回答下面几层：

| 层 | 真正要看的问题 | 为什么重要 |
| --- | --- | --- |
| 出发点 | 作者为什么会做它？他当时对现有工具哪里不满意？ | 决定项目是否有清楚的 thesis。 |
| 演示 | Demo 的第一个画面是什么？哪一步产生“转折”？ | 决定评委是否在 30–60 秒内理解价值。 |
| 架构 | 状态在哪里？Agent 如何分工？Tool 怎样挂载？失败怎么恢复？ | 区分产品结构与“prompt + tools”。 |
| 评委/奖项 | 评审标准是什么？公开评语强调了什么？ | 判断团队自认为的创新是否真的被外部认可。 |
| 社区反馈 | 程序员最常质疑什么？作者后来改了什么？ | 很多真正成熟的设计发生在 Demo 以后。 |
| 可迁移性 | 它最聪明的东西是 UI、数据模型、运行时，还是故事？ | 避免只“抄功能”。 |

**关键原则：**不是每个项目都值得深拆。355 是发现池；真正影响我思路的，是那些能找到项目页、仓库、Demo、作者自述、奖项或社区讨论，而且能明确提炼机制的案例。

03 / FIRST SHOCK

## 第一轮：我先被“Agent 能做什么”吸引，随后发现这还只是表层

第一批项目给我的直观冲击很强：浏览器真的能点、桌面真的能操作、Agent 能开终端、能调用真实工具、能语音、能在多个 Agent 之间协作。和传统“聊天机器人”比，这些项目的动感和完成任务能力明显强很多。于是我最早的直觉也是：把这些能力接到导师平台上。

[IMAGE_URL https://github.com/user-attachments/assets/57611d8e-0474-4de6-84b7-37a0c0cd27e7 alt="Browser Use demo"]

**Browser Use。** 它给我的第一层启发很直观：研究 Agent 不应该只会调用搜索 API，它可以真的进入网页环境。但后来 Browser Use 自己的产品演化又让我意识到，“所有流程都交给 Browser Agent”同样是一个过度设计。
Source: browser-use/browser-use official README

[IMAGE_URL https://raw.githubusercontent.com/bytedance/UI-TARS-desktop/main/images/tars.png alt="Agent TARS"]

**Agent TARS / UI-TARS。** GUI、Vision、Browser、Terminal、MCP 和 Event Stream 被放在一个统一 Agent stack 中。真正启发我的后来不只是“多模态”，而是它把 Event Stream 直接作为 Agent UI 和 Context Engineering 的基础。
Source: bytedance/UI-TARS-desktop official README

**我最开始的想法**
导师主页抓不到？加 Browser Agent。输入太单调？加语音、图片、PDF。Agent 看不见？做 Agent Crew。前端不够亮眼？把 3D 星图做得更大。

→

**看多以后产生的怀疑**
这些单项能力已经非常普遍。即使我全部实现，评委仍然可以把它总结成一句：“一个加入很多 Agent 功能的导师推荐平台。”

### OpenHands 又把我的注意力从“聊天”推向“工作区”

[IMAGE_URL https://assets.openhands.dev/screenshot/automation-preview.png alt="OpenHands Agent Canvas"]

**OpenHands Agent Canvas。** 它没有把所有价值塞进一串聊天消息，而是让任务、自动化、Agent backend 和执行环境成为可管理对象。这让我第一次强烈意识到：当前 SearchPage 左卡片 + 右 ChatWindow 的信息结构，可能从根上就压扁了后端已经拥有的运行时能力。
Source: OpenHands/OpenHands official README

于是第一轮调研以后，我得到第一个真正的产品级变化：把 `/search` 从“搜索页面”升级成持久 Research Workspace，把 PDF、Compare、Email、Cloud 从几个孤立页面重新挂到一次长期任务上。这个想法后来还会继续被修改，但“Chat 不应该等于整个产品”从此没有再被推翻。

04 / HACKATHON WINNERS CHANGED THE STANDARD

## 第二轮：真正改变我的，是获奖项目并不靠“Agent 数量”取胜

当我把注意力从 GitHub 高 Star 项目转到黑客松留档，评价标准发生了明显变化。ETHGlobal 的正式评审把 Technicality、Originality、Practicality、Usability、WOW Factor 并列；Finalist 的现场通常只有 4 分钟 Demo + 3 分钟问答。这意味着“架构复杂”只是五分之一，真正优秀的项目必须同时让人迅速理解它为什么存在、已经做到哪里、为什么可信，以及为什么会被记住。

### GitLab AI Hackathon 2026

这一场近 7000 名开发者做出了 600+ Agent/Flow。主办方甚至明确强调，希望看到进入 workflow、响应事件并采取行动的 Agent，而不是只回答问题的聊天机器人。

总冠军 LORE 有 8 个 Agent、router、知识图防循环、Dashboard、碳追踪和 43 个测试。Anthropic 评委 April Guo 的公开评价非常短，却非常说明问题：它“像一个产品”。

**我真正学到：**Agent 数量完全没有稀缺性；完成度、可靠性、实际痛点、测试和视觉化运行过程才稀缺。

[官方获奖复盘 ↗](https://about.gitlab.com/blog/gitlab-ai-hackathon-2026-meet-the-winners/)

### RAISE YOUR HACK 2025

6246 名参与者、919 个团队、223 个最终项目；Groq、Llama、LangChain、Fetch.ai、Whisper、GPT-4 Vision、Generative Agents 等技术已经大量出现。

冠军 “Autonomous Agents from APIs – Zero Code Builder” 的故事并不是“我用了多少框架”，而是从用户意图一路走到 Plan → Code → Execute → Iterate → Deploy。用户能看见任务怎样逐步变成可运行的东西。

**我真正学到：**多模态和 Multi-Agent 已经变成公共词汇。更重要的是让用户看到一个完整“转化过程”。

[官方 Live Dashboard ↗](https://lablab.ai/ai-hackathons/raise-your-hack/live)

### 几个项目分别把我的某一条思路推向了下一步

Deptheon1st Place

#### 它让我意识到：推荐不是任务终点

Deptheon 的 Demo 把 web research、电话采访、transcript、内容生成、邮件串成一个长任务。它最值得借的不是“能打电话”，而是结果继续触发真实下一步。

于是我开始认为：导师 shortlist 后面自然应该继续长出论文阅读、导师 briefing、沟通问题、邮件、follow-up，而不是“推荐完成”。

[Devpost 项目页 ↗](https://devpost.com/software/deptheon-ai)

GliderETHGlobal Finalist

#### 它让我改变了对“全自动”的态度

Glider 可以自动操作 Web3 UI，但真正影响资产的交易仍然回到用户自己的 wallet 签名。它把“强自动化”和“最后控制权在人”同时放进一个很容易理解的 Demo。

于是我不再追求“科研 Agent 什么都自己做”，而开始设计 Autonomy Boundary：网页读可以自动、论文查可以自动、邮件 draft 可以自动，外发和提交必须审批。

[ETHGlobal 项目页 ↗](https://ethglobal.com/showcase/glider-zr9bd)

MintConditionMulti-prize

#### 它先启发了 Compare Council，后来又被我自己推翻了一半

MintCondition 同时展示多个模型的估值、权重、解释和最终 consensus。这让“透明分歧”非常有产品感，我一度计划做 Advocate / Skeptic / Auditor / Consensus。

但继续看可信研究后，我意识到多个 LLM 互相讨论并不天然增加真值。因此最终留下“可见分歧”的交互思想，却把技术核心改成 Claim–Evidence Verification。

[ETHGlobal 项目页 ↗](https://ethglobal.com/showcase/mintcondition-8kqc4)

Geneva

#### 它让我看到：Agent 可以真正有“组织形态”

Geneva 直接把 GitHub Discussions、Issues、PR、Wiki 变成 Agent swarm 的协作场，每个 Agent 有身份、任务、review 对象，甚至保留幽默和 lore。

它让我想把 Dynamic Domain Expert 做成真正有 role / tools / output / responsibility 的 Agent Crew；但后来的 12-Factor 又提醒我：只有任务需要时才生成 Crew。

[ETHGlobal 项目页 ↗](https://ethglobal.com/showcase/geneva-n0oc3)

这一轮最大的思维变化是：我第一次不再问“别人有什么功能我还没有”，而开始问“为什么这些团队能把一个技术机制变成一个三分钟就能被理解的故事？”

### 于是 Demo 也从“展示功能”改成“展示一次转折”

我后来反复保留的一个设计，就是让一个最初排名很高的导师被 Evidence Auditor 打回，系统自动补证据，排名与 3D 图发生变化，最终重新通过审核。这样一个现场转折可以同时解释 Multi-Agent、Evidence、Review、Retry、Event Stream、3D 和 Human-in-the-loop，不需要先讲五分钟架构图。

05 / PRODUCTION PROJECTS CORRECTED US

## 第三轮：看生产项目和社区反馈以后，我开始主动“少做一点 Agent”

如果只看黑客松，很容易产生一个错觉：Agent 越多、工具越多、流程越自主越厉害。继续看真正进入长期开发的项目后，我的方向发生了第二次关键纠偏——很多成熟团队都在把确定性控制重新拿回来。

[IMAGE_URL https://raw.githubusercontent.com/humanlayer/12-factor-agents/main/img/155-unify-state-animation.gif alt="12 Factor Agents state"]

**12-Factor Agents：统一执行状态与业务状态。** 作者在尝试大量框架并和许多生产团队交流后，得到的核心观察是：很多真正好用的“Agent 产品”其实主要仍是软件，只在最适合的决策点使用 LLM。它特别强调 own control flow、pause/resume、small focused agents、state 可序列化和可 fork。
Source: humanlayer/12-factor-agents

### 这直接推翻了我一个很危险的方向：固定 Agent Crew

**曾经想做**
所有任务默认启动 Planner、Domain Expert、Researcher、Paper Agent、Auditor、Outreach，前端同时出现多个 Agent，让“多 Agent 感”更明显。

→

**现在改成**
**任务自适应拓扑。** 一个简单导师事实查证可能只需要 deterministic connector + verifier；只有真正可并行的宽研究任务才 spawn 多个 Research Agent。

这个变化非常重要，因为它把“多 Agent”从品牌装饰降级成一种执行策略。系统应该根据任务依赖、信息宽度、成本和风险决定：

Mission Compiler
      │
      ├── deterministic workflow
      ├── single focused agent
      ├── parallel research agents
      ├── browser fallback
      └── human escalation

不是用户每说一句话都召集一个 AI 公司。

### Browser Use 的后续演化又让我重新理解 Browser Agent

最开始 Browser Use 最吸引我的地方是“LLM 像人一样操作网页”。但持续自动化场景中，一个越来越合理的工程策略是：稳定来源优先走结构化 connector / API / 已知路径，只有未知网页或路径失效时才把问题交给 Browser Agent。成功的探索轨迹还可以沉淀为未来的确定性 route。

Known Source / API / DBLP / OpenAlex
                │
         deterministic path
                │
         ┌──────┴──────┐
         │ success     │ fail / unknown
         ▼             ▼
      Evidence      Browser Agent
                        │
                  successful trace
                        │
                 reusable research skill

这个思想后来进一步变成我非常喜欢的一句话：

**Agent 负责探索未知，软件负责固化已知。**
它比“接一个 Browser Use”更接近我希望开源项目最终形成的工程哲学。

### Graphiti 又把 Memory 从“聊天历史”变成“会变化的事实”

[IMAGE_URL https://raw.githubusercontent.com/getzep/graphiti/main/images/graphiti-graph-intro.gif alt="Graphiti"]

**Graphiti Temporal Context Graph。** 它明确区分当前事实、历史事实和原始 episode，并保留 provenance。对于科研系统，这意味着“导师研究方向”“用户技能”“实验状态”都不是永远不变的 profile 字段。
Source: getzep/graphiti official README

这一步直接启发了后来两个更有自己味道的概念：**Research Genome** 不应该是一张静态简历；**Research Time Machine** 应该允许我看一个导师、实验室、方向和用户自己的能力怎样随时间变化。

06 / SIMULATED DESIGN REVIEW

## 如果把这些团队“请进一个会议室”，他们会怎样把我现在的方案一轮轮拆掉

下面是基于各项目公开设计哲学做的模拟评审，用来呈现我实际经历的思路碰撞；不是这些创作者的真实原话。

OpenHands / Agent TARS / VoltAgent 派Runtime & Workspace

**他们会先问：**你后端明明有 Plan、Event、Evidence、Review、Retry、Resume，为什么用户只看到一串 thinking 文本？

→ 我接受了这个攻击。

因此 SearchPage 不再应该是中心，`ReasoningChain` 也不能再只是文本按行编号。未来前端消费的是 `stage_started / tool_called / artifact_created / evidence_added / claim_conflict / review_failed / retry_started / approval_required` 等真实 Runtime Event。

Geneva / Power Agents / Swarm 派Multi-Agent Organization

**他们会说：**如果你强调 Multi-Agent，就让每个 Agent 有清楚的任务、工具、产物和责任，不要只是换头像。

→ 我吸收了一半。

我保留 Agent Contract，但拒绝“每次固定 5 Agent”。Crew 成为 Mission Compiler 的动态结果。

12-Factor / Production Engineering 派Control & Reliability

**他们会继续攻击：**为什么这一步一定要 LLM？为什么不写普通代码？状态能序列化吗？可以 pause、resume、fork 吗？失败以后是重试还是重新规划？

→ 这改变了底层。

我开始把执行节点统一抽象成 `ExecutionNode`：它可以是 deterministic function、connector、single agent、parallel agents 或 human，不再默认“一个节点等于一个 Agent”。

MintCondition / Transparent AI 派Visible disagreement

**他们会说：**把不同模型的意见和 confidence 展示出来，用户会更理解系统为什么这样判断。

→ 这让我提出 Compare Council，但后来我又反过来质疑它。

多个 LLM 同意并不能把一个缺乏来源的事实变真。所以最终真正的争论对象不再是“Agent A vs Agent B”，而是“Claim 是否被独立 Evidence 支持或反驳”。

Graphiti / Evidence-first 派Temporal provenance

**他们会追问：**“王老师现在做 diffusion”这句话是什么时候成立的？官网是 2022 年的，论文是 2026 年的，发生冲突怎么办？

→ 这让 EvidenceLedger 继续升级。

Evidence 不再只挂在 Candidate Mentor 下，而要和 Claim 建立 `SUPPORT / CONTRADICT / SUPERSEDE` 等关系，形成时间化的 Claim–Evidence Graph。

Deptheon / Hackathon Product 派Outcome & Story

**他们最后会问：**找到导师以后呢？用户真正的事情完成了吗？四分钟 Demo 里哪里会发生一次让人记住的变化？

→ 这把我的边界从“导师推荐”打穿了。

推荐只是 Research Mission 中间的一种 Artifact。任务还可以继续到论文阅读、mini project、能力补齐、导师沟通和 follow-up。

真正深刻的地方并不是我把六种优秀思想“全部加进来”，而是它们彼此制衡：

Multi-Agent 派让系统更主动；工程派限制它乱跑。

透明讨论派让分歧可见；Evidence 派又要求分歧必须落到来源。

黑客松派要求三分钟抓眼球；开源派又要求这个机制不是一次性舞台效果。

07 / HOW OUR THINKING EVOLVED

## 把几轮对话连起来看，我的方向其实发生了五次明显的迁移

### 阶段 A：导师匹配平台 + 多 Agent

最初的目标非常具体：把用户的研究兴趣和已有材料理解清楚，搜索老师，给出匹配度和理由，再提供 PDF、比较、邮件等功能。这个版本已经足够做出比赛原型。

**当时的不足：**容易被理解成“更智能的导师数据库”。

### 阶段 B：Research Workspace

看 OpenHands、VoltAgent、Agent TARS、Geneva 以后，我开始把 Plan、Agent、Tool、Evidence、Review、Retry 显式化，把不同页面收进一次持久 Mission。

**得到：**完整 Agent 产品感。
**仍然不足：**这仍可能只是“科研版 Agent Workspace”。

### 阶段 C：Verifiable Agent Runtime

看 12-Factor、可信 Agent、temporal memory 等路线后，我把固定 Agent Crew 改成自适应执行拓扑，把 Evidence 升级成 Claim–Evidence，把 Plan 升级成 Mission Contract，并加入 Autonomy Policy、Artifact、Trace。

**得到：**有清楚技术 thesis 的 runtime。
**仍然不足：**它更像一个很好的“基础设施”，用户为什么长期回来还不够强。

### 阶段 D：从“推荐谁”转向“我怎样改变”

当目标从一〇七杯提升到长期开源项目时，问题终于发生改变。导师推荐只能回答“我现在适合谁”；更有价值的是回答“我想去那里，我还差什么，最小要做哪些真实事情才能让状态改变”。

于是出现了 **Research Genome + Counterfactual Navigation + Mission Forge**。

### 阶段 E：开放科研成长系统

如果每次成功任务还能固化成 Skill，如果 Mission 可以像代码一样 Fork，如果领域专家可以贡献 Research Pack，如果失败路径也成为 Negative Knowledge，那么系统不只帮助一个用户，它开始形成社区可积累资产。

**这时我第一次觉得：**它可能值得比赛结束后继续做。

08 / THE NEW THESIS

## 我现在真正想做的，不是一台“替人找老师”的机器

经过这些项目的连续冲击以后，我现在更愿意把核心问题描述成：

**一个人现在处在怎样的科研状态？他想去哪里？真正阻挡他的能力、证据和经历缺口是什么？什么最小行动能够改变这种状态？这些行动做完后，我怎样验证“人真的成长了”，同时让 Agent 也从成功和失败中学到可复用的东西？**

这使整个系统的最小循环变成：

Observe
  ↓
Research Genome
  ↓
Target / Direction
  ↓
Gap Modeling
  ↓
Counterfactual Options
  ↓
Mission Forge
  ↓
Adaptive Execution
  ↓
Claim–Evidence Verification
  ↓
Artifacts
  ↓
Human & Agent both update
  ↓
Evolve

导师、论文、课程、实验、开源项目不再是五种互不相干的模块。它们都成为“一个人的科研状态怎样发生变化”中的实体和行动。

### 一个具体例子

如果用户说：“我现在做过一次 StableFlow 复现，我想以后进一个做可控生成/多模态的实验室。”

普通推荐系统输出导师列表；普通科研助手给学习建议；我的目标是把它进一步变成：

当前 Research Genome
────────────────────
Diffusion 基础：有证据
论文复现：有证据
Attention injection：中等
Flow matching：中等
大规模实验设计：缺口
Multimodal editing：缺口
开源 artifact：缺口

            ↓

目标实验室 / 目标方向

            ↓

Counterfactual Engine

A. 补一个 multimodal editing reproduction
   predicted gap reduction: HIGH

B. 继续读 5 篇 diffusion paper
   predicted gap reduction: MEDIUM

C. 做一个有公开报告的 controlled experiment
   predicted gap reduction: VERY HIGH

            ↓

Mission Forge

“在 6–8 小时内完成一个最小实验，
必须提交代码、结果图、失败记录和解释，
通过 Evidence Contract 后才写回 Genome。”

这个例子对我非常重要，因为它说明为什么课程复习、科研探索、导师匹配可以真正落到同一套 runtime 上：它们都在改变一个人的状态。

09 / IDEAS THAT CAME OUT OF THE SURVEY

## 上百个项目不是让我“加了十个功能”，而是逼出了十个可以继续长大的原创方向

01

### Research Genome

**来自什么冲击：**Graphiti 的时间化事实、Evidence-first 项目的 provenance、我自己的导师/论文证据工作流。

**我自己的变化：**把“用户画像”从兴趣标签升级为可验证能力图。`读过 / 能解释 / 能实现 / 能调试 / 能复现 / 能设计实验 / 有公开 artifact` 是不同状态。

**为什么有产品记忆点：**用户可以看到自己的科研地图真的随着任务完成而生长；这本身就是一种强视觉和长期使用理由。

02

### Counterfactual Research Navigator

**它回答的不是：**“哪个导师和我最匹配？”

**它回答：**“为什么现在不匹配？改变哪一件事最能改变结果？如果我走 A/B/C 三条路径，未来的 Research Genome 会怎样？”

这让推荐从静态 scoring 变成 intervention / what-if。3D 星图也第一次有机会从装饰变成真正的交互计算界面。

03

### Mission Forge

差距不能只转成一句“建议学习 XX”。系统应该把 gap 编译成一个真正可验收的 Mini Research Mission：读什么、跑什么、改哪个变量、产出哪些 Artifact、怎样算完成。

这延续了优秀黑客松项目“意图 → 可见过程 → 可运行结果”的共同模式，但把它放进科研成长。

04

### Mission Contract

Plan 只说“怎么做”，Contract 还要说：什么证据算完成、哪些来源可以信、多少预算、Agent 自治到哪里。

goal
outputs
acceptance
source_policy
autonomy
budget
stop_conditions

这样 Reviewer 不需要最后凭感觉打分，而是检查一个任务开始前就约定的合同。

05

### Claim–Evidence Graph

我从 MintCondition 得到“把分歧展示出来”，但后来把核心进一步推到事实层：真正需要争论的是 Claim，而不是 Agent 人格。

Entity → Claim
          ↙   ↘
     SUPPORT  CONTRADICT
          ↘   ↙
         Evidence
            │
          time
            │
       provenance

这个结构能够直接支撑导师研究方向变化、论文结论、用户能力证据，以及以后更广泛的科研调查。

06

### Forkable Research Mission

一次成功科研路线不应该死在聊天记录里。它可以被发布成一个 Mission Package：目标、输入 schema、工具、Evidence Contract、步骤、Artifact、Eval 和轨迹。

别人可以 Fork：“StableFlow reproduction” → 换成 FlowEdit；“CV 导师调查” → 换成 NLP；就像 Fork 一个 repo 一样 Fork 一条科研路径。

07

### Skill Evolution

第一次访问一个难抓的实验室网页，Agent 用 Browser 探索；成功以后把路径凝练成 Skill。第一次做某类论文复现审计很慢，完成后沉淀成领域 Skill。

**长期哲学：**Agent 探索未知，系统把已知编译成更便宜、更稳定的行为。

08

### Negative Knowledge

科研里“这条路为什么没走通”经常比成功答案更值钱。系统应该一等记录：无效查询、冲突来源、失败环境、错误指标、无法复现的 repo、被 Reviewer 打回的原因。

这样社区不是只累积答案，还能累积“不用再踩的坑”。

09

### Research Time Machine

导师方向、实验室成员、热点、用户能力都随时间变化。3D 图增加时间轴后，可以回答：“这个实验室是不是在离开 diffusion？”、“这个方向的增长从什么时候开始？”、“我的能力变化从哪几个 Mission 开始？”

10

### Research Commons & Packs

真正的开源生态不能只让别人提交 React/FastAPI PR。我希望别人能贡献“知识与行为模块”：CV Research Pack、Security Pack、RecSys Pack……其中包含 connectors、ontology、Evidence Rules、Mission Templates、Eval cases、Skills。

这会让社区扩展的单位从“代码函数”变成“一个领域的科研能力”。

**创新边界：**我现在可以有底气说，在这 355+ 候选和后续深潜样本中，没有看到一个成熟项目把 **Research Genome + Counterfactual Navigation + Forkable Mission + Claim–Evidence Verification + Skill Evolution** 以同一个长期用户闭环组织起来。但我不会声称“全球从来没有任何相近思想”；比赛和开源都应该把创新表述建立在可查证边界上。

10 / LANDING ON THE CURRENT CODEBASE

## 这些讨论并没有让现有代码作废；恰好相反，后端已有的东西现在终于有了更好的用途

我原来最担心的一个问题是：如果方向升级得这么大，是不是要把整个后端重写。现在看没有必要。现有 A 端真正值得保留的五块骨架——typed state、evidence、review、retry、event——正好可以成为新 runtime 的起点。

| 当前已有 | 升级后的含义 | 具体作用 |
| --- | --- | --- |
| TaskPlan | MissionContract + ExecutionGraph | 除了 steps，还增加 acceptance、source policy、autonomy、budget，并允许节点不是 Agent。 |
| AgentAssignment | ExecutionNode | 节点可以是 connector / deterministic function / agent / parallel agents / human。 |
| EvidenceRecord | Evidence + ClaimEdge | 明确支持、反驳或覆盖哪个 Claim，并保存时间与来源。 |
| ReviewDecision | VerificationReport | 由 contract checks + semantic verification + conflict resolution 组成。 |
| RetryRecord | Recovery / Replan Event | 区分简单重试、换工具、扩大来源、改拓扑、请求用户输入。 |
| AgentMessage | RuntimeEvent | 前端展示动作与状态，而不是伪装成 Agent 内心独白。 |
| WorkflowState | MissionState | 成为整个 Mission 的 single source of truth，可 replay / fork。 |

### 前端怎么具体改，不再停留在“做一个 Workspace”

#### 1. SearchPage → Mission Workspace

当前的左侧导师卡 + 右侧 ChatWindow 不再承担全部信息。页面改成三个主要区域：

Mission / Plan / Sources
        │
Workspace / Artifacts
        │
Timeline / Evidence / Review

Chat 退到底部 Composer，成为输入方式之一。

#### 2. ReasoningChain → Runtime Timeline

当前按换行编号的 thinking 文本直接替换为结构化事件视图：

stage_started
tool_called
source_opened
artifact_created
claim_added
evidence_added
conflict_found
review_failed
replan_started
approval_required

#### 3. PDF 页面 → Unified Intake

PDF、URL、图片、语音、GitHub repo、DOI/arXiv 都进入同一个 Mission。PDF 不再是“一个额外工具”，而是一种 observation。

#### 4. Compare 页面 → Evidence Comparison

不再只比较部门、标签、论文数和 match score。比较对象变成：关键 Claim、支持证据、反证、证据新鲜度、能力差距、下一步 Mission。

#### 5. Email 页面 → Action Board

Briefing、邮件、follow-up、预约、阅读任务都变成 Mission 后续 Action，并受 Autonomy Policy 控制。

#### 6. 3D Cloud → Mission State Graph

图里同时出现 User Profile、Direction、Mentor、Paper、Claim、Evidence、Agent 和 Review。Replay 时，节点随事件出现、被打回、重新获得证据和改变排名。

### Mission Replay：从“防 Demo 翻车”升级成核心能力

很多黑客松团队会为现场准备 replay/cached mode。我最初也只是把 Replay 当作展示保险。但继续分析后发现，如果所有 Runtime Event 都能持久化，Replay 会同时解决五件事：

- **Demo：**现场服务挂了仍能展示完整真实轨迹。

- **Debug：**开发者拖时间轴看 Agent 在哪一步走偏。

- **Eval：**同一 Mission 在不同模型/拓扑上重复运行比较。

- **Explainability：**用户看到“为什么这个导师从第 1 变第 3”。

- **Fork：**从某个历史状态分叉，修改 source policy 或目标，再比较结果。

11 / HACKATHON DEMO

## 比赛版仍然要抓人，但抓人的东西应该就是长期架构本身

我不希望为了比赛另外做一套“假的炫技动画”。最理想的 Demo 是把未来开源项目最独特的闭环压缩成三四分钟。

00:00
**从真实材料开始。**
用户拖入一份项目 PDF，同时语音说：“我做过这个方向，想继续做可控图像编辑，优先找最近两年仍然活跃、适合本科生进一步研究的老师。”

00:20
**Research Genome 出现。**
系统从材料中只写入“有证据”的能力；不确定项明确标注 unknown，而不是强行画像。

00:35
**Mission Contract。**
界面直接显示：导师身份需要官方来源；研究方向需要近期论文或新鲜官方信息；外发邮件需要审批。

00:50
**系统自己决定执行拓扑。**
三个研究方向可以并行，所以出现 3 个 Research Node；导师身份查询走确定性 connector，没有为了展示而额外 spawn Agent。

01:20
**第一次转折。**
Professor A 暂时排名第一，但 Verification 发现“图像编辑”只被一个旧主页支持；Claim 被标成 stale / insufficient，任务自动触发 RESEARCH_AGAIN。

01:45
**证据改变结果。**
Browser fallback 找到新的 2026 论文和实验室页面；Claim–Evidence Graph 更新，3D Mission Graph 动态重排。

02:15
**第二次转折：推荐变成成长。**
用户点 Professor B，不只看到“匹配 73%”，还看到：“如果希望三个月后更适合这个方向，最有价值的缺口是缺少 multimodal editing 的实证 artifact。”

02:40
**Counterfactual Navigator。**
界面展示三条未来路线及预计补齐的 Genome 区域。用户选一条。

03:00
**Mission Forge。**
系统生成一个可 Fork 的 mini research mission：论文、repo、实验变量、必须提交的图和报告、验收条件。

03:25
**开放循环。**
屏幕最后定格在：“完成 Mission 后，你的 Genome 会更新；成功路径会沉淀为 Skill；你可以选择把匿名 Mission Template 贡献到 Research Commons。”

这样四分钟里看到的不是十个 feature，而是一件完整的事：

系统先理解“我现在是谁”，再理解“我想去哪里”，用证据判断“我为什么还没到”，最后真的生成一条能改变这个差距的行动路径。

12 / WHY THIS CAN BECOME OPEN SOURCE

## 如果比赛以后继续做，真正需要设计的是“别人可以贡献什么”

大量 AI 开源项目的问题是：用户可以 clone，但只有原作者真正能扩展核心能力。我希望从一开始就把贡献面设计出来，让社区不是只能提 feature request。

#### Research Pack

一个领域的 ontology、connectors、Evidence Rules、Mission templates、Eval cases。例如 CV Pack、Security Pack、RecSys Pack。

#### Mission Template

一次成功的可复用研究路径。可以版本化、Fork、比较不同模型的执行结果。

#### Skill

从成功 trajectory 固化出的可复用行为，例如实验室网站解析、论文复现审计、Benchmark 结果抽取。

#### Evidence Rule

社区可以贡献“什么来源足以支持什么 Claim”的规则，而不是只贡献 prompt。

#### Eval Mission

一组可重放的困难场景：旧主页、同名导师、冲突论文、模糊输入、错误 repo、缺失证据。

#### Negative Knowledge

经过验证的失败路径也可以成为可共享资产，帮助后来者减少重复探索。

### 这个开源项目可以有两层

#### Product layer

给学生/科研新人真正使用：Research Genome、方向探索、导师、Mission、论文、行动、成长轨迹。

#### Runtime layer

给开发者二次开发：Mission / Contract / Claim / Evidence / Artifact / Event / Policy / Trace / Skill 等 primitive。

这样比赛 Demo 不会把项目锁死在“导师匹配”。导师匹配只是我最早、最容易讲清楚的一种 Research Mission。

13 / WHAT WE ACTUALLY BUILD NEXT

## 下一步的优先级：先把“思维变化”落实成架构，再修那些会被新架构推翻的旧页面

| 优先级 | 要做的事 | 为什么现在做 | 直接利用现有资产 |
| --- | --- | --- | --- |
| P0 | 定义 MissionState / MissionContract / RuntimeEvent | 这是所有新 UI、Replay、动态拓扑的共同数据底座。 | WorkflowState、TaskPlan、event bus |
| P0 | Claim–Evidence schema + Verification | 这是项目可信性的核心，也是我区别普通 recommendation 的关键。 | EvidenceLedger、ReviewDecision |
| P0 | Mission Workspace + Runtime Timeline | 让后端真正已经存在的能力第一次被用户看见。 | /events、/evidence、/review、/status |
| P0 | Replay / canonical missions | 同时解决比赛稳定、调试和 Eval。 | 现有 trace / logs / state version |
| P1 | Research Genome v0 | 让项目从“任务工具”获得长期用户状态。 | Profile + Artifact + Evidence |
| P1 | Gap model + Counterfactual UI | 形成真正抓眼球、且属于我自己的产品机制。 | 匹配评分、方向图、Genome |
| P1 | Mission Forge | 把建议变成真正行动，连接课程、研究、导师三个场景。 | TaskPlan / workflow builder |
| P1 | Unified multimodal intake | 语音/PDF/URL/图片作为同一 Mission 输入，而不是继续扩独立页面。 | 现有 PDF/Chat |
| P2 | Skill extraction + Tool Registry | 让系统逐渐从“每次 Agent 探索”演化到“已知流程自动固化”。 | tool layer / browser integrations |
| P2 | Research Pack / Commons | 这是开源项目形成社区贡献面的关键。 | 等 core primitive 稳定后开放 |

### 哪些事情现在反而不应该优先

- 不为了“多 Agent”继续增加固定角色数量。

- 不继续新建 PDF / Voice / Browser 等独立功能页。

- 不把私有 chain-of-thought 做成所谓透明推理；展示结构化事件、证据、状态和决策摘要即可。

- 不先做一个巨大的通用 Agent OS；我的差异应该扎在科研成长和可验证 Mission。

- 不把 3D 图当作单独创新点；只有它能表达 Genome / Claim / Mission / Replay 时才值得继续投入。

- 不因为比赛追求“全 live”而牺牲可靠性；真实 Runtime Event 可 replay，比现场 loading 三分钟更专业。

**现在最值得保留的一句话：**
比赛版应该是这个开源项目最小但完整的一次自证，而不是比赛结束后需要全部推翻的临时拼装。

14 / FINAL POSITION

## 我为什么做这个

因为今天的问题已经不是“AI 能不能帮学生搜到一个老师”。搜索、总结、聊天、推荐都越来越廉价。真正困难的是：一个刚进入科研的人往往不知道自己的能力到底在哪里，不知道一个目标为什么离自己远，不知道下一步应该做什么才真正改变状态，也很难把自己过去做过的项目、课程、失败实验和读过的论文积累成一个能够持续使用的科研模型。

与此同时，Agent 自己也有类似问题：每次任务都重新搜索、重新踩坑、重新生成一份不可复用的聊天记录。大量优秀项目分别解决了浏览器操作、工作区、协作、多 Agent、记忆、Evidence、Human-in-the-loop、Replay、Skill 等局部问题。我看完这些项目后真正想尝试的，是把这些成熟思想重新组织到一个新的长期循环里：

人：
经历 → 证据 → Research Genome → Gap → Mission → Artifact → 成长

Agent：
未知 → 探索 → Trace → Verification → Skill → 更稳定的下一次执行

社区：
Mission → Fork → Pack → Eval → Negative Knowledge → 累积

如果这个循环能够跑起来，那么它不再只是“一〇七杯项目”。比赛只负责证明第一件事：这套系统确实可以从真实用户材料出发，理解一个科研目标，发现关键缺口，用可验证的 Agent 工作流完成研究，并给出一条能让用户状态发生改变的下一步。

**我现在希望队伍对齐的核心：**接下来讨论一个功能要不要加时，不再问“它酷不酷”，而问三件事：

① 它有没有让 Research Mission 更可执行、更可信或更可积累？

② 它有没有让“人的科研状态发生变化”这条主线更强？

③ 它未来能不能成为社区可以 Fork、扩展或贡献的资产？

三条都没有，它很可能只是装饰。

REFERENCES / REPRESENTATIVE SOURCES

## 这份报告使用的主要外部证据

- [GitLab AI Hackathon 2026 — Meet the winners](https://about.gitlab.com/blog/gitlab-ai-hackathon-2026-meet-the-winners/)：近 7000 developers、600+ agents/flows、LORE、43 tests、评委反馈。

- [ETHGlobal New York 2025 — Judging details](https://ethglobal.com/events/newyork2025/info/details)：4 分钟 Demo + 3 分钟 Q&A；Technicality / Originality / Practicality / Usability / WOW Factor。

- [RAISE YOUR HACK Live Dashboard](https://lablab.ai/ai-hackathons/raise-your-hack/live)：6246 participants、919 teams、223 projects 以及技术使用分布。

- [Deptheon AI — Devpost](https://devpost.com/software/deptheon-ai)：web research → voice call → email 的长任务 Demo 与状态管理。

- [Glider — ETHGlobal](https://ethglobal.com/showcase/glider-zr9bd)：Browser Agent 自动执行 + 用户最终签名控制。

- [MintCondition — ETHGlobal](https://ethglobal.com/showcase/mintcondition-8kqc4)：多个模型意见、confidence 和透明 consensus。

- [Geneva — ETHGlobal](https://ethglobal.com/showcase/geneva-n0oc3)：通过 GitHub Discussions / Issues / PR / Wiki 组织 Agent swarm。

- [browser-use/browser-use](https://github.com/browser-use/browser-use)：真实浏览器 action space、benchmark、开放 Agent runtime。

- [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands)：Agent Canvas、execution environment、automation、self-hosted developer workspace。

- [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop)：multimodal Agent、Hybrid Browser Agent、MCP、Event Stream。

- [humanlayer/12-factor-agents](https://github.com/humanlayer/12-factor-agents)：own control flow、unify state、pause/resume、small focused agents。

- [getzep/graphiti](https://github.com/getzep/graphiti)：temporal context graph、fact validity、episode provenance、incremental updates。

- 内部调研记录：《一〇七项目：2024–2026 Agent / Hackathon 案例库与融合解构（第一轮）》：355 条原始候选、32 个机制级精选案例以及现有代码审查。

说明：黑客松并非都公开评委原始评论。报告只在官方页面明确给出评语时引用；其余以官方获奖结果、项目自述、公开仓库与社区讨论为依据。模拟团队讨论均为我基于这些公开设计哲学做的内部设计推演。

107 → OPEN RESEARCH

内部队伍讨论稿 · 目标：把比赛原型推进成一个真正值得长期维护的开放科研 Agent 项目。

