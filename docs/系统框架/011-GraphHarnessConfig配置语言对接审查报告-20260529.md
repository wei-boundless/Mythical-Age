# GraphHarnessConfig 配置语言对接审查报告（代码证据版）

日期：2026-05-29

状态：正式审查稿

证据范围：只依据当前代码，不引用旧设计文档、不引用历史计划书。

## 0. 结论

当前代码已经形成一条可运行的图任务主链路：

```text
任务图编辑器 draft
-> TaskGraphRecord 保存
-> TaskGraphDefinition
-> graph_harness_config_publisher 编译/发布 GraphHarnessConfig
-> orchestration API 读取已发布 GraphHarnessConfig
-> GraphRuntime 锁定配置并创建 GraphRun / 根 TaskRun
-> GraphLoop 初始化状态、派发 GraphNodeWorkOrder
-> QueryRuntime 将 WorkOrder 转成单 agent TaskRun
-> 单 agent task_executor 执行
-> GraphNodeWorkOrderExecutor 转成 NodeResultEnvelope
-> GraphLoop 接收结果并推进图状态
-> GraphRunRunner 从 GraphLoop checkpoint 续取 active/ready work orders 并持续执行到 idle/terminal/budget
```

但是这条链路还没有达到“GraphHarnessConfig 是唯一、完整、逐字段闭合的 harness 配置语言”的标准。现在的主要问题不是缺少一个新的合同对象，而是代码中已经发布的 `GraphHarnessConfig` 字段有相当一部分没有被 `GraphLoop`、`GraphContextMaterializer`、单 agent runtime 或结果回写链完整消费。

最重要的判断如下：

1. `GraphHarnessConfig` 已经是运行入口的唯一配置对象。启动接口不再从编辑器草稿启动，也不直接从 `TaskGraphDefinition` 启动。
2. `GraphRuntime` 的职责是静态锁定已发布配置、创建运行记录。它没有做节点调度，也没有执行 agent。
3. `GraphLoop` 的职责是动态状态推进。但当前它主要还是基础 DAG 调度器，没有完整消费图级 `control`、节点 `execution/retry/gates`、边 `ack/result_delivery/context_filter/payload_contract` 等策略。
4. `GraphContextMaterializer` 是图节点配置到 agent 可见输入包的实际桥。它能把 prompt、contracts、memory、artifact、file、permission、tools 放进 work order，但多数语义仍被包在 `input_package/resource_requirements` 中，不是一等运行字段。
5. 单 agent 节点能接上 agent harness，并且图节点 `TaskRunContract` 已明确填充 `prompt_contract/runtime_profile/task_environment_id/origin`。
6. `NodeResultEnvelope` 模型有结构化输出能力，但 `GraphNodeWorkOrderExecutor` 当前主要回填 `final_answer`、artifact refs、基础 artifact/materialization receipts，仍不足以支撑高质量结构化节点通信。
7. 当前代码已补上 `GraphRunRunner` 执行泵；它只读取 `GraphLoopState.active_work_orders/ready_node_ids`，通过 `GraphHarness.execute_work_order()` 执行节点，再把结果交回 `GraphLoop.accept_node_result()`，不会扫描普通单 agent waiting 队列，也不会直接修改 graph state。

因此后续修复方向应是：以 `GraphHarnessConfig` 为唯一配置语言，逐字段关闭“发布器写了但 harness 没消费”的缺口；不要再新增独立外部合同对象绕开它。

## 1. 代码证据：编辑器到 TaskGraphRecord

前端任务图 draft 的核心类型在：

```text
frontend/src/components/workspace/views/task-system/taskGraphDraftV2.ts
```

代码证据：

- `TaskGraphDraftV2` 包含 `graph_id/title/domain_id/task_id/graph_kind/entry_node_id/output_node_id/nodes/edges/contract_bindings/runtime_policy/context_policy/working_memory_policy/publish_state/metadata/ui_state`。
- `TaskGraphRuntimePolicyDraftV2` 仍包含 `coordinator_agent_id`、`participant_agent_ids`、`agent_group_id`、`coordination_mode`、`human_gate_mode`。
- `taskGraphRecordToDraftV2()` 会从 `TaskGraphRecord` 反解 draft，并从 `metadata` 中剥离部分历史字段。

保存映射在：

```text
frontend/src/components/workspace/views/task-system/taskGraphSaveMapper.ts
```

代码证据：

- `buildTaskGraphUpsertPayload()` 将 draft 保存成 `TaskGraphRecord`。
- 它从 `metadata/runtime_policy/context_policy` 中解析 `task_environment_id`。
- 它将 `runtime_policy`、`context_policy`、`working_memory_policy`、`contract_bindings` 写回 record。
- 它调用 `normalizeGraphContractBindings()`、`normalizeNodeContractBindings()`、`normalizeEdgeContractBindings()`，把 graph/node/edge 的合同字段归到 `contract_bindings` 下。

当前判断：

```text
编辑器保存链路是存在的。
编辑器不是直接启动 GraphLoop，而是保存 TaskGraphRecord。
但编辑器仍保留 coordination_mode、participant_agent_ids、legacy 字段迁移等旧语义，必须保证这些字段只作为编辑/迁移信息，不能成为 harness 的第二套运行权威。
```

## 2. 代码证据：TaskGraphDefinition 到 GraphHarnessConfig

后端保存入口在：

```text
backend/api/task_system.py
```

代码证据：

- `upsert_task_system_task_graph()` 保存 `TaskGraphUpsertRequest`。
- 保存前会调用 `_migrate_task_graph_legacy_prompt_nodes()`。
- 当 `payload.publish_state == "published"` 时，调用 `publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=payload.graph_id)`。

编译预览入口也在：

```text
backend/api/task_system.py
```

代码证据：

- `_compile_task_graph_contract(graph_id)` 调用 `build_graph_harness_config_from_graph(... publish_version="preview" ...)`。
- 返回 `graph_harness_config`、`scheduler_view`、`composition_sources`、`split_plans`、`object_trace_index`、`issues`、`summary`。
- 这个接口证明前端“编译图契约”实际看到的是 `GraphHarnessConfig`，不是另一个合同对象。

发布器在：

```text
backend/task_system/compiler/graph_harness_config_publisher.py
```

代码证据：

- `publish_graph_harness_config_for_graph()` 从 `TaskFlowRegistry.get_task_graph(graph_id)` 读取任务图。
- `build_graph_harness_config_from_graph()` 构造 `GraphHarnessConfig`。
- 发布器输出字段包括：

```text
graph_id
graph_title
publish_version
task_environment_id
root_task_ref
control
nodes
edges
loop_frames
resources
memory
artifacts
permissions
tools
agents
contracts
composition_sources
diagnostics
authority_map
source_refs
```

节点配置由 `_node_config()` 生成，主要字段包括：

```text
node_id
title
node_type
node_class
task_ref
agent_id
agent_profile_id
executor
execution
contracts
prompt
context
memory
artifacts
stream
gates
retry
permissions
tools
metadata
```

边配置由 `_edge_config()` 生成，主要字段包括：

```text
edge_id
source_node_id
target_node_id
edge_type
semantic_role
scheduler_role
wait_policy
ack_policy
ack_required
failure_propagation_policy
result_delivery_policy
payload_contract_id
contract_bindings
context_filter_policy
artifact_ref_policy
working_memory_handoff_policy
temporal_policy
revision_policy
metadata
```

当前判断：

```text
GraphHarnessConfig 的发布链路是主链。
任务系统/发布器是图语言归一化的权威。
但 GraphHarnessConfig.nodes 和 edges 仍是 dict[str, Any]，字段可写入但缺少类型级闭合约束。
```

## 3. 代码证据：已发布配置的存储与启动

配置存储在：

```text
backend/task_system/repositories/graph_harness_config_repository.py
```

代码证据：

- `GraphHarnessConfigRepository.upsert()` 只保存 `status in {"published", "archived"}` 的配置。
- 如果 `content_hash` 存在，会校验 `expected_content_hash()`。
- `published_bindings` 维护 `graph_id -> config_id`。
- `get_published_for_graph(graph_id)` 只返回绑定的 published config。

运行启动 API 在：

```text
backend/api/orchestration.py
```

代码证据：

- `start_task_graph_harness_run()` 只调用 `registry.get_published_graph_harness_config(graph_id)`。
- 如果没有已发布配置，返回 409，并提示必须先发布 `GraphHarnessConfig`。
- 启动时调用 `runtime.query_runtime.graph_harness.start_run(graph_config=graph_config, ...)`。
- `dispatch-ready`、`node-results`、`work-orders/execute` 都要求传入 `graph_harness_config_id`，然后从仓库读取 `GraphHarnessConfig`。

当前判断：

```text
运行入口已经不是“用图编辑器草稿运行”。
运行入口也不是“现场重新解释 TaskGraphDefinition”。
运行入口是已发布 GraphHarnessConfig。
这是正确主链。
```

## 4. 代码证据：GraphRuntime 的职责

GraphRuntime 在：

```text
backend/harness/graph/runtime.py
```

代码证据：

- `GraphRuntime.start()` 要求 `graph_config.status == "published"`。
- 它重新计算 `expected_content_hash()`，并和 `graph_config.content_hash` 比对。
- 它创建根 `TaskRun`、`GraphRun`、`GraphRuntimeEnvelope`。
- `GraphRuntimeEnvelope` 保存 `initial_inputs`、`permission_scope`、`file_scope`、`memory_scope`、`sandbox_scope`。
- 它写入 `state_index` 和 `runtime_objects`，并记录 `graph_run_created` 事件。

