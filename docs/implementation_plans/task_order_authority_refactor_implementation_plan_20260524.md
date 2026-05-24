# 任务系统权威统一重构实施方案

日期：2026-05-24

状态：已实施主链路 / 历史实施方案

依据设计书：`docs/系统规划/214-任务系统权威统一重构设计书-20260524.md`

## 1. 实施目标

本实施方案把设计书中的任务系统权威模型落到当前代码结构中。目标不是继续扩展 `task_selection`，也不是在现有 `TaskRun` 外面包一层 UI 名称，而是建立可执行的权威链路：

```text
ConversationTurn
-> TaskIntentDecision
-> TaskOrderDraft 或 TaskOrder
-> TaskOrderRun
-> ExecutionChannel
-> TaskExecutionEnvelope
-> EffectiveRuntimeAssembly
-> 现有 TaskRunLoop / CoordinationRuntime / AgentAssembly
```

核心约束：

- `ConversationTurn` 不是任务订单。
- `task_selection` 只能是投影或迁移期输入，不能继续作为执行事实。
- Agent mode 只能影响主会话的交互投影，不能决定任务类型。
- 所有任务型工作必须有 `order_id/run_id/execution_channel_id`。
- 普通前台只读检索可以属于 `ConversationTurn` 的观察性运行轨迹，不强行订单化。
- 文件修改、持久写入、后台运行、任务图启动、worker spawn、人工 gate 前必须存在 `TaskOrderRun`。
- Cutover 后不保留无用兼容投影；没有 `TaskOrderRun` 绑定的普通 `TaskRun` 不生成任务订单投射。

## 2. 当前代码依据

### 2.1 `/chat` 仍以 `task_selection` 作为事实输入

相关文件：

```text
backend/api/chat.py
backend/query/models.py
backend/query/runtime.py
frontend/src/lib/store/runtime.ts
frontend/src/lib/mainAgentAssemblyModes.ts
```

现状：

- `ChatRequest` 接收 `task_selection: dict[str, Any]`。
- `QueryRequest` 继续携带 `task_selection`。
- `frontend/src/lib/store/runtime.ts` 的 `sendMessage` 调用 `streamChat`，传入 `buildMainAgentTaskSelection(state.taskSelection, state.mainAgentAssemblyMode)`。
- `frontend/src/lib/mainAgentAssemblyModes.ts` 会把 `agent_id`、`agent_profile_id`、`runtime_lane`、`mode_policy`、`intent_decision` 合入 `task_selection`。

问题：

- `task_selection` 混合了任务选择、Agent 模式、执行策略和运行装配 hint。
- Agent mode 有机会被误当成任务类型真相。
- `/chat` 没有先保存 `ConversationTurn`、`TaskIntentDecision`、`TaskOrderDraft/TaskOrder`。

### 2.2 `QueryRuntime` 直接生成 `taskinst:*` 并进入 `TaskRunLoop`

相关文件：

```text
backend/query/runtime.py
backend/runtime/unit_runtime/loop.py
```

现状：

```text
turn_id = f"turn:{session_id}:{turn_index}"
task_id = f"taskinst:{turn_id}:{_task_instance_suffix(task_selection)}"
TaskRunLoop.run_single_agent_stream(...)
```

问题：

- `taskinst:*` 是运行层 ID，不是上游任务订单。
- 同一条聊天轮次是否是任务、草稿、普通对话，没有结构化判定记录。
- run 与 order 的关系无法审计，也无法表达重试、恢复、人工接管后的新 run。

### 2.3 任务库入口只设置前端状态

相关文件：

```text
frontend/src/components/workspace/views/TaskSystemView.tsx
backend/api/task_system.py
backend/task_system/registry/flow_registry.py
```

现状：

```text
sendTaskToChat(...)
-> setTaskSelection({ selected_task_id, domain_id, label, mode: "single_task" })
-> setWorkspaceView("chat")
```

问题：

- 特定任务仍像 skill/tag。
- 没有创建 `specific_task` order。
- 输入契约、输出契约、role contract、验收策略没有在发起时固化。

