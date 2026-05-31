# 检索与图运行时算法优化计划书（2026-05-31）

## 1. 目标

本计划只覆盖当前未处于修改中的稳定链路，先不触碰工作区内已有改动的 runtime / dynamic context 相关文件。

目标是把检索系统和图运行时从“能跑的 baseline”升级为更成熟、可验证、权威清晰的架构：

- 检索重建必须具备正确的缓存失效、并发合并和可诊断失败。
- 检索排序必须从分散的 rank-only baseline 升级为统一的混合检索排序链路。
- 页码、表格、文档概览等查询意图必须在规划层闭环，不允许分类和过滤脱节。
- 图运行时 terminal 语义必须和并行执行兼容，不允许 completed 状态携带 active work。
- 删除或迁移旧检索执行入口，避免两套 retrieval authority 并存。

## 2. 当前问题与架构原因

### 2.1 具体问题

- `backend/knowledge_system/indexing/llamaindex_backend.py` 的 `_write_units()` 写入新 units 后没有清理 `_units_cache`，同一进程重建索引后仍会读取旧 units。
- `backend/knowledge_system/retrieval/service.py` 的 `_collection_rebuild_pending` 只被写入，不会在锁释放后消费，重建并发请求会被丢弃。
- `backend/capability_system/units/mcp/local/retrieval/query_rewriter.py` 能识别中文数字页码，但 `router.py` 的 `_page_hints()` 只提取阿拉伯数字，导致“第三页”不会产生 page filter。
- `backend/harness/graph/state_machine.py` 在 terminal 节点完成时直接返回 `completed`，没有检查其它 running / active work；`validate()` 又禁止 terminal state 带 active work，形成运行时矛盾。
- `backend/capability_system/units/mcp/local/retrieval/router.py` 的 `RAGQueryRouter.retrieve()` 和 `RetrievalService.retrieve_execution()` 存在两套检索执行路径，CLI 仍走旧路径。
- `backend/knowledge_system/indexing/llamaindex_backend.py` 的 fusion 主要按 rank 做 RRF-like 加权，dense/BM25 原始分数没有统一校准；`candidate_graph.py` 合并候选时只取 max score，多证据命中没有形成可控的证据增强。

### 2.2 深层原因

这是一个“决策权威分散”问题，而不是单点 bug 问题：

- Router 同时承担 plan 和旧 retrieve 执行。
- Backend 同时承担召回、融合、候选合并和部分结果粒度决策。
- Candidate graph 同时做聚合和隐式打分。
- Rebuild service 既做并发控制，又没有完整的队列/合并语义。
- Graph state machine 定义了 terminal 语义，但没有把 active work 纳入 terminal 判定。

## 3. 本地代码依据

主要依据文件：

- `backend/knowledge_system/retrieval/service.py`
- `backend/knowledge_system/indexing/llamaindex_backend.py`
- `backend/knowledge_system/retrieval/candidate_graph.py`
- `backend/capability_system/units/mcp/local/retrieval/router.py`
- `backend/capability_system/units/mcp/local/retrieval/query_rewriter.py`
- `backend/capability_system/units/mcp/local/retrieval/reranker.py`
- `backend/harness/graph/state_machine.py`
- `backend/harness/graph/loop.py`
- `backend/harness/graph/runner.py`
- `backend/tests/retrieval_planner_regression.py`
- `backend/tests/retrieval_candidate_graph_regression.py`
- `backend/tests/graph_task_runtime_facade_regression.py`
- `backend/tests/writing_graph_language_preservation_regression.py`

项目约束：

- 大改 runtime / workflow / state / API contract 必须先写计划并等待确认。
- 旧链路没有明确外部契约时应删除或迁移，不能以兼容为理由长期保留。
- 测试必须验证真实行为，不能通过降低断言、跳过测试或硬编码输出来制造通过。
- Agent prompt / runtime 设计必须体现角色、职责、边界、输入、输出和失败处理，不要把开发说明当 prompt。

## 4. 外部成熟方案参考

这些参考只用于提取成熟机制，不照搬命名或框架：

