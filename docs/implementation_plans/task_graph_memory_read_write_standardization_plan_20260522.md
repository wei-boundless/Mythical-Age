# 通用任务图记忆库读写标准化重构计划

日期：2026-05-22

## 1. 问题定义

当前系统的记忆问题不是“写作任务提示词不够详细”，而是通用任务图缺少一套严格的记忆读写协议。结果是：图上看起来有记忆库、有读写边、有提交节点，真实运行时却可能只把 artifact 引用或空摘要写入 formal memory，下游节点拿到的不是任务事实，而是“某节点产出了几个引用”的壳。

正确的终态是：

1. 任何任务图都能用统一协议声明记忆库、集合、地址、读取选择器、写入候选、提交策略、缺失策略和可见性策略。
2. formal memory 是可继承、可审计、可恢复的任务事实权威；artifact repository 只存文件，working memory 只做运行中转。
3. 下游节点如果声明 required memory，运行时必须保证模型输入里有真实可读内容，或者在派发前 fail closed。
4. 图编辑器能把记忆配置变成通用模板和预检规则，减少复杂任务图开发门槛。
5. 写作任务可以使用世界观、人设、大纲这类业务 collection，但这些词不能进入通用 runtime 的默认逻辑。

## 2. 技术源报告

### 2.1 当前代码事实

1. `backend/memory_system/formal_memory_models.py`
   已有 formal memory 基础模型：
   - `FormalMemoryRepository`
   - `FormalMemoryCollection`
   - `FormalMemoryRecord`
   - `FormalMemoryRecordVersion`
   - `FormalMemoryTransaction`
   - `FormalMemoryReadLog`

   这是可保留的版本化存储底座，但它缺少面向图编辑器的协议对象，例如 memory address、read selector、write candidate contract、missing policy、snapshot contract。

2. `backend/memory_system/formal_memory_service.py`
   `sync_graph_spec()` 会从 memory repository 节点同步 repositories/collections。  
   `write_candidate_from_edge()` 只从 candidate 的 `canonical_text`、`payload.canonical_text`、`payload.text`、`payload.content` 取正式正文，不会根据 artifact ref 自动展开正文。  
   `select_for_node()` 能返回 `missing_required_records`，但这个缺失诊断没有被稳定提升为派发前硬门。

3. `backend/runtime/coordination_runtime/runtime.py`
   `_select_stage_working_memory_context()` 已经能根据 `_graph_memory_edge_descriptors()` 读取 formal memory。  
   `_submit_stage_working_memory_candidates()` 在没有显式候选时，会用 artifact refs 自动造 working memory candidate。这个候选通常只有 summary 和 artifact refs，没有 `canonical_text`。  
   `_readable_memory_snapshot_sections()` 只展示 `summary` 或 `canonical_text`，不会把 formal memory 的 artifact refs 展开成可读内容，也不会显式警告空壳记录。

4. `backend/runtime/coordination_runtime/memory_helpers.py`
   `_graph_memory_edge_descriptors()` 已经能归一化 graph memory edges，但 descriptor 还是散字段：`repository`、`collection`、`record_key`、`record_kind`、`on_missing`、`source_output_key` 等，没有形成一等协议。  
   `_formal_memory_write_records()` 能把 write edge 和 candidate 结合成 formal metadata，但缺少通用 materialization policy 和 canonical text 必填校验。

5. `backend/runtime/contracts/runtime_assembly_builder.py`
   `_working_memory_sections()` 能把 `formal_memory.required_records` 做成模型可见 section，但 section 只是 structured metadata。它没有统一的 snapshot rendering 规则，也没有 content budget、空壳记录警告、collection 分组展示。

6. `backend/task_system/compiler/layered_graph_normalizer.py`
   memory layer 会抽出 `memory_edges` 和 `memory_matrix`，但 `memory_matrix` 仍按 phase/resource 形成展示矩阵。它不是记忆读写协议，也不能证明某条边会产生可读 formal memory。

7. `scripts/configure_writing_modular_novel_graph.py`
   写作图已经声明了专业 collections，例如 `world_bible`、`character_baselines`、`outline_canon`、`chapter_summaries`。  
   但 `_memory_edges_for_nodes()` 仍通过 `_repository_collection()` 把读写集合压成粗集合：`baseline`、`mutable`、`manuscript`、`issues`、`artifact_refs`。这让专业 collection 停留在资源节点 metadata 里，没有成为真实 memory address。

