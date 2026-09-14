# 贡献指南

感谢你考虑为 AcadMate 贡献力量。本项目正在从一项校内比赛的获奖作品，演进为一个**自进化科研助手**：它记录你真实做过什么，理解你目前在哪，把模糊的科研目标变成可执行、可验证的任务，并在任务结束后让人获得新的能力证据、让 Agent 获得新的可复用技能。

这意味着我们欢迎的不只是改 bug 或补 UI——我们同样欢迎你贡献一整个研究领域、一条任务路径、一个工具能力，甚至一次失败经验（详见 [路线图](docs/roadmap.md) 中的 Research Pack / Skill Evolution / Negative Knowledge）。

## 在开始之前

1. **代码、迁移和运行时数据是唯一事实来源。** 仓库根目录的 `AGENTS.md` 是编码约束入口，`docs/CODE_LOGIC_REPORT.md` 是完整的当前架构与调用链。说明文档不覆盖代码事实；当你发现文档与代码冲突，以代码为准并在 PR 中指出。
2. **先读再改。** 修改前先读相关调用链与测试，做最小、可回退的改动。不要为了"整洁"做无关重构。
3. **保持数据契约稳定。** 跨模块统一主键是 `candidate_id`。如果你要调整 ID 形态，必须同步 RAG、A 端返回值、D 端详情接口和星图节点——这是四个模块的硬契约。

## 项目结构速览

| 目录 | 角色 |
|---|---|
| `Code/` | D 主站：React 18 前端 + Express BFF + SQLite（用户域） |
| `paper-claw-master/backend/` | A 智能体后端：FastAPI + PostgreSQL/pgvector，导师工作流 + 通用 Agent/Harness |
| `paper-claw-master/data_scripts/` | C 数据流水线：抓取、核验、去重、生成 RAG，以及接入任意机构导师列表的入口 |
| `cloud3d/` | B 星图数据生成器：从 RAG 生成 `cloud_data.json`，渲染在 D 端 `CloudGraph.tsx` |
| `scripts/` | Windows 一键启动、环境准备、运行时数据校验、新用户冒烟测试 |
| `docs/` | 架构报告与路线图 |

## 开发环境

仓库自带面向单台 Windows 主机的一键部署链路：先运行 `检查启动环境.bat`，再运行 `启动项目.bat`。首次运行或依赖更新后执行前者，日常启动执行后者。启动器会校验运行时数据、准备依赖、启动 PostgreSQL、执行迁移，并验证 A 后端、D 后端和前端。

- Node.js `>=22.12.0`（D 端依赖 `better-sqlite3@13`）
- uv 管理的 Python 3.12+（A 端）
- Docker Desktop（PostgreSQL）

非 Windows 环境目前没有等价一键脚本，需要按同一进程与环境变量契约自行编排。

## 验证

提交前请运行与你改动相关的验证：

```powershell
# D 端（主站类型检查、构建、测试）
cd Code
npm run check
npm test
npm run build

# A 端（导师工作流与后端，需 Docker PostgreSQL）
cd ..\paper-claw-master\backend
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest -q

# B 星图
cd ..\..\cloud3d
py -m unittest -v test_build_cloud.py

# C 数据流水线（接入导师数据后）
cd ..\paper-claw-master\data_scripts
py test_data_quality.py
py verify_rag.py
```

## 提交规范

- 一个 PR 解决一个问题。改动小、可审查、可回退。
- commit message 用中文或英文均可，但要写清楚"做了什么"和"为什么"。避免只写 "fix" 或 "update"。
- 不要在 PR 里夹带与主题无关的格式化或重构。
- 不要硬编码密钥、机器路径、模型名或模拟数据。
- 区分仓库配置 `.codex/agents` 与产品代码中的 `backend/.../agents`；后者是运行时功能，不是助手配置。

## 数据贡献（重要）

本项目**不内置任何特定高校的导师数据**。`paper-claw-master/data/ustc_mentor_rag.json` 当前是一个空的合法骨架，运行时导师检索在空库下会返回明确的"无匹配"结果，而不是虚构导师。

如果你想让某个机构的导师数据可用：

1. 阅读 [`paper-claw-master/data_scripts/README.md`](paper-claw-master/data_scripts/README.md)，了解如何为任意机构接入导师列表与论文证据。
2. 数据流水线坚持"没有证据就不能推荐"：每位入库导师必须有官方身份/角色链，论文只能补充方向、不能反向证明身份，每条结论必须绑定证据引用。
3. 重建 RAG 后，重新运行 `cloud3d/build_cloud.py` 生成星图，并运行 `verify_rag.py` 与根目录 `node scripts/verify-runtime-data.mjs` 确认 RAG 与星图节点一致。

## 社区贡献的更高形态

除了代码与数据，我们尤其欢迎这些与"自进化"定位直接相关的贡献（详见 [路线图](docs/roadmap.md)）：

- **Research Pack**：为某个领域贡献数据源、领域术语、Evidence Rules、典型任务与 Eval cases。
- **Skill**：把一条稳定可复用的 Agent 轨迹提炼成可复用技能。
- **Forkable Mission**：把一次成功的科研任务沉淀成别人可以直接复制的模板。
- **Negative Knowledge**：记录哪个网页长期失效、哪个 repo 无法复现、哪条路线已被验证无效，让后来者不必重复踩坑。

## 行为准则

请保持尊重、专业、对事不对人。我们期望一个对科研新手友好的社区——很多贡献者可能正是这个项目想要服务的、刚刚踏入科研的人。
