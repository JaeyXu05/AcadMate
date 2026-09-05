# 科研导师推荐与科研伴学平台

本仓库的可运行产品由一套 React/Express 主站、Paper Claw FastAPI 智能体后端、导师 RAG 数据流水线和 3D 星图数据构建器组成。代码、配置和测试是当前行为的唯一事实来源。

## 目录

- `Code/`：用户主站。React 18 前端通过 Express BFF 访问 SQLite 用户数据、导师 RAG 和 A 端智能体。
- `paper-claw-master/backend/`：FastAPI + PostgreSQL 后端，提供导师工作流、通用 Agent/Harness、论文处理、报告和 arXiv 任务。
- `paper-claw-master/frontend/`：Paper Claw 独立管理前端，不是主站入口。
- `paper-claw-master/data_scripts/`：官网与论文平台数据抓取、清洗、人工裁决辅助、RAG 构建和质量验证。
- `paper-claw-master/data/ustc_mentor_rag.json`：运行时导师知识库。
- `cloud3d/`：从同一 RAG 数据生成主站星图所需的 `cloud_data.json`。
- `scripts/`：Windows 环境准备、启动、运行时数据校验和首次使用冒烟测试。
- `docs/future/`：未承诺实现的产品研究与未来规划；不代表当前代码。
- `比赛材料/`：比赛提交材料。

跨模块导师主键固定为 `candidate_id`（`ustc_faculty_<faculty_id>`）。修改这一格式必须同步 RAG、A 端、D 端和星图数据。

## Windows 启动

首次运行或依赖更新后执行 `检查启动环境.bat`，日常启动执行 `启动项目.bat`。启动器会校验数据、准备依赖、启动 PostgreSQL、执行迁移，并验证 A 后端、D 后端和主前端。

默认地址：

- 主站：`http://127.0.0.1:5173`
- Express BFF：`http://127.0.0.1:3001`
- Paper Claw API：`http://127.0.0.1:8000`

详细启动参数和故障定位见 `一键启动说明.md`。模型 API 对确定性导师检索不是必需项；需要模型的功能可在登录后的 API 设置页按用户配置。

## 验证

```powershell
cd Code
npm run check

cd ..\paper-claw-master\backend
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest -q

cd ..\..\cloud3d
py -3.13 -m unittest -v test_build_cloud.py

cd ..\paper-claw-master\data_scripts
py -3.13 test_data_quality.py
py -3.13 verify_rag.py
```

完整的当前架构、调用链、状态机、数据契约、存储与失败路径见 `docs/CODE_LOGIC_REPORT.md`。