### 2.2 已经暴露的真实故障

真实运行里出现过 committed formal memory 记录：

```text
logical_repository_id = memory.writing.baseline
collection_id = baseline
record_key = world_review
record_kind = world_review
status = committed
canonical_text = ''
summary = memory_commit_world 已产出 2 个产物引用，等待后续审核或提交。
```

这说明系统把“产物引用壳”当成正式记忆提交了。下游节点读到这种记录时，既无法知道世界观事实，也无法保证设定连续。这个问题是结构性读写协议失败，不是单个 prompt 失败。

## 3. 当前坏味道清单

这些设计要清理或降级，不能继续包装成可用能力。

1. **粗集合压扁**
   专业 collections 存在于资源节点里，但 memory edges 写成 `baseline/mutable/manuscript`。这会让检索、预算、快照、缺失判断都失去精度。

2. **artifact-ref-only 记忆伪装 canon**
   artifact refs 可以证明“有文件”，不能证明“有正式记忆正文”。没有 `canonical_text` 或授权 materialized text 的记录，不能满足 required formal memory。

3. **runtime 自动造空壳 candidate**
   `_submit_stage_working_memory_candidates()` 的 refs-only fallback 对 artifact index 可以接受，对 formal canon 是污染源。默认兜底应该收窄为 refs-only 仓库，不能对所有 write edge 都当成可提交事实。

4. **required memory 缺失但继续执行**
   `select_for_node()` 已经返回 missing required records，但派发前没有稳定阻断。复杂任务一旦在空记忆下继续跑，后面审核只是在修复已经扩散的偏移。

5. **快照展示弱**
   模型输入里看不到清晰的 repository / collection / record_key / usage instruction / canonical text 分组。空壳记录也没有明显警告，容易被模型误当成“已经有记忆”。

6. **working memory 与 formal memory 边界模糊**
   working memory 是运行切片和交接，不应该在 formal memory edge 存在时继续作为事实权威兜底。否则会出现“这次运行看起来有上下文，断点续跑后正式事实丢失”的问题。

7. **测试验证层级偏低**
   现有测试较多验证“有 policy、有 section、有 edge”，但缺少验证“下游节点模型输入中真的有非空 canonical memory”。这类测试通过不代表任务能持续运行。

## 4. 目标通用协议

新增一个通用协议族，建议命名为：

```text
TaskGraphMemoryProtocol
```

它不是新的业务模板，而是图编辑器、编译器、运行时、formal memory service 共同遵守的读写规范。

### 4.1 MemoryRepositorySpec

表达一个任务图资源库：

```text
repository_id
repository_kind: formal_memory | artifact_repository | issue_ledger | runtime_state
scope_kind: run_scoped | project_scoped | durable
scope_id
lifecycle_policy
collections[]
visibility_default
write_authority
```

规则：

1. repository 是资源节点的一等协议，不靠 node id 前缀猜。
2. `scope_kind` 决定断点续跑和跨运行共享，不能在 runtime 临时推断。
3. artifact repository 不能 masquerade 成 formal memory。

### 4.2 MemoryCollectionSpec

表达同一 repository 内的结构化集合：

```text
collection_id
title
schema_id
record_kinds[]
key_strategy
default_version_selector
retention_policy
content_requirement
snapshot_budget
```

新增 `content_requirement`：

```text
canonical_text_required
summary_required
artifact_refs_allowed
artifact_ref_only_allowed
```

例如 refs-only 的 artifact index 可以允许 `artifact_ref_only_allowed=true`；baseline canon 默认不允许空 `canonical_text`。

### 4.3 MemoryAddress

统一读写地址：

```text
repository_id
collection_id
record_key
record_kind
scope_kind
scope_id
version_selector
```

规则：

1. edge 必须能解析出 repository + collection。
2. `record_key` 是稳定事实地址，`record_kind` 是类型，不得互相替代。
3. 没有 record_key 的批量集合读取必须显式声明 selector mode 和 limit。

### 4.4 MemoryReadEdgeSpec

表达读边：

```text
edge_id
source_repository_id
target_node_id
address_selector
requirement: required | preferred | diagnostic
missing_policy: block | warn | ignore
visibility: model_visible | runtime_only
usage_instruction
snapshot_budget
version_selector
```

规则：

