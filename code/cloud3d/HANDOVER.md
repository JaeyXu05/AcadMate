# 中科大导师 3D 研究星图 —— 交接文档

## 项目背景（大意保持不变）

Paper Claw 的 `mentor_workflow` 内部 RAG 库（`data/ustc_mentor_rag.json`，715 位导师 / 1523 条证据）
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
  "evidence_count": 1523,
  "candidates": [ … ],   // 715 位导师
  "evidence":   [ … ]    // 1523 条证据
}
```

`candidate` 关键字段（供 3D 表达使用）：
- `candidate_id`、`mentor_name`、`affiliation`、`department`（45 个学院/系）
- `research_topics`（研究方向，437 位有）、`methods`（方法，39 位有）
- `publications`（论文标题，231 位有）、`homepage`、`recruitment_status`、`evidence_refs`

`evidence` 关键字段：`candidate_id`、`source_type`、`source_uri`、`extracted_fact`、
`confidence`、`freshness`、`metadata`（含 `identity_verified`、`mentor_role_verified`）。

> 内部 RAG 召回协议 `InternalMentorRag.retrieve(intent, domain_judgements)`（后端工作流用）
> 与本可视化无关，保留在 `data_scripts/internal_mentor_rag.py` 未改动。

## 3D 星图：当前文件结构（本目录 = cloud3d/）

```
cloud3d/                     ← 独立 3D 模块目录（不改动 paper-claw-master/data 下任何文件）
  HANDOVER.md                ← 本交接文档（已移入 3D 模块）
  build_cloud.py             # 数据生成脚本（每次运行重新读最新 RAG 库 → 布局/坐标/配色）
  cloud_data.json            # 预计算的可视化数据（生成脚本产出，接口稳定）
  index.html                 # 单文件 Three.js 前端（加载 cloud_data.json 渲染）
  server.js                  # 极简本地静态服务器（node server.js → :8090）
  start_starmap.bat          # 启动器：起服务并打开浏览器
  OPEN_STARMAP.bat           # 备用启动
  .previews/                 # 验证截图
```

## 数据流（重要：数据分离、每次生成读最新库）

```
data/ustc_mentor_rag.json   (RAG 库，可能随时更新；在 ../paper-claw-master/data/)
        │  py build_cloud.py   ← 每次运行都重新读取当前库
        ▼
cloud3d/cloud_data.json   (生成与展示分离，接口稳定)
        │  fetch
        ▼
