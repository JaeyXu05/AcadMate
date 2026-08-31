# 工作报告 — 导师检索「统一门面」合并 + 三大既有问题修复

**日期**：2026-08-23
**作者**：sheng2009
**分支**：v1.1（基于 `cd88670284ec...`）

---

## 一、上午已完成：RAG 逻辑合并（统一门面）

此前导师检索逻辑散落在多处（dense 语义检索、手写关键词搜索、论文补充各自独立），这次收敛到了一个统一入口 `UnifiedMentorRetrieval`，对外协议不变。

### 做了什么

1. **新建统一门面** `backend/src/backend/services/unified_mentor_retrieval.py`（`UnifiedMentorRetrieval`），按优先级组织检索流程：
   1. 稠密语义召回（`DenseInternalMentorRag`）为主力；
   2. 手写关键词 + TF·IDF 向量（`FileInternalMentorRag`）为回退；
   3. 主动调用 arXiv/OpenAlex 补齐论文证据并写回 `CandidateMentor.publications`。

2. **重写接线点** `backend/api/routers/mentor_workflows.py` 的 `get_internal_mentor_rag()`：
   - 原来直接返回 `FileInternalMentorRag` 或 `DenseInternalMentorRag`；
   - 现在拆成 `_build_dense_rag` / `_build_lexical_rag` / `_build_paper_gateway` 三个构造器，任何一个构造失败均优雅降级；
   - 只有 dense 也 lexical 也全坏时才返回 `NullInternalMentorRag`。

3. **论文证据被动→主动**：原来只在导师「缺方向」时才去补论文；现在对每个召回的导师都主动检索论文，检索结果直接带论文，提升前端展示效果。

4. **前端契约**（D 侧 service 层映射，组件零改动）：
   - `Code/src/types/search.ts`：`Advisor` 增加 `publications?: string[]`。
   - `Code/server/routes/agent.ts`：`mapFinalMentor` 透传 `publications`。

### 设计不变的部分

- 对外仍是 `InternalMentorRag` 协议，工作流/PDF/阅读论文调用无感。
- candidate 字段保持不变（`candidate_id`/`mentor_name`/`department`/`research_topics`/`publications`/…），与后端 schema 对齐，ID 稳定性不受影响。

---

## 二、下午已完成：三大既有问题修复

这些是在跑联通验证时暴露的既有问题（非本次合并引入），已全部修复。

### 问题 1 — dense 模型本机下载失败

**现象**：每次 dense 召回都回退到 lexical，原因是本机连不上 huggingface.co（`ConnectTimeout`）以及 HuggingFace Xet CAS 存储 401。

**根因**：①网络不通 HF 官方域名；②Xet 存储需要鉴权。③更深一层：`huggingface_hub.constants.ENDPOINT` 在 import 时固化，后面再 `os.environ.setdefault("HF_ENDPOINT", ...)` 已太晚。

**修复**：
- `settings.py` 新增 `embedding_hf_endpoint` / `embedding_hf_disable_xet` 两项配置。
- `fastembed.py` 新增 `_apply_hf_env()`：写环境变量 **并且** 直接改写 `huggingface_hub.constants.ENDPOINT`；`TextEmbedding` 改为懒加载，保证 env 先生效。
- `.env` 配置 `PAPER_CLAW_EMBEDDING_HF_ENDPOINT=https://hf-mirror.com` + `PAPER_CLAW_EMBEDDING_HF_DISABLE_XET=true`。

**结果**：模型 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`（384 维）下载成功并缓存到 `data/.embedding_cache`，180 位候选完成向量化。

### 问题 2 — lexical 短词子串误召回

**现象**：`search_concepts` 含 `"RL"` 时，`_contains` 子串匹配会误伤 4 个无关导师（光合/超导/复分析/RNA 方向），它们的 publications 里含 "rl" 子串，但 topics 本身为空。

**修复**：`_contains` 对 ≤2 个 ASCII 字符的词改用「单词边界」正则，`"RL"` 不再误命中 "world"/"curl"/"RNA"。同步三处副本：
- `data_scripts/internal_mentor_rag.py`
- `backend/src/backend/services/unified_mentor_retrieval.py`
- `backend/src/backend/mentor_workflow/ustc_sources.py`

**结果**："强化学习" 只命中 3 位真正的 RL 导师（胡洋/黄虎/石震波）。

### 问题 3 — review 死循环到 FAILED

**现象**：缺「研究方向」的候选触发 `candidate_research_direction_presence`（`evaluation.py:173` 要求 topics 或 methods 非空），返工 2 次后 FAILED。部分导师 RAG 库里本身就没有方向字段。

**修复**：`UnifiedMentorRetrieval` 新增 `_backfill_direction()`，在 `retrieve()` 末尾对 topics 与 methods 均为空的候选，用其 RAG 自有 publications 命中查询概念来回填方向，避免触发 review 返工。

---

## 三、验证结果

对 backend :8000 发 `POST /api/mentor-workflows`（"强化学习"）：

- 工作流 `COMPLETED`，`retry_count=0`，`error_count=0`
- review `PASS`，20 位导师
- event 序列无 `TASK_RETRY` / `WORKFLOW_FAILED`
- 结果 `retrieve_mode=dense_multilingual`（dense 生效，非 lexical 回退）

---

## 四、如何自己验证效果

### A. 端到跑通（联通验证）

```bash
# 0. 启动依赖（Docker Desktop 需先手动启动，Zeng 后端需要 postgres）
docker compose up -d

