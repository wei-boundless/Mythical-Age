# 022-GraphHarness节点边记忆与循环状态机重构计划书

状态：重构前计划书  
日期：2026-05-30  
范围：仅 Graph Harness / 图任务运行链路，不包含 rollout，不改其它任务结构  
目标：图编辑器发布出的图配置可以直接、稳定、无二次对齐地对接 Graph Runtime / Graph Loop

## 0. 结论

本次重构的核心不是继续给现有 Graph Harness 补分支，而是重新锁定图任务运行的四个权威边界：

```text
节点契约 = agent 装配合同
边契约 = 上游内容向下游上下文增加什么的通信合同
记忆契约 = 跨时序上下文的读取、写入、可见性合同
输出契约 = 模型输出如何切分、验收、落盘、登记、进入产物区的合同
运行时/循环 = GraphRuntime 负责拓扑与静态装配，GraphLoop 负责循环控制与动态状态推进
```

其中最重要的纠偏是：

```text
边契约不是下游完整上下文。
边契约只定义下游上下文里允许新增哪些来自上游的内容、以什么字段、什么摘要方式、什么证据引用进入。
```

正确运行链路应为：

```text
TaskGraphDefinition
  -> GraphCompiler / Publisher
  -> GraphRuntimePlan / GraphHarnessConfig
  -> GraphRuntime
  -> GraphRuntimeEnvelope / StaticTopologyView
  -> GraphLoop
  -> GraphStateMachine / LoopEngine
  -> NodeContractAssembler
  -> EdgeContextAssembler
  -> MemoryContextAssembler
  -> OutputPolicyResolver
  -> GraphNodeExecutor
  -> Output / Artifact / Memory / Checkpoint
  -> GraphLoop.advance
```

Graph Harness 只消费图编辑器和编译器发布出的确定配置。运行期不得再根据节点名、任务族、旧字段或临时 prompt 拼接来“猜”合同。

本计划中的纠偏目标是：

```text
GraphRuntime 负责图拓扑、静态合同索引、运行 envelope、资源/权限/记忆/产物 scope 装配。
GraphLoop 负责基于 GraphRuntime 静态装配结果推进循环、节点状态、边状态、checkpoint 和 resume。
GraphStateMachine 是 GraphLoop 内部的状态归约器。
LoopEngine 是 GraphLoop 内部的循环变量解析器。
```

## 1. 当前问题

### 1.1 症状

近期写作图任务暴露出以下问题：

- `world_review` 等节点可能收不到它需要审核的上游正文或产物文本。
- 下游节点上下文可能混入不该出现的其它节点 prompts 或全局 prompts。
- 图运行可能同时出现 active work order 和 graph `blocked`，状态语义互相冲突。
- checkpoint 恢复可能选到旧状态，导致断点重续位置不稳定。
- `blocked` 同时承载模型失败、契约缺输入、审核返修、人工等待、运行异常等不同含义。
- 写作任务中的记忆读取、写入、审核、提交边界不够硬，容易造成正文节点、审核节点、记忆提交节点职责混淆。
- 写作任务虽然绑定了 `env.creation.writing`，但产物不一定能出现在创作环境产物区，因为输出政策、节点产物根、环境产物根、产物库索引和前端筛选没有被同一合同锁定。

### 1.2 代码事实与根因

这些问题不是单点 bug，而是运行架构缺少统一不变量：

- 当前 `backend/harness/graph/runtime.py` 中 `GraphRuntime` 的职责是锁定发布配置、创建 `TaskRun` / `GraphRun` / `GraphRuntimeEnvelope`，并写入启动事件。它的代码注释明确说明：`It does not decide node readiness or execute agents`。
- 当前 `backend/harness/graph/loop.py` 中 `GraphLoop` 实际承担动态推进：初始化 node / edge state、计算 ready nodes、dispatch work order、accept node result、更新 edge state、处理 loop route、写 checkpoint、更新 formal run。
- 这个分层原则本身是正确的：Runtime 做静态装配，Loop 做动态控制。问题不在于 GraphLoop 负责循环控制，而在于 GraphLoop 当前实现里混入了过多应由独立契约装配器、错误语义分类器、checkpoint store 保证的细节。
- 当前 `backend/harness/graph/context_materializer.py` 在 `GraphLoop.dispatch_ready` 下被调用，负责生成 agent 可见 input package；它应被拆成节点契约、边契约、记忆契约装配器，由 GraphLoop 编排调用，而不是让 Loop 内部隐式拼上下文。
- 当前 `backend/harness/graph/resume.py` 依赖 GraphLoop 读取 checkpoint、重连 active work order、重排 blocked nodes；恢复可以由 Loop 执行，但必须受状态机不变量约束，不能把业务语义和运行恢复混成一个 `blocked` 分支。
- 节点契约、边契约、记忆契约、循环变量、运行状态没有被统一解析成一次节点执行的可审计合同。
- GraphRuntime 目前静态装配偏薄，缺少明确的 `StaticTopologyView / GraphRuntimePlan` 输出，导致 GraphLoop 后续需要直接读 raw config、临时算 scheduler view、临时取 contract bindings。
- 当前写作图脚本 `scripts/configure_writing_modular_novel_graph.py` 为每个节点生成了 `artifact_policy` / `artifact_targets`，但没有独立的 `output_policy`。因此“模型最终回答的哪些部分是正文、哪些部分是审查报告、哪些部分必须落盘、哪些登记到创作环境产物区、哪些进入正式作品库”没有一等合同。
- 当前写作图常量 `ARTIFACT_ROOT = "output/novel_artifacts/modular_novel/runs"` 会进入节点 `artifact_policy.default_artifact_root`。这会优先于创作环境解析出的 `storage/task_environments/creation/writing/artifacts`，导致物理落盘位置和创作环境产物区预期不一致。
- 创作环境定义 `env.creation.writing` 的 `artifact_policy.artifact_root` 是逻辑仓库 `repo.writing.artifact_repository`，文件 profile 中该仓库的 root 是 `artifact://writing/manuscript`。但当前 Graph work order executor 主要把 artifact root 当成本地路径解析，没有先通过文件管理 profile 把逻辑 repo root 投影到环境产物区。
- 前端产物区通过 `/memory/artifacts/overview` 读取 artifact repository 索引，且部分页面默认按 `task_run_id` 过滤。如果产物只写了文件、没有登记索引，或登记在 graph root task_run_id 而页面筛的是 node executor task_run_id，就会出现“任务写了东西但产物区看不到”。
- edge payload 虽然在部分运行状态里存在，但未被作为模型可见输入合同稳定进入节点装配。
- runtime compiler / prompt compiler 层存在过滤或重组上下文的可能，导致图契约已经授权的输入在模型侧消失。
- resume 层有恢复动作，但没有严格区分“恢复执行现场”和“替业务状态机做裁决”。

