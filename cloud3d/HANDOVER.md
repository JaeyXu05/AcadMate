# 中科大导师 3D 研究星图 —— 交接文档

## 项目背景（大意保持不变）

Paper Claw 的 `mentor_workflow` 内部 RAG 库（`data/ustc_mentor_rag.json`，715 位导师 / 1580 条证据）
已经建成。为让用户更直观地浏览导师分布，在 RAG 库之上构建了一个 **3D 导师研究星图可视化**：
每个导师是一颗星，按研究方向聚类成多个独立「星系」，可拖拽/缩放/旋转浏览，
点击星星查看研究方向、论文、主页、招生信息等详情。

当前的重点任务已经从「抓取数据构建 RAG」转移到「基于已有 RAG 库做 3D 可视化」，
视觉重点从「识别导师个体」进一步演化为「营造真实银河系观感」（旋臂、星尘、星云、中央亮核）。

## RAG 数据接口格式（保持不变，星图的数据源头）

`data/ustc_mentor_rag.json`（在 `../paper-claw-master/data/`）是本可视化的唯一数据源，结构为：

```json
{
  "generated_at": "…",
  "source_chain": ["internal_ustc_rag"],
  "mentor_count": 715,
  "evidence_count": 1580,
  "candidates": [ … ],   // 715 位导师
  "evidence":   [ … ]    // 1580 条证据
}
```

`candidate` 关键字段（供 3D 表达使用）：
- `candidate_id`、`mentor_name`、`affiliation`、`department`（45 个学院/系）
- `research_topics`（研究方向，500 位有）、`methods`（方法，39 位有）
- `publications`（论文标题，231 位有）、`homepage`、`recruitment_status`、`evidence_refs`

`evidence` 关键字段：`candidate_id`、`source_type`、`source_uri`、`extracted_fact`、
`confidence`、`freshness`、`metadata`（含 `identity_verified`、`mentor_role_verified`）。

> 内部 RAG 召回协议 `InternalMentorRag.retrieve(intent, domain_judgements)`（后端工作流用）
> 与本可视化无关，保留在 `data_scripts/internal_mentor_rag.py` 未改动。

## 数据流（重要：数据分离、每次生成读最新库）

```
data/ustc_mentor_rag.json   (RAG 库，可能随时更新；在 ../paper-claw-master/data/)
        │  py build_cloud.py   ← 每次运行都重新读取当前库
        ▼
cloud3d/cloud_data.json   (生成与展示分离，接口稳定)
        │  fetch
        ▼
Code/src/components/CloudGraph.tsx   (Three.js 渲染，正式前端即此组件)
```

## 本目录当前文件结构（cloud3d/）

```
cloud3d/                     ← 独立 3D 数据模块目录（不改动 paper-claw-master/data 下任何文件）
  HANDOVER.md                ← 本交接文档
  AGENTS.md                  ← 本模块给代码助手的工作约定
  build_cloud.py             # 数据生成脚本（每次运行重新读最新 RAG 库 → 布局/坐标/配色）
  cloud_data.json            # 预计算的可视化数据（生成脚本产出，接口稳定）
  cloud_data.json.bak_old    # 旧版备份（26-galaxy 旧布局，重新生成前的兜底，可删）
```

> **注意**：原本的独立演示前端（`index.html` / `server.js` / `start_starmap.bat` /
> `OPEN_STARMAP.bat` / `.previews/`）已移除。真正的星图前端在 D 模块的
> `Code/src/components/CloudGraph.tsx`，通过后端的 `GET /api/cloud/graph` 接口消费本目录
> 产出的 `cloud_data.json`。本目录只负责「生成数据」，不负责「渲染」。

## cloud_data.json 接口（新会话接手者需掌握）

```json
{
  "meta": {
    "title": "中国科学技术大学 · 导师研究星图",
    "generated_at": "…", "mentor_count": 715, "evidence_count": 1580,
    "domain_count": 10,
    "departments": [ … ],          // 学院列表
    "legend": [ {id,name,color,count}, … ],  // 10 个研究领域 + 配色
    "camera": { "target":[0,0,0], "radius":1500, "r_out":540, "r_in":170, "arms":4 },
    "layout": { "galaxy_spacing": 540, "cloud_scale": 70, "disk_radius": 540, "arms": 4 }
  },
  "nodes": [
    {
      "candidate_id", "name", "department", "affiliation",
      "domain", "domain_name", "secondary",
      "color",        // 领域色
      "lum",          // 相对亮度 0.55~1.0（研究方向/论文多的更亮）
      "core_lum",     // 径向亮度因子 0~1，越靠中心亮核越大
      "size",         // 星星大小（同上的丰富度）
      "x","y","z",    // 预计算 3D 坐标
      "topics","methods","pub_count","pubs","homepage","recruitment"
    }, …
  ]
}
```