1. `required` 默认 `missing_policy=block`。
2. `preferred` 只能 warning，不能制造假阻断。
3. `usage_instruction` 是给 agent 的使用说明，不是开发说明。

### 4.5 MemoryWriteEdgeSpec

表达写边：

```text
edge_id
source_node_id
target_repository_id
address_rule
write_mode: candidate | commit | refs_only | issue_append
source_output_selector
candidate_contract
materialization_policy
content_requirement
idempotency_policy
```

规则：

1. `candidate` 是待审版本，不等于 committed fact。
2. `commit` 必须能追踪 candidate/ref/review/approval 来源。
3. refs-only 只能写入 artifact index 或声明允许 refs-only 的 collection。

### 4.6 MemoryCandidate

所有入库候选统一成：

```text
candidate_id
address
record_kind
record_key
summary
canonical_text
payload
artifact_refs
source_node_id
source_stage_id
source_artifact_refs
source_review_refs
content_hash
status: draft | accepted | rejected
```

硬规则：

1. formal memory 候选必须通过 content requirement。
2. 如果候选没有正文，但 write edge 要求正文，runtime 必须 materialize 或报错。
3. candidate 不允许只靠 title/summary 伪装成完整事实。

### 4.7 MemoryMaterializationPolicy

从 artifact 或 output bundle 转成 formal candidate 的通用规则：

```text
enabled
source: candidate_payload | output_bundle | accepted_artifact_refs | explicit_artifact_refs
artifact_filters
canonical_text_mode: none | full_text | excerpt | json_field | structured_payload
summary_mode
max_chars
record_rules[]
on_materialization_failure: block | warn | skip
```

规则：

1. materializer 只做“把已授权内容转成候选”，不做业务创作。
2. 默认排除 debug/report 类产物。
3. 对长文本要按 collection budget 截断或拆 record，而不是粗暴塞进一条。

### 4.8 MemoryCommitPolicy

表达候选如何成为 committed：

```text
approval_source
candidate_ref_selector
required_verdict
commit_visibility_policy
supersede_policy
reject_policy
idempotency_policy
```

规则：

1. commit 只提交已通过候选。
2. commit 成功后才对下游 required read 可见。
3. 被拒绝或被隔离版本不得被 selector 默认选中。

### 4.9 MemorySnapshotContract

模型可见记忆快照统一格式：

```text
snapshot_id
node_run_id
clock_seq
sections[]
missing_required_records[]
read_log_ids[]
content_budget
authority
```

每个 section：

```text
repository_id
collection_id
record_key
record_kind
version_id
version
usage_instruction
summary
canonical_text_excerpt
artifact_refs
content_state: canonical | materialized_artifact | refs_only | missing | invalid
```

规则：

1. required 记录必须有 `content_state=canonical` 或明确授权的 `materialized_artifact`。
2. `refs_only` 不能满足 required canonical memory。
3. 快照按 repository/collection 分组，不能只列前 20 条摘要。

### 4.10 MemoryMissingPolicy

统一缺失行为：

```text
block
warn
skip
repair_route
manual_gate
```

运行规则：

1. required + block：派发前阻断。
2. required + repair_route：进入指定修复节点或重提交流程。
3. preferred + warn：继续执行，但 timeline 和 diagnostics 必须记录。
4. missing 不能靠 working memory 或 artifact refs 静默兜底。

### 4.11 MemoryVisibilityPolicy

控制何时对下游可见：

```text
visible_after: same_clock | next_clock | after_commit | manual_release
reader_scope
status_filter
version_selector
```

规则：

1. candidate 默认不能被普通下游作为 canon 读取。
2. reviewer 可以读 candidate，producer 的后续节点读 committed。
3. 断点续跑必须使用同一 task_run_id 下的 committed visible records，隔离 invalidated records。

## 5. 层级权责

### 5.1 图编辑器

负责：

1. 让用户创建 repository / collection / read edge / write edge / commit edge。
2. 提供通用模板：baseline、mutable、issue ledger、artifact index。
3. 预检 edge 是否有可解析 address。
4. 显示哪些 memory edge 是 runtime-consumed，哪些只是 display/diagnostic。

不负责：

1. 猜业务 collection。
2. 把 artifact edge 自动当成 memory edge。
3. 用 metadata overlay 建第二套记忆真相。

### 5.2 图编译器

负责：