正确方向不是把 GraphLoop 消灭，也不是把动态控制塞回 GraphRuntime。正确方向是：

```text
GraphRuntime 把图拓扑、静态合同、scope、运行 envelope 装配成稳定输入。
GraphLoop 只基于这些稳定输入推进循环和状态。
契约装配、上下文投影、记忆快照、错误分类从 GraphLoop 的杂糅逻辑中拆成明确组件。
```

## 2. 依据与约束

本计划对齐以下现有设计文档和代码事实：

- `docs/系统框架/007-图任务系统架构设计书-20260528.md`：任务图权威是 `TaskGraphDefinition`，harness 只消费编译后的运行合同。
- `docs/系统框架/004-图编辑器契约统一化框架报告-20260529.md`：图、节点、边的 `contract_bindings` 应成为统一契约权威。
- `docs/系统框架/015-Prompts系统框架设计书-20260529.md`：agent prompt 必须描述角色、职责、边界、输入、输出、判断标准，不能写成开发说明。
- `docs/系统规划/208-写作任务流程记忆防污染与持续运行优化方案-20260521.md`：写作任务必须保证记忆库读写边界、审核提交边界、正文提交边界清晰。
- 当前代码链路中 `backend/harness/graph/*`、`backend/harness/runtime/compiler.py`、`backend/query/runtime.py` 是本次审查和重构的核心范围。

执行约束：

- 不碰 rollout。
- 不改无关任务结构。
- 不保留旧 Graph Harness 决策链路作为兼容兜底。
- 不用特定写作节点名修补通用图运行问题。
- 不通过 mock、硬编码产出或降低验证标准来制造通过。

## 2.5 图编辑器到 Runtime / Loop 的代码审视

结论：现有代码已经具备直接对接 GraphRuntime / GraphLoop 的一部分基础，但还不能算严格完成。底层模型和发布器能承载大多数信息，前端编辑器也能编辑不少字段；缺口在于这些字段还没有全部收敛成一等 canonical contract，运行侧也还没有完全按 resolved contract 装配节点输入。

### 2.5.1 已经具备的基础

后端图模型已有这些承载能力：

- `TaskGraphNodeDefinition` 已包含 `agent_id`、`executor_policy`、`contract_bindings`、`memory_read_policy`、`memory_writeback_policy`、`dynamic_memory_read_policy`、`artifact_policy`、`loop`、`execution_mode`、`wait_policy`、`join_policy`。
- `TaskGraphEdgeDefinition` 已包含 `payload_contract_id`、`contract_bindings`、`context_filter_policy`、`artifact_ref_policy`、`working_memory_handoff_policy`、`failure_policy`、`result_delivery_policy`。
- `TaskGraphDefinition` 已包含 `contract_bindings`、`runtime_policy`、`context_policy`、`loop_frames`、`working_memory_policy`。
- `normalize_*_contract_bindings` 已经把图、节点、边的部分旧字段归并进 `contract_bindings`。

发布器已有这些能力：

- `graph_harness_config_publisher.build_graph_harness_config_from_graph` 能发布 `control`、`nodes`、`edges`、`loop_frames`、`resources`、`memory`、`artifacts`、`contracts`。
- `_build_protocol_indexes` 会生成 `node_protocol_index` 和 `edge_protocol_index`，并对 payload contract、source output key、target input key 做部分对齐检查。
- `_node_config` 会保留节点 `contract_bindings`、prompt、memory、artifact、runtime/loop 信息。
- `_edge_config` 会保留边 `contract_bindings`、context filter、artifact ref、working memory handoff、temporal/revision metadata。
- `layered_graph_normalizer` 能从 `memory_repository` 资源节点和 `memory_*` 边派生 `memory_protocol`，这是拓扑驱动记忆协议的正确方向。

前端编辑器已有这些能力：

- `taskGraphSaveMapper` 会把图、节点、边字段规范化写回 `contract_bindings`。
- `TaskGraphContractBindingInspector` 可编辑 `schema`、`execution`、`memory`、`artifact`、`handoff`、`acceptance`、`runtime`、`temporal`、`governance`。
- `TaskGraphNodeUnitInspector` 可编辑节点身份、任务绑定、Agent、节点契约、执行策略、artifact target。
- `TaskGraphPortEdgeInspector` 可编辑边端点、payload contract、handoff 策略、context/temporal/memory handoff 的一部分字段。
- `TaskGraphMemoryArtifactPage` 已经把记忆仓库、collection、读写矩阵、selector、version selector、commit visibility 做成图拓扑编辑入口。
- `taskGraphPreflight` 已经有 memory repository、memory selector、memory commit path、revision edge、artifact、batch contract 等预检。

这些说明：目标不是重做整个图编辑器，而是把已经分散存在的能力收敛成严格的协议编辑与发布链路。

### 2.5.2 当前不能宣称完成的缺口

现状还不能说“图编辑器编辑出的配置可以无损直接驱动 GraphRuntime / GraphLoop”，原因如下：

1. 节点契约还不是一等 AgentAssembly。

   当前节点装配分散在 `agent_id`、`executor_policy`、`metadata.runtime_profile`、`contract_bindings.execution`、`contract_bindings.runtime.model_requirement`、prompt metadata 等位置。编辑器能填字段，但没有一个清晰的 `NodeContract / AgentAssembly` 视图来保证：

   ```text
   role prompt
   model profile / model mode / reasoning policy
   tool policy
   skill policy
   output policy
   memory permission
   acceptance policy
   ```

   都被同一个节点契约锁定并发布。

2. `output` 契约不是一等 section。

   后端 `CONTRACT_BINDING_SECTIONS` 当前没有 `output`。前端 `TaskGraphContractBindingInspector` 和 `taskGraphSaveMapper` 也没有 first-class `output_policy`。这会迫使运行侧继续从 `artifact_policy` 或 final answer 中猜“哪些内容应落盘、登记、进入创作环境产物区、进入正式作品库”。