### 2.4 任务图入口绕过统一订单

相关文件：

```text
backend/api/orchestration.py
backend/runtime/unit_runtime/loop.py
backend/orchestration/coordination_scheduler.py
frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
```

现状：

- `/orchestration/runtime-loop/task-graphs/{graph_id}/start` 直接编译 graph 并调用 `TaskRunLoop.start_task_graph_run`。
- 初始节点通过 `_schedule_stage_execution_background` 直接调度后台执行。
- 前端 `TaskGraphPublishRunPage.startRun` 只拿到 `task_run_id/coordination_run_id`。

问题：

- graph root 没有 `graph_run TaskOrder`。
- graph node 没有 `graph_node_task TaskOrderRun / ExecutionChannel`。
- 并行节点依赖现有 scheduler 去重和 task_run 追踪，但缺少订单级归属。

### 2.5 运行时骨架可复用

相关文件：

```text
backend/runtime/shared/models.py
backend/runtime/memory/state_index.py
backend/runtime/memory/trace_reader.py
backend/api/orchestration_runtime_loop.py
backend/runtime/agent_assembly/models.py
```

可复用能力：

- `TaskRun`、`AgentRun`、`CoordinationRun`、`CoordinationNodeRun` 已存在。
- `RuntimeStateIndex` 已持久化 task run、agent run、coordination run、node run、worker spawn、delegation。
- `RuntimeLoopTraceReader` 已能按 task run 生成 live monitor。
- `orchestration_runtime_loop` 已有 monitor、approval、stop API。
- `agent_assembly.WorkOrder` 已具备 direct/node/human/subruntime work order 雏形。

实施策略：

- 不重写 `TaskRunLoop`。
- 先新增上游 `TaskOrderAuthority`，再把现有 `TaskRun` 绑定到 `TaskOrderRun`。
- 现有监控从 `TaskRun` 视角扩展为 order/run/channel projection。

### 2.6 `task_selection` 使用面比入口层更广

实施前代码搜索显示，`task_selection` 还被以下系统使用：

```text
backend/agent_system/assembly/runtime_chain.py
backend/runtime/agent_assembly/boundary.py
backend/runtime/agent_assembly/assembler.py
backend/runtime/unit_runtime/sandbox_policy.py
backend/health_system/registry.py
backend/api/orchestration_catalog.py
backend/tests/system_eval/*
backend/tests/professional_task_run_regression.py
backend/tests/query_runtime_runtime_loop_regression.py
```

因此实施时不能在早期“一刀切删除” `task_selection`。正确处理顺序是：

1. Shadow 阶段：保留 `task_selection` 作为 projection / current_turn_context 输入，同时新增 order refs。
2. Cutover 阶段：所有任务型执行必须以 `TaskOrderRun` 为事实源，`task_selection` 只能由 order/envelope 投影生成。
3. Cleanup 阶段：删除仍把 `task_selection` 当执行事实的分支和测试。

特别注意：

- `runtime_chain.py` 中的 `explicit_task_selection` 需要迁移为 `task_order_projection` 或 `task_execution_envelope`。
- `sandbox_policy.py` 可以读取投影，但权限上限必须来自 envelope / effective assembly。
- health/test/system eval 入口必须迁移为标准 order facade，不能长期保留独立任务真相。

## 3. 目标工程结构

新增后端模块：

```text
backend/task_system/orders/__init__.py
backend/task_system/orders/models.py
backend/task_system/orders/intent_decision.py
backend/task_system/orders/order_draft.py
backend/task_system/orders/order_factory.py
backend/task_system/orders/order_registry.py
backend/task_system/orders/run_registry.py
backend/task_system/orders/execution_channel.py
backend/task_system/orders/envelope_compiler.py
backend/task_system/orders/effective_assembly.py
backend/task_system/orders/api_models.py
backend/api/task_orders.py
```

扩展现有模块：

