# 39-TaskGraphIR 与 LangGraph 执行底座统一重构计划书

日期：2026-05-09

## 1. 目标

本计划书用于判断并规划：在现有任务系统框架下，是否可以把单任务、多 Agent 任务、任务图编辑器、RunLoop 和 LangGraph 底层统一起来，形成真正的“图编辑器 + 图语言 + 执行编译器”体系。

结论先行：

- 可以统一图化。
- 流程性很强、协作边界明确、需要长期运行和恢复的任务适合使用图来运行。
- 通用 Agent 架构必须保留；图只是任务组织形式，不替代 Agent 自主处理能力。
- 单任务可以在运行时被规范化为最小任务图，但不强迫用户显式建图。
- 编辑器是任务能力制造台，不是运行入口附属物。用户可以先打造任务图能力，暂时不用运行。
- 不建议 fork 或直接修改第三方 LangGraph 源码。
- 应建立 `TaskGraphIR` 作为任务系统唯一图事实源，再编译为 LangGraph 可执行计划。
- LangGraph 应作为运行时执行引擎、checkpoint 引擎、interrupt/人工门控引擎、并发 superstep 引擎，而不是前端编辑器的数据模型本身。

## 2. 当前结构判断

### 2.1 已经存在的任务图资产层

当前 `backend/tasks/task_graph_models.py` 已有 `TaskGraphDefinition`：

- `graph_id`
- `graph_kind`
- `entry_node_id`
- `output_node_id`
- `nodes`
- `edges`
- `graph_contract_id`
- `default_protocol_id`
- `working_memory_policy_profile_id`
- `working_memory_policy`
- `runtime_policy`
- `context_policy`
- `publish_state`

节点模型已包含：

- `node_type`
- `task_id`
- `agent_id`
- `agent_group_id`
- `node_contract_id`
- `input_contract_id`
- `output_contract_id`
- `projection_overlay_id`
- `memory_read_policy`
- `memory_writeback_policy`
- `dynamic_memory_read_policy`
- `execution_mode`
- `wait_policy`
- `join_policy`
- `background_policy`
- `notification_policy`
- `resource_lifecycle_policy`

边模型已包含：

- `source_node_id`
- `target_node_id`
- `edge_type`
- `a2a_message_type`
- `payload_contract_id`
- `context_filter_policy`
- `artifact_ref_policy`
- `working_memory_handoff_policy`
- `ack_policy`
- `timeout_policy`
- `wait_policy`
- `failure_propagation_policy`
- `result_delivery_policy`

这说明任务图资产层已经接近目标 IR，只是还没有被提升为全系统唯一事实源。

### 2.2 当前仍存在的双轨问题

当前系统至少有三套相近但未完全统一的表达：

1. `SpecificTaskRecord`
   - 单任务定义。
   - 目前仍像“非图任务”。

2. `CoordinationTask + TopologyTemplate + CommunicationProtocol`
   - 多 Agent 协调任务的旧组合结构。
   - `graph_nodes` / `graph_edges` 仍挂在 coordination task 和 topology draft 上。

3. `TaskGraphDefinition`
   - 新任务图资产。
   - `TaskFlowRegistry.list_task_graphs()` 会从 `coordination_tasks` 兼容生成 graph。

问题不在于图模型不存在，而在于当前事实源还没有收敛。

### 2.3 当前 LangGraph 使用方式

当前后端已有两条 LangGraph 相关链路：

1. `backend/orchestration/runtime_loop/langgraph_coordination_runner.py`
   - 用 `StateGraph` 遍历 `CoordinationGraphSpec`。
   - 明确标记为 planning-only。
   - 不负责真实运行。

2. `backend/orchestration/runtime_loop/langgraph_coordination_runtime.py`
   - 使用固定的 `StateGraph`：
     - `stage_accept`
     - `route_next`
     - `stage_prepare`
     - `stage_execute`
     - `blocked`
     - `complete`
   - 它不是直接按用户画布动态生成 LangGraph 节点。
   - 它把任务图编译为 stage contracts，然后用固定状态机推进。

这条路线是正确的雏形：用户画布不应该直接等于 LangGraph 源码图，而应该编译为一个运行计划。