3. 边契约还缺少完整的上下文增量协议。

   当前边已有 `payload_contract_id`、`context_filter_policy`、`artifact_ref_policy`、`working_memory_handoff_policy`，也能做部分 protocol alignment。但编辑器还没有把以下内容作为 canonical edge contract 强制编辑：

   ```text
   source_output_selector
   target_context_key
   projection_policy
   required_payload_fields
   visibility_policy
   loop_binding
   receipt_policy
   ```

   因此现在只能部分保证“下游多了什么上游内容”，还不能严格保证每条边的投影字段、目标上下文键和动态循环变量都被契约锁死。

4. 记忆协议方向正确，但字段仍主要落在 metadata。

   记忆仓库节点和 `memory_read / memory_write_candidate / memory_commit` 边已经能派生 `memory_protocol`。但 selector、repository、collection、record_key、version_selector、usage_instruction、commit_visibility_policy 当前主要存在边 `metadata` 中。它能工作，但还不是最干净的 canonical memory contract。

   目标应是：

   ```text
   memory repository node = logical repository / collection / schema / namespace policy
   memory edge = read/write/commit protocol
   runtime = per graph task namespace resolution
   materializer = resolved MemorySnapshot
   ```

5. 拓扑和动态控制在 UI 上还没有完全拆清。

   当前 `TaskGraphTopologyPage` 能编辑节点/边拓扑和资源流；`taskGraphLoopConfig` 能编辑 loop frame 初始输入、长度预算、批次参数。但编辑器还没有一个完整的“静态状态机设置 + 动态控制契约”视图来表达：

   ```text
   start / terminal nodes
   dependency / context / commit edge role
   node ready condition
   edge activation condition
   loop frame route policy
   iteration variables
   checkpoint / resume policy
   blocked / retry / human gate semantics
   ```

6. 运行侧目前还没有完全消费 resolved contract。

   `GraphContextMaterializer` 会生成 `input_package`，其中包含 `inbound_context`、`memory_view`、`artifact_view`、`runtime_profile`、`expected_result_contract`。但 `memory_view` 当前主要是 read rules / protocol summary / policy view，不等于已经读取并放进模型可见上下文的 `ResolvedMemorySnapshot`。

   也就是说，图编辑器目前能表达“这个节点应该读什么记忆”，发布器能派生 memory protocol，但运行时还需要补齐：

   ```text
   memory protocol + loop variables + graph state -> resolved memory snapshot -> model-visible input package
   ```

7. 前端标准视图和保存结构仍有旧字段旁路。

   保存链路仍会保留 `metadata`、旧 contract 字段、部分 legacy 字段，并通过 normalize 合并。这对迁移有帮助，但重构完成后不能让 runtime 从旧字段兜底猜合同。旧字段只能作为编辑器迁移输入，发布前必须归一到 canonical contract。

### 2.5.3 目标图编辑器信息架构

图编辑器必须按运行权威拆成四类编辑面，而不是让用户在散字段里猜：

```text
节点页：
  AgentAssembly
  NodeContract
  OutputPolicy
  MemoryPermission
  AcceptancePolicy

边页：
  EdgeContract
  SourceOutputSelector
  TargetContextKey
  ProjectionPolicy
  Visibility / Failure / Receipt

记忆页：
  MemoryRepositoryNode
  CollectionSpec
  MemoryReadContract
  MemoryWriteCandidateContract
  MemoryCommitContract
  NamespacePolicy

拓扑/控制页：
  StaticTopology
  StateMachinePolicy
  LoopFrameContract
  DynamicControlContract
  CheckpointResumePolicy
```

编辑器保存出的结构必须满足：

```text
TaskGraphDefinition
  nodes[].contract_bindings.execution = NodeContract / AgentAssembly
  nodes[].contract_bindings.output = OutputPolicy
  edges[].contract_bindings.handoff = EdgeContract
  edges[].contract_bindings.memory = MemoryEdgeContract
  graph.contract_bindings.runtime = StaticStateMachine / GraphRuntime policy
  graph.loop_frames[] = DynamicControlContract / LoopFrameContract
```

### 2.5.4 发布器和运行时的对齐要求

发布器必须成为唯一归一化边界：

```text
TaskGraphDefinition
  -> canonical contract validation
  -> GraphHarnessConfig
  -> StaticTopologyView
  -> GraphRuntimeEnvelope
```

发布器必须 fail fast：

- 节点缺 AgentAssembly 必须报错，不能运行时回退默认 Agent。
- 边缺 `target_context_key` 或 `source_output_selector` 时，不能让下游节点自己猜。
- 必需 memory read 缺 repository / collection / selector 时必须阻断。
- 必需 output policy 缺产物目标或创作环境投影时必须阻断。
- loop frame 缺 route / exit / variable binding 时必须阻断。

运行时只能消费发布后的 canonical structure：

```text
GraphRuntime consumes:
  StaticTopologyView
  ContractIndex
  ResourceIndex
  MemoryNamespacePlan
  OutputRepositoryPlan

GraphLoop consumes:
  GraphRunState
  StaticTopologyView
  ResolvedLoopVariables
  ResolvedNodeRunContract
  ResolvedEdgeContext
  ResolvedMemorySnapshot
```

禁止运行时继续从节点名、旧 metadata、任务脚本常量里补上下文或补产物路径。

## 3. 目标架构

目标模块关系：