> `edges` 边数据 **不在** `cloud_data.json` 里。同域（星座）连线由 D 的
> `Code/server/routes/cloud.ts` 在请求时动态生成（同域最近邻连线），前端组件据此渲染。
> 正式前端只需加载 `/api/cloud/graph` 返回的 `{meta, nodes, edges}`，不依赖本目录生成逻辑。

## 布局算法（build_cloud.py，纯 Python 标准库，无 numpy/scipy 依赖）

- 每个导师按 `department + research_topics + methods` 关键词映射到 **10 个研究领域**（domain）。
- **多臂对数螺旋银河盘布局**：
  - 4 条对数螺旋悬臂（`N_ARMS=4`，每臂缠绕 1.4 圈 `TURNS`），螺旋盘内径 `R_IN=170` / 外径 `R_OUT=540`。
  - **人口中心化**：10 领域按人口降序 `rank=0..9`，目标半径 `target_radius(rank) = R_CORE_EDGE(250) + frac*(R_RIM_EDGE(460) - R_CORE_EDGE(250))=250→460`（人口越多越靠内）。
    方位角由 `ARM_BY_RANK`（10 领域按 3+3+2+2 分配进 4 条臂）+ `spiral_phase(arm)=arm*2π/4` 决定，
    不再使用旧的"均匀角 rank*(360/10)"。
  - 半径反解螺旋参数：`tc = log(r_des/R_IN) / log(R_OUT/R_IN)`，
    存入 `ARM_PLAN[dom_id] = (arm, tc, seg, trans)`。
  - 每个领域沿其悬臂的一段**窄径向带**聚集（云团高斯式聚在 `tc` 中心），
    分割清晰，min 质心间距约 140，互不重叠。
  - **Y 向透镜状厚度** `thickness(t)=26→13`，轴向约 ±70，中央鼓、边缘收，
    扁平盘带明显 3D 弧面感。
  - 每个 node 带 `core_lum = (1 - r_norm)^1.6`（r_norm 为径向归一），前端用它做「越近越亮」调色。
- 布局全部手写标准库，`random.seed(42)` 固定可复现。

> **4 臂 vs 6 臂**：`build_cloud.py` 的 `N_ARM=4` 是导师布点用的；D 前端
> `CloudGraph.tsx` 里背景星尘的 `SPIRAL.arms:6` 是纯装饰参数，不影响布点（已知 cosmetic
> 差异，非 bug）。若要让背景星尘与布点臂数一致，可单独在 D 前端把 `arms` 改回 4。

## 运行方式

```bash
# 数据更新后重生成可视化数据（每次都会重读最新 RAG 库）
cd cloud3d
py build_cloud.py          # 读取 ../paper-claw-master/data/ustc_mentor_rag.json → cloud_data.json
```

生成产物 `cloud_data.json` 由 D 后端 `cloud.ts` 读取（路径见 D 侧配置），前端
`CloudGraph.tsx` 经 `GET /api/cloud/graph` 消费。**本目录无需再起独立静态服务**。

## 验证手段（沿用，便于回归）

- 数据：`py build_cloud.py` 应幂等成功，`{meta, nodes}` 结构完整，
  `mentor_count=715`、`domain_count=10`、`legend=10`、坐标全有限、全部 node 含 `core_lum`。
- 布局：半径随人口单调、角距均匀、质心最小间距≈140。
- 前端：D 模块 `CloudGraph.tsx` 加载 `/api/cloud/graph` 后渲染 715 节点、
  10 个领域 legend，`focus` 聚焦流程正常、无 JS console 错误。

## 相关脚本清单

```
cloud3d/        （3D 星图数据，当前工作，本模块）
  build_cloud.py            # 读 RAG 库 → 生成 cloud_data.json（银河盘布局/配色/坐标）

Code/src/components/CloudGraph.tsx   # 前端渲染（Three.js，D 模块）
Code/server/routes/cloud.ts          # 后端 /api/cloud/graph（读 cloud_data.json + 生成同域 edges）

paper-claw-master/data_scripts/   （RAG 库构建，已完成，仅需在数据更新时重跑）
  build_rag.py              # 组装 RAG 库（产出 ustc_mentor_rag.json）
  internal_mentor_rag.py    # 后端 RAG 召回协议实现
  ustc_scraper.py 等爬虫    # 官网/论文抓取
```

## 后续可能的扩展（尚未做）

1. 导师名字已按用户要求去掉；如未来需要可按需加回（此前按相机距离分级淡入的 LOD 逻辑已被移除，需重做）。
2. 可加搜索框/按学院筛选/星座连线开关。
3. 论文平台多源（OpenAlex + S2 + DBLP）已汇总进 RAG 库，星图可加「合作网络/共著连线」。
4. 正式前端已接 D 的 CloudGraph.tsx；`cloud_data.json` 接口稳定，无需重复开发。