1. 把 canonical nodes/edges 编译成标准化 `TaskGraphMemoryProtocol`。
2. 为 runtime 提供 normalized descriptors。
3. 生成 memory matrix 作为诊断，不作为协议本体。
4. 对旧散字段做迁移诊断。

不负责：

1. 在编译期补写业务默认值。
2. 因为某个模板常见就生成隐藏写边。

### 5.3 运行时

负责：

1. 根据 read specs 读取 formal memory。
2. 在派发前执行 missing policy。
3. 根据 write specs 生成/验证 candidates。
4. 根据 materialization policy 展开 artifact 文本。
5. 根据 snapshot contract 给模型装配可读记忆。
6. 把 read/write/commit 结果写入 timeline。

不负责：

1. 替业务节点创作记忆内容。
2. 用 refs-only 记录满足 required canon。
3. 在 formal memory edge 存在时静默 fallback 到 working memory。

### 5.4 FormalMemoryService / Store

负责：

1. 版本化存储。
2. 地址解析和 scope 解析。
3. selector 查询。
4. candidate/commit/reject/invalidated 状态。
5. read log 和 transaction log。

不负责：

1. 模型输入展示文案。
2. 业务 prompt。
3. 从 artifact 中猜哪个文件该成为 canon；这由 materialization policy 指定。

### 5.5 WorkingMemory

负责：

1. 节点运行中的短期切片。
2. candidate handoff。
3. 审核、返修、交接时的临时引用。

不负责：

1. 作为断点续跑后的长期事实权威。
2. 替代 formal memory 的 required read。

### 5.6 Artifact Repository

负责：

1. 保存文件。
2. 提供 artifact refs。
3. 在授权 materialization 时提供正文。

不负责：

1. 直接成为任务事实。
2. 替代 formal memory 的版本、提交和可见性规则。

## 6. 固定运行流

### 6.1 读取流

```text
compile graph memory read edges
  -> resolve repository/collection/scope/address
  -> select committed visible versions
  -> validate content_state against requirement
  -> build MemorySnapshotContract
  -> if missing required: block/repair/manual_gate
  -> dispatch node with model-visible snapshot
```

### 6.2 写入流

```text
node result/output bundle/artifact refs
  -> select write edges
  -> extract source output
  -> build MemoryCandidate
  -> materialize canonical_text if policy allows/requires
  -> validate content_requirement
  -> write candidate version
  -> return write acknowledgement
```

### 6.3 提交流

```text
review verdict + candidate refs
  -> match commit edge
  -> validate required verdict/source approval
  -> commit candidate version
  -> set visible_after_clock
  -> supersede/reject old versions as policy declares
  -> return commit acknowledgement
```

### 6.4 断点续跑流

```text
resume same task_run_id
  -> load committed visible formal memory
  -> isolate invalidated/bad versions
  -> rerun from selected node
  -> new candidates write into same repository scope
  -> rejected/old artifacts stay in task folder but not selected by default
```

## 7. 实施计划

### 阶段一：定义通用协议模型

文件：

```text
backend/memory_system/formal_memory_models.py
backend/task_system/graphs/task_graph_models.py
backend/task_system/compiler/coordination_graph_models.py
backend/task_system/compiler/layered_graph_normalizer.py
backend/tests/formal_memory_store_regression.py
backend/tests/task_graph_standard_models_test.py
```

动作：

1. 新增或扩展通用模型：
   - `MemoryRepositorySpec`
   - `MemoryCollectionSpec`
   - `MemoryAddress`
   - `MemoryReadEdgeSpec`
   - `MemoryWriteEdgeSpec`
   - `MemoryCandidateContract`
   - `MemoryMaterializationPolicy`
   - `MemoryCommitPolicy`
   - `MemorySnapshotContract`
2. 让旧 edge metadata 能编译成新 spec，但标记 `source_compat_mode=true`。
3. 对 missing repository/collection、refs-only canon、无 commit path 的 write edge 生成 error 级预检。

完成标准：

1. 标准图视图能看到 normalized memory protocol。
2. 通用模型不包含写作、章节、世界观等业务词。
3. 旧散字段仍可迁移，但不作为新编辑器主入口。

### 阶段二：标准化 read edge selector

文件：

```text
backend/runtime/coordination_runtime/memory_helpers.py
backend/memory_system/formal_memory_service.py
backend/memory_system/formal_memory_store.py
backend/tests/formal_memory_store_regression.py
backend/tests/formal_memory_run_scope_regression.py
```

