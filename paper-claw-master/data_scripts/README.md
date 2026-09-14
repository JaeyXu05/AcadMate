# 数据流水线（data_scripts）

本目录是导师知识库（RAG）的构建流水线。**项目不内置任何特定高校的导师数据**——`paper-claw-master/data/ustc_mentor_rag.json` 当前是一个空的合法骨架。要让某个机构的导师检索可用，需要用本流水线为该机构构建一份 RAG。

本流水线的设计原则是"没有证据就不能推荐"：每位入库导师必须有官方身份/角色链，论文只能补充方向、不能反向证明身份，每条结论必须绑定证据引用。

## 流水线总览

```text
机构官方师资页/教师主页 + OpenAlex / Semantic Scholar / DBLP
    -> 抓取、身份核验、作者归属确认、去重
    -> ustc_mentor_rag.json（candidates + evidence）
    -> 语义索引（FastEmbed 本地向量）+ 关键词索引
    -> 多智能体检索 -> 证据审核 -> 匹配结果
```

运行时 RAG 顶层结构：

```json
{
  "generated_at": "...", "run_date": "...",
  "source_chain": ["internal_ustc_rag"],
  "mentor_count": 0, "evidence_count": 0, "skipped_non_mentor": 0,
  "warnings": [],
  "candidates": [],
  "evidence": []
}
```

`candidates` 是 `CandidateMentor` 列表（与 A 端 Pydantic schema 对齐），`evidence` 是 `EvidenceRecord` 列表，两者通过 `candidate_id` 与 `evidence_refs` 关联。

## 文件说明

| 文件 | 作用 | 机构相关性 |
|---|---|---|
| `build_rag.py` | 从原始导师数据 + 论文平台 JSON + override 文件组装 RAG。机构无关的组装/去重/方向一致性逻辑；仅 affiliation 字符串、`candidate_id` 前缀、identity 证据文本/URI 和默认路径与具体机构相关 | 主体通用 |
| `internal_mentor_rag.py` | 运行时适配器 `FileInternalMentorRag`，加载 RAG 并实现 TF-IDF/cosine + 词法检索。**后端运行时直接 import 此文件** | 通用（仅默认文件名与机构相关） |
| `openalex_scraper.py` | 按英文名在 OpenAlex 解析作者并取代表作 | 通用；机构过滤用一个 OpenAlex institution ID，可替换 |
| `semantic_scholar_scraper.py` | Semantic Scholar 同上 | 通用；机构名只作作者排序的 tie-breaker |
| `dblp_scraper.py` | DBLP 同上 | 完全通用（仅按名 + pid） |
| `ustc_scraper.py` | 抓取中科大官方师资目录与教师主页 | **科大专属**，其他机构需写等价的机构抓取器 |
| `review_mentor_roles.py` | 复核未确认导师角色，产出 role override | 依赖机构官方主页，机构相关 |
| `export_fuzzy_review.py` | 导出模糊作者匹配供人工裁决，产出 manual override | 通用 |
| `prewarm_mentor_index.py` | 预热后端稠密语义索引 | 通用 |
| `verify_rag.py` | 7 门只读自检（schema/引用/召回/覆盖/检索质量/语义元数据） | 通用 |
| `audit_rag.py` | 覆盖率与质量审计报告（不阻断） | 通用 |
| `test_data_quality.py` | `build_rag.py` 清洗函数的单元测试 | 通用 |

## 为新机构接入导师数据

流水线的核心是机构无关的：`build_rag.py` 接收一份"原始导师列表"（含 `faculty_id / name / english_name / college / profile_url / research_topics / mentor_role_verified` 等）和按 `faculty_id` 索引的论文 JSON，组装成标准 RAG。为另一个机构接入的典型步骤：

1. **写一个机构抓取器**，产出与 `ustc_scraper.py` 相同形状的原始导师列表（机构官方师资页 → `data/<inst>_mentors_raw.json`）。`ustc_scraper.py` 可作为参考实现。
2. **配置论文平台抓取的机构过滤**：
   - `openalex_scraper.py` 用一个 OpenAlex institution ID 过滤作者归属（当前是科大的 `I126520041`），换成目标机构的 ID。
   - `semantic_scholar_scraper.py` 的机构名 token 仅作作者排序参考，可按需调整。
   - `dblp_scraper.py` 无机构过滤，可直接复用。
   - 三个抓取器都接受 `--input / --output` 参数，默认文件名可按机构命名。
3. **调整 `build_rag.py` 的机构相关常量**：`affiliation` 字符串、`candidate_id` 前缀、identity 证据的 `source_type` / `source_uri` 文案、默认输入输出路径。
4. **构建 RAG**：`python build_rag.py --raw data/<inst>_mentors_raw.json --papers ... --role-overrides ... --paper-overrides ...`。
5. **质检**：`python verify_rag.py`（注意：空 RAG 或无"有方向+有证据"候选的 RAG 会在门 C/D 失败，这是数据存在性门，预期行为）；`python audit_rag.py` 出覆盖与质量报告。
6. **生成星图**：在 `cloud3d/` 运行 `py build_cloud.py --rag ../paper-claw-master/data/<your_rag>.json`，或保持默认路径写入 `ustc_mentor_rag.json` 后重新生成 `cloud_data.json`。
7. **跨模块一致性校验**：在仓库根运行 `node scripts/verify-runtime-data.mjs <rag> <cloud_data.json>`，确认 RAG 与星图 `candidate_id` 集合一致。

> 改 `candidate_id` 格式时，必须同步 A 端返回值、D 端详情接口（`Code/server/routes/advisors.ts`）和星图节点（`cloud3d/build_cloud.py`），因为四个模块以 `candidate_id` 硬关联。

## 运行时：空库行为

当 RAG 为空（`candidates: []`）：

- 后端 `FileInternalMentorRag` / `MentorSemanticIndex` 返回空召回，工作流给出明确的 `NO_MATCH` 而不是虚构导师。
- D 端 `/api/recommend`、`/api/advisors/:id` 等返回明确的 503/404，不崩溃。
- 启动器与冒烟测试接受空库为合法状态（见根目录 `scripts/`）。

即"没有数据就诚实地说没有"，这是本流水线与检索系统共同遵守的边界。

## 验证

```powershell
cd paper-claw-master/data_scripts
py test_data_quality.py      # build_rag.py 清洗函数单元测试
py verify_rag.py             # RAG 7 门自检
py audit_rag.py              # 覆盖与质量审计报告
```

完整的数据生产链路、schema、证据来源层级与失败路径见 [`docs/CODE_LOGIC_REPORT.md`](../../docs/CODE_LOGIC_REPORT.md) 第 10 节。