```text
backend/app.py
backend/api/chat.py
backend/query/models.py
backend/query/runtime.py
backend/api/orchestration.py
backend/api/orchestration_runtime_loop.py
backend/orchestration/coordination_scheduler.py
backend/runtime/unit_runtime/loop.py
backend/runtime/memory/state_index.py
backend/runtime/memory/trace_reader.py
backend/runtime/agent_assembly/models.py
frontend/src/lib/api.ts
frontend/src/lib/store/types.ts
frontend/src/lib/store/runtime.ts
frontend/src/lib/mainAgentAssemblyModes.ts
frontend/src/components/workspace/views/TaskSystemView.tsx
frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
frontend/src/components/workspace/views/task-system/*
```

新增测试：

```text
backend/tests/task_order_models_test.py
backend/tests/task_order_registry_regression.py
backend/tests/task_intent_decision_regression.py
backend/tests/task_order_draft_regression.py
backend/tests/task_order_entrypoints_regression.py
backend/tests/task_order_runtime_binding_regression.py
backend/tests/task_order_graph_run_regression.py
backend/tests/task_order_graph_node_regression.py
backend/tests/task_order_monitor_projection_regression.py
frontend/src/lib/taskOrders.test.ts
frontend/src/lib/mainAgentAssemblyModes.test.ts
```

## 4. 数据模型实施

### 4.1 `ConversationTurn`

职责：

- 记录主会话轮次。
- 可关联观察性 `AgentRun`。
- 如果升级为任务，指向 `task_order_ref`。

最小字段：

```text
turn_id
session_id
user_message_ref
assistant_message_ref
interaction_kind = chat_turn | task_order_draft | executable_task
task_intent_decision_id
task_order_ref
created_at
status
metadata
authority = "conversation.turn"
```

存储：

- 放入 `backend/task_system/orders/models.py`。
- 由 `order_registry.py` 持久化到 runtime root 下的 `task_orders/conversation_turns`。
- Shadow 阶段不改 session 原有 message 存储，只额外建索引。

### 4.2 `TaskIntentDecision`

职责：

- 区分聊天、草稿和可执行任务。
- 保存 hard/contract/weak signals、证据和缺失字段。

最小字段：

```text
decision_id
turn_id
decision = chat_turn | task_order_draft | executable_task
confidence
hard_signals
contract_signals
weak_signals
evidence_spans
missing_fields
lifecycle_needs
created_order_id
reason
authority = "task_system.intent_decision"
```

实现规则：

- `intent_decision.py` 先用结构化规则做确定性分类。
- 只读前台检索不自动升级任务。
- `task_selection`、Agent mode、当前页面只能产生 weak signal。
- 任务库明确运行、任务图启动、节点调度、worker spawn 属于 hard signal。
- 自然语言只有在发起者、目标、对象、交付/验收、生命周期价值可抽取时才产生 contract signal。

### 4.3 `TaskOrderDraft`

职责：

- 承接“像任务但证据不足”的状态。
- 防止弱信号直接执行。

规则：

- 不能绑定 `ExecutionChannel`。
- 不能触发持久副作用、后台执行、子 Agent、任务图。
- 只能确认、补齐输入、取消或升级为 `TaskOrder`。

### 4.4 `TaskOrder`

职责：

- 表达已接受的工作契约。
- 作为任务发起事实源。

固定 `order_kind`：

```text
ad_hoc_task
specific_task
graph_run
graph_node_task
agent_spawn_task
human_work
subruntime_task
```

禁止：

- 不允许 `chat_turn` 成为 `order_kind`。
- 不允许 `TaskOrder` 直接代表一次运行。

幂等键：

```text
source + source_ref + task_id + normalized_input_hash + parent_run_id
```

### 4.5 `TaskOrderRun`

职责：

- 表达一张订单的一次运行实例。
- 绑定现有 `TaskRun`。

关系：

```text
TaskOrder 1 -> N TaskOrderRun
TaskOrderRun 1 -> 1 primary TaskRun
TaskOrderRun 1 -> N AgentRun
TaskOrderRun 1 -> 1 primary ExecutionChannel
TaskOrderRun 0/1 -> 1 CoordinationRun
```