## 3. 外部参考：LangGraph 能提供什么

基于 LangGraph 官方 API 文档和本地 Python 包接口检查，LangGraph 的关键机制包括：

- `StateGraph` 是共享状态图，节点读取 state 并返回 partial state update。
- state key 可用 reducer 聚合多节点写入，适合并发节点输出合并。
- 图需要 `compile()` 后执行。
- compiled graph 可配置 checkpointer、store、interrupt before/after。
- checkpointer 以 `thread_id` 管理一系列 checkpoint，可保存每个 superstep 的状态。
- `interrupt` / `Command` 可用于人工门控和恢复。
- `Send` / `Command` 可表达动态路由和动态并发。

参考：

- LangGraph `StateGraph` API：<https://langchain-ai.github.io/langgraphjs/reference/classes/langgraph.StateGraph.html>
- LangGraph checkpoint 概念：<https://langchain-ai.github.io/langgraphjs/reference/modules/langgraph-checkpoint.html>
- LangGraph `interrupt` API：<https://langchain-ai.github.io/langgraphjs/reference/functions/langgraph.interrupt-2.html>
- LangGraph compiled graph / Pregel 运行模型：<https://langchain-ai.github.io/langgraphjs/reference/classes/langgraph.CompiledGraph.html>

本地 Python 包也确认：

- `StateGraph.compile(checkpointer=None, cache=None, store=None, interrupt_before=None, interrupt_after=None, debug=False, name=None)`
- `langgraph.types.Command`
- `langgraph.types.Send`
- `langgraph.types.interrupt`

## 4. 关键判断：不要直接修改 LangGraph 源码

### 4.1 不直接 fork 的原因

不建议直接修改 LangGraph 的第三方源码，原因：

- LangGraph 是运行时框架，不是我们的产品级任务资产模型。
- 我们需要维护任务域、任务、契约、Agent 授权、投影、工作记忆、任务长期记忆、A2A 通信、RunLoop 事件，这些都超出 LangGraph 的核心职责。
- 直接 fork 会让升级困难，也会把业务语义污染到通用执行框架里。
- 编辑器需要稳定 IR、DSL、校验器、可视化布局，不应该依赖 LangGraph 内部类结构。

### 4.2 应该修改的是“LangGraph 适配层”

正确做法：

```text
前端图编辑器
  -> TaskGraphIR
  -> TaskGraphDSL
  -> TaskGraphValidator
  -> RuntimeManifest / ContractManifest
  -> LangGraphExecutionPlan
  -> LangGraph StateGraph
  -> TaskRunLoop
  -> AgentRun / NodeRun / Memory / Artifact
```

也就是说，我们不是改 LangGraph，而是新增一个足够强的 `TaskGraphIR -> LangGraph` 编译器。

## 5. 目标架构

### 5.0 图化边界

图化的目标不是把所有 Agent 行为都变成流程图。

图编辑器的定位必须单独明确：

- 编辑器是“打造任务能力”的地方。
- 它不依赖当前是否要运行任务。
- 它不要求用户先进入任务模式。
- 它不因为某个任务暂时不用，就不允许构建该任务图。
- 它产出的任务图是可保存、可审计、可复用、可发布、可运行的资产。

也就是说，图编辑器类似制造武器：武器可以不用，但制造能力本身必须存在。

必须保留三种任务形态：

1. 即时 Agent 任务
   - 主 Agent 直接理解、规划、调用工具或子 Agent。
   - 用户不需要创建任务域、任务或任务图。
   - 系统可以在运行时生成临时最小图用于追踪生命周期、权限、记忆和输出，但不暴露为必须编辑的资产。

2. 可复用单任务
   - 用户希望保存一个任务能力，但流程仍然简单。
   - 系统提供默认最小图。
   - 用户可以不打开图编辑器。

3. 流程型任务图
   - 适合长篇小说、健康系统修复、复杂研发任务、批处理流水线等流程性强的任务。
   - 用户主动使用图编辑器配置节点、边、Agent、契约、记忆和调度。
   - 这类任务图应成为 RunLoop 和 LangGraph 执行的主输入。