当前判断：

```text
GraphRuntime 是静态装配层。
它锁定配置和运行身份。
它不负责节点 ready 判断，不负责调度推进，不负责执行 agent。
这个边界是合理的。
```

## 5. 代码证据：GraphLoop 的实际消费

GraphLoop 在：

```text
backend/harness/graph/loop.py
```

调度视图在：

```text
backend/harness/graph/scheduler_view.py
backend/harness/graph/language.py
```

代码证据：

- `GraphLoop.initialize()` 初始化 `node_states`、`edge_states`、`ready_node_ids`。
- `GraphLoop.dispatch_ready()` 用 `graph_config.control.max_active_nodes` 作为派发上限。
- `GraphLoop.accept_node_result()` 校验节点当前 active work order，接收 `NodeResultEnvelope`，更新 node state、edge state、result index。
- 完成规则目前是：

```text
有 failed node -> graph failed
terminal_node_ids 全部 completed -> graph completed
否则 executable_node_ids 全部 completed -> graph completed
```

- `_ready_nodes()` 主要逻辑是：可执行节点处于 pending/blocked，并且所有上游 dependency 节点 completed，即 ready。
- `build_scheduler_view()` 只抽取 `dependency_edges`、`executable_node_ids`、`start_node_ids`、`terminal_node_ids`。
- `edge_is_scheduler_dependency()` 只把 `scheduler_role == "dependency"` 视为依赖；`commit` 边只有在目标是可执行 memory commit 节点时才参与调度。

当前 GraphLoop 明确消费的字段：

```text
GraphHarnessConfig.nodes[*].node_id
GraphHarnessConfig.nodes[*].node_type
GraphHarnessConfig.nodes[*].node_class
GraphHarnessConfig.nodes[*].executor.executor_type

GraphHarnessConfig.edges[*].edge_id
GraphHarnessConfig.edges[*].source_node_id
GraphHarnessConfig.edges[*].target_node_id
GraphHarnessConfig.edges[*].edge_type
GraphHarnessConfig.edges[*].semantic_role
GraphHarnessConfig.edges[*].scheduler_role

GraphHarnessConfig.control.start_node_ids
GraphHarnessConfig.control.terminal_node_ids
GraphHarnessConfig.control.max_active_nodes
```

当前 GraphLoop 保存但没有完整解释的字段：

```text
control.completion_policy
control.failure_policy
control.retry_policy
control.checkpoint_policy
control.human_gate_policy
control.graph_loop_policy
control.temporal_edges
control.revision_edges

nodes[*].execution.wait_policy
nodes[*].execution.join_policy
nodes[*].stream
nodes[*].gates
nodes[*].retry

edges[*].wait_policy
edges[*].ack_policy
edges[*].ack_required
edges[*].failure_propagation_policy
edges[*].result_delivery_policy
edges[*].payload_contract_id
edges[*].context_filter_policy
edges[*].artifact_ref_policy
edges[*].working_memory_handoff_policy
edges[*].temporal_policy
edges[*].revision_policy
```

当前判断：

```text
GraphLoop 已经是主控制器，但它目前更像基础拓扑调度器。
它还不是完整的 GraphHarnessConfig 控制语言解释器。
```

### 5.1 代码证据：持续运行闭环缺失

这是当前图任务运行能力的最高优先级缺口。

代码证据显示：

```text
backend/api/orchestration.py
```

- `start_task_graph_harness_run()` 调用 `graph_harness.start_run(... dispatch_ready=True)`。
- 默认 `run_mode=dispatch_only` 时，它返回 `node_work_orders`，不隐式执行。
- `run_mode=auto_run` 时，它会调用 `graph_harness.run_until_idle()`，并返回 runner 后的最新 checkpoint、loop state、root task run、graph run 和 active work orders。
- `dispatch_graph_run_ready_nodes()` 只派发 ready work order，不执行它们。
- `execute_graph_work_order()` 可以执行一个指定 work order，并在 `accept_result=True` 时回写结果、推进 GraphLoop。
- `/graph-runs/{graph_run_id}/run-until-idle` 可以显式启动 GraphRunRunner 执行泵。

```text
backend/harness/graph_harness.py
```

- `execute_work_order()` 只执行传入的一个 work order。
- 执行完成后，如果 `accept_result=True`，会调用 `accept_node_result()`。
- `accept_node_result()` 可能返回下一批 `node_work_orders`。
- `execute_work_order()` 本身不继续执行下一批 work order；持续执行由 `GraphRunRunner` 负责。

```text
backend/harness/graph/runner.py
```

- `GraphRunRunner.run_until_idle()` 从 checkpoint 中读取最新 `GraphLoopState`。
- 它只从 `active_work_orders` / `work_order_index` 重连节点 work order，不扫描普通 `single_agent_task` waiting 队列。
- 没有 active work order 但存在 ready nodes 时，它只通过 `GraphLoop.dispatch_ready_and_checkpoint()` 派发。
- 执行节点时只通过 `GraphHarness.execute_work_order(..., accept_result=True)`，不直接写 `node_states/result_index/active_work_orders/terminal_state`。
- 每轮执行前校验 `GraphHarnessConfig.config_id/content_hash` 和 `GraphNodeWorkOrder.config_id/config_hash`。
- 它校验节点 executor TaskRun 必须是 `origin_kind=graph_node_assigned`，且 `graph_run_id/work_order_id` 属于当前 graph run。
- 它有 `max_node_executions/max_loop_iterations/max_dispatches/max_runtime_seconds/max_node_steps` 预算；预算耗尽返回 `budget_exhausted`，不伪造完成。

```text
frontend/src/lib/store/runtime.ts
frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
```

- 前端 `continueBoundTaskGraphRun()` / `resumeTaskGraphRun()` 调用的是 `dispatchGraphRunReadyNodes()`。
- `frontend/src/lib/api.ts` 已新增 `runGraphRunUntilIdle()`。
- 任务图页面仍需要从旧的只派发行为切换到 runner 行为。

对比单 agent 普通任务：

```text
backend/harness/loop/agent_loop.py
backend/api/orchestration_harness.py
```

- 普通 `request_task_run` 会通过 `_schedule_task_executor()` 创建后台 runner。
- `/orchestration/harness/task-runs/{task_run_id}/execute` 也会用 `BackgroundTasks` 调度 `execute_task_run()`。
- 图任务已有 facade/API 执行泵，但尚未接成后台 `BackgroundTasks` 调度器。

当前运行逻辑真实状态：

```text
启动图任务 -> GraphLoop 派发第一批 work order -> work order 进入 active_work_orders
如果外部调用 run_until_idle 或 start(run_mode=auto_run)
-> GraphRunRunner 执行 active work orders
-> GraphNodeWorkOrderExecutor 创建/续跑 graph_node_assigned 单 agent TaskRun
-> 单 agent task_executor 产出结果
-> GraphNodeWorkOrderExecutor 包装 NodeResultEnvelope
-> GraphLoop.accept_node_result 推进状态并派发下一批 work order
-> GraphRunRunner 继续执行，直到 terminal / idle / blocked / budget_exhausted
```

当前执行泵的权威边界：

```text
GraphRunRunner:
  load locked GraphHarnessConfig
  read latest GraphLoopState/checkpoint
  reconnect active_work_orders only from GraphLoopState
  dispatch ready nodes only through GraphLoop.dispatch_ready_and_checkpoint
  execute node only through GraphHarness.execute_work_order
  accept result only through GraphLoop.accept_node_result
  stop on terminal / idle / blocked / budget_exhausted
```

目标判断：

```text
GraphRunRunner 的基础持续运行闭环已经补上。
但前端任务图页面和后台调度仍需改成调用 runner，而不是只 dispatch ready nodes。
GraphRun monitor 仍需展开 node_runtime_views/timeline，不能只显示根事件和 active work orders。
```

## 6. 代码证据：节点配置到 agent 可见输入

节点上下文装配在：

```text
backend/harness/graph/context_materializer.py
```

代码证据：

- `GraphContextMaterializer.build_work_order()` 读取当前 node、state、graph_config，构造 `GraphNodeWorkOrder`。
- 它调用 `handoff_packets_for_node()` 和 `upstream_results_for_node()`，把上游结果放进当前节点输入。
- `build_input_package()` 输出：

```text
node_identity
prompt_contract
prompt
agent_instruction
input_contract
output_contract
initial_inputs
upstream_results
upstream_handoff_packets
memory_view
artifact_view
file_view
issue_view
permission_summary
tool_capability_table
hidden_control_refs
expected_result_contract
```

- `GraphNodeWorkOrder` 保存：

```text
message
explicit_inputs
input_package
graph_state
context_refs
memory_view_request
artifact_view_request
file_view_request
permission_scope
tool_scope
expected_result_contract
retry_policy
timeout_policy
dispatch_context
```

当前判断：

```text
GraphContextMaterializer 是图节点到 agent runtime 的关键桥。
它已经把节点配置带到了 work order。
但大量语义仍在 input_package 里作为泛型字典传递，单 agent runtime 没有把它们作为一等字段精确消费。
```

特别断点：

```text
_file_view_request() 读取 node.files。
但 graph_harness_config_publisher._node_config() 当前没有写 nodes[*].files。
所以文件管理策略无法从编辑器/发布器稳定进入 file_view_request。
```