```text
GraphHarness
  owns: 对外启动/恢复入口、服务依赖注入、API/CLI 适配
  calls: GraphRuntime

GraphRuntime
  owns: 发布配置锁定、图拓扑静态装配、静态合同索引、GraphRun/TaskRun/Envelope、资源/权限/记忆/产物 scope
  calls: GraphLoop
  does not own: 动态 ready 判定、循环路由、节点执行调度、直接拼模型 prompt

GraphLoop
  owns: 动态状态推进、循环控制、ready/running/blocked/completed 判定、work order dispatch、accept result、checkpoint、resume
  calls: GraphStateMachine, LoopEngine, NodeContractAssembler, EdgeContextAssembler, MemoryContextAssembler, GraphNodeExecutor
  does not own: 静态拓扑生成、节点名特判、隐式上下文扩权、模型 prompt 内容裁决

GraphStateMachine
  owns: 图状态推进、不变量校验、事件归约、ready/running/blocked/completed 判定
  does not own: prompt 拼装、模型调用、记忆检索实现

LoopEngine
  owns: 循环帧、迭代变量、章节范围、批次范围、循环退出条件
  does not own: 图运行事实源、节点模型选择、边 payload 内容裁剪、checkpoint 提交

NodeContractAssembler
  owns: 根据节点契约装配 agent role、prompt、model、mode、tools、skills、artifact policy、memory permission
  does not own: 上游内容选择

EdgeContextAssembler
  owns: 根据边契约把上游输出投影成下游新增上下文
  does not own: 节点自有 prompt、记忆库查询

MemoryContextAssembler
  owns: 根据记忆契约和循环变量生成 memory snapshot / memory pack / write receipt
  does not own: 边的上游内容传递

OutputPolicyResolver
  owns: 模型输出切分、结构化输出抽取、正文/报告/回执分类、落盘目标、产物库登记目标、正式作品提交边界
  does not own: 模型执行、边上下文授权、记忆提交裁决

GraphNodeExecutor
  owns: 执行单个节点 work order，调用 AgentHarness 或其它执行单元
  does not own: 图拓扑推进、下游 ready 判定、输出政策解释

CheckpointStore
  owns: revision/event_cursor 有序持久化和恢复读取
  does not own: 业务语义修复
```

## 4. 核心数据模型

### 4.1 GraphRunState

运行实例的唯一状态源。

必须包含：

```text
graph_run_id
graph_config_ref
status
revision
event_cursor
node_states
edge_states
loop_frames
active_work_orders
ready_node_ids
blocked_reasons
artifact_refs
memory_refs
created_at
updated_at
```

`revision` 和 `event_cursor` 必须单调递增。checkpoint 恢复必须按数值版本读取最新状态，不能依赖字符串排序或文件枚举顺序。

### 4.2 NodeState

节点运行状态。

```text
node_id
status
attempt
current_loop_frame_id
current_iteration_key
last_input_contract_ref
last_output_ref
last_error
started_at
completed_at
```

节点状态只描述该节点是否可执行、执行中、完成、阻塞、失败、等待人工，不保存其它节点的完整上下文。

### 4.3 EdgeState

边的交接状态。

```text
edge_id
source_node_id
target_node_id
status
source_output_ref
resolved_payload_ref
visibility_receipt
failure_reason
```

边状态表示“这条边是否已经把授权内容交给下游”。它不等于下游节点完整输入。

### 4.4 LoopFrameState

循环帧状态。

```text
loop_frame_id
loop_type
owner_node_id
iteration_index
iteration_key
variables
bounds
exit_condition
status
cursor
```

章节写作中的第 10 章、第 20 章差异必须通过 `variables` 表达，而不是生成两套不同协议。

### 4.5 Contract Templates

运行前的稳定模板：

```text
NodeContractTemplate
EdgeContractTemplate
MemoryContractTemplate
OutputPolicyTemplate
LoopContractTemplate
```

运行中的解析结果：

```text
ResolvedNodeRunContract
ResolvedEdgeContext
ResolvedMemorySnapshot
ResolvedOutputPolicy
ResolvedLoopVariables
```

原则：

```text
稳定模板 + 当前 loop variables + graph state refs = 本轮 resolved contract
```

## 5. GraphRuntime / GraphLoop / 状态机设计

GraphRuntime 和 GraphLoop 的分工必须稳定：

```text
GraphRuntime:
  负责拓扑和静态装配。
  读取发布后的 GraphHarnessConfig。
  校验 config hash。
  生成 GraphRun / TaskRun / GraphRuntimeEnvelope。
  生成 StaticTopologyView / contract index / scope index。
  把静态装配结果交给 GraphLoop。

GraphLoop:
  负责循环控制和动态状态推进。
  初始化 GraphRunState。
  根据拓扑和 edge state 计算 ready。
  根据 loop frame 解析动态变量。
  编排节点/边/记忆契约装配。
  dispatch work order。
  accept NodeResultEnvelope。
  更新 node state / edge state / loop state。
  写 checkpoint。
  执行 resume。
```

目标固定流程：

```text
GraphRuntime.start
  -> load published GraphHarnessConfig
  -> validate content hash
  -> build static topology / contract / scope indexes
  -> create GraphRun / TaskRun / GraphRuntimeEnvelope
  -> GraphLoop.initialize(static_runtime_view, envelope)

GraphLoop.advance
  -> apply GraphTransitionEvent through GraphStateMachine
  -> ask LoopEngine for current loop variables
  -> resolve node / edge / memory contracts
  -> validate resolved node run contract
  -> create GraphNodeWorkOrder
  -> execute or dispatch work order
  -> accept NodeResultEnvelope
  -> commit artifacts / memory receipts
  -> commit checkpoint
  -> continue until wait / blocked / completed / failed
```

`GraphLoop` 现有代码里承担的 `initialize`、`dispatch_ready`、`accept_node_result`、`requeue_blocked_nodes_and_checkpoint` 属于动态控制职责，可以保留在 GraphLoop；但其内部必须拆出状态机、循环变量、契约装配、错误语义和 checkpoint store，不允许继续通过散落分支隐式决定上下文或恢复语义。

GraphStateMachine 的唯一形式是：

```text
GraphRunState + GraphTransitionEvent -> GraphRunState
```

允许事件：

```text
graph_started
node_ready
work_order_created
node_started
node_completed
node_failed
node_blocked
edge_payload_resolved
edge_payload_failed
loop_iteration_started
loop_iteration_completed
loop_exited
memory_snapshot_resolved
memory_commit_completed
human_gate_waiting
human_gate_resolved
checkpoint_committed
resume_requested
resume_completed
graph_completed
graph_failed
```

必须强制的不变量：

```text
有 active_work_orders 时，graph.status 不得是 blocked / completed / failed。
blocked 节点不得出现在 ready_node_ids。
running 节点必须有 active work order。
completed 节点不得有 active work order。
下游节点 ready 只能来自依赖边 ready，不得由节点名或业务脚本直接推进。
source_failed 必须指向真实 failed / blocked 的 source node 或 edge。
latest checkpoint 必须按 revision / event_cursor 读取。
resume 不得修改业务裁决，只能恢复可恢复的执行现场。
```