此外还存在第四种编辑器资产形态：

4. 待用任务图能力
   - 用户只是在编辑器中设计、保存、预检一个任务图。
   - 它可以尚未绑定具体运行入口。
   - 它可以作为模板、能力资产、任务包组成部分或后续任务的基础。
   - 它仍然必须使用正式 TaskGraphIR、契约、Agent 引用、权限和校验体系。

判断任务是否适合图化的标准：

- 是否有明确阶段。
- 是否需要多个 Agent 分工。
- 是否需要节点间结构化通信。
- 是否需要长期记忆、工作记忆或跨章节/跨阶段连续性。
- 是否需要 checkpoint、恢复、人工门控、失败重试或并行汇合。
- 是否需要复用和审计。

如果只是普通问答、临时工具调用、主 Agent 临时派发一个子 Agent，不应强迫用户建图。

但这不限制用户主动打开编辑器构建一把“暂时不用的武器”。编辑器不是自动运行链路的替代品，而是任务能力资产的生产工具。

### 5.1 唯一事实源

`TaskGraphIR` 成为任务执行结构唯一事实源。

`TaskGraphDefinition` 可以作为第一版 `TaskGraphIR` 的持久化形态，但需要补齐：

- `ir_version`
- `dsl_source`
- `layout`
- `graph_scope`
- `node_ports`
- `edge_ports`
- `compile_targets`
- `runtime_bindings`
- `validation_profile`

### 5.2 单任务图化

单任务不是特殊执行链路，而是最小图：

```text
input
  -> agent_executor
  -> output
```

单任务图的 `graph_kind = single_agent`。

这里的“单任务图化”是运行时 IR 统一，不是交互流程复杂化。

用户仍然可以通过主 Agent 直接调用子 Agent 完成大多数任务。系统可以在后台把这类调用包装成临时或默认 `single_agent` 图，用于生命周期、权限、契约、记忆、checkpoint 和输出治理。

`SpecificTaskRecord` 不再承担执行拓扑职责，只保留：

- 任务身份
- 任务描述
- 任务域归属
- 默认契约引用
- 默认投影策略
- 默认运行策略入口

真正运行时拓扑从 `TaskGraphDefinition` 读取。

### 5.3 多 Agent 任务图化

多 Agent 任务同样是 `TaskGraphIR`：

- 每个 Agent 节点绑定 `agent_id` 或 `agent_group_id`。
- 每个节点声明输入契约、输出契约、记忆读取、写回策略、执行模式。
- 每条边声明 handoff、ack、结果投递、工作记忆交接、失败传播。

### 5.4 代码语言与图语言统一

建立 `TaskGraphDSL`。

原则：

- DSL 不直接是 Python / TypeScript 任意代码。
- DSL 是 `TaskGraphIR` 的文本表达。
- 画布编辑和 DSL 编辑共享同一个 IR。
- DSL 可解析为 IR，IR 可格式化回 DSL。
- 解析失败时不得写回 IR。

示意：

```ts
graph "longform_novel" {
  node input_brief type input title "项目简报"

  node showrunner type agent {
    agent "agent.longform.showrunner"
    output "contract.novel.project_plan"
    execution sync
  }

  node chapter_writer type agent {
    agent "agent.longform.chapter_writer"
    input "contract.novel.chapter_brief"
    output "contract.novel.chapter_draft"
    execution async
    memory.read kinds ["outline", "character_state"]
  }

  edge showrunner -> chapter_writer {
    type handoff
    payload "contract.novel.chapter_brief"
    ack explicit
  }
}
```

### 5.5 LangGraph 编译目标

新增 `LangGraphExecutionPlan`，不直接暴露第三方对象：

```text
LangGraphExecutionPlan
  graph_id
  task_run_id
  thread_id
  state_schema
  node_specs
  edge_specs
  reducers
  interrupt_points
  checkpoint_policy
  dispatch_policy
  resume_policy
```

`LangGraphExecutionPlan` 再编译成 `StateGraph`。

## 6. 固定执行流

### 6.1 编辑期

输入：

