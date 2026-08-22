# 中科大导师 RAG 数据抓取

抓取中科大官网全校教师库 + OpenAlex / Semantic Scholar / DBLP 论文，组装成 Paper Claw
`mentor_workflow` 的 `InternalMentorRag` 接口可直接加载的 RAG 库
（`data/ustc_mentor_rag.json`）。

## 依赖

- Python 3.12+
- `httpx`（抓取）；`internal_mentor_rag.py` 还需 `pydantic` 与后端源码（因为它实现的是后端协议）

```bash
pip install httpx pydantic
```

> 脚本设计为自包含：`ustc_scraper.py` / `openalex_scraper.py` /
> `semantic_scholar_scraper.py` / `dblp_scraper.py` / `build_rag.py`
> 不 import 后端包，只依赖 `httpx`，任何装了 httpx 的环境都能直接跑。
> 只有 `internal_mentor_rag.py` 实现后端 `InternalMentorRag` 协议，需在后端
> 环境（已装 openai/pydantic 等）里 import。

## 抓取流程

### 1. 抓中科大官网导师

#### 重点学院模式（默认）

```bash
python data_scripts/ustc_scraper.py --max-per-college 200 --delay 0.5
```

- 遍历 9 个重点学院（`USTC_COLLEGE_IDS`），分页拉满每个学院的教师列表。
- `--colleges` 可限定子集，如 `--colleges 人工智能 软件`。

#### 全校模式（推荐）

```bash
python data_scripts/ustc_scraper.py --all-colleges --delay 0.5
```

- 用空 `collegeid`（后端 `USTC_ALL_TEACHING_UNITS_ID=""` 约定）单流分页拉取
  **全校所有教学单位**（非 9 学院之外的全校学院）。
- 每条搜索记录自带 `collegeName`/`unit`，学院归属不丢失。
- `--max-total N`（默认 0=不限）作全局上限；`--max-per-college` 在该模式下忽略。
- 输出 JSON 顶层加 `"mode": "all_colleges"` 标记。
- 断点续抓：已有 `faculty_id` 自动跳过，与重点学院模式共享 `data/ustc_mentors_raw.json`。
- 产出 `data/ustc_mentors_raw.json`（全校约 900+ 导师、45 学院）。

小样验证：

```bash
# 重点学院小样
python data_scripts/ustc_scraper.py --colleges 人工智能 --max-per-college 3 --delay 0.3
# 全校小样
python data_scripts/ustc_scraper.py --all-colleges --max-total 5 --delay 0.5
```

### 2. 抓 OpenAlex 代表论文

```bash
python data_scripts/openalex_scraper.py --max-papers 10 --delay 1
```

- 读取 `data/ustc_mentors_raw.json`，用每位导师英文名 + USTC 机构
  （`I126520041`）在 OpenAlex 解析作者实体，取被引最高的 N 篇论文。
- 作者消歧：优先 `display_name` 精确匹配；模糊命中会记 warning。
- 无英文名或解析不到作者的，记 warning 跳过。
- 断点续抓：已解析的 `faculty_id` 跳过。
- 输出 `data/ustc_mentor_papers.json`。

小样：

```bash
python data_scripts/openalex_scraper.py --max-papers 3 --delay 1
```

### 3. Semantic Scholar 论文（扩展平台）

```bash
# 探针
python data_scripts/semantic_scholar_scraper.py --limit 20 --max-papers 5 --delay 2
# 全量（默认在所有有英文名导师上运行）
python data_scripts/semantic_scholar_scraper.py --limit 0 --max-papers 10 --delay 2
```

- 公开免费 API（`api.semanticscholar.org`），匿名约 1 req/s，申请免费 key 可提速。
- 作者解析：`/graph/v1/author/search`，精确 `name` 匹配优先；`affiliations` 含
  "University of Science and Technology of China" 者优先。
- 论文：`/graph/v1/author/{id}/papers`，客户端按 `citationCount` 降序取前 N
  （该端点无服务端 sort）。
- 输出 `data/ustc_mentor_papers_s2.json`，字段对齐 `openalex_scraper` 输出
  （`s2_author_id` / `s2_exact_match` / `s2_paper_count` / `s2_cited_by_count`）。