## 6. 节点契约

节点契约只负责 agent / executor 装配。

节点契约字段应覆盖：

```text
node_id
executor_type
agent_profile_ref
role_prompt
task_prompt_template
model_policy
reasoning_policy
tool_policy
skill_policy
input_schema
output_schema
output_policy
artifact_policy
memory_permission
acceptance_policy
timeout_policy
retry_policy
```

节点 prompt 必须是给 agent 看的角色说明，不得写成运行时开发说明。

例如审核节点应表达为：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你需要指出问题、给出裁决、说明是否允许进入下一阶段。
```

不允许表达为：

```text
这是 runtime 节点。
根据任务图执行 world_review。
这个节点用于校验资产。
```

模型模式、推理模式、工具、skills 都必须来自节点契约解析。写作链路当前以跑通拓扑为先时，可以统一关闭推理模式和 agent 工具绑定，但这个关闭也必须体现在节点契约或图级默认策略里，不能运行时临时覆盖。

## 7. 输出契约

输出契约负责“节点执行结果如何成为系统可追踪产物”。它不同于 artifact policy：

```text
OutputPolicy:
  定义模型最终输出的结构、分段、验收、抽取、落盘、索引和可见性。

ArtifactPolicy:
  定义已被 OutputPolicy 接受的内容写到哪里、以什么路径、登记到哪个产物仓库。
```

输出契约字段应覆盖：

```text
output_contract_id
output_kind
primary_content_key
structured_sections
required_sections
content_extraction_policy
acceptance_metrics
artifact_materialization_policy
artifact_repository_policy
environment_projection_policy
official_work_commit_policy
visibility_policy
failure_policy
```

写作图必须至少区分：

```text
project_brief        -> 启动包
world_candidate      -> 世界观候选正文
world_review         -> 审核报告
world_commit         -> 基准提交回执
chapter_outline      -> 章节细纲
chapter_draft        -> 章节正文草稿
chapter_review       -> 章节审核报告
chapter_batch_commit -> 章节提交回执
final_manuscript     -> 正式汇编稿
```

`chapter_draft` 的输出政策必须明确：

```text
primary_content_key: chapter_draft_text
required_sections:
  - 写前取材判断
  - 章节正文候选
artifact_materialization_policy:
  required: true
  target_repository_id: repo.writing.artifact_repository
  target_collection_id: draft_workspace 或 chapter_drafts
  environment_artifact_area: env.creation.writing
official_work_commit_policy:
  commit_required: false
  committed_only_after: chapter_review + memory_commit_chapter
```

也就是说，写手节点可以产出创作 artifact，但不能直接写正式作品库；正式作品或正文记忆必须等审核与提交节点完成。

当前写作图只有 `artifact_policy/artifact_targets`，缺少一等 `output_policy`。重构时必须把 `output_policy` 加进节点契约，并让 GraphNodeExecutor 只执行已经解析好的 `ResolvedOutputPolicy`，不能自己猜 final answer 应该如何落盘。

## 8. 边契约

边契约只负责“上游向下游新增什么内容”。

边契约字段应覆盖：

```text
edge_id
source_node_id
source_port
target_node_id
target_port
payload_contract_id
source_output_selector
target_context_key
projection_policy
visibility_policy
required_payload_fields
failure_policy
loop_binding
receipt_policy
```

例子：

```text
world_design -> world_review
  source_output_selector: artifact.world_design.draft_text
  target_context_key: upstream.world_design.draft_text
  required_payload_fields: [text, artifact_ref, version]
```

这表示 `world_review` 的上下文里会新增 `upstream.world_design.draft_text`，不表示 `world_review` 的完整上下文只来自这条边。

边契约不得做以下事情：

- 不得携带整张图的 prompts。
- 不得把所有上游节点输出默认塞给下游。
- 不得替记忆契约读取跨章节记忆。
- 不得替节点契约决定模型、工具、skills。
- 不得让下游访问未经授权的候选稿、审核意见或提交包。

## 9. 记忆契约

记忆契约负责跨时序上下文，不属于普通上游边 payload。

记忆系统的标准不是“每个任务一个物理记忆库”。标准应是：

```text
集中式物理存储 + 分布式逻辑管理 + 契约化读写授权
```

物理层：

```text
storage/formal_memory/formal_memory.sqlite
```

逻辑层：

```text
environment_id
project_id / scope_id
graph_id / graph_run_id
logical_repository_id
effective_repository_id
collection_id
record_key
version_id
source_node_id
source_edge_id
source_node_run_id
visible_after_clock
```

这表示所有正式记忆可以集中存储在一个索引库中，但逻辑记忆库必须由任务拓扑图声明，并在一次图任务启动时实例化出本任务自己的 namespace。节点只能通过拓扑图里的 memory repository 节点、memory edge 和 memory contract 读取被授权的 logical repository / collection，不能直接按物理路径访问，也不能跨任务混读混写。

当前代码事实：

```text
MemoryRuntimeServices(layout.storage_root)
  -> FormalMemoryService(storage/formal_memory)
  -> FormalMemoryStore(storage/formal_memory/formal_memory.sqlite)

FormalMemoryService.resolve_repository_scope()
  -> run_scoped: run:{task_run_id}:{logical_repository_id}
  -> project_scoped: project:{project_id}:{logical_repository_id}
  -> durable: {logical_repository_id}
```

拓扑驱动的目标语义：

```text
Graph topology:
  memory repository nodes define logical repositories.
  memory_read / memory_commit edges define which node can read or write which collection.

GraphRuntime.start:
  creates graph_task_memory_namespace for this graph task instance.
  binds every topology memory repository node into that namespace.
  writes namespace_id into GraphRuntimeEnvelope and GraphRunState.

GraphLoop.resume:
  reloads the same namespace_id from checkpoint.
  never creates a new memory namespace during resume.

Different graph task instances:
  must use different namespace_id by default.
  cannot share memory unless an explicit import / durable repository contract says so.