cloud3d/index.html   (Three.js 渲染，正式前端可复用同一份数据)
```

## cloud_data.json 接口（新会话接手者需掌握）

```json
{
  "meta": {
    "title": "中国科学技术大学 · 导师研究星图",
    "generated_at": "…", "mentor_count": 715, "evidence_count": 1523,
    "domain_count": 10,
    "departments": [ … ],          // 学院列表
    "legend": [ {id,name,color,count}, … ],  // 10 个研究领域 + 配色
    "camera": { "target":[0,0,0], "radius":1500, "r_out":540, "r_in":170, "arms":6 },
    "layout": { "galaxy_spacing": 540, "cloud_scale": 70, "disk_radius": 540, "arms": 6 }
  },
  "nodes": [
    {
      "candidate_id", "name", "department", "affiliation",
      "domain", "domain_name", "secondary",
      "color",        // 领域色
      "lum",          // 相对亮度 0.55~1.0（研究方向/论文多的更亮）
      "core_lum",     // 径向亮度因子 0~1，越靠中心亮核越大（需求1新增）
      "size",         // 星星大小（同上的丰富度）
      "x","y","z",    // 预计算 3D 坐标
      "topics","methods","pubs","pub_count","homepage","recruitment"
    }, …
  ]
}
```

正式前端只要加载 `cloud_data.json`（`{meta, nodes}`），即可复用星图，
不依赖生成逻辑，接口稳定。

## 布局算法（build_cloud.py，纯 Python 标准库，无 numpy/scipy 依赖）

- 每个导师按 `department + research_topics + methods` 关键词映射到 **10 个研究领域**（domain）。
- **多臂对数螺旋银河盘布局**：
  - 6 条对数螺旋悬臂（`N_ARMS=6`，1.4 圈 `turns`），盘内径 `R_IN=170` / 外径 `R_OUT=540`。
  - **人口中心化 + 均匀角分布**：10 领域按人口降序 rank=0..9，
    目标方位角 = `rank*(360/10)`（均匀绕盘），目标半径 = `205 + rank*(470-205)/9`
    （人口越多越靠核心亮核）。`best_arm_t()` 把 (目标角, 目标半径) 逆映射回
    最近悬臂的螺旋参数 `(arm, t)`，存入 `ARM_PLAN[dom_id] = (arm, tc, seg)`。
  - 每个领域沿其悬臂的一段**窄径向带**聚集（云团高斯式聚在 `tc` 中心），
    分割清晰，min 质心间距约 140，互不重叠。
  - **Y 向透镜状厚度** `thickness(t)=26→13`，轴向约 ±70，中央鼓、边缘收，
    扁平盘带明显 3D 弧面感。
  - 每个 node 带 `core_lum = (1 - r_norm)^1.6`（r_norm 为径向归一），前端用它做「越近越亮」调色。
- 布局全部手写标准库，`random.seed(42)` 固定可复现。

## 前端（index.html，Three.js 0.160 + OrbitControls，CDN importmap）

### 环境与背景（纯装饰、非导师、不可交互）
- **深空星尘** `makeStarDust(5200)`：远处渐变背景粒子，缓慢自转。
- **沿旋臂星尘** `makeArmDust(2500)`：6 条臂贴中心线、薄盘内（Y≈±5.5）的密集加性星尘，
  让旋臂有实体颗粒感。共享 `SPIRAL={r_in:170, r_out:540, turns:1.4, arms:6}`（与布局脚本一致）。
- **沿臂星云** `makeArmNebulae`：每条臂 2~3 块、中远段绕盘分布、长轴沿臂压扁的柔和椭圆发光。
- **中央亮核** `makeGalacticCore()`：原点 4 层同心暖金→白发光层（scale 150/95/55/26，
  亮度最高、聚集感强）+ 一个紧凑暗色黑洞环（scale 340，衬托亮核），成为视觉焦点。
- 三者并入 `discBg` Group 与 `starDust` 同步自转 `discBg.rotation.y = time*0.004`，
  保持旋臂方向一致。

### 交互
- **不含导师姓名标签**（用户要求全部去掉姓名，字体曾过大）。
- 领域(学院)名 3D 标签默认调暗（opacity 0.5），悬停发光。
- 点击领域标签 / 图例 → `focusGalaxy(id)`：相机平滑飞行至该星系（其余星系淡出），
  顶部显示院名+导师数，`← 返回总览` 按钮 `resetOverview()` 退回全局（相机 `(0, r_out*0.85, r_out*1.15)` 斜俯视）。
- 点击星星 → 右侧详情面板（方向/方法/论文/主页/招生）。
- 拖拽旋转 / 滚轮缩放 / 自动缓旋转。

## 运行方式

```bash
# 1) 数据更新后重生成可视化数据（每次都会重读最新 RAG 库）
cd cloud3d
py build_cloud.py          # 读取 ../paper-claw-master/data/ustc_mentor_rag.json → cloud_data.json

# 2) 起本地服务并打开（fetch 需 http，file:// 会被 CORS 拦截）
node server.js             # 或双击 start_starmap.bat
# → http://localhost:8090/
```

## 验证手段（沿用，便于回归）

- 数据：`py build_cloud.py` 应幂等成功，`{meta, nodes}` 结构完整，
  `mentor_count=715`、domain=10、legend=10、坐标全有限、全部 node 含 `core_lum`。
- 布局：半径随人口单调（physics 最内、energy 最外）、角距均匀、质心最小间距≈140。
- 中心亮度：渲染帧按屏幕中心环带采样，中心/外缘亮度比 ≈ 5 倍；
  旋臂对比（臂上亮斑 vs 臂间暗区）≈ 3.4×，6 臂螺旋清晰。
- 前端：JS `node --check` 通过（临时 `.mjs` 校验后删除）；puppeteer-core + Edge 截图，
  DOM 断言（715/10/legend 10 项/无 fatal）、`focus_physics` 聚焦流程正常、无 JS console 错误。

## 相关脚本清单

```
cloud3d/        （3D 星图，当前工作，本模块）
  build_cloud.py            # 读 RAG 库 → 生成 cloud_data.json（银河盘布局/配色/坐标）
  index.html                # 前端渲染（Three.js）
  server.js / start_starmap.bat   # 本地服务与启动

paper-claw-master/data_scripts/   （RAG 库构建，已完成，仅需在数据更新时重跑）
  build_rag.py              # 组装 RAG 库（产出 ustc_mentor_rag.json）
  internal_mentor_rag.py    # 后端 RAG 召回协议实现
  ustc_scraper.py 等爬虫    # 官网/论文抓取
```

## 后续可能的扩展（尚未做）

1. 导师名字已按用户要求去掉；如未来需要可按需加回（此前按相机距离分级淡入的 LOD 逻辑已被移除，需重做）。
2. 可加搜索框/按学院筛选/星座连线开关。
3. 论文平台多源（OpenAlex + S2 + DBLP）已汇总进 RAG 库，星图可加「合作网络/共著连线」。
4. 正式前端未开发；`cloud_data.json` 接口已稳定，前端可直接接。
```