规则：

- retry 创建新 `TaskOrderRun`。
- checkpoint resume 可以保留同 run，但必须记录 `resume_attempt`。
- executor assignment 改变后再执行必须创建新 run。

### 4.6 `ExecutionChannel`

职责：

- 表达隔离执行通道实例。
- 支持同一协议多通道并行。

状态机：

```text
created -> running -> waiting_approval -> paused -> completed/failed/cancelled
```

通道拥有：

- cancellation token
- stream binding
- artifact scope
- memory scope
- checkpoint scope
- event cursor
- approval gate binding

## 5. 阶段实施计划

### Phase 1：对象模型、Registry 和 Shadow 写入

目标：

- 新增 order authority 的持久对象。
- 不改变现有执行行为。
- 每个任务型运行旁路生成 order/run/channel projection。

改动文件：

```text
backend/task_system/orders/models.py
backend/task_system/orders/order_registry.py
backend/task_system/orders/run_registry.py
backend/task_system/orders/execution_channel.py
backend/task_system/orders/intent_decision.py
backend/task_system/orders/order_draft.py
backend/task_system/orders/api_models.py
backend/runtime/memory/state_index.py
backend/runtime/memory/trace_reader.py
backend/api/task_orders.py
backend/app.py
```

实施步骤：

1. 定义 dataclass / Pydantic API model。
2. 新增 `TaskOrderRegistry`，使用 runtime root 存储，不复用 task graph registry。
3. 扩展 `RuntimeStateIndex`，增加 order/run/channel bucket 和索引。
4. 新增只读 API：
   - `GET /tasks/orders/{order_id}`
   - `GET /tasks/orders`
   - `GET /tasks/order-runs/{run_id}`
   - `GET /tasks/order-runs/{run_id}/monitor`
5. 在 `TraceReader` 的 monitor summary 中加入 order projection 字段。

完成标准：

- 现有 `/chat`、任务图、监控行为不变。
- 可以通过 API 查询 order/run/channel。
- `TaskRun` 没有 order 时不返回 `task_order_projection`，只能作为会话运行观察轨迹显示，不能伪装为任务订单。

测试：

```text
python -m pytest backend/tests/task_order_models_test.py
python -m pytest backend/tests/task_order_registry_regression.py
python -m pytest backend/tests/task_order_monitor_projection_regression.py
```

### Phase 2：`/chat` 意图判定与订单草稿

目标：

- `/chat` 先创建 `ConversationTurn` 和 `TaskIntentDecision`。
- 弱信号停在 `TaskOrderDraft`。
- 普通对话不误建订单。

改动文件：

```text
backend/api/chat.py
backend/query/models.py
backend/query/runtime.py
backend/task_system/orders/intent_decision.py
backend/task_system/orders/order_draft.py
frontend/src/lib/api.ts
frontend/src/lib/store/types.ts
frontend/src/lib/store/runtime.ts
frontend/src/lib/mainAgentAssemblyModes.ts
```

实施步骤：

1. `ChatRequest` 增加 `task_order_intent`，保留 `task_selection` 仅作为迁移期输入。
2. `QueryRequest` 增加：
   - `conversation_turn_ref`
   - `task_intent_decision_ref`
   - `task_order_ref`
   - `task_order_run_ref`
3. 在 `QueryRuntime.astream` 开始处创建 `ConversationTurn`。
4. 调用 `TaskIntentDecisionService`：
   - pure chat -> 继续普通前台 run 或直接回答。
   - draft -> 返回澄清/确认事件，不进入 `TaskRunLoop`。
   - executable -> 交给 `TaskOrderFactory`。
5. 前端 `mainAgentAssemblyModes` 不再把 mode 生成的 `intent_decision` 写入任务事实，只作为 `main_agent_projection`。
6. 前端 stream event 处理新增：
   - `task_intent_decision`
   - `task_order_draft`
   - `task_order_projection`

完成标准：