```

当前仍有三个必须修正的风险：

1. 写作图当前把 `memory.writing.*` 仓库声明为 `project_scoped`。这会让不同图任务可能因为同一个 project_id 混到同一套记忆里，不符合“一次任务一个记忆 namespace”的默认原则。
2. `GraphRuntime._graph_runtime_scope` 在没有显式 `project_id` / `scope_id` 时会生成 `project_id = graphrun.{graph_run_id}`。这虽然避免了空 scope，但语义上仍然是 project scope，不是明确的 graph task memory namespace。
3. 写作图资源节点同时出现 `node_id = memory.writing.baseline` 和 `repository_id = writing_modular_baseline`，但 metadata 里的 `memory_repository.repository_id` 又写成了节点 id。读写边使用的是 `memory.writing.baseline`。后续实现必须统一 logical repository id，不能让资源节点 id、展示 id、formal memory logical id 三者漂移。

目标标准：

```text
physical_store:
  storage/formal_memory/formal_memory.sqlite

graph_task_memory_namespace:
  required for graph tasks
  namespace_id = graphmem:{graph_run_id} or graphmem:{root_task_run_id}
  created once at GraphRuntime.start
  persisted in GraphRunState checkpoint
  reused by resume
  default isolation: one graph task instance, one namespace

logical_repository_id:
  memory.writing.baseline
  memory.writing.mutable
  memory.writing.manuscript
  memory.writing.artifact_index
  memory.writing.issue_ledger

effective_repository_id:
  graphmem:{namespace_id}:{logical_repository_id}

collection:
  world_bible / outline_canon / chapter_summaries / approved_chapter_batches / ...
```

`project_scoped` 和 `durable` 只能用于显式共享库，例如长期项目知识、跨任务素材库、用户明确指定的公共世界设定库。写作图主流程的 baseline / mutable / manuscript 默认不得 project-wide 共享，否则两个写作任务会污染同一套正文事实。

写作图中的基本原则：

- 正式写手需要读取固定记忆库中的相关记忆，但优先通过运行时 memory pack / snapshot 协议装配，不依赖 agent 自己调用记忆工具。
- 审核员可以带必要上下文记忆，但其写权限只能指向 issue ledger 或审核结果，不得污染 baseline / mutable canon。
- 记忆提交节点是记忆写入权威，正文节点和审核节点不得直接写 canon。
- memory read / write 都是契约，绑定在节点契约、边契约和记忆契约的组合解析结果上。

记忆契约字段：

```text
memory_contract_id
logical_repository_id
repository_refs
read_topics
read_window_template
loop_variable_bindings
required_visibility
missing_policy
write_policy
commit_authority
receipt_schema
```

动态循环示例：

```text
MemoryContractTemplate:
  repository_refs: [memory.writing.baseline, memory.writing.mutable]
  read_window_template:
    baseline: all_committed_core
    mutable:
      previous_chapters: chapter_index in [current_chapter - 3, current_chapter - 1]
      outline_slice: volume_id == current_volume

Resolved at chapter 10:
  previous_chapters: 7..9

Resolved at chapter 20:
  previous_chapters: 17..19
```

这里变化的是变量，不是协议。

## 10. LoopEngine 与动态契约

LoopEngine 是 GraphLoop 调用的循环算法组件，不是图运行权威。它负责循环变量解析，不负责拼 prompt，不负责 dispatch，不负责 checkpoint。

必须支持的循环类型：

```text
bounded_count_loop
metric_loop
router_loop
nested_loop
```

章节写作是一种典型 bounded count loop：

```text
target_words = 1000000
chapter_words = 2000
target_chapters = 500
observability_target = 50
```

当前实测可以只观察到 50 章，但图任务目标仍是一百万字。断点重续必须能从最近 committed checkpoint 和 committed memory refs 继续。

LoopEngine 输出：

```text
current_iteration_key
current_chapter_index
current_volume_id
current_word_target
memory_window_variables
edge_projection_variables
exit_condition_status
```

每轮节点执行前：

```text
NodeContractTemplate
EdgeContractTemplate
MemoryContractTemplate
LoopFrameState.variables
GraphRunState.refs
  -> ResolvedNodeRunContract
```

## 11. 输入装配链路

单个节点的最终模型可见输入必须由以下部分组成：

```text
node_self_context
initial_graph_inputs
graph_runtime_state_projection
loop_variables
resolved_edge_contexts
resolved_memory_snapshots
authorized_artifact_refs
human_gate_payloads
```

装配顺序：

```text
1. GraphRuntime 提供静态拓扑、合同索引和 envelope。
2. GraphLoop 载入当前 GraphRunState。
3. GraphStateMachine 判断节点 ready。
4. LoopEngine 解析本轮 loop variables。
5. NodeContractAssembler 解析节点 agent 装配合同。
6. EdgeContextAssembler 解析所有入边授权 payload。
7. MemoryContextAssembler 解析记忆快照。
8. OutputPolicyResolver 解析输出政策。
9. InputContractValidator 检查 required fields。
10. Runtime compiler 将 resolved contract 转为 AgentHarness 输入。
11. GraphNodeExecutor 执行节点。
```

关键要求：

```text
runtime compiler 不得删除模型可见的 graph input context。
profile 过滤不得隐藏 contract 标记为 required_visibility 的 edge context 或 memory snapshot。
如果必须隐藏，必须 fail closed，不能让节点空跑。
```

## 12. 输出到创作环境产物区

创作环境产物区必须由环境和产物库共同决定，不能由写作图脚本私自写死本地目录。

当前代码链路：

```text
env.creation.writing
  -> artifact_policy.artifact_root = repo.writing.artifact_repository
  -> file_profile.writing_manuscript
  -> repo.writing.artifact_repository
  -> root_ref = artifact://writing/manuscript

scripts/configure_writing_modular_novel_graph.py
  -> ARTIFACT_ROOT = output/novel_artifacts/modular_novel/runs
  -> node.artifact_policy.default_artifact_root = ARTIFACT_ROOT

GraphNodeWorkOrderExecutor
  -> _contract_artifact_root 优先使用 node policy default_artifact_root
  -> 文件落到 output/novel_artifacts/...
  -> _artifact_materialization_receipts 再登记 artifact repository

Frontend artifact store
  -> /memory/artifacts/overview
  -> 默认按 task_run_id / repository filters 展示索引