## 7. 代码证据：单节点 WorkOrder 到单 agent TaskRun

桥接代码在：

```text
backend/query/runtime.py
```

代码证据：

- `QueryRuntime.__init__()` 创建同一个 `single_agent_runtime_host`，然后同时创建 `AgentHarness` 和 `GraphHarness`。
- `GraphHarness` 的 services 中注入 `execute_graph_agent_work_order_callback=self.execute_graph_agent_work_order`。
- `execute_graph_agent_work_order()` 会调用 `_create_graph_node_task_run()`，再调用 `execute_task_run()`。
- `_create_graph_node_task_run()` 将 `GraphNodeWorkOrder` 转成一个 `single_agent_task` 类型的 `TaskRun`。
- `_graph_node_contract_from_work_order()` 从 work order 生成 `TaskRunContract`。

关键问题在 `_graph_node_contract_from_work_order()`：

```text
它设置 user_visible_goal/task_run_goal/completion_criteria/resource_requirements/permission_requirements/acceptance_policy/recovery_policy。
它把 input_package、graph_state、memory_view_request、artifact_view_request、file_view_request 放进 resource_requirements。
它没有显式填充 TaskRunContract.task_environment_id。
它没有显式填充 TaskRunContract.runtime_profile。
它没有显式填充 TaskRunContract.prompt_contract。
```

`_graph_node_task_selection()` 会生成：

```text
selected_task_id
task_environment_id
runtime_mode
runtime_profile
allowed_operations
```

它把 `work_order.tool_scope` 放进 `runtime_profile.tool_policy`，把 `work_order.permission_scope` 放进 `runtime_profile.permission_policy`。

单 agent 执行器在：

```text
backend/harness/loop/task_executor.py
```

代码证据：

- `execute_task_run()` 从 `TaskRun` 加载 contract。
- `_task_selection_from_task_run()` 读取 `task_run.diagnostics.runtime_task_selection`。
- `assemble_runtime()` 用 task selection 装配 runtime assembly。
- `RuntimeCompiler.compile_task_execution_packet()` 把 `task_contract`、`task_environment`、`available_tools`、`operation_authorization`、`runtime_context` 放进模型 packet。

当前判断：

```text
单 agent 节点可以真实运行。
但它对 GraphHarnessConfig.nodes[*] 的消费是间接的：
GraphHarnessConfig.nodes[*] -> GraphNodeWorkOrder.input_package -> TaskRunContract.resource_requirements -> RuntimeCompiler.task_contract。

这条链能跑，但字段语义不够硬。
prompt、runtime_profile、task_environment、工具权限、文件策略应该成为明确字段，而不是主要藏在 resource_requirements/input_package。
```

另一个具体风险：

```text
execute_graph_agent_work_order() 选择 executor services profile 时优先 work_order.agent_profile_id，其次 work_order.agent_id。
但 _create_graph_node_task_run() 写 TaskRun.agent_profile_id 时使用 work_order.agent_profile_id 或图级 coordinator profile。
当节点只有 agent_id、没有 agent_profile_id 时，实际 executor profile 与 TaskRun.agent_profile_id 可能不一致。
```

### 7.1 代码证据：任务来源协议缺失

当前系统可以通过分散信号区分“系统下发任务”和“agent 自主发起任务”，但还没有统一、硬约束的任务来源协议。

agent 自主发起正式任务的入口在：

```text
backend/harness/loop/agent_loop.py
```

代码证据：

- 当 agent 输出 `action_type == "request_task_run"` 时，`agent_loop` 调用 `contract_from_action_request()`。
- `contract_from_action_request()` 位于 `backend/harness/loop/task_lifecycle.py`，生成的 `TaskRunContract.contract_source` 是：

```text
model_request
```

- `start_task_lifecycle()` 创建 `TaskRun` 时，会在 diagnostics 写入：

```text
turn_id
action_request_ref
contract
runtime_task_selection
```

这说明该任务来自 agent 在当前 turn 中提交的任务合同。

agent 请求已注册任务计划的入口同样在：

```text
backend/harness/loop/agent_loop.py
```

代码证据：

- 当 agent 输出 `action_type == "request_registered_engagement"` 时，代码调用：

```text
EngagementService.start(... requested_by="agent", source_ref=action_request.request_id, turn_id=turn_id)
```

这说明该任务来自 agent 主动请求系统启动特定任务计划。

系统下发图节点任务的入口在：

```text
backend/query/runtime.py
```

代码证据：

- `QueryRuntime._create_graph_node_task_run()` 把 `GraphNodeWorkOrder` 转成单 agent `TaskRun`。
- `_graph_node_contract_from_work_order()` 生成的 `TaskRunContract.contract_source` 是：

```text
graph_node_work_order
```

- `TaskRun.diagnostics` 写入：

```text
source = "query_runtime.graph_agent_work_order_adapter"
graph_run_id
graph_harness_config_id
graph_node_id
graph_work_order_id
```

- 对应 `AgentRun` 写入：

```text
spawn_mode = "graph_node"
context_scope = "graph_node_work_order"
parent_agent_run_ref = graph_run_id
```

这说明该任务不是 agent 自主决定创建，而是图 loop 根据已发布配置下发给节点 agent 的执行单。

任务系统/用户启动特定任务的入口在：

```text
backend/task_system/engagement/service.py
backend/task_system/engagement/dispatcher.py
backend/harness/graph/runtime.py
```

代码证据：

- `EngagementService.start()` 的默认 `requested_by` 是 `user`。
- `EngagementDispatcher._dispatch_graph_task_run()` 启动图任务时在 diagnostics 写入：

```text
source = "task_system.engagement.graph_task_run"
engagement_contract_ref
engagement_plan_ref
engagement_run_ref
```

- 直接图运行 API 启动时，`GraphRuntime.start()` 接收的 diagnostics 来自：

```text
source = "harness.task_graph_start_api"
```

当前判断：

```text
系统现在能通过 contract_source、diagnostics.source、requested_by、spawn_mode、context_scope、parent_agent_run_ref 等信号推断任务来源。
但这些信号分散在不同对象里，不是统一协议。
缺少统一来源协议会导致审计、权限、恢复、监控、图任务节点归因和 agent 自主任务归因出现边界不清。
```

目标协议应收口为一组稳定字段：

```text
origin_kind:
  user_requested
  agent_requested
  system_assigned
  graph_node_assigned
  engagement_assigned

origin_authority:
  harness.loop.agent
  harness.graph_loop
  harness.api
  task_system.engagement
  task_system.scheduler

origin_ref:
  action_request_id
  graph_work_order_id
  engagement_run_id
  api_request_id

parent_run_ref:
  turn_id
  graph_run_id
  engagement_run_id
  task_run_id

origin_policy:
  user_visible
  agent_requested_requires_admission
  graph_config_locked
  system_policy_bound

delegation_depth:
  0 for user/system root
  1+ for agent/subtask/graph-node spawned work
```

协议判断规则：

```text
agent 自主发起任务 = origin_kind == "agent_requested"
agent 请求注册计划 = origin_kind == "engagement_assigned" 且 origin_authority 记录 agent action_request
系统下发图节点任务 = origin_kind == "graph_node_assigned"
用户/API 直接启动任务 = origin_kind == "user_requested"
任务系统按计划下发 = origin_kind == "engagement_assigned"
```

实现位置建议：

```text
TaskRun.diagnostics.origin
TaskRunContract.origin
AgentRun.diagnostics.origin
GraphNodeWorkOrder.dispatch_context.origin
GraphRuntimeEnvelope.initial_inputs.origin
EngagementRunRecord.source
```

这不是给 agent 的 prompt，而是系统审计和控制协议。agent 可以看到必要的任务背景，但不能用来源协议来改写任务来源。

## 8. 代码证据：节点结果回写

节点执行器在：

```text
backend/harness/graph/work_order_executor.py
```

结果模型在：

```text
backend/harness/graph/models.py
```

代码证据：

- `NodeResultEnvelope` 支持：

```text
outputs
decisions
artifact_refs
memory_candidates
handoff_summary
error
diagnostics
```

- `GraphNodeWorkOrderExecutor._node_result_from_agent_execution()` 当前主要从 executor result 中抽取：

```text
final_answer
node_executor_task_run_id
executor_status
artifact_refs
handoff_summary
error
diagnostics
```

当前判断：

```text
NodeResultEnvelope 的模型能力强于当前回填逻辑。
现在下游节点主要拿到 final_answer、artifact_refs、handoff_summary。
structured_output、contract_output、decisions、memory_candidates、verification 等没有形成标准回写。
这会直接限制节点之间的精确通信。
```

## 9. 代码证据：边通信不是完整协议

边语言定义在：

```text
backend/harness/graph/language.py
```

代码证据：

- 已定义 memory/artifact/file/revision/event/audit/dependency 等 edge type。
- `harness_edge_scheduler_role()` 会给不同 edge type 归类为 `dependency/context/commit/event/audit/conditional_dependency/none`。
- `validate_harness_edge_config()` 校验 edge_id/source/target/edge_type/semantic_role/scheduler_role。

边 handoff 构造在：

```text
backend/harness/graph/context_materializer.py
```

代码证据：

- `handoff_packets_for_node()` 会为入边生成 packet。
- packet 包含 `payload_contract_id`、`payload.outputs`、`payload.decisions`、`payload.artifact_refs`、`payload.memory_candidates`、`delivery_policy`、`ack_required`。