- “我们讨论一下方案”只生成 `ConversationTurn + TaskIntentDecision(chat_turn)`。
- 只有任务标签/Agent mode 时生成 draft 或保持 chat，不执行。
- 明确要求写文件/跑测试/后台执行时创建 order/run/channel。
- 现有主会话流式回答不丢失。

测试：

```text
python -m pytest backend/tests/task_intent_decision_regression.py
python -m pytest backend/tests/task_order_draft_regression.py
python -m pytest backend/tests/task_order_entrypoints_regression.py
npm --prefix frontend test -- mainAgentAssemblyModes
```

### Phase 3：特定任务订单化

目标：

- 任务库“发送到主会话/运行”创建 `specific_task TaskOrder`。
- 普通任务不再是 skill/tag。

改动文件：

```text
backend/task_system/orders/order_factory.py
backend/task_system/orders/envelope_compiler.py
backend/task_system/orders/effective_assembly.py
backend/api/task_orders.py
frontend/src/lib/api.ts
frontend/src/components/workspace/views/TaskSystemView.tsx
frontend/src/components/workspace/views/task-system/*
```

实施步骤：

1. `TaskOrderFactory.create_specific_task_order` 从 `SpecificTaskRecord`、projection binding、flow contract binding、execution policy 编译订单。
2. `TaskExecutionEnvelopeCompiler` 生成：
   - role contract
   - responsibility boundary
   - input/output contract
   - artifact policy
   - acceptance policy
   - executor policy
3. API 增加：
   - `POST /tasks/orders`
   - `POST /tasks/orders/{order_id}/runs`
   - `POST /tasks/order-runs/{run_id}/execute`
4. `TaskSystemView.sendTaskToChat` 改成调用 create order，而不是 `setTaskSelection`。
5. 前端 chat 页面显示 order projection。

完成标准：

- 点击任务库任务后产生 `order_id`。
- 前端可看到 `specific_task` order。
- 执行时 TaskRun diagnostics 含 `order_id/run_id/channel_id/envelope_id`。
- 任务 role contract 覆盖本次 effective role，但 Agent profile 不变。

测试：

```text
python -m pytest backend/tests/task_order_entrypoints_regression.py
python -m pytest backend/tests/task_execution_envelope_regression.py
python -m pytest backend/tests/effective_runtime_assembly_regression.py
```

### Phase 4：TaskRunLoop 绑定 order/run/channel

目标：

- 现有运行层消费 `TaskOrderRun` 引用。
- 不再只从 `task_selection` 拼 `taskinst:*`。

改动文件：

```text
backend/query/runtime.py
backend/runtime/unit_runtime/loop.py
backend/runtime/memory/state_index.py
backend/runtime/agent_assembly/models.py
backend/runtime/agent_assembly/*
```

实施步骤：

1. `run_single_agent_stream` 增加参数：
   - `task_order_ref`
   - `task_order_run_ref`
   - `execution_channel_ref`
   - `task_execution_envelope_ref`
2. `TaskRunLoop.start` 写入 diagnostics：
   - `task_order_id`
   - `task_order_run_id`
   - `execution_channel_id`
   - `task_execution_envelope_id`
3. `RuntimeStateIndex.upsert_task_run` 同步写入 run binding index。
4. `WorkOrder` 增加 source refs，不改变现有 direct/node/human/subruntime 类型。
5. 所有 runtime events refs 增加 order/run/channel。

完成标准：

- 按 `order_id` 可查所有 run。
- 按 `task_run_id` 可反查 order/run/channel。
- stop/resume/approval 仍兼容 task_run_id，但内部可定位 channel。

测试：

```text
python -m pytest backend/tests/task_order_runtime_binding_regression.py
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py
python -m pytest backend/tests/runtime_loop_live_monitor_test.py
```

### Phase 5：任务图 root 订单化

目标：

- 任务图 start API 内部变成 facade。
- 每次启动创建 `graph_run TaskOrder`。

改动文件：

```text
backend/api/orchestration.py
backend/task_system/orders/order_factory.py
backend/task_system/orders/envelope_compiler.py
frontend/src/lib/api.ts
frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
```