```

因此用户在创作环境里看不到产物，可能有四种真实原因：

1. 节点还没有成功完成，`NodeResultEnvelope` 没有 artifact refs。
2. 文件写到了 `output/novel_artifacts/...`，不是环境产物区 `storage/task_environments/creation/writing/artifacts` 或文件管理 profile 投影路径。
3. artifact repository 没有登记，或登记失败但被节点错误语义吞掉。
4. 前端按错误的 `task_run_id` 过滤：产物登记在 graph root task_run_id，页面筛的是 node executor task_run_id，或反过来。

重构目标：

```text
OutputPolicy.target_environment_id = env.creation.writing
OutputPolicy.target_repository_id = repo.writing.artifact_repository
OutputPolicy.target_collection_id = node/output kind 对应集合
ArtifactPolicy.path_template = 相对产物路径
EnvironmentProjection.resolve(repo.writing.artifact_repository) -> 创作环境产物区真实 root
ArtifactRepository.record_materialization 使用 graph root task_run_id + graph_run_id + node_run_id 全量索引
Frontend 支持 graph_run_id / task_run_id / node_run_id 三种定位，不让用户猜筛选项
```

写作图不应再用 `output/novel_artifacts/modular_novel/runs` 作为主产物根。它可以作为迁移期旧产物目录，但新链路必须以创作环境 artifact repository 为权威。

## 13. 错误语义与恢复

必须拆分状态和错误类型：

```text
recoverable_model_error
contract_input_missing
edge_payload_missing
memory_snapshot_missing
review_revise_required
human_gate_waiting
executor_timeout
checkpoint_corrupted
fatal_failed
```

`blocked` 只能作为需要外部动作或明确前置条件未满足的状态，不再混用所有异常。

恢复规则：

- provider 临时错误、executor 重启、进程中断：允许 resume。
- checkpoint 读取旧版本：修 checkpoint 读取和 revision 选择，不允许业务绕过。
- contract input missing：不允许 resume 伪造输入，必须修边契约或上游产物。
- review revise：进入返修边或审核循环，不是系统恢复。
- human gate waiting：等待人工事件，不是失败。
- fatal_failed：需要人工处理或重新启动图运行。

## 14. 实施计划

### Phase 1：模型清理与权威边界锁定

目标：

- 梳理 `backend/harness/graph/models.py` 和相关配置模型。
- 明确 `GraphRunState`、`NodeState`、`EdgeState`、`LoopFrameState`。
- 增加 `OutputPolicyTemplate` / `ResolvedOutputPolicy`，把输出政策从 artifact policy 中拆出来。
- 删除或迁移旧的 `upstream_results`、`handoff_packets`、隐式 prompt 汇总等重复链路。

完成标准：

- 图状态只有一个权威结构。
- 节点输出政策有一等结构，不再由 GraphNodeExecutor 猜 final answer。
- 旧链路不再被 runtime 消费。
- 节点、边、记忆、循环模板和 resolved contract 命名清晰。

### Phase 2：GraphRuntime 静态装配强化

目标：

- 保持既定分工：GraphRuntime 负责图拓扑和静态装配，不负责循环控制。
- 在 GraphRuntime 中生成稳定的 `StaticTopologyView`、`contract index`、`scope index`。
- GraphRuntime 必须要求写作图提供真实 `project_id` / `scope_id`，不能默认把 `graph_run_id` 当作长期创作项目作用域。
- GraphRuntime 必须根据拓扑图创建 `graph_task_memory_namespace`，并把 namespace 写进 envelope / checkpoint。
- GraphLoop 不再直接反复扫描 raw config 推断拓扑和合同，而是消费 GraphRuntime 的静态装配结果。

完成标准：

- `GraphRuntime` 输出的静态视图能覆盖 node index、edge index、入边/出边、start/terminal nodes、contract bindings、scope。
- `GraphLoop` 的动态推进只依赖静态视图和 GraphRunState。
- 静态拓扑问题在 Runtime 阶段 fail fast，不进入 Loop 后再猜。
- 每次图任务启动只创建一套逻辑记忆 namespace；断点恢复必须复用同一套 namespace。
- 不同 graph_run / root task_run 默认不能读写同一套 baseline / mutable / manuscript。

### Phase 3：GraphStateMachine 重写

目标：

- 新建或重写状态机核心。
- 所有推进都由 event reducer 完成。
- ready / running / blocked / completed / failed 由统一不变量检查。

完成标准：

- active work order 与 graph blocked 不再共存。
- 下游 ready 只由依赖边状态推出。
- 单元测试覆盖并行、失败、返修、人工等待、完成。

### Phase 4：LoopEngine 重写

目标：

- 把章节、批次、循环变量从节点执行代码里拆出。
- 动态契约只改变变量，不改变模板。

完成标准：

- 第 10 章和第 20 章使用同一记忆契约模板。
- loop frame 可 checkpoint / resume。
- 一百万字目标和前 50 章观察目标能同时表达。

### Phase 5：契约装配器拆分

目标：

- 实现 `NodeContractAssembler`、`EdgeContextAssembler`、`MemoryContextAssembler`、`OutputPolicyResolver`。
- 节点装配、边传递、记忆读取、输出政策四者独立。

完成标准：

- 节点不会看到未授权 prompts。
- 下游只收到边契约授权的上游内容。
- memory snapshot 按记忆契约进入模型可见上下文。
- 记忆读写统一使用 logical_repository_id，不混用资源节点 id 和展示 repository_id。
- 记忆读写必须携带 graph_task_memory_namespace，不允许只靠 repository_id 解析。
- 输出政策决定模型输出如何落盘和登记产物库。
- agent 工具绑定不再被临时用作写作记忆读取通道。

### Phase 6：创作环境产物区闭环

目标：

- 写作图产物根改为创作环境 artifact repository 投影。
- GraphNodeExecutor 不再把逻辑 repo id 当成本地路径。
- ArtifactRepository 索引同时支持 graph root task_run_id、node executor task_run_id、graph_run_id、node_run_id 查询。
- 前端产物区显示当前创作环境和当前 graph_run 的产物。

完成标准：

- `chapter_draft` 完成后，创作环境产物区能看到对应 draft artifact。
- `chapter_review` 完成后，产物区能看到 review artifact。
- `memory_commit_chapter` 完成后，产物区能看到 commit receipt artifact。
- 用户无需手动猜 node task_run_id 才能看到产物。

### Phase 7：checkpoint 与 resume 修正

目标：

- checkpoint 按 revision / event_cursor 读取最新状态。
- resume 只恢复执行现场，不替业务状态机裁决。

完成标准：

- 中断后恢复到最近 committed checkpoint。
- active work order、node state、edge state、loop frame 一致。
- stale checkpoint 不会覆盖新状态。

### Phase 8：runtime compiler 集成

目标：

- Graph resolved contract 到 AgentHarness 输入的投影稳定。
- 修正 profile 过滤导致 required graph context 消失的问题。

完成标准：

- 有 required edge context 的节点，模型输入中必定可见该 section。
- 有 required memory snapshot 的节点，模型输入中必定可见该 section。
- 缺失时 fail closed，并给出可诊断 receipt。

### Phase 9：写作图实测

目标：

- 用写作图验证架构链路。
- 先跑通到正文节点稳定产出，再观察前 50 章推进。

完成标准：

- seed 能进入世界观设计节点。
- world_review 能收到 world_design 授权产物。
- 正式写手能收到章节目标、必要记忆快照和授权上游上下文。
- 审核节点只看到它应审核的正文、相关记忆和标准。
- memory commit 节点只提交审核通过内容。
- checkpoint 后可恢复继续跑。

## 15. 文件级执行清单

预计涉及：

```text
backend/harness/graph/models.py
backend/harness/graph/loop.py
backend/harness/graph/runtime.py
backend/harness/graph/resume.py
backend/harness/graph/work_order_executor.py
backend/artifact_system/artifact_repository_service.py
backend/harness/graph/langgraph_checkpoint_store.py
backend/harness/runtime/compiler.py
backend/query/runtime.py
backend/tests/graph_task_runtime_facade_regression.py
backend/tests/writing_agent_runtime_professional_regression.py
```

可能新增：

```text
backend/harness/graph/state_machine.py
backend/harness/graph/loop_engine.py
backend/harness/graph/contract_assembler.py
backend/harness/graph/output_policy.py
backend/harness/graph/context_assembler.py
backend/tests/graph_state_machine_regression.py
backend/tests/graph_contract_assembly_regression.py
backend/tests/graph_output_policy_regression.py
backend/tests/graph_checkpoint_resume_regression.py
```

禁止涉及：

```text
rollout
无关前端页面结构
无关 task run 控制链
无关 query/chat 普通对话链
```

如果实施中发现某个必要改动会跨出以上范围，必须暂停并说明原因，不能顺手改。

## 16. 验证标准

最低测试矩阵：

```text
节点契约：
  - 模型、模式、prompt、工具、skills 来自节点契约。
  - 节点不接收其它节点 prompts。