- 用户在画布上的节点和边操作。
- 用户在检查器中配置契约、Agent、投影、记忆、调度策略。
- 可选 DSL 文本编辑。

输出：

- `TaskGraphIR draft`
- `TaskGraphValidationReport`
- `TaskGraphDSL`
- `GraphLayoutState`

禁止：

- 编辑器直接创建运行时对象。
- 编辑器直接写 `CoordinationRun` / `AgentRun`。
- 编辑器绕过正式 API 私下注册 Agent、契约或任务。

### 6.2 保存期

输入：

- `TaskGraphIR draft`

输出：

- `TaskGraphDefinition`
- 可选兼容生成的 `CoordinationTask / TopologyTemplate / CommunicationProtocol`

禁止：

- 把 coordination 旧组合结构继续作为主事实源。
- 保存时偷偷修改任务管理台当前选择态。

### 6.3 编译期

输入：

- `TaskGraphDefinition`
- `ContractSpec`
- `AgentRuntimeProfile`
- `TaskMemoryRequestProfile`
- `WorkingMemoryProfile`
- `TaskDurableMemoryProfile`

输出：

- `ContractManifest`
- `RuntimeAssembly`
- `LangGraphExecutionPlan`
- `TaskGraphCompileReport`

禁止：

- 编译器调用模型。
- 编译器执行工具。
- 编译器写入工作记忆正文。

### 6.4 运行期

输入：

- `LangGraphExecutionPlan`
- `TaskRun`
- `thread_id`
- 上一轮 checkpoint
- 当前事件

输出：

- `StageExecutionRequest`
- `A2A payload`
- `AgentDispatchPlan`
- checkpoint
- runtime events

禁止：

- 运行期改变任务图结构。
- 运行期把节点内部 prompt 当成图结构。
- 运行期把主会话记忆和任务工作记忆混写。

### 6.5 回收期

输入：

- 节点结果
- artifact refs
- 工作记忆写回候选
- 任务长期记忆晋升候选

输出：

- `NodeRunResult`
- `TaskGraphRunState`
- `WorkingMemoryWritebackCandidate`
- `TaskDurableMemoryPromotionCandidate`
- 用户可审查的最终交付包

禁止：

- 未经策略/人工门控直接将工作记忆晋升到任务长期记忆库。
- 将任务长期记忆写入主 Agent durable 记忆库。

## 7. 数据模型调整

### 7.1 TaskGraphDefinition 扩展

新增字段：

- `ir_version: str`
- `dsl_source: str`
- `layout: dict`
- `graph_scope: str`
- `node_ports: tuple`
- `edge_ports: tuple`
- `compile_targets: tuple[str, ...]`
- `runtime_bindings: dict`
- `validation_profile: str`

### 7.2 TaskGraphNodeDefinition 扩展

新增或规范字段：

- `node_kind`
  - `input`
  - `agent`
  - `tool`
  - `subgraph`
  - `barrier`
  - `manual_gate`
  - `memory`
  - `output`
- `ports`
- `langgraph_node_key`
- `interrupt_policy`
- `resume_policy`
- `retry_policy`
- `cache_policy`

### 7.3 TaskGraphEdgeDefinition 扩展

新增或规范字段：

- `source_port`
- `target_port`
- `condition`
- `route_expression`
- `send_policy`
- `reducer_key`
- `langgraph_edge_kind`
  - `normal`
  - `conditional`
  - `send`
  - `interrupt_resume`

### 7.4 新增编译产物

新增 `TaskGraphCompileReport`：

- `graph_id`
- `valid`
- `issues`
- `warnings`
- `compiled_node_count`
- `compiled_edge_count`
- `langgraph_features`
- `unsupported_features`
- `manifest_refs`

新增 `LangGraphExecutionPlan`：

- 只作为我们自己的中间产物。
- 不序列化第三方 LangGraph 对象。
- 可被测试、审计、展示、回放。

## 8. 模块计划

### 8.1 后端任务图模型层

影响文件：

- `backend/tasks/task_graph_models.py`
- `backend/tasks/flow_registry.py`
- `backend/api/tasks.py`
- `frontend/src/lib/api.ts`