实施步骤：

1. `start_task_graph_runtime_loop_run` 先调用 `TaskOrderFactory.create_graph_run_order`。
2. 创建 root `TaskOrderRun` 和 root `ExecutionChannel`。
3. 再调用现有 `TaskRunLoop.start_task_graph_run`，传入 order refs。
4. API 返回新增字段：
   - `order_id`
   - `run_id`
   - `execution_channel_id`
5. 前端 bind monitor 时保存 order/run/channel。

完成标准：

- 旧 API 路径仍可用，但 authority 显示为 task order facade。
- 每次图启动都是新的 `graph_run TaskOrder`。
- 返回结果同时包含旧 `task_run_id/coordination_run_id` 和新 `order_id/run_id/channel_id`。

测试：

```text
python -m pytest backend/tests/task_order_graph_run_regression.py
python -m pytest backend/tests/langgraph_coordination_runtime_regression.py
python -m pytest backend/tests/task_graph_batch_runtime_regression.py
```

### Phase 6：任务图节点订单化和并行通道

目标：

- 每个图节点成为 `graph_node_task TaskOrderRun`。
- 并行节点拥有独立 channel。

改动文件：

```text
backend/orchestration/coordination_scheduler.py
backend/runtime/unit_runtime/loop.py
backend/runtime/execution/node_execution_request.py
backend/runtime/agent_assembly/models.py
backend/runtime/coordination_runtime/*
```

实施步骤：

1. `_schedule_stage_execution_background` 在真正后台执行前创建 node order/run/channel。
2. `NodeExecutionRequest` 增加 order refs。
3. `_continue_coordination_delivery_stream` 消费 node run/channel。
4. `CoordinationNodeRun.diagnostics` 写入：
   - `task_order_id`
   - `task_order_run_id`
   - `execution_channel_id`
5. 并行调度时不共享 channel。

完成标准：

- node_A/node_B 并行运行时有不同 `TaskOrderRun` 和 `ExecutionChannel`。
- 两者共享 root `CoordinationRun`。
- join 仍按 node result 等待，不被 order 层破坏。

测试：

```text
python -m pytest backend/tests/task_order_graph_node_regression.py
python -m pytest backend/tests/task_graph_batch_runtime_regression.py
python -m pytest backend/tests/langgraph_coordination_runtime_regression.py
```

### Phase 7：Agent 派生任务与人工介入

目标：

- worker spawn、subruntime、human work 都进入任务系统监管。
- approval、human work、takeover 三分法落地。

改动文件：

```text
backend/runtime/unit_runtime/loop.py
backend/runtime/execution/agent_delegation_executor.py
backend/runtime/execution_permit/approval_gateway.py
backend/api/orchestration_runtime_loop.py
backend/task_system/orders/order_factory.py
backend/task_system/orders/run_registry.py
```

实施步骤：

1. Worker spawn 前创建 `agent_spawn_task TaskOrder`。
2. SubRuntime 前创建 `subruntime_task TaskOrder`。
3. Human work 创建 `human_work TaskOrder`。
4. Approval 只写 approval event，不改变 executor assignment。
5. Takeover 改 executor assignment 时创建新 `TaskOrderRun` 或记录 checkpoint resume takeover event。

完成标准：

- 不存在孤立 `AgentRun`。
- approval 不产出任务结果。
- human work 产出结果并进入验收/产物体系。
- takeover 可审计，不写回 Agent profile。

测试：

```text
python -m pytest backend/tests/main_agent_natural_delegation_regression.py
python -m pytest backend/tests/agent_delegation_permission_regression.py
python -m pytest backend/tests/task_order_entrypoints_regression.py
```

### Phase 8：监控、前端任务订单页和刷新恢复

目标：

- 前端可以按 order/run/channel 查看运行。
- 刷新后不依赖 `taskSelection` 恢复任务状态。

改动文件：