动作：

1. `_graph_memory_edge_descriptors()` 输出标准 `MemoryReadEdgeSpec`。
2. `select_for_node()` 支持 `content_requirement` 和 `content_state`。
3. 空 `canonical_text` 且 refs-only 不再满足 required canonical read。
4. read log 记录 selector、content_state、missing reason。

完成标准：

1. required read 缺正文时返回 missing，不返回伪记录。
2. preferred read 缺正文可以 warning，但 diagnostics 清楚。
3. run-scoped/project-scoped/durable scope 读取测试通过。

### 阶段三：标准化 write candidate 与 materialization

文件：

```text
backend/runtime/coordination_runtime/memory_helpers.py
backend/runtime/coordination_runtime/runtime.py
backend/memory_system/formal_memory_service.py
backend/tests/langgraph_coordination_runtime_regression.py
backend/tests/formal_memory_store_regression.py
```

动作：

1. 移除“所有 write edge 都可由 artifact refs 自动造 canon candidate”的宽兜底。
2. 增加通用 materializer：
   - 从 output bundle 指定字段取正文。
   - 从授权 artifact refs 读取 markdown/text/json。
   - 排除 debug/report 文件。
   - 按 policy 生成 summary 和 canonical_text。
3. 对 `canonical_text_required=true` 的 collection，materialize 失败即 write failure。
4. refs-only 只允许写入 `artifact_ref_only_allowed=true` 的 collection。

完成标准：

1. formal memory 不再出现新的空 canonical canon committed 记录。
2. artifact index 仍能 refs-only 工作。
3. 写作图只是通过配置使用 materializer，runtime 不识别写作节点名。

### 阶段四：提交与可见性硬化

文件：

```text
backend/runtime/coordination_runtime/runtime.py
backend/runtime/coordination_runtime/memory_helpers.py
backend/memory_system/formal_memory_store.py
backend/tests/langgraph_coordination_runtime_regression.py
```

动作：

1. commit edge 必须有 candidate ref selector、approval source 或显式 direct commit 权限。
2. commit 前验证 content requirement。
3. committed 版本写入 `visible_after_clock_seq`。
4. rejected / invalidated / superseded 版本默认不被 latest selector 选中。
5. timeline 记录 commit acknowledgement 和 content_state。

完成标准：

1. 未审核 candidate 不能通过普通 commit edge 进入 canon。
2. 空壳 candidate 不能提交到要求 canonical_text 的 collection。
3. 断点续跑能稳定读取同 task_run_id 的 committed versions。

### 阶段五：派发前 fail closed

文件：

```text
backend/runtime/coordination_runtime/runtime.py
backend/runtime/coordination_runtime/context_packet_resolver.py
backend/runtime/graph_runtime/run_monitor.py
backend/tests/langgraph_coordination_runtime_regression.py
```

动作：

1. 在 node dispatch 前检查 `MemorySnapshotContract.missing_required_records`。
2. required + block 时不派发 agent。
3. 写 timeline event：
   - `memory_required_records_missing`
   - `stage_blocked_by_memory`
4. 支持 `repair_route` / `manual_gate` 作为后续扩展，但默认不静默继续。

完成标准：

1. required formal memory 缺失时，节点状态进入 blocked 或 pending repair。
2. 用户能在运行监控里看到缺哪个 repository/collection/record_key。
3. 不再出现空记忆下继续生成下游产物。

### 阶段六：模型可见快照标准化

文件：

```text
backend/runtime/coordination_runtime/context_packet_resolver.py
backend/runtime/coordination_runtime/runtime.py
backend/runtime/contracts/runtime_assembly_builder.py
backend/runtime/execution/node_handoff_protocol.py
backend/tests/runtime_assembly_builder_test.py
```

动作：

1. 生成 `MemorySnapshotContract`。
2. 按 repository/collection 分组渲染模型可见 section。
3. 展示：
   - 地址
   - 用途
   - summary
   - canonical_text excerpt
   - content_state
   - read_log_ids
4. refs-only 空壳记录展示明确警告，不允许伪装成 canon。
5. 按 collection 配置预算，避免长文本挤掉关键短记忆。

完成标准：