动作：

- 扩展 `TaskGraphDefinition`。
- 保持 `task_graph_from_dict()` 对旧字段兼容读取。
- `CoordinationTask` 兼容生成 `TaskGraphDefinition`，但不再新增旧链路能力。
- API 以 `task_graphs` 为图资产主入口。

### 8.2 DSL 层

新增文件：

- `backend/tasks/task_graph_dsl.py`
- `backend/tests/task_graph_dsl_regression.py`
- `frontend/src/components/workspace/views/task-system/taskGraphDsl.ts`

动作：

- 实现 IR -> DSL formatter。
- 实现 DSL -> IR parser。
- 第一阶段只支持显式结构，不支持任意表达式求值。
- 所有 DSL 解析错误返回结构化 diagnostics。

### 8.3 LangGraph 编译层

新增文件：

- `backend/orchestration/runtime_loop/task_graph_langgraph_models.py`
- `backend/orchestration/runtime_loop/task_graph_langgraph_compiler.py`
- `backend/orchestration/runtime_loop/task_graph_langgraph_runtime.py`

动作：

- 将 `TaskGraphDefinition` 编译为 `LangGraphExecutionPlan`。
- 再由 `LangGraphExecutionPlan` 构造 `StateGraph`。
- 支持：
  - 顺序边
  - 条件边
  - barrier 汇合
  - background 节点通知
  - manual gate interrupt
  - dynamic send
  - checkpoint thread

### 8.4 RunLoop 接入层

影响文件：

- `backend/orchestration/runtime_loop/task_run_loop.py`
- `backend/orchestration/runtime_loop/langgraph_coordination_runtime.py`
- `backend/orchestration/runtime_loop/contract_compiler.py`
- `backend/orchestration/runtime_loop/runtime_assembly_builder.py`

动作：

- `TaskRunLoop` 优先查找 `TaskGraphDefinition`。
- 如果存在任务图，走 `TaskGraphIR -> LangGraphExecutionPlan`。
- 如果不存在任务图，自动生成单任务最小图。
- `langgraph_coordination_runtime.py` 逐步降级为兼容适配器。

### 8.5 前端编辑器层

影响文件：

- `frontend/src/components/workspace/views/TaskSystemView.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx`
- `frontend/src/components/workspace/views/task-system/CoordinationEditorWorkbench.tsx`
- `frontend/src/components/workspace/views/task-system/taskGraphTypes.ts`
- `frontend/src/components/workspace/views/task-system/taskGraphDraft.ts`

动作：

- 编辑器操作对象从 legacy coordination draft 改为 `TaskGraphDraft/TaskGraphIR`。
- 增加 DSL 面板，但不默认展示给普通用户。
- 单任务模板变成默认最小图。
- 节点检查器显示 Agent、投影、契约、记忆、调度策略。
- 边检查器显示 handoff、ack、条件、记忆交接、失败传播。

### 8.6 测试层

新增或扩展：

- `backend/tests/task_graph_registry_test.py`
- `backend/tests/task_graph_dsl_regression.py`
- `backend/tests/task_graph_langgraph_compiler_regression.py`
- `backend/tests/task_graph_runloop_regression.py`
- `backend/tests/task_system_api_regression.py`
- 前端 lint 与 Playwright 检查。

## 9. 阶段计划

### 阶段 1：确认 TaskGraphIR 为主事实源

目标：

- 明确 `TaskGraphDefinition` 是任务图主模型。
- 单任务也必须拥有最小任务图。

完成条件：

- `TaskGraphDefinition` 扩展字段落库。
- `SpecificTaskRecord` 可生成默认 `single_agent` 图。
- API overview 中任务图主数据完整。

禁止：

- 新增新的 coordination 专用字段作为主链路。
- 新增 shadow 模式或隐藏双轨执行。

### 阶段 2：DSL 与可逆转换

目标：

- 图语言和代码语言共享 IR。

完成条件：

- IR -> DSL -> IR 可逆测试通过。
- 错误 DSL 不会覆盖有效 IR。
- 前端可显示 DSL 预览。

禁止：

- 使用 `eval`。
- 允许任意 Python / TypeScript 混入 DSL。

