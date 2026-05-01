# RAG Benchmark 优化记录 - 2026-05-02

## 目标

- SciFact 本地基准抽样 50 条查询
- 指标目标：
  - `hit@10 >= 0.85`
  - `recall@10 >= 0.85`

## 基线

- 基线文件：`backend/tests/_artifacts/scifact_v2_current_lexical_fix.json`
- 指标：
  - `hit@10 = 0.80`
  - `recall@10 = 0.776`

## 本轮问题诊断

1. 词法索引最初没有覆盖 `unit_type="document"` 的 benchmark 文档，已修复。
2. 修复后 `@100` 候选命中率可达 `0.92`，说明主要问题不是“完全找不到”，而是：
   - rerank 只处理很小的头部候选；
   - cross-encoder 排序没有利用原始检索先验；
   - 部分 dense 命中的金标在 fusion 后被挤出候选池。

## 本轮改动

### 1. 词法候选选择修复

- 文件：`backend/retrieval_core/llamaindex_backend.py`
- 改动：允许 `document` 单元在没有 `index_profiles` 时进入 lexical index。

### 2. Benchmark Runner 可复现化增强

- 文件：`backend/RAG/benchmark_runner.py`
- 改动：
  - 支持 `--rerank-top-n`
  - 支持 `--rerank-candidate-pool`
  - 输出当前 rerank 配置
  - 输出 gold 在 base/current 链路中的排名
  - 修正相对输出路径，统一相对 `backend/`

### 3. Cross-encoder 排序混合检索先验

- 文件：`backend/RAG/reranker.py`
- 改动：
  - 对 head 候选的 `retrieval_score` 做 min-max 归一化
  - 最终分数从纯 `rerank_score` 调整为：

    `final_score = cross_encoder_score + 0.05 * normalized_retrieval_score`

  - 保留：
    - `rerank_score`
    - `rerank_retrieval_score_normalized`
    - `rerank_score_blend`

## 中间验证

### rerank top100

- 文件：`backend/tests/_artifacts/scifact_v2_rerank_top100.json`
- 指标：
  - `hit@10 = 0.86`
  - `recall@10 = 0.822`

### rerank top200

- 文件：`backend/tests/_artifacts/scifact_v2_rerank_top200.json`
- 指标：
  - `hit@10 = 0.88`
  - `recall@10 = 0.842`

## 说明

- 当前已确认：`cross_encoder_score + 0.05 * normalized_retrieval_score` 在离线抽样分析中优于纯 cross-encoder。
- 最终正式结果如下：

### 最终正式验证

- 文件：`backend/tests/_artifacts/scifact_v2_hybrid_norm_rerank_top200.json`
- 配置：
  - `candidate_top_k = 200`
  - `rerank_top_n = 200`
  - `rerank_candidate_pool = 200`
- 指标：
  - `hit@10 = 0.92`
  - `recall@10 = 0.882`

## 结论

- 本轮目标已达成：
  - `hit@10 >= 0.85`
  - `recall@10 >= 0.85`
- 当前剩余失败样本主要属于两类：
  1. 候选深层仍未被稳定召回到前列；
  2. 个别语义对齐较弱的 biomedical query 仍需要 query expansion 或更强 sparse / hybrid retrieval 支撑。

## PDF 与结构化数据补充修正

### PDF

- 文件：
  - `backend/pdf_analysis/parser.py`
  - `backend/pdf_agent/runtime.py`
- 修正：
  - 本地 `pdfplumber` 解析追加表格段，不再只依赖页面纯文本。
  - 远程解析存在时也追加本地表格段，避免远程块缺少 table 时丢财报数据。
  - `table_text` 可进入 document/section 摘要候选。
  - 保留表格行边界，避免指标和值串行误读。
  - 财务类问题按“收入 / 利润 / 现金流”覆盖选择证据页。
  - 增加财务表格要点抽取，避免通用句子摘要破坏金额字段。

### 结构化数据

- 文件：`backend/structured_data/planner.py`
- 修正：
  - `多少行 / 行数` 正确进入 `row_count`。
  - `薪水最高的前五名员工是谁` 这类问题按记录排序，不再误判为按姓名聚合。

### 回归

- 文件：`backend/tests/capability_quality_regression.py`
- 覆盖：
  - RAG 本地知识库命中三一重工股东。
  - PDF 财报摘要输出营业收入与经营活动现金流量净额。
  - 结构化数据 row count 不退化成 schema preview。
  - 结构化数据薪资 Top-N 为记录级排序。