当前缺口：

```text
payload_contract_id 被带入 packet，但没有看到校验逻辑。
result_delivery_policy 被带入 packet，但没有看到按策略裁剪 payload。
context_filter_policy 没有驱动下游输入过滤。
artifact_ref_policy 没有驱动 artifact refs 选择。
working_memory_handoff_policy 没有驱动 memory_candidates 选择。
ack_required 被带入 packet，但 GraphLoop.edge_states 没有 ack 状态机。
```

当前判断：

```text
边现在既是拓扑线，也是部分 handoff packet 来源。
但它还不是完整通信协议。
图任务要做成熟长流程，必须把边通信变成可验证、可过滤、可确认、可恢复的协议。
```

## 10. 代码证据：prompt 权威存在断点

这是当前最需要单独指出的逻辑漏洞。

旧 prompt 迁移逻辑在：

```text
backend/api/task_system.py
```

代码证据：

- `_build_task_graph_node_role_prompt()` 会从 `metadata.role_prompt/role_identity/responsibility_scope/responsibility_exclusions/definition_of_done` 拼出 agent 可读 prompt。
- `_migrate_task_graph_legacy_prompt_nodes()` 会调用 `PromptLibraryRegistry.migrate_task_graph_node_prompt()` 保存 prompt resource。
- 然后 `_strip_task_graph_prompt_metadata()` 会从 node metadata 中移除这些 prompt 字段，只保留 `legacy_prompt_migration`，包括 `prompt_resource_id`。

但发布器 `_node_config()` 在：

```text
backend/task_system/compiler/graph_harness_config_publisher.py
```

代码证据：

- 它只从 `metadata.prompt_contract`、`metadata.role_prompt`、`metadata.task_instruction`、`metadata.output_instruction` 生成 `nodes[*].prompt`。
- 它没有根据 `metadata.legacy_prompt_migration.prompt_resource_id` 去 prompt library 解析 prompt。

当前判断：

```text
如果节点 prompt 已经被迁移到 prompt library，发布器可能无法把它装入 GraphHarnessConfig.nodes[*].prompt。
这会导致编辑器看起来完成了 prompt 迁移，但 GraphHarnessConfig 对 agent 可见 prompt 为空。
这是图任务 agent 节点职责表达的真实断点，不是文档问题。
```

这项必须优先修复，因为 prompt 是 agent 行为边界的一等输入。

## 11. 当前可运行能力

基于代码证据，当前已具备：

```text
1. 编辑器可以保存任务图。
2. 任务系统可以把 TaskGraphDefinition 编译为 GraphHarnessConfig。
3. 已发布 GraphHarnessConfig 有 content_hash，并通过 graph_id -> config_id 绑定。
4. orchestration API 只允许用已发布 GraphHarnessConfig 启动图运行。
5. GraphRuntime 能创建根 TaskRun、GraphRun、GraphRuntimeEnvelope。
6. GraphLoop 能按基本拓扑派发 ready 节点。
7. GraphContextMaterializer 能构造 GraphNodeWorkOrder。
8. QueryRuntime 能把 GraphNodeWorkOrder 转成 single_agent_task。
9. 单 agent task_executor 能执行节点 TaskRun。
10. NodeResultEnvelope 能回到 GraphLoop，并推进后续节点。
11. checkpoint/event/runtime_objects/state_index 都已接入主链。
```

必须注意：

```text
以上能力现在可以证明“通过 GraphRunRunner 显式执行泵可持续推进到 idle/terminal/budget”。
但前端任务图页面和后台调度还没有完全切到 runner，所以产品入口仍需继续收口。
```

## 12. 当前不完备能力

### 12.1 编辑器缺口

```text
1. runtime_policy 仍有 coordination_mode 等旧语义。
2. prompt 编辑/迁移和 GraphHarnessConfig.nodes[*].prompt 没有完全闭合。
3. 编译预览没有返回字段级消费诊断。
4. 文件策略没有稳定映射到 nodes[*].files。
5. contract_bindings 已保存，但哪些字段真正进入 harness 消费没有前端可视化证明。
```

### 12.2 发布器缺口

```text
1. GraphHarnessConfig.nodes/edges 是 dict[str, Any]，缺少闭合 schema。
2. 发布器写了很多 control/node/edge 字段，但没有消费覆盖校验。
3. prompt_resource_id 没有解析进 nodes[*].prompt。
4. files 字段没有发布，导致 materializer 的 file_view_request 断开。
5. contracts.manifest 被生成，但 GraphLoop 没有使用它做输入/输出/边 payload 校验。
```

### 12.3 Harness 缺口

```text
1. GraphLoop 未完整消费 completion_policy/failure_policy/retry_policy。
2. GraphLoop 未完整消费 wait_policy/join_policy。
3. edge ack 没有状态机。
4. edge context/payload/artifact/memory 策略没有驱动下游输入过滤。
5. conditional_dependency/revision edge 没有成熟推进语义。
6. memory/artifact/file commit 边没有完整提交和恢复语义。
7. GraphRunRunner 已补齐 facade/API 执行泵，但前端任务图页面和后台调度尚未完全接入。
8. execute_work_order 仍只执行一个 work order；这是正确边界，持续执行由 GraphRunRunner 负责。
```

### 12.4 单 agent 对接缺口

```text
1. TaskRunContract.prompt_contract 没有从 work_order.input_package.prompt_contract 填充。
2. TaskRunContract.task_environment_id 没有从 graph_config.task_environment_id 填充。
3. TaskRunContract.runtime_profile 没有从节点 runtime 配置填充。
4. input/output contract 主要藏在 resource_requirements/input_package。
5. 节点 agent profile 选择存在 TaskRun 记录和 executor services 不一致风险。
6. NodeResultEnvelope 没有标准提取 structured_output/contract_output/decisions/memory_candidates。
```

### 12.5 任务来源协议缺口

```text
1. agent 自主 request_task_run、agent request_registered_engagement、系统图节点下发、任务系统 engagement 下发、API 直接启动都能通过分散信号推断，但没有统一字段。
2. contract_source 只能描述合同来源，不能完整表达任务发起方、授权方、父运行、来源引用和委派深度。
3. diagnostics.source 是自由字符串，不能作为权限和审计的硬协议。
4. requested_by 只存在 engagement 链路，不能覆盖 graph node work order 和普通 agent task run。
5. spawn_mode/context_scope 只在 AgentRun 上表达执行形态，不能替代 TaskRun 任务来源。
6. 缺少 origin_kind/origin_authority/origin_ref/parent_run_ref 后，系统无法稳定区分 agent 自主任务与系统下发任务的权限、监控、恢复和责任归属。
```

### 12.6 图任务对单 agent 主链的隔离风险

当前没有看到图任务已经直接替换或破坏单 agent 主入口。

代码证据：

```text
backend/query/runtime.py
```

- 普通会话单 agent 入口仍是 `agent_harness.run_stream(...)`。
- agent 自主正式任务入口仍是 `backend/harness/loop/agent_loop.py` 中的 `request_task_run`。
- agent 自主任务合同仍由 `backend/harness/loop/task_lifecycle.py::contract_from_action_request()` 生成，`contract_source=model_request`。
- 图节点任务只通过 `QueryRuntime.execute_graph_agent_work_order()` 进入 `_create_graph_node_task_run()`，并生成 `contract_source=graph_node_work_order`。
- 图节点派生的 TaskRun 使用独立 ID 前缀：

```text
gtask:{graph_run_id}:{node_id}:{work_order_id}
```

所以当前主入口层面是分开的。

但仍存在三类必须收口的隔离风险：

```text
1. 图节点 TaskRun 和普通单 agent TaskRun 共享 execution_runtime_kind=single_agent_task。
   这是正确复用执行器，但不能让恢复、监控、权限、来源判断只靠 execution_runtime_kind。

2. recover_interrupted_task_executors() 会扫描所有 single_agent_task。
   图节点执行中如果后端重启，也会被普通单 agent 恢复器改回 waiting_executor。
   这不直接破坏普通单 agent，但会让图节点恢复语义绕过 GraphRunRunner / GraphLoop。

3. 图节点 TaskRunContract 目前没有显式填充 prompt_contract/task_environment_id/runtime_profile。
   因此图节点虽然复用单 agent executor，但它进入 executor 时可能退回单 agent 默认装配。
   这会破坏图节点语义，也会让单 agent executor 承担无法区分来源的隐性分支。
```

正确隔离原则：

```text
1. 单 agent executor 可以作为通用执行器被图节点复用。
2. 图任务不能修改普通单 agent 入口、普通 request_task_run 合同生成、普通 agent loop 决策协议。
3. 图节点进入单 agent executor 前，必须通过 GraphNodeWorkOrder -> TaskRunContract/runtime_task_selection 的显式适配层。
4. 图节点 TaskRun 必须带 origin_kind=graph_node_assigned、origin_ref=work_order_id、parent_run_ref=graph_run_id。
5. 普通单 agent 自主任务必须带 origin_kind=agent_requested，不能被图任务 runner 或图恢复器接管。
6. GraphRunRunner 只接管 origin_kind=graph_node_assigned 且 parent_run_ref 属于当前 GraphRun 的 TaskRun。
7. 普通 task executor recovery 不能独立续跑图节点 TaskRun；它最多把 executor lease 标记为可恢复，真正续跑必须回到 GraphRunRunner。
```

因此判断：