### 阶段 3：LangGraphExecutionPlan

目标：

- 建立不依赖第三方对象序列化的编译产物。

完成条件：

- `TaskGraphDefinition` 可编译为 `LangGraphExecutionPlan`。
- 编译报告可解释每个节点/边如何映射到 LangGraph。
- 不支持的图能力必须 fail-closed。

禁止：

- 在编译层执行 Agent。
- 在编译层写 memory。

### 阶段 4：TaskGraphLangGraphRuntime

目标：

- 由 `LangGraphExecutionPlan` 构造 `StateGraph` 并推进运行。

完成条件：

- 支持单任务最小图。
- 支持多 Agent 顺序图。
- 支持并行节点 + barrier。
- 支持人工门控 interrupt/resume。
- 支持 checkpoint thread 恢复。

禁止：

- 修改第三方 LangGraph 包源码。
- 运行时绕过 `TaskRunLoop` 直接创建 AgentRun。

### 阶段 5：RunLoop 主路径切换

目标：

- `TaskRunLoop` 统一吃任务图。

完成条件：

- 单任务运行也通过任务图编译链。
- 多 Agent 任务通过同一编译链。
- legacy coordination runtime 只作为旧数据兼容入口。

禁止：

- 保留两个同等主路径。
- 用兼容为理由继续扩展旧 coordination 链路。

### 阶段 6：前端编辑器升级

目标：

- 编辑器成为真正的任务图 IR 编辑器。

完成条件：

- 画布与 DSL 双向同步。
- 节点/边检查器写入 TaskGraphIR。
- 保存只保存任务图，不再同时维护三套 legacy draft 作为主事实。
- 单任务模板和多 Agent 模板统一显示。

禁止：

- 编辑器自动绑定任务管理台状态。
- 编辑器直接私下注册 Agent、契约、投影。

### 阶段 7：旧链路清理

目标：

- 删除无用旧残留。

完成条件：

- `CoordinationTask.graph_nodes/graph_edges` 不再作为主写入口。
- `TopologyTemplate` 不再承担任务图主事实源职责。
- 旧测试改为验证兼容读取或删除。

禁止：

- 为了旧测试保留无运行价值的假链路。

## 10. 文件级清单

| 文件 | 当前角色 | 动作 |
|---|---|---|
| `backend/tasks/task_graph_models.py` | 新任务图模型 | 扩展为 TaskGraphIR v1 |
| `backend/tasks/flow_registry.py` | 任务资产仓库 | 以 task_graphs 为主写入口，coordination 只兼容转换 |
| `backend/api/tasks.py` | 任务系统 API | 扩展 task graph API，补 DSL/compile report 接口 |
| `backend/orchestration/runtime_loop/task_graph_langgraph_models.py` | 不存在 | 新增 LangGraphExecutionPlan 模型 |
| `backend/orchestration/runtime_loop/task_graph_langgraph_compiler.py` | 不存在 | 新增 IR -> LangGraphExecutionPlan 编译器 |
| `backend/orchestration/runtime_loop/task_graph_langgraph_runtime.py` | 不存在 | 新增 plan -> StateGraph 运行器 |
| `backend/orchestration/runtime_loop/task_run_loop.py` | RunLoop 主控 | 接入 TaskGraphIR 主路径 |
| `backend/orchestration/runtime_loop/langgraph_coordination_runtime.py` | coordination 旧运行器 | 降为兼容适配器 |
| `backend/orchestration/runtime_loop/contract_compiler.py` | 契约编译 | 输入改为 TaskGraphIR 优先 |
| `backend/orchestration/runtime_loop/runtime_assembly_builder.py` | 节点上下文装配 | 从 TaskGraphIR 节点策略读取上下文、记忆、投影 |
| `frontend/src/components/workspace/views/task-system/taskGraphTypes.ts` | 前端图类型 | 对齐 TaskGraphIR |
| `frontend/src/components/workspace/views/task-system/taskGraphDraft.ts` | legacy draft 转换 | 改为 IR draft 构造与兼容转换 |
| `frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx` | 编辑器外壳 | 变为纯 TaskGraphIR 编辑器 |
| `frontend/src/components/workspace/views/task-system/CoordinationEditorWorkbench.tsx` | 图编辑实现 | 去 coordination 命名和旧 props |
| `frontend/src/components/workspace/views/TaskSystemView.tsx` | 任务系统页面 | 管理台和编辑器继续分离，编辑器只打开任务图 |

