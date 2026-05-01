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

## 长情景链路问题简报

### 现象

- 在长情景测试里，部分“明确可以直接执行”的请求没有立即调用工具，而是先停在确认话术。
- 典型表现：
  - `查询黄金价格。` 返回“要我现在查吗”
  - `再查一下北京今天天气。` 返回“要我现在直接拉数据吗”

### 结构性原因

- 问题不在工具实现本身，而在运行时任务契约装配。
- `query_understanding` 已经把这类请求识别为：
  - `execution_posture = direct_tool`
  - `route_hint = tool`
- 但 `build_task_runtime_contract(...)` 之前仍然只按原始文本走 `select_task_definitions(user_goal)`。
- 对于“查询黄金价格 / 查北京天气”这类短句，旧逻辑会错误落到：
  - `task.request_intake`
  - `Completion criteria: User goal is captured.; No execution is performed.`
- 这段内容被直接送进 Runtime Stage Projection，模型因此被提示成“先确认需求，不执行”。

### 本轮修正

- 删除运行环里对 `get_weather / get_gold_price` 的临时硬编码直连补丁，避免用特判掩盖结构问题。
- 增加运行时定义选择逻辑：优先根据 `query_understanding` 选择任务定义，而不是只看原始文本。
- 为直接能力执行新增：
  - `task.capability_execution`
- 为直接知识检索新增：
  - `task.knowledge_retrieval`
- 对 direct tool 场景的输出边界改为：
  - 当请求清楚且输入充分时，直接执行能力并返回结果，不先请求确认。

### 当前状态

- 针对性回归测试已通过。
- 还需要再跑一轮长情景复测，确认长上下文和 follow-up 场景下是否还有别的链路残留同类问题。

## 长情景问题报告补充

### 问题 1：文件 follow-up 已有上下文绑定，但任务理解没有消费它

#### 现象

- 长情景里，上一轮已经处理过 PDF 或结构化数据文件。
- session context 里已经存在：
  - `active_dataset`
  - `active_pdf`
  - 或 `committed_dataset / committed_pdf`
- 但下一轮用户只说：
  - `按仓库汇总前五。`
  - `把这份 PDF 的核心结论压成三条行动建议。`
- 系统仍把请求路由到通用知识检索 `search_knowledge`，而不是回到当前文件工作对象。

#### 根因

- 根因不在 tool registry，也不在 prompt 文案。
- 结构断点在运行时理解入口：
  - `backend/runtime/agent_chain.py`
  - `backend/understanding/query_understanding.py`
  - `backend/understanding/task_understanding.py`
- 原链路会先构建：
  - `memory_runtime_view`
  - `context_policy_result`
- 但随后调用 `analyze_query_understanding(...)` 时，只传当前消息文本，没有把 state snapshot 里的文件绑定送进去。
- 所以理解层仍是“纯当前句子分类器”：
  - 有显式路径时能识别
  - 没显式路径的 follow-up 会退回 `knowledge_lookup`

#### 本轮修正

- 文件：
  - `backend/runtime/agent_chain.py`
  - `backend/understanding/query_understanding.py`
  - `backend/understanding/task_understanding.py`
  - `backend/tests/task_understanding_regression.py`
  - `backend/tests/skill_runtime_regression.py`
  - `backend/tests/skill_runtime_integration_regression.py`

- 修正内容：
  1. 从 `MemoryRuntimeView.state_snapshot.context_slots` 提取结构化绑定快照。
  2. 将 `active_bindings` 显式传入 `analyze_query_understanding / analyze_task_understanding`。
  3. 理解层新增“绑定驱动的 follow-up 路由”：
     - 有 `active_dataset / committed_dataset` 且当前句子是数据 follow-up 形态时，直达 `structured_data_analysis`
     - 有 `active_pdf / committed_pdf` 且当前句子是 PDF follow-up 形态时，直达 `pdf_analysis`
  4. 保持边界：
     - 没有绑定时，`按仓库展开一下` 仍然只是普通 query
     - 不把通用短词变成全局触发器

#### 当前状态

- 已通过回归：
  - `backend/tests/task_understanding_regression.py`
  - `backend/tests/skill_runtime_regression.py`
  - `backend/tests/skill_runtime_integration_regression.py`
  - `backend/tests/query_runtime_runtime_loop_regression.py`
  - `backend/tests/task_runtime_contract_regression.py`
  - `backend/tests/file_work_object_writeback_regression.py`
- 当前这条问题已经从“上下文存在但不用”修正为“理解层可消费绑定快照并恢复文件工作对象”。
- 下一步应继续复测长情景，确认 PDF active slot 偶发丢失是否还存在第二层问题。