1. 模型输入里能直接看到可用正式记忆正文。
2. snapshot diagnostics 能说明每条记录为什么被选中。
3. 长任务节点不会只看到 artifact ref。

### 阶段七：编辑器与模板接入

文件：

```text
backend/task_system/editor/graph_template_catalog.py
backend/task_system/graphs/task_graph_standard_models.py
frontend/src/lib/api.ts
frontend/src/components/workspace/views/task-system/*
frontend/src/components/workspace/views/task-system/taskGraphPreflight.ts
```

动作：

1. 模板 memory layers 从“集合名列表”升级为 `MemoryRepositorySpec + MemoryCollectionSpec`。
2. 边编辑器支持 read/write/commit 三类 memory edge。
3. 预检检查：
   - read edge 是否有 repository/collection。
   - required read 是否有 missing policy。
   - write edge 是否有 content requirement。
   - commit edge 是否有 candidate/ref/approval 来源。
   - refs-only 是否只进入允许 collection。
4. 图编辑器提供通用 memory templates：
   - baseline canon
   - mutable delta
   - issue ledger
   - artifact index
   - runtime state

完成标准：

1. 新任务图能从模板快速生成标准记忆层。
2. 用户不需要手写散 metadata 才能配置记忆。
3. 发布前能发现“看起来配了但 runtime 读不到”的图。

### 阶段八：写作图迁移到通用协议

文件：

```text
scripts/configure_writing_modular_novel_graph.py
backend/tests/writing_modular_novel_graph_config_regression.py
backend/tests/writing_professional_runtime_regression.py
```

动作：

1. 移除 `_repository_collection()` 对专业 collection 的压扁逻辑。
2. 按写作业务声明具体 collection address：
   - `world_bible`
   - `world_element_cards`
   - `character_baselines`
   - `relationship_baselines`
   - `outline_canon`
   - `outline_thread_index`
   - `chapter_summaries`
   - `manuscript_fact_index`
   - `scene_continuity`
3. 让提交节点通过通用 materialization policy 写正式记忆。
4. 让写手/审核节点通过通用 read specs 拿快照。

完成标准：

1. 写作图不再依赖粗 `baseline/mutable/manuscript` collection。
2. 下游节点能读到非空世界观、人设、大纲、章节事实。
3. 通用 runtime 仍不出现写作业务特判。

### 阶段九：清理旧残留

文件：

```text
backend/runtime/coordination_runtime/runtime.py
backend/runtime/coordination_runtime/memory_helpers.py
backend/task_system/graphs/task_graph_models.py
backend/task_system/editor/graph_template_catalog.py
frontend/src/components/workspace/views/task-system/*
```

动作：

1. 删除或隔离旧 `working_memory` 散字段作为 formal memory 主路径的用法。
2. 删除 refs-only canon fallback。
3. 删除主编辑器里不能被 runtime 消费的 memory overlay。
4. 旧图迁移只保留在 migration diagnostics，不在新图主路径展示。

完成标准：

1. 新协议成为主路径。
2. 旧逻辑不再在新任务图里静默生效。
3. 没有为了兼容保留的用户可见噪声入口。

## 8. 测试与验收矩阵

### 8.1 单元测试

1. `FormalMemoryStore`
   - candidate -> commit -> select。
   - empty canonical_text 不满足 canonical required read。
   - invalidated/rejected/superseded 默认不被选中。

2. `FormalMemoryService`
   - repository scope 解析。
   - collection content requirement。
   - missing required records。

3. `memory_helpers`
   - edge descriptor 标准化。
   - source_output_selector 提取。
   - materialization 成功/失败。

### 8.2 运行时测试

1. required memory 缺失阻断 node dispatch。
2. refs-only artifact index 不污染 formal canon。
3. materialized artifact text 成功入库。
4. commit edge 校验 review verdict。
5. 断点续跑使用同一 task_run_id 的 committed memory。

### 8.3 编辑器/编译测试

1. memory repository spec 编译进 standard view。
2. read/write/commit edge 都有 normalized memory protocol。
3. 预检能抓出：
   - memory edge without collection
   - required read without missing policy
   - refs-only write to canonical collection
   - commit without candidate source
4. display-only matrix 不被当成 runtime protocol。

### 8.4 写作图回归测试