## 11. 验证矩阵

### 11.1 后端模型

- 单任务最小图 round-trip。
- 多 Agent 图 round-trip。
- 节点 memory policy round-trip。
- 边 handoff policy round-trip。
- DSL round-trip。
- 非法 DSL 不覆盖旧 IR。

### 11.2 编译器

- 单任务图编译为一个 agent execution stage。
- 顺序多节点图编译为顺序 LangGraph plan。
- 并行节点编译为 reducers 可合并的 state updates。
- barrier 节点必须等待上游。
- manual gate 编译为 interrupt point。
- background 节点不阻塞下游时必须有通知策略。

### 11.3 RunLoop

- 单任务和多 Agent 任务都通过同一 RunLoop 入口。
- checkpoint 可通过 thread_id 恢复。
- 人工门控可 resume。
- 失败传播策略生效。
- 工作记忆读取和通信 handoff 不互相抢上下文。

### 11.4 前端

- 编辑器打开任务后显示任务图。
- 未打开任务时不自动加载管理台任务。
- 单任务也是图。
- DSL 编辑错误有明确提示。
- 保存后刷新仍能恢复画布。

## 12. 迁移与切换规则

### 12.1 兼容读取

旧 `CoordinationTask + TopologyTemplate + CommunicationProtocol` 可以被读取并转换为 `TaskGraphDefinition`。

### 12.2 主写入口切换

新编辑器保存只写 `TaskGraphDefinition`。

旧 coordination 写入口在迁移期只允许：

- 读取
- 兼容导入
- 明确的数据迁移

不允许继续扩展旧写入口。

### 12.3 回退策略

如果新编译器失败：

- 不执行任务。
- 返回 `TaskGraphCompileReport`。
- 用户回到编辑器修图。

不允许静默回退到旧运行链路执行。

### 12.4 清理规则

满足以下条件后删除旧链路：

- 所有内置任务图已迁移。
- 单任务运行已通过图链路。
- 多 Agent 长篇小说任务可通过图链路预检。
- 健康系统相关协调任务可通过图链路运行。
- 旧测试已改为新链路测试或删除。

## 13. 禁止事项

- 禁止直接 fork 或修改第三方 LangGraph 源码作为业务方案。
- 禁止新增 shadow 模式。
- 禁止让任务域图化；任务域是仓库层，不是运行图。
- 禁止把 Agent prompt、投影内容塞进图结构；图只引用投影。
- 禁止让节点内部能力逻辑侵入图语言。
- 禁止编辑器私下注册 Agent、契约、投影、工具。
- 禁止单任务保留独立执行主链路。
- 禁止为了兼容旧测试保留无价值旧残留。

## 14. 预期结果

完成后，任务系统会收敛成：

```text
任务域
  -> 任务
    -> TaskGraphIR
      -> Visual Editor
      -> TaskGraphDSL
      -> Validator
      -> ContractManifest
      -> RuntimeAssembly
      -> LangGraphExecutionPlan
      -> TaskRunLoop
```

系统收益：

- 单任务和多 Agent 任务统一。
- 前端画布和代码语言统一。
- RunLoop 入口统一。
- LangGraph 的 checkpoint、interrupt、并发能力被纳入系统，但不污染任务资产模型。
- 长篇小说这类复杂任务可以通过同一编辑器配置、预检、运行、恢复和审查。

## 15. 下一步建议

下一步不要直接改前端画布。

应先执行阶段 1 和阶段 2：

1. 扩展 `TaskGraphDefinition` 为 `TaskGraphIR v1`。
2. 为现有单任务自动生成最小任务图。
3. 建立 DSL 可逆转换和测试。
4. 再进入 LangGraphExecutionPlan 编译层。

这是把“真正的编辑器”立住的地基。