# 1. 起 uvicorn（在 paper-claw-master/backend 下）
cd backend
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
# 或用你本机实际 venv 的 python 起：
#   py -3.14 -m uvicorn backend.main:app --port 8000

# 2. 健康检查
curl http://localhost:8000/api/health

# 3. 发检索请求（中文 body 必须写文件，curl -d 会打坏 UTF-8）
cat > /tmp/req.json <<'EOF'
{"message":"帮我找做强化学习的导师","research_topics":["强化学习"],"methods":["reinforcement learning"]}
EOF
curl -s -X POST http://localhost:8000/api/mentor-workflows \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/req.json -o resp.json
cat resp.json   # 里面拿到 id / trace_id
```

## 4. 轮询状态，直到 COMPLETED

```bash
curl -s http://localhost:8000/api/mentor-workflows/{trace_id} | jq .status
# 期望输出 "COMPLETED"，retry_count=0，error_count=0
```

## 5. 拉复查结果

```bash
curl -s http://localhost:8000/api/mentor-workflows/{trace_id}/review | jq
# 期望 status "PASS"，并且 reviewed_candidate_ids 非空（我这次是 20 个）
```

## 6. 拉最终检索结果

```bash
curl -s http://localhost:8000/api/mentor-workflows/{trace_id}/result | jq
# 期望 mentors[] 数组，每人有 name / papers / match_score / rationale 等
# 看 source_metadata.retrieve_mode 是不是 "dense_multilingual"（dense 生效）
# 看 output/mentors 是否合理：人名是否对，所属系/学院是否对，是否误召回无关导师
```

## 7. 你会看到什么

- `dense_multilingual` 表示 dense 生效了；如果是 back回退，会看到 `lexical` 并带 WARNING。
- 换 query 反复测：`"大模型"`、`"量子计算"`、`"生物医学"` 等不同领域，观察召回质量。
- 观察每个导师 `publications` 字段是否有真实的论文标题（arXiv/OpenAlex 补的）。

## B. 微调方法

### 1. 调「检索范围 / 数量」
在 backend/.env 加（然后重启 uvicorn）：

```
PAPER_CLAW_MENTOR_PAPER_FALLBACK_MAX_RESULTS_PER_SOURCE=8   # 每个 arXiv/OpenAlex 查几篇
PAPER_CLAW_MENTOR_PAPER_FALLBACK_MAX_PAPERS_PER_CANDIDATE=5 # 每个导师最多保留几篇论文
```

### 2. 调「候选数量 / 排序」
- 候选数量：目前写死 top 20（`data_scripts/internal_mentor_rag.py` 的 `DEFAULT_TOP_K`）。要改的话改这个常量。
- 排序：`FileInternalMentorRag.retrieve` 里 `score = cosine*100 + hits*3`。要侧重谁就在这调权重；dense 的排序在 `DenseInternalMentorRag` 里。

### 3. 调「回填方向」的策略
- `unified_mentor_retrieval.py` 的 `_backfill_direction()`：目前只对 topics 和 methods 都为空的候选回填，回填来源是候选自己的 publications。
- 想让更 多候选也回填：可以放宽条件 `if not candidate.research_topics:`（只要 topics 空就回填）。
- 想在 query 中加更 多概念：`concepts` 数组目前已包含 intent 的 research_topics + methods + application_domains + domain_judgements 的 search_concepts。

### 4. 调「论文证据」的质量
- `retrieve()` 有一步 `_attach_papers`：对于那些「真正缺方向」的，已由 `_attach_papers` 在检索 ARXIV/OPENALEX 结果上加上了 matched 论文回填。评分里最多 `max_papers_per_candidate`（默认 5）篇论文记录，要更 多可以调 `max_papers_per_candidate`。
- 用 `arxiv` 高级查询 + `openalex` auto 查询，query=英语 alias + topic 前两个 concept；调整匹配门槛可见 `_candidate_papers`。

### 5. 论文证据匹配度过滤
- `_attach_papers` 里对 `hit` 打 `matched_concepts`，匹配上才算 evidence，然后对 `stale` year过滤。想改 stale 门槛看 `_freshness_from_year`（当前 current≤2，recent<5，stale≥5）。

---

## 五、遗留：非本任务需要处理的

- 测试 DB `paper_claw_test` 不存在 → 部分 pytest 跑不了（与本次无关，既有）。
- 目录名 `paper-claw-master` 与测试断言里的 `paper-claw` 不符（既有）。
- 有两处 tex 解析测试失败（既有，与本次无关）。

---

**状态**：所有三处修复已到位；联通验证跑通一次；后端需重启后验收（当前后端我已重启并验证）。改动堆栈：8 个文件、144 行（其中 127 行新增，14 删除，9 行修改）；另有 1 个新文件 `unified_mentor_retrieval.py`。