- LangGraph runtime / Pregel 文档强调图运行时以 step 状态更新和 checkpoint 组织执行，terminal 需要来自一致的状态快照，而不是局部节点完成信号。
  - https://docs.langchain.com/oss/python/langgraph/pregel
  - https://docs.langchain.com/oss/javascript/langgraph/persistence
- Qdrant hybrid search 文档将 dense / sparse 召回作为不同信号源，再统一 fusion / rerank。
  - https://qdrant.tech/documentation/search/hybrid-queries/
- Elasticsearch RRF 文档将 reciprocal rank fusion 定义为多结果集融合方法，适合不同相关性信号的候选合并。
  - https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html
- LlamaIndex query fusion 示例体现“多个 retriever -> fusion retriever -> rerank”的单一路径。
  - https://docs.llamaindex.ai/en/stable/examples/retrievers/reciprocal_rerank_fusion/

本项目应借鉴的是结构不变量：召回信号分离、融合权威单一、rerank 显式降级、graph checkpoint 状态一致。不要照搬框架层级或新增过重依赖。

## 5. 目标权威链

### 5.1 检索链路

```text
QueryRewriter
-> RAGQueryRouter.plan
-> RetrievalService.retrieve_execution
-> RetrievalBackend.retrieve_candidates
-> HybridRanker
-> CandidateGraphCoalescer
-> Reranker
-> RetrievalExecutionResult
```

各层职责：

- `QueryRewriter`: 只做 query normalize、关键词抽取、弱意图识别，不执行检索。
- `RAGQueryRouter.plan`: 只产出 canonical `RetrievalPlan`，包括 collections、query_mode、filters、policy、page_hints。
- `RetrievalService`: 唯一运行时检索入口，负责执行 plan、诊断、重建协调。
- `RetrievalBackend`: 只负责 dense / lexical / sparse candidate recall，不做最终业务排序。
- `HybridRanker`: 唯一融合排序权威，负责分数归一化、RRF、权重、证据增强、MMR。
- `CandidateGraphCoalescer`: 只负责同页/同对象/同文档聚合和上下文拼接，不私自决定最终策略。
- `Reranker`: 只做二阶段重排；失败时返回 typed degraded result，不允许静默切换结果语义。

### 5.2 图运行时链路

```text
GraphConfig
-> SchedulerView
-> GraphStateMachine.status_snapshot
-> GraphLoop.accept_node_result / dispatch_ready
-> GraphRunRunner
-> CheckpointStore
```

各层职责：

- `SchedulerView`: 只负责从拓扑导出 executable/start/terminal/dependency。
- `GraphStateMachine`: 唯一状态分类权威，必须同时看 node status 和 active work。
- `GraphLoop`: 只应用节点结果、产生 work order、写 checkpoint。
- `GraphRunRunner`: 执行 active work，不能重新定义 terminal 语义。
- `CheckpointStore`: 只记录 state，不修正 state。

## 6. 设计决策

### 6.1 重建并发

采用“同集合单飞 + pending coalescing”：

- 同一个 collection 同时只允许一个实际 rebuild。
- 如果 rebuild 期间又收到请求，记录 pending generation。
- 当前 rebuild 完成后，如果 pending generation 存在，立即再执行一次 rebuild。
- 返回值必须区分 `rebuilt`、`rebuild_already_running_pending`、`rebuilt_after_pending`、`error`。
- 不引入后台线程，不改变 API 同步语义，先保证结果正确。

### 6.2 缓存失效

采用写路径主动失效：

- `_write_units()` 写入成功后必须清 `_units_cache[collection]`。
- `_build_collection_lexical()` 已清 `_lexical_cache`，保留并补充测试。
- 如果后续引入 metadata cache，所有 build/rebuild 写路径必须统一经由 cache invalidation helper。

### 6.3 混合排序

先不强制切到 Qdrant sparse vectors，避免一次性改变存储结构。第一阶段在现有 dense + application BM25 基础上抽出 `HybridRanker`：