```text
当前风险不是“图任务已经破坏单 agent 链条”，而是“后续补 GraphRunRunner 时，如果不先建立来源协议和恢复隔离，就会把图任务控制权混入普通单 agent 恢复/执行链”。
```

### 12.7 图任务监控显示边界

图任务监控不能把每个节点子任务都暴露成全局独立任务。

正确产品语义应是：

```text
全局/会话监控显式显示一个图任务根运行；
图节点 TaskRun 是 GraphRun 的内部执行单元；
节点子任务只出现在 GraphRun 监控内，包括节点状态、work order、节点 executor TaskRun 引用、节点 trace drilldown；
子任务不应污染全局任务列表，也不应被用户误认为独立平台任务。
```

当前代码已经有一部分符合这个方向。

代码证据：

```text
backend/harness/runtime/monitor_projection.py
```

- `TaskRunMonitorProjector.build_global_monitor()` 和 `build_session_monitor()` 会跳过 `_is_internal_child_run(task_run)`。
- `_is_internal_child_run()` 在 `diagnostics.graph_node_id` 或 `diagnostics.graph_work_order_id` 存在时返回 `True`。
- 图节点派生 TaskRun 在 `backend/query/runtime.py::_create_graph_node_task_run()` 写入：

```text
diagnostics.graph_run_id
diagnostics.graph_harness_config_id
diagnostics.graph_node_id
diagnostics.graph_work_order_id
```

所以图节点子任务原则上不会作为全局/会话监控中的独立任务显式列出。

但当前监控链还没有达到“全程可监视”：

```text
backend/harness/graph_harness.py::get_graph_run_monitor()
```

- 当前只读取根 TaskRun 的事件：

```text
events = event_log.list_events(task_run_id)
```

- 它会返回 `active_node_work_orders`。
- 但不会把已创建/已执行的节点 executor TaskRun trace 汇总进 GraphRun monitor。
- `GraphNodeWorkOrderExecutor` 的 `graph_node_work_order_executed` 事件虽然记录了 `node_executor_task_run_id`，但这只是一个引用，不是图监控里的节点执行时间线。

前端证据：

```text
frontend/src/components/workspace/views/task-system/TaskGraphRunInteractionDock.tsx
frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
```

- 当前浮窗展示 GraphLoop 状态、active work orders、最近根事件。
- 没有节点 executor TaskRun 的结构化 timeline。
- 没有按节点聚合的模型步骤、工具调用、产物、错误、重试、runner 状态。

因此判断：

```text
当前已经避免了“子任务污染全局监控”的一部分问题；
但还没有完成“子任务只列入图监控并可全程追踪”的要求。
```

目标监控模型应是：

```text
GlobalMonitorItem:
  只显示 GraphRun 根 TaskRun

GraphRunMonitor:
  graph_run
  root_task_run
  runner_status
  graph_loop_state
  checkpoint_summary
  node_runtime_views[]
  timeline[]

NodeRuntimeView:
  node_id
  node_status
  active_work_order
  node_executor_task_run_id
  executor_status
  latest_step
  tool_calls_summary
  artifact_refs
  memory_receipts
  error
  trace_url

TimelineEvent:
  scope = graph | node | runner | checkpoint
  node_id?
  work_order_id?
  task_run_id?
  event_type
  status
  created_at
  summary
```

监控边界：

```text
1. 全局监控不展示 graph_node_assigned 子任务为独立任务。
2. 会话监控不展示 graph_node_assigned 子任务为独立任务。
3. GraphRun monitor 必须展示所有节点子任务的执行状态。
4. 节点子任务 trace 可以 drilldown，但入口必须挂在 GraphRun monitor 下。
5. runner 状态必须进入 GraphRun monitor，否则无法判断图任务是在执行、等待、阻塞还是已终止。
```

### 12.8 产物、记忆空间与任务环境对接缺口

任务环境系统已经具备产物、记忆和文件空间的抽象，但图任务运行链还没有完成闭环。

已存在的任务环境能力：

```text
backend/task_system/environments/models.py
```

- `TaskEnvironmentSpec` 包含：

```text
sandbox_policy
file_management
resource_space
memory_space
execution_policy
risk_policy
artifact_policy
observability_policy
lifecycle_policy
```

```text
backend/task_system/environments/spec_resolver.py
```

- `resolve_task_environment()` 会根据环境的 `file_profile_refs` 构造 `file_access_tables`。
- `_storage_space_payload()` 会生成环境级存储空间：

```text
environment_storage_root
runtime_state_root
artifact_root
cache_root
task_library_root
```

```text
backend/task_system/environments/default_environments.py
```

- `env.creation.writing` 已声明正式作品库、草稿工作区、artifact repository、memory repository。
- `env.development.sandbox` 已声明项目工作区、sandbox workspace、test artifacts、runtime output。
- `env.general.workspace` 已声明 conversation artifacts。

单 agent 执行链已经部分消费任务环境：

```text
backend/harness/runtime/assembly.py
backend/harness/runtime/compiler.py
backend/harness/loop/task_executor.py
```

- `assemble_runtime()` 根据 `task_environment_id` 解析 runtime task environment。
- `RuntimeCompiler` 把 `task_environment.storage_space` 和 `artifact_policy` 放进 runtime packet。
- `task_executor._task_sandbox_policy()` 使用 `storage_space.artifact_root` 生成 `artifact_root/publish_scopes/write_scopes`。
- `task_executor` 能从工具观察中收集 `artifact_refs`，并用于 completion evidence。

图任务链目前的断点：

```text
backend/task_system/compiler/graph_harness_config_publisher.py
```

- `GraphHarnessConfig.task_environment_id` 已写入。
- 但 `GraphHarnessConfig.resources` 当前主要是图内 `resource_nodes`。
- `GraphHarnessConfig.memory` 当前主要是 `working_memory_policy/memory_matrix/memory_protocol/read_rules`。
- `GraphHarnessConfig.artifacts` 当前主要是 `artifact_context_edges`。
- 发布器没有把已解析任务环境的 `storage_space/file_access_tables/memory_space/artifact_policy` 一并锁进 GraphHarnessConfig。

```text
backend/harness/graph/context_materializer.py
```

- `memory_view_request` 只包含 `node_memory_policy` 和 `graph_memory_policy`。
- `artifact_view_request` 只包含 `node_artifact_policy` 和 `graph_artifact_policy`。
- `file_view_request` 只包含 `node_file_policy` 和 `graph_resource_policy`。
- 这些请求没有指向环境级正式 memory repository、artifact repository、artifact_root、file_access_table。

```text
backend/harness/runtime/single_agent_host.py
```

- `get_task_run_artifacts()` 只从 TaskRun diagnostics 和 AgentRunResult 收集 artifact refs，再按项目根检查文件存在。
- `get_task_run_memory_receipts()` 当前返回空 `memory_operations`。

```text
backend/artifact_system/artifact_repository_service.py
```

- ArtifactRepositoryService 已能记录 materialization，支持 run/project/durable scope、graph_run_id、producer_node_id、output_contract_id、content_hash。
- 但当前主运行链没有看到 `task_executor` 或 `GraphNodeWorkOrderExecutor` 自动调用 `record_materialization()`。
- 因此产物仓库存在，但没有成为图任务节点产物落盘的正式闭环。

因此判断：

```text
任务环境系统已经能规划产物空间、记忆空间和文件访问边界；
单 agent 执行链已经部分使用环境 storage/artifact_root；
图任务还没有把环境级 memory_space/artifact_policy/file_access_tables 变成 GraphHarnessConfig 的一等运行字段；
图节点的 memory/artifact/file view 还不是正式 repository handle；
产物 refs 能被收集和验证，但没有稳定写入 ArtifactRepositoryService；
记忆候选能在 NodeResultEnvelope 模型上表达，但没有正式写入/提交 receipt。
```

目标闭环应是：

```text
TaskEnvironment
-> resolved environment boundary
-> GraphHarnessConfig.environment
-> GraphRuntimeEnvelope resource/memory/artifact/file scope
-> GraphNodeWorkOrder memory_view_request/artifact_view_request/file_view_request
-> single agent RuntimeAssembly task_environment
-> tool write/read observations
-> ArtifactRepositoryService materialization
-> MemoryRepository / formal memory commit receipt
-> NodeResultEnvelope artifact_refs/memory_candidates
-> GraphLoop result_index
-> GraphRunMonitor node_runtime_views
```

必须补的一等字段：

```text
GraphHarnessConfig.environment:
  task_environment_id
  storage_space
  file_access_tables
  file_management
  memory_space
  artifact_policy

GraphNodeWorkOrder:
  artifact_space_ref
  memory_space_ref
  file_access_table_refs
  artifact_repository_targets
  memory_repository_targets

NodeResultEnvelope:
  artifact_materialization_receipts
  memory_commit_receipts
```

关键边界：

```text
1. 产物和记忆空间属于任务环境提供的系统环境，不由 agent 自行选择。
2. agent 可以提交 artifact refs、memory candidates、write intents，但正式落库/提交由系统服务执行。
3. 图任务节点可以读取和写入的记忆库、产物库必须来自任务环境和图配置的交集。
4. 产物读取/写入必须有 repository_id、collection_id、scope_kind、artifact_root 或 file_access_table 依据。
5. 记忆写入必须经过 memory candidate -> review/commit -> receipt，不能让普通 agent 任意写正式记忆。
```

## 13. 权限与工具配置判断