```text
backend/runtime/memory/trace_reader.py
backend/api/task_orders.py
frontend/src/lib/api.ts
frontend/src/lib/store/types.ts
frontend/src/lib/store/runtime.ts
frontend/src/components/workspace/views/task-system/TaskOrderLibraryPage.tsx
frontend/src/components/workspace/views/task-system/TaskSystemShell.tsx
```

实施步骤：

1. 后端 monitor view 增加 order/run/channel projection。
2. 前端 Store 增加：
   - `taskOrderProjection`
   - `taskOrderRunProjection`
   - `executionChannelProjection`
   - `selectedTaskOrderId`
   - `selectedTaskOrderRunId`
3. 新增任务订单页。
4. 刷新时从 `order_id/run_id/channel_id` 恢复选中，不读 `taskSelection`。
5. Chat 页面只展示 projection，不决定任务真相。

完成标准：

- 前端刷新后仍显示同一个 order/run/channel。
- global monitor 可进入任务订单详情。
- 聊天页面不再用 Agent mode 或 taskSelection 伪造运行状态。

测试：

```text
python -m pytest backend/tests/task_order_monitor_projection_regression.py
npm --prefix frontend test
```

### Phase 9：Cutover 与旧逻辑删除

目标：

- 发起权威完全切到 `TaskOrderAuthority`。
- 删除无用旧入口、旧兼容分支、旧测试。

删除或降级内容：

- 只靠 `task_selection` 触发执行的分支。
- `buildMainAgentTaskSelection` 中把 Agent mode 写成任务事实的逻辑。
- 任务库按钮只设置 `selected_task_id` 的逻辑。
- 任务图 start API 直接创建运行的独立真相。
- 图节点 scheduler 直接执行而无 node order/run/channel 的路径。
- worker spawn 创建孤立 `AgentRun` 的路径。
- 无订单绑定时生成任务订单投射的临时写入逻辑。
- 迁移期专用旧测试。

保留内容：

- `task_selection` 可作为只读 projection 或 UI 兼容展示，但不能进入执行事实。
- 旧 `/orchestration/runtime-loop/task-graphs/{graph_id}/start` API 可保留为 facade，内部必须调用 `TaskOrderAuthority`。
- 旧 monitor API 可保留为读取 projection 的 facade。

完成标准：

- 没有 `TaskOrderRun` 的任务型执行请求被拒绝。
- 没有 `ExecutionChannel` 的后台执行、worker spawn、任务图节点执行被拒绝。
- 代码搜索中不存在旧执行入口。

验证命令：

```text
python -m pytest backend/tests/task_order_* backend/tests/query_runtime_runtime_loop_regression.py backend/tests/langgraph_coordination_runtime_regression.py
npm --prefix frontend test
```

## 6. API 目标形态

新增：

```text
POST /tasks/orders
POST /tasks/orders/{order_id}/runs
POST /tasks/order-runs/{run_id}/execute
GET  /tasks/orders
GET  /tasks/orders/{order_id}
GET  /tasks/order-runs/{run_id}
GET  /tasks/order-runs/{run_id}/monitor
POST /tasks/order-runs/{run_id}/stop
POST /tasks/order-runs/{run_id}/resume
POST /tasks/order-runs/{run_id}/approval
```

迁移期 facade：

```text
POST /chat
POST /orchestration/runtime-loop/task-graphs/{graph_id}/start
GET  /orchestration/runtime-loop/task-runs/{task_run_id}/live-monitor
POST /orchestration/runtime-loop/task-runs/{task_run_id}/approval
POST /orchestration/runtime-loop/task-runs/{task_run_id}/stop
```

规则：

- facade 可以接受旧参数，但必须返回 order/run/channel projection。
- Cutover 后 facade 不允许绕过 `TaskOrderAuthority`。

## 7. 前端目标形态

### 7.1 Store

新增状态：

```text
taskOrderProjection
taskOrderRunProjection
executionChannelProjection
taskOrderDraft
taskIntentDecision
selectedTaskOrderId
selectedTaskOrderRunId
selectedExecutionChannelId
```

降级状态：

```text
taskSelection
```

`taskSelection` 仅用于：

