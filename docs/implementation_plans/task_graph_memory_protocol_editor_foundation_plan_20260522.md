# 通用任务图 Memory Protocol 编辑器底座实施计划

日期：2026-05-22

## 目标

上一轮已经把运行时 formal memory 的读写、提交、refs-only 防污染和 required memory 阻断做成硬边界。本轮继续推进编辑器底座：让任务图标准视图和模板目录能够表达同一套通用 memory protocol，而不是让前端从散 metadata 和 memory matrix 里猜。

本轮不做写作任务专用逻辑，不做大规模前端视觉重构。目标是把通用协议暴露给编辑器、预检和模板系统，给后续页面实现提供稳定结构。

## 当前问题

1. `layered_graph_normalizer` 只输出 `memory_edges` 和 `memory_matrix`，没有标准化 `repository / collection / read / write / commit` 协议对象。
2. `TaskGraphStandardView` 没有 `memory_protocol` 字段，前端只能读 `diagnostics.layered_graph.memory_edges` 或自己重建模型。
3. 资源节点的 `metadata.memory_repository.collections` 支持结构化集合，但标准视图仍主要把 collection 当字符串。
4. 模板目录的 `memory_layers` 只有 collection 名称，没有 `content_requirement`、`snapshot_budget`、默认 read/write/commit 规则。
5. 预检规则分散：后端 layered issues、前端 preflight、运行时验证各自判断，缺少一个可复用的协议级 issue 源。

## 实施范围

### 1. 后端标准 memory protocol

在 `backend/task_system/compiler/layered_graph_normalizer.py` 中新增通用 `memory_protocol`：

- `repositories`
- `collections`
- `read_edges`
- `write_edges`
- `commit_edges`
- `issues`
- `summary`

协议只使用通用词：repository、collection、record、candidate、commit、selector、materialization、content requirement，不出现写作业务概念。

### 2. 标准视图输出

在 `backend/task_system/graphs/task_graph_standard_models.py` 中新增 `memory_protocol` 字段，并在 `to_dict()` 输出。

资源节点标准化时保留结构化 collection specs：

- `collection_id`
- `schema_id`
- `record_kinds`
- `content_requirement`
- `snapshot_budget`

### 3. 模板目录升级

在 `backend/task_system/editor/graph_template_catalog.py` 中让 `TaskGraphTemplateMemoryLayer` 输出 `collection_specs`，并提供通用记忆层模板：

- baseline canon
- mutable delta
- issue ledger
- artifact index

每个模板声明内容要求，避免 refs-only collection 和 canonical collection 混淆。

### 4. 协议预检

后端 memory protocol issues 至少覆盖：

- memory edge 无 repository
- read/write/commit edge 无 collection
- required read 未声明 block/fail_closed
- canonical collection 的 write/commit 没有 content requirement
- canonical collection 使用 refs-only materialization
- refs-only collection 要求 canonical_text
- write edge 缺少 source_output_key 或可 materialize 来源
- commit edge 缺少 candidate ref / approval source / record selector

### 5. 测试

补充回归：

- 标准视图输出 `memory_protocol`。
- 结构化 collection spec 能保留 content requirement。
- 协议级 issues 能抓住无 collection、refs-only 写入 canonical、commit 缺候选来源。
- 模板目录输出 collection_specs 和 content requirements。

## 不做

1. 不在通用 runtime 中加入任何写作图特判。
2. 不把前端 memory matrix 当协议权威。
3. 不做大规模 UI 页面改版。
4. 不保留“看起来兼容但无法运行”的旧模板字段作为主入口；旧 `collections` 字符串只作为摘要展示，协议入口改为 `collection_specs`。

## 验收

1. `TaskGraphStandardView.to_dict()` 包含 `memory_protocol`。
2. 新 protocol 中能直接看到 repository/collection/read/write/commit 的规范化对象。
3. 新 issues 可被标准视图和前端预检统一消费。
4. 模板目录能作为新图 memory layer 的配置来源。
5. 相关后端测试通过，既有写作图配置测试不回退。