代码证据显示：

```text
GraphHarnessConfig.tools / permissions
-> GraphContextMaterializer.input_package.tool_capability_table / permission_summary
-> GraphNodeWorkOrder.tool_scope / permission_scope
-> QueryRuntime._graph_node_task_selection().runtime_profile.tool_policy / permission_policy
-> assemble_runtime()
-> project_operation_authorization()
-> available_tools
```

这是正确方向：工具和权限应由任务环境、agent profile、节点配置共同影响 runtime assembly。

但当前仍有两个问题：

```text
1. GraphHarnessConfig.tools 字段结构没有硬 schema，导致 allowed_operations、operation_ceiling、blocked_operations、tool_exposure_policy 的来源不够可审查。
2. work_order.tool_scope 中没有 allowed_operations 时，allowed_operations 字段会为空，但 runtime_profile.tool_policy 仍可能含 operation_ceiling。这个链路能被 assembly 部分消费，但报告/预览层不能证明最终工具表如何生成。
```

建议后续在 `GraphHarnessConfig` 中明确工具策略字段：

```text
tools.allowed_operations
tools.operation_ceiling
tools.blocked_operations
tools.tool_exposure_policy
tools.required_tools
tools.denied_tools
tools.risk_policy_refs
```

并让编译预览输出最终工具授权投影。

## 14. 字段消费矩阵

| 字段区域 | 生产者 | 当前消费者 | 当前状态 | 结论 |
| --- | --- | --- | --- | --- |
| `config_id/content_hash/status` | publisher/repository | repository/API/GraphRuntime | 强消费 | 已闭合 |
| `task_environment_id` | save mapper/publisher | GraphRuntime diagnostics、graph node task selection | 部分消费 | 需要进入 TaskRunContract |
| `control.start_node_ids` | publisher | SchedulerView/GraphLoop | 强消费 | 已闭合 |
| `control.terminal_node_ids` | publisher | SchedulerView/GraphLoop | 强消费 | 已闭合 |
| `control.max_active_nodes` | publisher | GraphLoop.dispatch_ready | 强消费 | 已闭合 |
| `control.completion_policy` | publisher | 无完整消费 | 弱消费 | 需实现 |
| `control.failure_policy` | publisher | 无完整消费 | 弱消费 | 需实现 |
| `control.retry_policy` | publisher | 无完整消费 | 弱消费 | 需实现 |
| `nodes[*].executor.executor_type` | publisher | SchedulerView/GraphLoop/WorkOrder | 强消费 | 已闭合基础能力 |
| `nodes[*].prompt` | publisher | Materializer input_package | 部分消费 | 需进入 TaskRunContract.prompt_contract |
| `nodes[*].contracts` | publisher | Materializer/TaskRunContract.acceptance_policy | 部分消费 | 需输入/输出/验收拆分 |
| `nodes[*].memory` | publisher | Materializer memory_view | 部分消费 | 需接 memory read/write |
| `nodes[*].artifacts` | publisher | Materializer artifact_view | 部分消费 | 需接 artifact policy |
| `nodes[*].files` | 当前未发布 | Materializer file_view 读取 | 断点 | 必须补上 |
| `nodes[*].permissions/tools` | publisher | Materializer/QueryRuntime/assembly | 部分消费 | 需 schema 和授权投影诊断 |
| `environment.storage_space` | TaskEnvironment resolver | single agent RuntimeAssembly / task_executor | 图链未锁定 | 需进入 GraphHarnessConfig.environment |
| `environment.file_access_tables` | TaskEnvironment resolver | RuntimeCompiler packet 展示 | 图链未锁定 | 需进入 WorkOrder file scope |
| `environment.memory_space` | TaskEnvironment resolver | packet 展示为主 | 未闭合 | 需映射为正式 memory repository handles |
| `environment.artifact_policy` | TaskEnvironment resolver | single agent artifact_root 部分消费 | 图链未闭合 | 需映射为 artifact repository targets |
| `ArtifactRepositoryService.record_materialization()` | artifact system | 当前主运行链无自动调用 | 未闭合 | 节点产物需正式落库 |
| `get_task_run_memory_receipts()` | runtime host | 当前返回空 | 未闭合 | 需接 memory candidate/commit receipts |
| `edges[*].scheduler_role` | publisher/language | SchedulerView | 强消费 | 已闭合基础能力 |
| `edges[*].payload_contract_id` | publisher | handoff packet | 弱消费 | 需校验 |
| `edges[*].result_delivery_policy` | publisher | handoff packet | 弱消费 | 需驱动过滤 |
| `edges[*].ack_policy/ack_required` | publisher | handoff packet | 弱消费 | 需 edge state 状态机 |
| `edges[*].context_filter_policy` | publisher | 几乎未消费 | 未闭合 | 需过滤 |
| `edges[*].artifact_ref_policy` | publisher | 几乎未消费 | 未闭合 | 需过滤 |
| `edges[*].working_memory_handoff_policy` | publisher | 几乎未消费 | 未闭合 | 需过滤 |
| `contracts.manifest` | publisher | preview 展示为主 | 未闭合 | 需 runtime 校验 |
| `NodeResultEnvelope.decisions` | model supports | loop/materializer 可传递 | 弱回写 | 需 executor 提取 |
| `NodeResultEnvelope.memory_candidates` | model supports | packet 可传递 | 弱回写 | 需 executor 提取 |
| `GraphRunRunner / graph execution pump` | `backend/harness/graph/runner.py` | active/ready work order 执行泵 | 基础闭合 | 仍需接前端运行按钮和后台调度 |
| `GraphHarness.execute_work_order()` | API / runner 调用 | 单个 work order 执行 | 局部闭合 | 持续执行由 runner 负责 |
| `dispatchGraphRunReadyNodes()` | 前端/接口调用 | GraphLoop 派发 active work order | 局部闭合 | 只派发不执行 |
| `TaskRunContract.contract_source` | task_lifecycle / graph work order adapter | task run diagnostics / 人工推断 | 部分消费 | 只能说明合同来源，不能替代任务来源协议 |
| `TaskRun.diagnostics.source` | 多个入口自由写入 | trace / monitor / 人工推断 | 弱协议 | 需收口到 `diagnostics.origin` |
| `EngagementRequest.requested_by` | EngagementService | engagement admission / run record | 局部消费 | 只覆盖 engagement 链路 |
| `AgentRun.spawn_mode/context_scope` | task lifecycle / graph adapter | monitor / 人工推断 | 局部消费 | 只表达执行形态，不表达任务来源 |
| `origin_kind/origin_authority/origin_ref/parent_run_ref` | 当前未统一生产 | 当前无统一消费者 | 缺失 | 必须新增统一来源协议 |

## 15. 修复原则

后续实施必须遵守以下原则：

```text
1. GraphHarnessConfig 是唯一发布后运行配置语言。
2. 任务系统/编辑器负责图语言、保存、归一化、发布。
3. Harness 不读取编辑器草稿，不读取未发布 TaskGraphDefinition。
4. GraphRuntime 只做静态锁定和运行记录创建。
5. GraphLoop 只做动态状态推进和控制策略执行。
6. GraphContextMaterializer 只做节点输入包装配，不重新决定任务语义。
7. 单 agent runtime 只消费 work order 派生的 TaskRunContract/runtime_task_selection。
8. 边通信必须由 edges[*] 策略驱动，不能默认全量透传上游结果。
9. GraphRun 必须有执行泵负责持续执行 active/ready work orders，不能依赖前端手动反复调用。
10. GraphRunRunner 可以调用 GraphHarness.execute_work_order，但不能绕过 GraphLoop 直接改状态。
11. TaskRun 必须带统一来源协议，不能只靠 diagnostics.source、contract_source、spawn_mode 推断。
12. agent 自主发起任务和系统下发任务必须在来源协议上硬区分。
13. prompt 必须是 agent 可直接理解的职责说明，不能是开发说明。
14. 图任务可以复用单 agent executor，但不能改写普通单 agent 入口和 agent loop 决策协议。
15. GraphRunRunner 只能接管来源明确为 graph_node_assigned 且 parent_run_ref 属于当前 GraphRun 的节点任务。
16. 普通 task executor recovery 不能独立续跑图节点 TaskRun；图节点恢复必须回到 GraphRunRunner / GraphLoop。
17. 全局/会话监控只显式展示图任务根运行；图节点子任务只作为 GraphRun monitor 的内部执行单元展示。
18. 产物和记忆空间由任务环境提供，agent 只提交 refs/candidates/intents，正式落库由系统服务执行。
19. 图任务节点可读写的 memory/artifact/file repository 必须来自任务环境与图配置的交集。
20. 不为兼容旧链路保留第二套运行入口。
```

## 16. 分阶段修复计划

### 阶段一：修复配置语言硬断点

目标：先关闭明显断链，不改复杂调度语义。

文件：

```text
backend/task_system/compiler/graph_harness_config_publisher.py
backend/api/task_system.py
backend/harness/graph/context_materializer.py
backend/query/runtime.py
backend/harness/graph/models.py
```

动作：