- 显示当前 UI 选择。
- 作为 `TaskOrderDraft` 的候选输入。
- 迁移期兼容旧组件。

它不能用于：

- 决定任务类型。
- 决定 executor。
- 决定运行通道。
- 判断任务是否正在运行。

### 7.2 页面

任务系统层级调整：

```text
任务系统
  任务域
  任务定义
  任务订单
  任务图
  运行管理
  资源权威
  编排资源
```

新增任务订单页显示：

- order id / kind / source
- task id / domain
- originating turn
- intent decision evidence
- current run
- channel
- executor
- envelope
- monitor
- artifact
- retry / resume / approval

## 8. 切换规则

### Shadow

允许：

- 旧入口继续执行。
- 旁路写入 order projection。
- monitor 显示 legacy projection。

禁止：

- 新代码依赖 `task_selection` 作为新真相。
- 新增没有 order/run/channel 的任务型入口。

### Cutover

允许：

- 旧 API 作为 facade。
- 旧前端组件读取 projection。

禁止：

- 任何任务型执行绕过 `TaskOrderFactory`。
- 任何后台执行绕过 `ExecutionChannel`。
- 任何 Agent spawn 绕过 `agent_spawn_task`。
- 任何 graph node 绕过 `graph_node_task`。

### Cleanup

必须：

- 删除无用兼容字段。
- 删除无用旧测试。
- 删除仅用于迁移期的写入分支。
- 删除旧执行入口。

不得：

- 为“兼容”保留双真相。
- 在旧壳上继续叠字段。

## 9. 风险与控制

风险 1：主会话被过度任务化。

控制：

- `TaskIntentDecision` 测试覆盖讨论、解释、只读检索。
- 前台只读检索只记录观察性 `AgentRun`。

风险 2：任务图运行被 order 层打断。

控制：

- 先 root order/run/channel，再 node cutover。
- 任务图现有 `TaskRun/CoordinationRun` 不替换，只加绑定。

风险 3：并行节点共享通道。

控制：

- `coordination_scheduler` 测试断言并行节点不同 `ExecutionChannel`。
- channel id 进入 node run diagnostics。

风险 4：Agent mode 继续污染任务事实。

控制：

- `mainAgentAssemblyModes` 测试改为验证 mode 只输出 projection。
- 后端拒绝仅由 Agent mode 触发的 executable task。

风险 5：迁移期出现双真相。

控制：

- Shadow 只写 projection。
- Cutover 后 `TaskOrderAuthority` 是唯一创建入口。
- Cleanup 删除旧分支。

## 10. 总体验收矩阵

必须通过：

- 普通聊天不创建 `TaskOrder`。
- 讨论方案不创建 `TaskOrder`。
- 只有任务标签/Agent mode 不执行。
- 任务库运行创建 `specific_task TaskOrder`。
- 主会话明确执行创建 `ad_hoc_task TaskOrder`。
- 任务图启动创建 `graph_run TaskOrder`。
- 任务图节点创建 `graph_node_task TaskOrderRun`。
- 并行节点不同 channel。
- worker spawn 创建 `agent_spawn_task TaskOrder`。
- approval 不改变 executor assignment。
- human work 有独立 order/run/channel。
- takeover 可审计且不写回 Agent profile。
- 前端刷新后恢复 order/run/channel。
- stop/resume/approval 保持 order 关系。
- 旧无用入口和测试在 Cleanup 阶段删除。

## 11. 开工顺序建议

正式实施时不要一次性改全链路。推荐按以下顺序提交：

1. Phase 1：新增对象和 registry，先写入标准 order/run/channel。
2. Phase 2：`/chat` 判定和草稿，但不切任务库。
3. Phase 3 + Phase 4：特定任务订单化并绑定 `TaskRunLoop`。
4. Phase 5：任务图 root 订单化。
5. Phase 6：任务图节点订单化。
6. Phase 7：Agent spawn / human work / takeover。
7. Phase 8：前端订单页与监控统一。
8. Phase 9：删除旧入口。

每一阶段必须以测试和代码搜索收尾，确认没有新的野生入口。