边契约：
  - 下游只收到入边授权 payload。
  - 缺 required payload 时 fail closed。
  - 审核节点能收到被审核正文。

记忆契约：
  - 有 memory read contract 的节点获得 memory snapshot。
  - 写手通过 runtime memory pack 读记忆，不依赖 agent 工具绑定。
  - 记忆提交节点只提交审核通过内容。
  - 正式记忆物理存储集中在 storage/formal_memory/formal_memory.sqlite。
  - 写作图主流程记忆为 graph task instance scoped，effective_repository_id 为 graphmem:{namespace_id}:{logical_repository_id} 或等价任务实例作用域。
  - 一次图任务一个 namespace；resume 复用原 namespace。
  - 不同图任务默认不得共享 baseline / mutable / manuscript。
  - repository id 不混用 memory.writing.* 与 writing_modular_*。

输出契约：
  - 每个可执行节点都有 output_policy 或明确 no_artifact_output。
  - chapter_draft 的正文输出能被抽取为 primary content。
  - artifact policy 只接收 OutputPolicy 认可后的内容。
  - 产物登记包含 output_contract_id、graph_run_id、graph root task_run_id、node_run_id。

创作环境产物区：
  - 写作图产物落入 env.creation.writing 的 artifact repository。
  - 前端按当前 graph_run_id 能看到产物。
  - task_run_id 过滤不会误导用户看不到当前图产物。

循环：
  - 章节变量随 iteration 改变。
  - 契约模板不随章节复制膨胀。
  - 50 章观察目标不改变一百万字总目标。

状态机：
  - active work order 与 blocked 不冲突。
  - ready/running/completed/failed 转移满足不变量。
  - 返修、人工等待、模型失败语义可区分。

checkpoint / resume：
  - latest checkpoint 按 revision/event_cursor 选择。
  - 中断后恢复 node/edge/loop 状态一致。
  - resume 不伪造缺失 contract input。

写作图实测：
  - 能从 seed 推进到正文产出。
  - 能持续推进章节循环。
  - 能断点恢复。
```

## 17. 明确禁止事项

本次重构中禁止：

- 禁止改 rollout。
- 禁止用旧 Graph Harness 决策链路作为新链路兼容兜底。
- 禁止把所有 prompts 或所有上游产物塞进单个节点。
- 禁止把边契约理解成下游完整上下文。
- 禁止把记忆读取降级为 agent 自己随意调用工具。
- 禁止 runtime 根据节点名补上下文。
- 禁止用写死的 `output/novel_artifacts/...` 作为新写作图主产物区。
- 禁止 GraphNodeExecutor 绕过 OutputPolicy 直接猜 final answer 落盘语义。
- 禁止把写作主流程 baseline / mutable / manuscript 默认做成 project-wide 共享库。
- 禁止 resume 重新创建新的记忆 namespace。
- 禁止资源节点 id、logical_repository_id、展示 repository_id 三套命名并行漂移。
- 禁止 profile 过滤静默隐藏 required edge context / memory snapshot。
- 禁止 resume 伪造业务输入或替审核循环做裁决。
- 禁止为了测试通过硬编码写作输出。

## 18. 交付判定

本重构完成的判定不是“某个节点不报错”，而是以下链条全部成立：

```text
图编辑器配置
  -> 发布配置
  -> 节点契约装配 agent
  -> 边契约精确传递上游授权内容
  -> 记忆契约按循环变量装配跨时序上下文
  -> 输出契约决定模型输出如何落盘、登记和进入创作环境产物区
  -> 状态机按拓扑和循环推进
  -> checkpoint 精确保存
  -> resume 精确恢复
  -> 写作图稳定产出正文
```

只有这条链路成立，才算 Graph Harness 重构完成。