```text
1. 发布器补齐 nodes[*].files，和 materializer._file_view_request() 对齐。
2. 发布器解析 prompt_resource_id，确保 prompt library 中的节点职责能进入 nodes[*].prompt。
3. _graph_node_contract_from_work_order() 填充 prompt_contract、task_environment_id、runtime_profile。
4. 修正 graph node executor profile 和 TaskRun.agent_profile_id 的一致性。
5. 建立统一任务来源协议 origin，并在 agent request_task_run、graph node work order、engagement graph task run、API graph start 四个入口写入。
6. 在恢复语义上隔离普通单 agent TaskRun 和 graph_node_assigned TaskRun，避免普通 executor recovery 绕过 GraphRunRunner 续跑图节点。
7. GraphHarnessConfig 增加 environment 字段，锁定 task_environment_id、storage_space、file_access_tables、file_management、memory_space、artifact_policy。
8. WorkOrder 增加环境派生的 artifact_space_ref、memory_space_ref、file_access_table_refs、artifact_repository_targets、memory_repository_targets。
```

验收：

```text
任意 agent 节点发布后，GraphHarnessConfig.nodes[*].prompt 非空时，TaskRunContract.prompt_contract 必须可见。
任务环境 ID 必须进入 TaskRunContract。
文件策略必须进入 work_order.file_view_request。
任意 TaskRun 都能通过 diagnostics.origin 或 contract.origin 判断是 agent 自主发起、系统图节点下发、任务系统下发，还是用户/API 直接启动。
普通 agent request_task_run 的合同生成、runtime_task_selection、task executor 入口不得因为图任务字段而改变。
图节点 TaskRun 被恢复时必须回到 GraphRunRunner / GraphLoop，不得被普通单 agent 恢复器独立续跑。
GraphHarnessConfig 发布后必须能证明任务环境的 storage/artifact/memory/file 边界已被锁定，不依赖运行时再猜。
```

### 阶段二：增加 GraphHarnessConfig 字段消费诊断

目标：让编辑器和后端都能看到字段是否被消费。

文件：

```text
backend/api/task_system.py
backend/harness/graph/models.py
backend/harness/graph/scheduler_view.py
frontend/src/components/workspace/views/task-system/TaskGraphContractPreviewPanel.tsx
frontend/src/lib/api.ts
```

动作：

```text
1. 编译预览返回 consumption_diagnostics。
2. 标记 consumed_by_runtime / consumed_by_loop / consumed_by_materializer / consumed_by_agent_runtime / unconsumed。
3. 前端预览显示未消费字段。
```

验收：

```text
发布前可以看到 GraphHarnessConfig 每个核心字段的消费状态。
```

### 阶段三：GraphLoop 控制策略闭合

目标：从基础 DAG 调度器升级为配置语言驱动的 loop。

文件：

```text
backend/harness/graph/loop.py
backend/harness/graph/scheduler_view.py
backend/harness/graph/language.py
backend/harness/graph/models.py
```

动作：

```text
1. 实现 completion_policy。
2. 实现 failure_policy。
3. 实现 retry_policy。
4. 实现 wait_policy / join_policy。
5. 明确 conditional_dependency / revision edge 的推进语义。
```

验收：

```text
GraphLoop 不再硬编码“任一 failed 则图 failed / terminal completed 则 completed”作为唯一策略。
```

### 阶段四：GraphRunRunner 持续执行泵

目标：让图任务从“可手动推进”升级为“启动后可持续运行到终态”。

文件：

```text
backend/harness/graph/runner.py
backend/harness/graph_harness.py
backend/api/orchestration.py
backend/harness/runtime/monitor_projection.py
backend/task_system/engagement/dispatcher.py
frontend/src/lib/api.ts
frontend/src/lib/store/runtime.ts
frontend/src/components/workspace/views/task-system/TaskGraphRunInteractionDock.tsx
```

动作：

```text
1. 新增 GraphRunRunner，负责循环执行 GraphLoop 当前 active/ready work orders。
2. runner 每次只通过 GraphHarness.execute_work_order() 执行节点，不直接修改 GraphLoopState。
3. runner 执行后读取返回的 node_work_orders，并继续执行，直到 graph_loop_state.status 进入 completed/failed/blocked/waiting_human_gate。
4. runner 每轮执行前校验 GraphHarnessConfig config_id/content_hash，保持 config 锁定。
5. runner 支持 max_steps/max_nodes/max_runtime_seconds，避免无限循环。
6. start_task_graph_harness_run 增加 run_mode：dispatch_only / auto_run。默认应按产品语义选择 auto_run，调试页面可保留 dispatch_only。
7. engagement graph task run 默认启动 auto_run。
8. resume_run 能在 active_work_orders 存在时继续执行这些 work orders，而不是只返回给前端。
9. 监控页面展示 runner 状态：idle/running/waiting/terminal/failed。
10. runner 不扫描普通 waiting_executor TaskRun，只从 GraphLoopState.active_work_orders / ready nodes 获取图节点执行单元。
11. runner 执行单 agent 节点时只创建或续跑 graph_node_assigned TaskRun，不接管 agent_requested TaskRun。
12. GraphRun monitor 增加 node_runtime_views 和 timeline，把节点 executor TaskRun 的状态、最新步骤、工具调用摘要、产物、错误挂回对应 node。
13. 全局/会话 monitor 保持只显示图任务根 TaskRun，不把 graph_node_assigned 子任务显示成独立任务。
```

验收：

```text
一个三节点线性图启动后，不需要前端手动调用 executeGraphWorkOrder，就能自动执行 first -> second -> third 并完成 GraphRun。
中途服务重启后，runner 能从 checkpoint 中恢复 active_work_orders 或 ready nodes 继续运行。
runner 不绕过 GraphLoop，不直接写 node_states/result_index。
全局/会话监控中只出现一个图任务根运行；节点子任务只在 GraphRun monitor 内可见。
GraphRun monitor 能看到 runner 状态、每个节点状态、active work order、节点 executor TaskRun 引用和节点 trace drilldown。
```

### 阶段五：边通信协议闭合

目标：边既是拓扑关系，也是通信和状态协议。

文件：

```text
backend/harness/graph/context_materializer.py
backend/harness/graph/loop.py
backend/harness/graph/models.py
```

动作：

```text
1. payload_contract_id 做结构校验。
2. result_delivery_policy 决定 payload 内容。
3. context_filter_policy 过滤下游可见上下文。
4. artifact_ref_policy 过滤 artifact refs。
5. working_memory_handoff_policy 过滤 memory_candidates。
6. ack_policy / ack_required 进入 edge_states。
```

验收：

```text
下游节点输入包能证明自己只接收了边策略允许的上游数据。
```

### 阶段六：节点结果标准化

目标：让节点输出能稳定支撑后续节点。

文件：

```text
backend/harness/graph/work_order_executor.py
backend/harness/loop/task_executor.py
backend/harness/loop/model_action_protocol.py
backend/harness/runtime/compiler.py
```

动作：

```text
1. task execution 输出协议支持 structured_output / contract_output / decisions / memory_candidates / verification。
2. task_executor 保存结构化结果。
3. work_order_executor 从 executor_result 提取 NodeResultEnvelope 标准字段。
```

验收：

```text
下游节点不再只能依赖 final_answer/handoff_summary。
```

### 阶段七：产物与记忆环境闭环

目标：让图节点产物、记忆候选、正式记忆提交都进入任务环境提供的空间。

文件：

```text
backend/harness/graph/work_order_executor.py
backend/harness/loop/task_executor.py
backend/harness/runtime/single_agent_host.py
backend/artifact_system/artifact_repository_service.py
backend/memory_system/formal_memory_service.py
backend/harness/graph/context_materializer.py
backend/harness/graph/models.py
```

动作：

```text
1. task_executor 完成后根据 verified artifact_refs 和 output_contract_id 调用 ArtifactRepositoryService.record_materialization()。
2. graph work_order_executor 把 artifact materialization receipt 写入 NodeResultEnvelope.artifact_materialization_receipts。
3. GraphRun monitor 的 node_runtime_views 展示 artifact repository records，而不是只展示路径字符串。
4. NodeResultEnvelope.memory_candidates 进入正式 memory candidate 流程。
5. memory_commit 节点或 commit edge 通过系统服务产生 memory_commit_receipts。
6. get_task_run_memory_receipts() 返回真实 memory candidate/commit receipts，不再返回空列表。
7. 下游节点的 memory_view_request/artifact_view_request 根据 repository_id/collection_id/scope_kind 读取正式库。
```

验收：

```text
写作环境下的 draft 节点产物进入 repo.writing.artifact_repository 或环境映射的 artifact repository。
memory_commit 节点只能提交任务环境允许的 memory_repository。
下游节点读取的 artifact/memory 必须能回溯到 repository_id、collection_id、scope_kind、producer_node_id、graph_run_id。
```

## 17. 必须补的测试