- 每个召回通道输出 `CandidateHit`，包含 `channel`、`rank`、`raw_score`、`normalized_score`、`doc_id`、`page`、`object_ref_id`。
- 分数归一化以 query-local 为主：dense 使用 bounded similarity，BM25 使用 min-max 或 saturation normalization。
- 初始 final score:
  - `weighted_rrf`
  - `weighted_normalized_score`
  - `corroboration_boost`，用饱和函数限制多命中刷分
  - `mode_policy_boost`，如 page lookup 强化 page filter 命中
- 使用 MMR 或轻量 diversity pass 控制同一页面/同一文档霸榜。
- cross-encoder / remote rerank 作为二阶段，不负责弥补召回错误。

### 6.4 页码解析

页码解析权威放在 router planning 层：

- `_page_hints()` 支持阿拉伯数字和中文数字。
- `QueryRewriter` 的 `pdf_page` 判断和 router filter 使用同一 parser，避免分类和过滤分裂。
- 中文数字范围先覆盖 `零一二三四五六七八九十百两` 组合，失败时返回空 hints 但保留 `query_type` 诊断。

### 6.5 terminal 并行语义

采用“默认等待 active work 清空”的成熟语义：

- `status_snapshot()` 在存在 running 或 active work 时不能返回 `completed`。
- terminal nodes completed 只表示“不再产生新的下游工作”，不等于整个 graph completed。
- 如果未来需要显式 short-circuit，应新增 `terminal_policy=preempt_active` 并记录 cancelled work order；本计划不实现 preempt。
- `validate()` 保留，作为防止 terminal 状态带 active work 的最后防线。

### 6.6 旧检索链路

迁移 CLI 到 `RetrievalService.retrieve_execution()`，然后删除或降级 `RAGQueryRouter.retrieve()`：

- Router 只保留 `plan()`。
- CLI 输出保持 JSON，但数据来自 `RetrievalExecutionResult.to_dict()` 或 `results`。
- 旧 `_fuse()` 如果没有其它调用，删除对应测试或改成保护新 `HybridRanker` 行为。

## 7. 分阶段实施计划

### Phase 1: 修复正确性底座

目标：

- 先修复缓存、pending、页码、terminal active work 四个明确 bug。

影响文件：

- `backend/knowledge_system/indexing/llamaindex_backend.py`
- `backend/knowledge_system/retrieval/service.py`
- `backend/capability_system/units/mcp/local/retrieval/router.py`
- `backend/capability_system/units/mcp/local/retrieval/query_rewriter.py`
- `backend/harness/graph/state_machine.py`
- `backend/harness/graph/loop.py`，仅在需要传 active work 给 state machine 时修改
- 对应 tests

完成标准：

- units 重写后同实例读取新 units。
- rebuild 期间第二次请求不会丢，至少会被 coalesced 后补跑一次。
- “第三页”“第十二页”“第 12 页”“page 12”都能得到一致 page filter。
- terminal 节点完成但仍有 active work 时 graph 状态保持 running。

禁止事项：

- 不引入后台 worker。
- 不改变现有集合目录结构。
- 不为了通过测试而放宽 `validate()`。

### Phase 2: 建立统一 HybridRanker

目标：

- 从 `LlamaIndexRetrievalBackend._fuse_hits()` 和 `CandidateGraph` 中抽出排序权威。
- 将 fusion、normalized score、evidence boost、MMR 放到单一模块。

建议新增/调整文件：

- 新增 `backend/knowledge_system/retrieval/hybrid_ranker.py`
- 新增 `backend/tests/retrieval_hybrid_ranker_regression.py`
- 修改 `backend/knowledge_system/indexing/llamaindex_backend.py`
- 修改 `backend/knowledge_system/retrieval/candidate_graph.py`

完成标准：

- dense-only、lexical-only、dense+lexical、多证据同页、同文档多页、page lookup 都有确定性测试。
- Candidate graph 不再通过 max score 隐式定义最终排名。
- score breakdown 能解释 final score 来源。

禁止事项：

- 不在 router 或 service 里临时拼 score。
- 不把 reranker 失败当作 silent heuristic success。

### Phase 3: 统一检索执行入口并清理旧链路

