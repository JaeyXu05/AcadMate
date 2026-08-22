# AGENTS.md — 【B】cloud3d/ 3D 星图数据生成（详述）

> 本文件描述 B 模块代码现状，供所有 AI 编码助手共用。跨模块向导见根 `AGENTS.md`。
> **不含协作规则**（见根 `CLAUDE.md`）。数据基准：2026-08-21 通读，2026-08-22 更新。
>
> ✅ 2026-08-22 已完成：`HANDOVER.md` 重写为与代码一致；`cloud_data.json` 重生成。

B 把 RAG 库的 715 导师按研究领域映射成 10 个领域，生成多臂对数螺旋银河盘布局的 3D 坐标，输出 `cloud_data.json` 供 D 的 `CloudGraph.tsx` 渲染。**B 现在只是数据生成模块，不含前端**——真正的 3D 渲染在 D。

## 目录现状

```
cloud3d/
├── build_cloud.py          # ★ 数据生成脚本（当前源码 = 真相）
├── cloud_data.json         # ✅ 已重生成，与 build_cloud.py 一致
├── cloud_data.json.bak_old # 旧版备份（26-galaxy 布局），兜底可删
├── HANDOVER.md            # ✅ 已重写为与代码一致
└── AGENTS.md              # 本文件
```

## `build_cloud.py`（当前源码 = 真相）

### 领域映射

把每位导师按 `department + research_topics + methods` 关键词映射到 **10 个研究领域**（`DOMAINS`，id 如 `physics_quantum / cs_ai / ...`，各带颜色与 keys）。

### 多臂对数螺旋银河盘布局

| 参数 | 值 | 旧文档（错） |
|---|---|---|
| **`N_ARMS`** | **4** | HANDOVER 写 6（旧版） |
| `R_IN` / `R_OUT` | 170 / 540 | — |
| `TURNS` | 1.4 | — |
| 目标半径范围 | **`R_CORE_EDGE=250 → R_RIM_EDGE=460`**（`target_radius(rank)=250 + rank/9*(460-250)`） | 旧文档 205→470 |
| 分臂 | **`ARM_BY_RANK` = 3+3+2+2**（10 领域按人口降序 rank=0..9 分到 4 臂） | 旧文档均匀角 `rank*(360/10)`、`best_arm_t()`（当前代码**无此函数**） |

### 视觉参数

- `thickness(jt) = 26 → 13`（内厚外薄）
- `core_lum = (1-r_norm)^1.6`（中心 1.0 → 外缘 0）
- `lum = 0.55 + 0.45*min(1, score)`（∈[0.55, 1.0]）
- `size ∈ [1.0, 3.5]`
- `random.seed(42)`（确定性可复现）

### 输入输出

- **输入**：`../paper-claw-master/data/ustc_mentor_rag.json`
- **输出**：`cloud_data.json`，结构 `{meta, nodes}`（**无 edges**——边由 D 在请求时动态生成）：
  - `meta`：`title / generated_at / source_chain / mentor_count / evidence_count / domain_count / departments / legend[10] / camera{target, radius:1500, r_out, r_in, arms:4} / layout{galaxy_spacing:540, cloud_scale:70, disk_radius:540, arms:4}`
  - `nodes[]`（20 字段）：`candidate_id, name, department, affiliation, domain, domain_name, secondary, color, lum, core_lum, size, x, y, z, topics, methods, pub_count, pubs, homepage, recruitment`

## ✅ cloud_data.json 已重生成（历史 bug 已修复）

磁盘 `cloud_data.json` 曾由**旧版生成器**产出，结构与当前代码**不一致**，导致 D 的
`/api/cloud/graph` 返回 `legend:[]` / `domain_count:0`，云图领域图例为空。现已重跑
`py build_cloud.py` 修复（旧版备份为 `cloud_data.json.bak_old`）。

- 重生成命令：`cd cloud3d && py build_cloud.py`（每次都会重读最新 RAG 库）。
- RAG 库更新后需**重跑此命令**（输入 `../paper-claw-master/data/ustc_mentor_rag.json`）。
- 同域星座边由 D 的 `cloud.ts` 在请求时动态生成（按 `domain` 分组、每人连同域内最近邻 1 条、
  `MAX_PER_DOMAIN=400`、`relation:"same-field"`），**不在 cloud_data.json 里**。

## 与其它模块的关系

- **输入**：读 C 的 `data/ustc_mentor_rag.json`（715 导师）。
- **输出**：`cloud_data.json` 被 D 的 `Code/server/routes/cloud.ts` 消费 → `GET /api/cloud/graph` → D 的 `CloudGraph.tsx`（Three.js）渲染。
- **ID 关联**：`nodes[].candidate_id` ⇔ RAG `candidate_id` ⇔ D `Advisor.id`，必须一致。
- **关于 `CloudGraph.tsx` 的 `arms:6`**：D 的 `CloudGraph.tsx` 用 `SPIRAL={r_in:170, r_out:540, turns:1.4, arms:6}` 画背景装饰星尘，**此 `arms:6` 仅为背景装饰，与 B 的节点布局 `N_ARMS=4` 无关**——非功能 bug，仅观感上的数字不一致，可择机统一。

## 已知缺口

- `cloud3d/cloud_data.json.bak_old` 旧备份可删（仅兜底）。
- D 的 `CloudGraph.tsx` 背景装饰 `arms:6` 与 B 布局 `N_ARMS=4` 不一致（仅观感，非功能 bug，可择机统一）。
