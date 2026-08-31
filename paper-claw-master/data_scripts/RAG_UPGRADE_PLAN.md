# RAG 库升级计划（数据缺失/过少 专项）

> 2026-08-23 定稿。目标：把 `data/ustc_mentor_rag.json` 从「180 导师 / 358 证据」升级到
> 「715 导师 / 更完整字段」，补齐论文、研究方向、bio、email、招生信息，并保持
> 与 A 后端检索、B 云图、D 前端三者 `candidate_id` 一致。

## 一、现状诊断（实测）

| 指标 | 现状 | raw 数据支撑 |
|---|---|---|
| 导师数 | 180 | raw 有 715 位 `mentor_role_verified=true` |
| 证据数 | 358 | — |
| 论文覆盖 | 64/180 有论文 | OpenAlex 135、S2 223、DBLP 9（三平台未合并进库） |
| 研究方向 | 107/180 | raw 437/715 已有 |
| methods | 16/180 | — |
| recruitment_status | 21/180 | raw 78/715 |
| bio/email | 完全缺失 | profile_text 964/968 非空、203 含 `@` |
| english_name | 270/715 | 接口 `ename` 仅 281/968 |

**根因（6 条）：**
1. 库过期：`source_metadata` 里 `paper_platforms` / `topics_source` 全为 `None`，说明库是从 7/26 旧 raw 构建的，从未用 7/28 的 968 条 raw 重跑。
2. 只进 180/715：旧 raw 只有 180 条核验导师；新 raw 有 715 条。
3. 论文只并 OpenAlex：`build_rag.py` 已支持 `--papers` 多平台，但当前产物未合并 S2/DBLP。
4. profile_text 被丢弃：bio/email/更多方向全丢。
5. 方向解析漏抓：「研究方向」标签后的「【查看更多】」折叠区未展开，导致部分导师 topics 为空（仍可从正文恢复）。
6. email 多为官网页加密哈希（明文 `@` 仅约 203 位）。

## 二、方案

### A. 审计脚本（新增 `data_scripts/audit_rag.py`）
可复跑覆盖率报告：导师数 / 方向 / 论文（分平台）/ email / bio / 招生 / 垃圾残留 / ID 一致性。

### B. 增强 `build_rag.py`：抽取 bio/email/富文本方向
- 从 `profile_text` 抽：`email`（正则 + 域名黑名单）、`bio`（去模板后正文截断）、
  补充 `research_topics`（从「个人简介 / 研究方向」段落恢复，复用清洗逻辑）。
- 存储：写入 `candidate.source_metadata` 新增键 `profile_email` / `profile_bio` /
  `profile_office` / `profile_graduated_from`（标量，符合 schema 约束），
  不改 `CandidateMentor` schema、不改 A/C 输出格式。D 侧 `ragAdvisors.ts` 读这些键拼 `bio/contact`。

### C. 补字段
- `recruitment_status`：放宽匹配，全文再扫（招生/欢迎/招收 + 学生类型）。
- `english_name`：优先 `ename`，缺失用 OpenAlex/S2 模糊 + affiliation 消歧兜底。

### D. 重跑流水线（联网抓取由用户执行）
```
py data_scripts/ustc_scraper.py            # 断点续抓（补 english_name/富文本）
py data_scripts/openalex_scraper.py --max-papers 10 --delay 1
py data_scripts/semantic_scholar_scraper.py --limit 0 --max-papers 10 --delay 1
py data_scripts/dblp_scraper.py --limit 0 --max-papers 10 --delay 0.5
py data_scripts/build_rag.py               # 本地可先跑（三平台合并 + bio/email）
py data_scripts/verify_rag.py
```

### E. 验证 + 下游
1. `verify_rag.py` A~F 全 PASS。
2. `cloud3d/build_cloud.py` 重生成 715 节点 cloud_data.json。
3. D 侧 `ragAdvisors.ts` 补 `bio/contact/recruiting` 映射（读 source_metadata 新键）。
4. 端到端 smoke：`POST /api/mentor-workflows` 查「强化学习」，dense + lexical 双向召回正常。

## 三、风险与规避
| 风险 | 规避 |
|---|---|
| 715 全量后同名错配/无方向导师 | 方向一致性过滤 + `_backfill_direction` + 垃圾查询门禁 |
| email 误抽 | 正则 + 域名黑名单 + 去重；官网多为加密哈希，仅约 203 明文可用 |
| bio 过长/模板 | 复用 `_BOILERPLATE` 清洗 |
| 联网限速/失败 | 断点续抓 + 429 退避 |
| 下游无 bio/contact 字段 | 放 `source_metadata`（标量 dict），D service 层读，不改 A/C 输出格式 |