目标：

- `RetrievalService.retrieve_execution()` 成为唯一运行时和 CLI 检索入口。
- `RAGQueryRouter.retrieve()` 删除，或改为私有兼容 shim 并在同阶段删掉调用。

影响文件：

- `backend/capability_system/units/mcp/local/retrieval/router.py`
- `backend/capability_system/units/mcp/local/retrieval/cli.py`
- `backend/knowledge_system/retrieval/service.py`
- `backend/tests/retrieval_filter_execution_regression.py`
- `backend/tests/retrieval_evidence_packager_regression.py`
- `backend/tests/retrieval_planner_regression.py`

完成标准：

- `rg "router.retrieve|RAGQueryRouter\\(.+retrieve"` 不再发现生产调用。
- CLI query 结果来自 service execution result。
- 旧 `_fuse()` 相关测试改为新 ranker 行为测试。

禁止事项：

- 不保留两套 retrieve 结果格式长期并存。
- 不在 CLI 中复制 service 的执行逻辑。

### Phase 4: Rerank 降级显式化

目标：

- cross-encoder / remote rerank 失败时输出 typed degraded diagnostics。
- 排名可回退，但必须在结果和 diagnostics 中可见。

影响文件：

- `backend/capability_system/units/mcp/local/retrieval/reranker.py`
- `backend/knowledge_system/retrieval/service.py`
- `backend/tests/retrieval_*`

完成标准：

- 远程 rerank 异常时结果带 `rerank_backend=heuristic_fallback` 或同等 typed marker。
- `RetrievalExecutionResult.degraded_reason_typed` 能表达 rerank degraded。
- 日志和返回诊断都能说明失败阶段。

禁止事项：

- 不吞异常后只返回 heuristic 排名。
- 不把 reranker 不可用伪装成正常高质量 rerank。

### Phase 5: 图运行时并行 terminal 回归扩展

目标：

- 将 terminal active work 语义写成明确回归测试。
- 检查 runner 在并行 active work 下不会提前 completed。

影响文件：

- `backend/harness/graph/state_machine.py`
- `backend/harness/graph/loop.py`
- `backend/harness/graph/runner.py`
- `backend/tests/graph_task_runtime_facade_regression.py`
- `backend/tests/writing_graph_language_preservation_regression.py`

完成标准：

- `max_active_nodes=2` 且一个 terminal 节点先完成时，graph 保持 running，另一个 active work 可继续接受结果。
- 所有 terminal 节点完成且没有 active work 时才 completed。
- blocked / failed / waiting_human_gate 状态继续不允许 active work 残留。

禁止事项：

- 不通过清空 active_work_orders 来掩盖仍在执行的节点。
- 不让 runner 重新定义和 state machine 不一致的完成条件。

## 8. 文件级清单

| 文件 | 当前角色 | 计划动作 | 完成条件 |
| --- | --- | --- | --- |
| `backend/knowledge_system/indexing/llamaindex_backend.py` | dense/lexical 召回、fusion、cache | Phase 1 修 cache；Phase 2 移出 fusion 权威 | build/rebuild 后缓存正确；fusion 调用 HybridRanker |
| `backend/knowledge_system/retrieval/service.py` | runtime retrieval service、rebuild coordination | 实现 rebuild coalescing；承接唯一 retrieve execution | pending 不丢；service 是唯一执行入口 |
| `backend/knowledge_system/retrieval/candidate_graph.py` | 候选聚合和隐式打分 | 降级为 coalescer，移除最终排名权威 | 聚合解释完整，排序由 HybridRanker 控制 |
| `backend/knowledge_system/retrieval/hybrid_ranker.py` | 不存在 | 新增 | 统一 score normalization、RRF、boost、MMR |
| `backend/capability_system/units/mcp/local/retrieval/router.py` | plan + 旧 retrieve | 保留 plan；删除/迁移 retrieve；修 page parser | Router 不再执行检索 |
| `backend/capability_system/units/mcp/local/retrieval/query_rewriter.py` | query normalize/type detect | 和 router 共用页码 parser 或迁移 parser | 中文页码分类和 filter 一致 |
| `backend/capability_system/units/mcp/local/retrieval/cli.py` | CLI 入口 | 改用 RetrievalService | CLI 不再调用 router.retrieve |
| `backend/capability_system/units/mcp/local/retrieval/reranker.py` | rerank | 显式 typed fallback | 失败可诊断 |
| `backend/harness/graph/state_machine.py` | graph status authority | terminal 判定纳入 running/active | completed 不携带 active work |
| `backend/harness/graph/loop.py` | result accept / dispatch / checkpoint | 必要时传 active_work_orders 给 state machine | 状态写入前满足 invariant |
| `backend/harness/graph/runner.py` | work order runner | 保持执行，不重新定义 terminal | 并行 active 场景可跑完 |