- 结尾打印可行性汇总：resolved/exact/fuzzy/miss 计数 + 样例论文。
- **暂不并入 RAG**（留待人工裁决后统一合并）。

### 4. DBLP 论文（扩展平台）

```bash
# 探针
python data_scripts/dblp_scraper.py --limit 20 --max-papers 5 --delay 0.5
# 全量
python data_scripts/dblp_scraper.py --limit 0 --max-papers 10 --delay 0.5
```

- 公开免费 API（`dblp.org`），无需 key；DBLP PID 是稳定的作者标识。
- 作者解析：`/search/author/api` → `result.hits.hit[].info`，从 `info.url`
  抽 pid，`info.author` 精确名匹配（去掉末尾 `0001` 序号后缀）。
- 论文：`/pid/{pid}.xml`（XML 端点兼容所有 pid 格式），解析 `<r>/<article|inproceedings>`
  的 `<title>`/`<year>`/`<journal|booktitle>`/`<ee>`，按年份降序取最近 N。
- DBLP 无被引量字段，按年份取论文（与 OpenAlex/S2 按被引取互补）。
- 仅覆盖 CS 学科，命中集中在 CS/AI/EE 学院——预期行为。
- 输出 `data/ustc_mentor_papers_dblp.json`（`dblp_pid` / `dblp_exact_match` / `papers[]`）。
- **暂不并入 RAG**。

### 5. 组装 RAG 库

```bash
python data_scripts/build_rag.py
```

- 默认合并 OpenAlex + S2 + DBLP 三平台论文：自动读取
  `data/ustc_mentor_papers.json` / `ustc_mentor_papers_s2.json` /
  `ustc_mentor_papers_dblp.json`，按导师聚合、逐平台做方向一致性过滤后统一去重。
- 也可显式指定单/多平台：`--papers a.json --papers b.json`（可多次，旧单文件
  用法仍兼容）。
- 为每位导师生成 `CandidateMentor` + 2~N 条 `EvidenceRecord`
  （身份证据 / 主页方向证据 / 每平台一条论文证据），元数据标 `identity_verified` /
  `mentor_role_verified` / `supports_fields`。
- 输出 `data/ustc_mentor_rag.json`，结构：
  `{ candidates: [...], evidence: [...], source_chain: ["internal_ustc_rag"], ... }`
- 字段与 `backend/mentor_workflow/schemas.py` 的
  `CandidateMentor` / `EvidenceRecord` 对齐。
- **方向一致性过滤**：某平台作者仅模糊命中（`exact_match=False`）时，用官网
  研究方向对比命中论文标题，按三态处理——同语言却无重叠判"同名错配"丢弃该平台
  论文证据；跨语言（如中文方向 vs 英文论文）无法判定则保留并记 warning 待人工裁决；
  有重叠或导师无官网方向则保留。

## 自检

每次重新抓取/重建后跑一遍，确认库没坏（只读、不联网）：

```bash
python data_scripts/verify_rag.py
```

4 项检查：A. schema 合规（后端环境走严格 model_validate，否则手写校验）
B. 证据引用闭环（无悬空/孤儿）C. 跳过外部源条件（合格候选有身份核验证据）
D. 召回升单测（需后端完整依赖，conda 环境会 SKIP）。全 PASS 即可。

## 模糊命中人工裁决

把各论文平台（OpenAlex / Semantic Scholar / DBLP）中所有模糊/非精确命中的导师
导出统一对照表，供人工裁决：

```bash
# 自动读 data/ 下所有可用 papers JSON（默认）：
python data_scripts/export_fuzzy_review.py

# 只导出指定平台：
python data_scripts/export_fuzzy_review.py --papers data/ustc_mentor_papers.json data/ustc_mentor_papers_s2.json
```

产出：
- `data/fuzzy_review.md` — 人眼可读 Markdown 表格（每平台一列：命中实体 / 论文数 / 样例标题） + 逐人详情。
- `data/fuzzy_review.json` — 结构化，每条带空 `verdict` 待填 `keep`/`drop`/`uncertain`。