1. `memory_commit_world` 后，formal memory 存在非空 `world_bible`。
2. `character_design` 的快照包含世界观 canon。
3. `outline_design` 的快照包含世界观和角色基准。
4. `chapter_draft` 的快照包含大纲、上一批摘要、活跃伏笔或连续性记录。
5. 空壳 committed record 不能满足写作 required memory。

## 9. 迁移与切换规则

1. 新协议先 shadow 编译，输出 diagnostics，不立刻删除旧图。
2. 写入路径先切：新任务图默认使用标准 write/materialization/commit；旧图进入 compatibility mode。
3. 读取路径后切：required read 按新 content requirement fail closed。
4. 对历史空壳记录增加维护脚本或诊断：
   - `canonical_text = ''`
   - `artifact_refs_json != '[]'`
   - `status = committed`
   - collection 不允许 refs-only
5. 这类记录应标记 invalidated/quarantined，不能继续被 latest committed selector 选中。
6. 旧散字段保留到迁移完成后删除，不在编辑器主路径显示。

## 10. 风险控制

| 风险 | 控制 |
|---|---|
| 通用协议被写作业务污染 | 协议只使用 repository/collection/address/candidate/commit 等通用词，写作词只留在写作图配置 |
| materialization 把 debug report 写进 canon | 默认排除 debug/report 路径，collection 级白名单 |
| 长文本挤爆上下文 | collection 级 snapshot budget，必要时拆分 element records |
| required memory 阻断导致任务跑不动 | 缺失诊断必须指出 repository/collection/record_key，并支持 repair route |
| 旧图断点续跑受影响 | shadow/cutover 双阶段，旧图 compatibility mode 明确标记 |
| working memory 被过早废弃 | working memory 保留为运行中转，只是不再作为 formal required memory 的静默兜底 |
| 测试只测配置不测真实可读 | 新增“模型输入中含非空 canonical_text”的端到端断言 |

## 11. 文件级执行清单

### 必改

```text
backend/memory_system/formal_memory_models.py
backend/memory_system/formal_memory_service.py
backend/memory_system/formal_memory_store.py
backend/runtime/coordination_runtime/memory_helpers.py
backend/runtime/coordination_runtime/runtime.py
backend/runtime/coordination_runtime/context_packet_resolver.py
backend/runtime/contracts/runtime_assembly_builder.py
backend/task_system/compiler/layered_graph_normalizer.py
backend/task_system/compiler/coordination_graph_models.py
backend/task_system/graphs/task_graph_models.py
backend/task_system/graphs/task_graph_standard_models.py
backend/task_system/editor/graph_template_catalog.py
scripts/configure_writing_modular_novel_graph.py
```

### 前端接入

```text
frontend/src/lib/api.ts
frontend/src/components/workspace/views/task-system/taskGraphPreflight.ts
frontend/src/components/workspace/views/task-system/TaskGraphObjectInspector.tsx
frontend/src/components/workspace/views/task-system/TaskGraphTopologyPage.tsx
frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
frontend/src/components/workspace/views/task-system/TaskGraphExecutionPackagePanel.tsx
```

### 测试

```text
backend/tests/formal_memory_store_regression.py
backend/tests/formal_memory_run_scope_regression.py
backend/tests/langgraph_coordination_runtime_regression.py
backend/tests/runtime_assembly_builder_test.py
backend/tests/task_graph_standard_models_test.py
backend/tests/writing_modular_novel_graph_config_regression.py
backend/tests/writing_professional_runtime_regression.py
```

### 维护

```text
backend/maintenance/
docs/implementation_plans/writing_formal_memory_commit_repair_plan_20260522.md
```

## 12. 最终验收标准

这次重构完成后，必须做到：

1. 新任务图能用通用 memory protocol 配置 repository、collection、read、write、commit。
2. formal memory 不再把 refs-only 空壳记录当成 required canon。
3. required memory 缺失时，节点不会被派发。
4. 模型可见快照包含清晰的地址、用途、正文摘要、content_state 和缺失诊断。
5. working memory 与 formal memory 的职责分离清楚。
6. artifact repository 只作为文件存储和 materialization 来源，不直接成为事实权威。
7. 图编辑器提供可复用的标准记忆层模板和严格预检。
8. 写作图迁移后可以作为复杂任务验证样板，但 runtime 不出现写作特判。
9. 旧空壳记录能被识别、隔离或失效，不继续污染断点续跑。
10. 回归测试能证明下游节点真实读到非空正式记忆，而不是只证明有 edge 或 section。

