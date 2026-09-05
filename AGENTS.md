# AGENTS.md

本文件是仓库内编码助手唯一的项目约束入口。项目说明以代码、迁移和磁盘数据为准；完整代码逻辑见 `docs/CODE_LOGIC_REPORT.md`。

## 真实架构

- `Code/src`：React 18 主站；`Code/server`：Express BFF、SQLite 用户数据、SSE 代理、邮件、PDF、报告与计划。
- `paper-claw-master/backend`：FastAPI、PostgreSQL/pgvector、多智能体运行时与导师工作流。
- `paper-claw-master/data_scripts`：导师抓取、清洗、审核与 RAG 构建。
- `cloud3d/build_cloud.py`：星图数据生成；渲染代码在 `Code/src/components/CloudGraph.tsx`。
- `paper-claw-master/data/ustc_mentor_rag.json`：当前检索数据；`cloud3d/cloud_data.json`：当前星图数据。

四模块以 `candidate_id` 关联。任何 ID 形态调整都必须同步 RAG、A 返回值、D 详情接口和星图节点。

## 当前数据契约

- RAG：972 位导师、1969 条证据；660 位导师有非空 `research_topics`。
- 星图：972 个节点，与 RAG 的 `candidate_id` 集合完全一致。
- A 的导师匹配默认走确定性模式；模型增强由 `PAPER_CLAW_MENTOR_WORKFLOW_MODEL_REASONING_ENABLED` 显式开启。
- D 通过 `/api/agent/chat` 创建并轮询 A 的 run，再映射为前端 `Advisor`；详情、推荐、邮件和 PDF 均使用真实 RAG/工作流数据。

## 修改边界

- 先读调用链和测试，再做最小改动；不得用说明文档覆盖代码事实。
- 保持 A/C/B 输出 schema 与 `candidate_id` 稳定。前端需要不同字段时，在 `Code/src/services` 或 `Code/server/routes` 映射。
- 不把确定性逻辑无故改成模型调用，不硬编码密钥、机器路径、模型名或模拟数据。
- 区分仓库配置 `.codex/agents` 与产品代码中的 `backend/.../agents`；后者是运行时功能，不得当作助手配置清理。
- 运行数据默认写入 `Code/data.db`、`Code/data`、`Code/generated`、PostgreSQL volume 与 `paper-claw-master/data/files`，部署迁移时需一并备份。

## 验证基线

- D：在 `Code` 运行 `npm test` 与 `npm run build`。
- A：在 `paper-claw-master` 运行 `uv run --project backend pytest backend/tests`。
- C：按需运行 `backend/.venv/Scripts/python.exe data_scripts/verify_rag.py`。
- B：在 `cloud3d` 运行 `py build_cloud.py`，随后执行根目录 `node scripts/verify-runtime-data.mjs`。
- Windows 新机：先运行 `检查启动环境.bat`，再运行 `启动项目.bat -RunSmoke`。
- D 端依赖 `better-sqlite3@13`，因此 Node.js 要求为 `>=22.12.0`。

保留用户已有修改，避免无关重构；删除文件前确认它不是产品入口、动态导入、迁移、生成源或测试契约。
