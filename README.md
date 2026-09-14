# AcadMate · 自进化科研助手

AcadMate 是一个面向科研入门者的**自进化科研助手**。它记录你真实做过什么，理解你目前在哪，把一个模糊的科研目标变成可执行、可验证的任务，并在任务结束后让人获得新的能力证据、让 Agent 获得新的可复用技能。

它从一个校内比赛的获奖作品起步，现在正演进为一个不局限于任何学校的开源项目。

## 它解决什么问题

科研入门真正的困难，往往不是"读论文"，而是：

- **我是谁**——我做过什么、真正会什么、哪些只是看过、哪些有证据？
- **我想去哪**——通常只有一个模糊目标，不知道自己离它差什么。
- **下一步做什么**——普通 AI 容易给"读论文、学基础、做项目"这类正确但无用的建议，却很难告诉你哪一个动作最值得做、会补哪个缺口、做完怎么验证。
- **做过的事为什么总重新开始**——一次调研、一次复现、一次踩坑之后，往往只剩一段聊天记录。

AcadMate 用"多智能体工作流 + 证据审核"来回应这些问题：多个智能体分工完成意图理解、领域研究、导师调研、证据审核与结果表达，保证每一步有证据、可解释、可复盘，而不是把问题一次性丢给模型。

## 核心能力

- **导师检索工作流**：意图理解 → 规划 → 领域专家 → 导师调研 → 匹配 → 证据审核 → 结果撰写。可在确定性模式下离线运行，不依赖模型 Key；也可开启模型推理模式。
- **证据审核**：独立审核角色检查意图完整性、身份核验、证据引用闭环、论文时效与结论一致性；审核不通过按指定阶段返工。八维匹配分涵盖研究方向、方法、应用、活跃度、学生背景、约束、招生意愿与证据完整度。
- **论文阅读与 PDF 分析**：PDF 页级语义召回、可选模型结构化重排、导师匹配与证据审核；多篇合并分析，每条结论绑定 PDF 页码证据。
- **科研伴学**：科研画像（能力、方向、缺口、下一步）、计划拆解与提醒、日报/周报/月报、导师联系邮件、Zotero 文献同步、3D 研究星图。
- **可恢复运行时**：类型化状态、事件总线、重试控制器与乐观锁，支持任务中断后继续与审计轨迹回放。
- **本地优先与隐私**：模型 API Key 按账号加密保存、接口不回传明文；支持无模型 Key 的确定性离线运行。

## 不内置任何特定高校的导师数据

本项目**不在仓库中内置任何特定高校的导师数据**。运行时导师知识库 `paper-claw-master/data/ustc_mentor_rag.json` 当前是一个空的合法骨架。

- 空库下，导师检索会返回明确的"无匹配"结果，而不是虚构导师；推荐、详情等接口返回明确的"数据源不可用"，不崩溃。
- 如需启用导师检索，请通过数据流水线接入目标机构的导师列表，详见 [`paper-claw-master/data_scripts/README.md`](paper-claw-master/data_scripts/README.md)。流水线坚持"没有证据就不能推荐"。
- 接入数据后，重新运行 `cloud3d/build_cloud.py` 生成星图，并运行 `node scripts/verify-runtime-data.mjs` 确认 RAG 与星图节点一致。

> 已知遗留：后端导师工作流中仍保留一个向中科大官网实时抓取的兜底检索源（`paper-claw-master/backend/src/backend/mentor_workflow/ustc_sources.py`）。它在本地 RAG 召回为空时被触发。后续版本会将其替换为机构无关的检索源；在此之前，若不需要该行为，可按 `data_scripts/README.md` 接入自有数据后以本地 RAG 召回为主。

## 目录

- `Code/`：用户主站。React 18 前端通过 Express BFF 访问 SQLite 用户数据、导师 RAG 和 A 端智能体。
- `paper-claw-master/backend/`：FastAPI + PostgreSQL 后端，提供导师工作流、通用 Agent/Harness、论文处理、报告和 arXiv 任务。
- `paper-claw-master/frontend/`：Paper Claw 独立管理前端，用于直接查看 A 端内部对象，不是主站入口。
- `paper-claw-master/data_scripts/`：导师数据抓取、清洗、人工裁决辅助、RAG 构建与质量验证，以及接入任意机构导师列表的入口。
- `paper-claw-master/data/ustc_mentor_rag.json`：运行时导师知识库（当前为空骨架）。
- `cloud3d/`：从 RAG 生成主站 3D 星图所需的 `cloud_data.json`；渲染在 `Code/src/components/CloudGraph.tsx`。
- `scripts/`：Windows 环境准备、启动、运行时数据校验和首次使用冒烟测试。
- `docs/`：架构报告与[路线图](docs/roadmap.md)。

跨模块导师主键是 `candidate_id`。修改这一格式必须同步 RAG、A 端、D 端和星图数据。

## 快速开始（Windows）

仓库自带面向单台 Windows 主机的一键部署链路。要求 Node.js `>=22.12.0`、uv 管理的 Python 3.12+ 和 Docker Desktop。

1. 首次运行或依赖更新后执行 `检查启动环境.bat`，准备依赖、启动 PostgreSQL、执行迁移并预热本地向量索引。
2. 日常启动执行 `启动项目.bat`。启动器会校验数据、启动服务并验证 A 后端、D 后端和前端。

默认地址：

- 主站：`http://127.0.0.1:5173`
- Express BFF：`http://127.0.0.1:3001`
- Paper Claw API：`http://127.0.0.1:8000`

详细启动参数和故障定位见 `一键启动说明.md`。模型 API 对确定性导师检索不是必需项；需要模型的功能可在登录后的 API 设置页按用户配置。非 Windows 环境目前没有等价一键脚本，需按同一进程与环境变量契约自行编排。

## 配置

两份 `.env.example` 是配置来源，首次启动会自动复制为本机 `.env` 并生成随机密钥：

- `Code/.env.example`：D 端端口、CORS、JWT 密钥、邮件凭据加密密钥、A 端地址、SMTP/IMAP。
- `paper-claw-master/.env.example`：数据库、OpenAI 兼容对话模型（Base URL / Model / API Key 由部署或用户配置，不绑定供应商）、arXiv/OpenAlex、本地多语种向量模型（`BAAI/bge-small-zh-v1.5`，FastEmbed 加载，默认走 `hf-mirror.com` 镜像）。

## 验证

```powershell
cd Code
npm run check
npm test
npm run build

cd ..\paper-claw-master\backend
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest -q

cd ..\..\cloud3d
py -m unittest -v test_build_cloud.py

cd ..\paper-claw-master\data_scripts
py test_data_quality.py
py verify_rag.py
```

完整的当前架构、调用链、状态机、数据契约、存储与失败路径见 [`docs/CODE_LOGIC_REPORT.md`](docs/CODE_LOGIC_REPORT.md)。

## 路线图

项目的长期方向是开放式个人科研成长系统：Research Genome（科研能力画像）、Counterfactual Research Navigator（反事实方向导航）、Mission Forge（差距生成可验收任务），以及 Forkable Mission、Skill Evolution、Research Pack、Negative Knowledge 等社区可贡献形态。详见 [`docs/roadmap.md`](docs/roadmap.md)。

## 贡献

欢迎代码、数据，以及更高形态的贡献——Research Pack、Skill、Forkable Mission、失败经验。详见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 许可证

本项目基于 [GPL-3.0](LICENSE) 许可证开源。