## 9. 测试计划

### 聚焦测试

```powershell
python -m pytest backend/tests/retrieval_planner_regression.py -q
python -m pytest backend/tests/retrieval_candidate_graph_regression.py -q
python -m pytest backend/tests/retrieval_filter_execution_regression.py -q
python -m pytest backend/tests/retrieval_evidence_packager_regression.py -q
python -m pytest backend/tests/graph_task_runtime_facade_regression.py -q
python -m pytest backend/tests/writing_graph_language_preservation_regression.py -q
```

### 新增/改写测试

- `test_units_cache_invalidates_after_write`
- `test_rebuild_collection_consumes_pending_rebuild`
- `test_page_query_accepts_chinese_numeral_page_hint`
- `test_hybrid_ranker_blends_rrf_and_normalized_scores`
- `test_hybrid_ranker_applies_saturated_corroboration_boost`
- `test_hybrid_ranker_diversifies_same_document_results`
- `test_router_retrieve_path_removed_or_delegates_to_service`
- `test_terminal_node_completion_waits_for_active_parallel_work`

### 行为验收

- 重建后同进程检索能看到新内容。
- 并发 rebuild 不丢最后一次更新。
- 中文页码查询命中指定页。
- 并行图不会因为一个 terminal 节点先完成而提前结束。
- 检索结果 diagnostics 能解释 query plan、召回通道、fusion、rerank 和降级原因。

## 10. 迁移与切换规则

- Phase 1 可以直接修复，无需保留旧行为。
- Phase 2 引入 `HybridRanker` 时允许短期内部调用新模块，但不允许保留两套最终排序结果给上层选择。
- Phase 3 后，CLI 和 runtime 必须共用 `RetrievalService.retrieve_execution()`。
- 如果 Phase 2 排序质量测试出现回归，回滚点是 `HybridRanker` 接入点，不回滚 Phase 1 的正确性修复。
- 旧路径清理完成后必须用 `rg` 验证没有生产调用残留。

## 11. 明确不做

- 不在本轮引入新的外部向量数据库或替换 Qdrant。
- 不重写整个 ingestion pipeline。
- 不把 graph runtime 换成 LangGraph；只借鉴状态一致性和 checkpoint 不变量。
- 不触碰当前工作区内正在改动的 dynamic context / prompt accounting 文件。
- 不用兼容壳保留旧检索链路。

## 12. 预期结果

完成后系统应具备以下性质：

- 检索重建是幂等、可合并、可诊断的。
- 检索排序由单一权威模块控制，召回、融合、聚合、rerank 边界清晰。
- 查询规划和过滤闭环，中文自然查询不会掉页码约束。
- 图运行时 completed 状态严格表示没有 active work 且 terminal 条件满足。
- 后续继续做更高级算法，如 Qdrant sparse vectors、ColBERT、多查询扩展、学习排序时，有清晰插入点，不需要继续在旧链路上打补丁。

## 13. 等待确认的问题

我建议按以上方案实施。实施前只需要确认一个决策：

- CLI 是否允许从“直接输出 hits list”切换为 `RetrievalExecutionResult` 结构？推荐允许。若必须保持 CLI 旧 JSON list 格式，则 CLI 可以调用 service 后只打印 `results`，但内部仍不能走 `RAGQueryRouter.retrieve()`。