```text
1. 发布器测试：prompt_resource_id 能进入 GraphHarnessConfig.nodes[*].prompt。
2. 发布器测试：nodes[*].files 被发布，并进入 work_order.file_view_request。
3. 单 agent 桥接测试：TaskRunContract.prompt_contract/task_environment_id/runtime_profile 被填充。
4. GraphLoop 测试：completion_policy/failure_policy/retry_policy 控制运行结果。
5. GraphRunRunner 测试：三节点线性图启动后自动执行所有节点并完成 GraphRun，不需要前端手动 executeGraphWorkOrder。
6. GraphRunRunner 恢复测试：存在 active_work_orders 的 checkpoint 可以恢复并继续执行；config_id/content_hash 不匹配时 fail closed。
7. GraphRunRunner 预算测试：max_nodes/max_runtime_seconds 生效，超预算后留下可恢复状态。
8. 边通信测试：context_filter_policy/result_delivery_policy/payload_contract_id 生效。
9. ack 测试：ack_required 边进入 edge_states 并影响推进。
10. NodeResultEnvelope 测试：structured_output/decisions/memory_candidates 可以从单 agent 执行结果回写。
11. 来源协议测试：agent request_task_run 生成 origin_kind=agent_requested；graph node work order 生成 origin_kind=graph_node_assigned；engagement graph task run 生成 origin_kind=engagement_assigned；API 直接启动图任务生成 origin_kind=user_requested 或 system_assigned；TaskRun、TaskRunContract、AgentRun 的 origin_ref 与 parent_run_ref 一致。
12. 单 agent 隔离测试：普通 agent request_task_run 的 contract_source、runtime_task_selection、agent loop action protocol 不受图任务字段影响。
13. 恢复隔离测试：recover_interrupted_task_executors 不得把 graph_node_assigned TaskRun 当作普通任务独立续跑；图节点恢复必须由 GraphRunRunner 驱动。
14. runner 隔离测试：GraphRunRunner 不扫描或执行 origin_kind=agent_requested 的 TaskRun。
15. 监控隔离测试：全局/会话 monitor 只显示图任务根 TaskRun，不显示 graph_node_assigned 子任务为独立任务。
16. GraphRun monitor 测试：node_runtime_views 按节点列出子任务状态、work_order、node_executor_task_run_id、latest_step、artifact_refs、error。
17. GraphRun timeline 测试：timeline 同时包含 graph_loop、runner、node executor、checkpoint 的关键事件，并能按 node_id/work_order_id/task_run_id 关联。
18. 任务环境锁定测试：发布 GraphHarnessConfig 后包含 environment.storage_space/file_access_tables/memory_space/artifact_policy。
19. 产物落库测试：节点写入 artifact 后自动调用 ArtifactRepositoryService.record_materialization，并能按 graph_run_id/output_contract_id/producer_node_id 查询。
20. 记忆 receipt 测试：memory_candidates 经过 memory_commit 节点后产生 memory_commit_receipts，get_task_run_memory_receipts 不再为空。
21. 产物/记忆读取测试：下游节点只能读取环境和图配置允许的 repository/collection/scope。
22. 前端预览测试：未消费字段能在图契约预览中显示。
```

## 18. 最终判断

当前代码不是“完全没接上”，而是“主链接上了，基础持续运行闭环已补上，但配置语言、监控、产物和记忆仍没有逐字段闭合”。

`GraphRunRunner / graph execution pump` 的基础能力已实现；后续阻塞点转为前端/后台调度接入、GraphRun monitor 节点视图、结构化节点通信、正式 artifact/memory repository 闭环。

主链的权威关系应保持：

```text
TaskGraphDefinition
-> GraphHarnessConfig
-> GraphRuntime
-> GraphLoop
-> GraphNodeWorkOrder
-> single agent TaskRun
-> NodeResultEnvelope
-> GraphLoop
-> GraphRunRunner 持续拉取下一批 active/ready work orders
```

需要立刻避免的错误方向：

```text
1. 不要新增 GraphAgentNodeContract / GraphControlContract / GraphHandoffContract 这类外部权威对象。
2. 不要让 GraphLoop 回读 TaskGraphDefinition。
3. 不要让编辑器图草稿直接启动运行。
4. 不要用 metadata 猜语义。
5. 不要把 input_package/resource_requirements 当作永久万能桶。
6. 不要用 diagnostics.source、contract_source、spawn_mode 任意组合替代正式来源协议。
7. 不要让 agent 自己声明或改写任务来源；来源只能由系统入口写入。
8. 不要把 dispatch_ready 或前端“续跑”按钮当作持续执行能力。
9. 不要让 runner 绕过 GraphLoop 直接改 node_states/result_index。
10. 不要让 GraphRunRunner 扫描普通单 agent waiting_executor 队列。
11. 不要让普通 task executor recovery 独立续跑 graph_node_assigned TaskRun。
12. 不要为了图任务修改普通 agent loop 的 request_task_run 决策协议。
13. 不要把图节点子任务作为全局/会话监控里的独立任务显式展示。
14. 不要让 GraphRun monitor 只展示根事件而丢失节点 executor trace。
15. 不要让 agent 直接决定正式产物库或正式记忆库写入位置。
16. 不要只保存 artifact_refs 路径字符串而不写 ArtifactRepositoryService。
17. 不要让 memory_candidates 绕过 review/commit/receipt 直接变成正式记忆。
18. 不要保留旧运行链路作为兼容入口。
```

正确方向是：

```text
把 GraphHarnessConfig 的字段定义变硬；
把发布器输出、GraphLoop 控制、Materializer 输入包、单 agent runtime packet、NodeResultEnvelope 回写逐字段闭合；
把 TaskRun / TaskRunContract / AgentRun 的来源协议统一；
把 GraphRunRunner 接入前端运行按钮和后台调度，让图任务启动后可以自动持续执行到终态；
隔离 GraphRunRunner 与普通单 agent 主链，保证图任务只通过明确来源的 graph_node_assigned TaskRun 复用单 agent executor；
把监控收口为“全局一个图任务，图内完整节点子任务时间线”；
把产物和记忆收口到任务环境提供的 artifact repository、memory repository、file access table 和 storage_space；
用测试证明每个关键字段是真的进入了运行，不只是被保存或展示。
```

## 19. 本轮实施记录

已完成：

```text
1. GraphHarnessConfig 增加 environment，一次发布时锁定任务环境 runtime payload。
2. graph_harness_config_publisher 从 runtime_policy/context_policy 解析 task_environment_id；不再把 domain_id 当任务环境。
3. GraphRuntimeEnvelope 的 file_scope/memory_scope/sandbox_scope 改为读取已锁定 environment。
4. GraphNodeWorkOrder 增加 artifact_space_ref、memory_space_ref、file_access_table_refs、artifact_repository_targets、memory_repository_targets。
5. GraphContextMaterializer 把 task_environment、runtime_profile、prompt_contract、file/artifact/memory refs 写入 input_package。
6. QueryRuntime 图节点 adapter 把 WorkOrder 精确转为 TaskRunContract.prompt_contract/task_environment_id/runtime_profile。
7. TaskRunContract 增加 origin；普通 agent request_task_run 写入 agent_requested。
8. 图节点 TaskRun/AgentRun/TaskRunContract 写入 graph_node_assigned，并以 graph_run_id 作为 parent_run_ref。
9. recover_interrupted_task_executors 跳过 graph_node_assigned，避免普通单 agent recovery 绕过 GraphLoop 接管图节点。
10. NodeResultEnvelope 增加 artifact_materialization_receipts 和 memory_commit_receipts。
11. Graph work_order_executor 根据已验证 artifact_refs 生成基础 artifact materialization receipts。
12. GraphLoop handoff 和 GraphResultEnvelope 汇总 artifact refs、artifact receipts、memory receipts。
13. 全局/会话 monitor 已通过现有 internal child run 过滤隐藏 graph_node_assigned 子任务，并新增测试锁定。
14. 新增 `backend/harness/graph/runner.py`，实现 GraphRunRunner 执行泵。
15. `GraphHarness.run_until_idle()` 暴露 runner facade。
16. 新增 `/orchestration/harness/graph-runs/{graph_run_id}/run-until-idle` API。
17. `start_task_graph_harness_run()` 支持 `run_mode=auto_run` 和 `runner_budget`，并在 auto-run 后返回最新 root TaskRun、GraphRun、checkpoint、loop state 和 active work orders。
18. `QueryRuntime._create_graph_node_task_run()` 对已存在图节点 TaskRun 增加 origin 校验，防止复用 agent_requested 或错误 graph_run/work_order 的 TaskRun。
19. 前端 API client 新增 `runGraphRunUntilIdle()` 和 `GraphRunUntilIdleResult` 类型。
```

已验证：

```text
python -m compileall backend\harness\graph backend\harness\loop backend\query backend\task_system\compiler
python -m pytest backend/tests/graph_task_runtime_facade_regression.py -q
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
python -m pytest backend/tests/task_environment_registry_regression.py -q
python -m pytest backend/tests/graph_harness_api_regression.py -q
python -m pytest backend/tests/engagement_graph_task_run_regression.py -q
python -m pytest backend/tests/graph_task_runtime_facade_regression.py backend/tests/graph_harness_api_regression.py -q
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py backend/tests/task_environment_registry_regression.py backend/tests/engagement_graph_task_run_regression.py backend/tests/writing_graph_language_preservation_regression.py backend/tests/task_graph_standard_models_test.py backend/tests/specific_task_assembly_policy_regression.py -q
```

仍未完成，不能误判为闭环：

```text
1. 前端任务图页面仍需改为调用 runGraphRunUntilIdle，而不是只调用 dispatchGraphRunReadyNodes。
2. GraphRunRunner 还没有接成后台 BackgroundTasks 调度器；当前是 facade/API 显式执行。
3. ArtifactRepositoryService 尚未正式接入，本轮 receipts 是系统生成的基础 materialization receipt，不是正式 artifact repository record。
4. formal memory commit 服务尚未接入，memory_commit_receipts 只预留并传递结构，尚未形成真实记忆落库闭环。
5. GraphRun monitor 还需要 node_runtime_views，把节点 executor trace、latest_step、artifact receipts 和 error 按 node_id 展开。
6. 下游节点读取 artifact/memory repository 的查询接口还未闭合。
```