重点看：命中实体姓名是否对得上、论文方向是否与官网吻合、学院是否一致。
裁决后写成 `data/manual_overrides.json`（faculty_id → platform:author_id 或 null），
各 scraper（`openalex_scraper.py` / `semantic_scholar_scraper.py` /
`dblp_scraper.py`）重跑时**优先读取**该文件：
- 某平台裁决为 `null` → 跳过该导师在该平台的论文抓取（无需再网络请求）。
- 裁决为确定的 author id / s2 id / dblp pid → 直接用该 id 抓论文，覆盖自动解析。
- 用 `--overrides <path>` 可指定别的文件（默认 `data/manual_overrides.json`）。
- `build_rag.py` 聚合各平台产出时天然继承这些裁决（被跳过的平台无论文记录）。

## 接入工作流

`internal_mentor_rag.py` 的 `FileInternalMentorRag` 实现了
`InternalMentorRag.retrieve()`，加载 `data/ustc_mentor_rag.json` 做关键词召回。

自检（需后端环境）：

```bash
python data_scripts/internal_mentor_rag.py
```

它已接入 FastAPI（`backend/src/backend/api/routers/mentor_workflows.py` 的
`get_internal_mentor_rag()`）：仓库根加入 `sys.path` 后导入
`FileInternalMentorRag`，加载 `data/ustc_mentor_rag.json`；文件存在即用内部库，
缺失/导入失败时回退 `NullInternalMentorRag`（走外部源），保证工作流可用。

```python
def get_internal_mentor_rag() -> InternalMentorRag:
    # 仓库根/data/ustc_mentor_rag.json 存在 -> 用内部 RAG；否则回退 Null
    ...
```

或在测试里直接传给 `UstcMentorResearchTool`（参考
`backend/tests/mentor_workflow/test_ustc_sources.py` 的
`test_complete_internal_rag_result_skips_all_external_sources`）：
当内部库候选带 `identity_verified=true` 且有研究方向时，工作流会跳过
外部官方源，`source_chain == ["internal_ustc_rag"]`。

## 输出文件

| 文件 | 内容 | 产出脚本 |
| --- | --- | --- |
| `data/ustc_mentors_raw.json` | 官网导师（含研究方向/主页文本） | `ustc_scraper.py` |
| `data/ustc_mentor_papers.json` | OpenAlex 作者实体 + 代表论文 | `openalex_scraper.py` |
| `data/ustc_mentor_papers_s2.json` | Semantic Scholar 作者实体 + 代表论文 | `semantic_scholar_scraper.py` |
| `data/ustc_mentor_papers_dblp.json` | DBLP 作者实体 + 论文 | `dblp_scraper.py` |
| `data/ustc_mentor_rag.json` | 最终 RAG 库（candidates + evidence） | `build_rag.py` |
| `data/fuzzy_review.md` | 多平台模糊命中对照表（人眼可读） | `export_fuzzy_review.py` |
| `data/fuzzy_review.json` | 模糊命中结构化数据（待填 verdict） | `export_fuzzy_review.py` |

## 注意事项

- **OpenAlex 限流**：默认每位作者间隔 1 秒；遇到 429 自动退避重试。
- **Semantic Scholar 限流**：匿名 ~1 req/s，默认间隔 2 秒；429 退避至 30s。
- **DBLP 限流**：礼貌 `--delay 0.5`；XML 端点兼容所有 pid 格式（数字 pid 也适用
  `pid/{pid}.xml`，而 JSON 端点对数字 pid 返回 404）。
- **官网限速**：默认每次主页请求间隔 0.5 秒，避免压垮 `faculty.ustc.edu.cn`。
- **同名歧义**：论文平台作者解析以英文名为准，模糊命中已在 warning 标注 +
  `fuzzy_review` 表中导出；论文证据的 `identity_verified=false`，身份仍以官网证据为准。
- **Google Scholar 不用**：无官方 API、反爬严格、作者难消歧。
- **Windows 终端乱码**：控制台打印中文可能显示乱码（GBK 终端），但写入的
  JSON 文件始终是 UTF-8，内容正确。