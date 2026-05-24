# 任务运行台统一改造计划书

日期：2026-05-24

适用范围：任务系统、图任务运行、单 Agent 特定任务运行、运行监控、系统设置中的任务并发限制。

本计划只处理结构改造，不处理模型 prompt 内容优化，不处理具体游戏任务模板质量，不处理单个图任务节点内部业务逻辑。

## 1. 问题结论

当前系统的问题不是页面布局不顺眼，而是任务启动和任务监控的权威链路分裂。

现有代码里有两条不一致的运行入口：

1. 特定任务入口已经创建了 `TaskOrder / TaskOrderRun / ExecutionChannel / TaskExecutionEnvelope`，但前端仍然把它送回主会话，由主会话通过 `/api/chat` 承接执行。
2. 图任务入口直接调用 `/orchestration/runtime-loop/task-graphs/{graph_id}/start`，后端直接进入 `TaskRunLoop.start_task_graph_run()`，绕过了 `TaskOrderRun / ExecutionChannel / TaskExecutionEnvelope`。

这导致三个结构性后果：

1. 主会话承担了不该承担的任务启动职责，聊天层和任务运行层混在一起。
2. 图任务和单 Agent 特定任务无法共享同一套运行限制、运行事件、产物收口、恢复和监控协议。
3. 前端“图任务层”只能展示图任务，不是一个真正的任务运行台；特定任务、图任务、未来的 verifier / artifact / multi-agent 层没有统一选择和显示方式。

本次改造的目标是把系统收敛成一条链路：

```text
TaskDefinition / SpecificTask / GraphTemplate
-> TaskExecutionLayer[]
-> TaskOrder
-> TaskOrderRun
-> ExecutionChannel
-> TaskExecutionEnvelope
-> TaskRunLoop
-> RuntimeEventLog
-> Runtime Work Projection
-> Task Workbench
```

## 2. 成熟 Agent 架构约束

参考本项目设计原则中的任务系统、Agent 系统和工具系统原则，本次改造采用以下约束：

1. 任务运行必须有统一生命周期：`created -> running -> completed / failed / cancelled`。
2. 任务状态必须有单一权威对象，不能让主会话、图运行、前端本地状态各自解释“当前任务”。
3. 工具、任务、子 Agent、图节点都可以是不同执行形态，但必须收敛到统一的运行记录和事件流。
4. 主会话可以发起任务或展示摘要，但不应该成为任务运行本身的唯一入口。
5. 图任务不是独立于任务系统的特殊世界，它应该是任务的一个执行层；当用户直接运行图模板时，也必须先生成 `graph_run` 类型的任务订单。
6. 并发和运行数量限制必须在后端执行入口强制，不允许只靠前端按钮禁用。
7. 前端任务台应该展示运行事实，不应该用前端本地状态伪造运行状态。

## 3. 当前代码事实

### 3.1 特定任务入口

相关文件：

```text
frontend/src/components/workspace/views/TaskSystemView.tsx
frontend/src/lib/store/runtime.ts
backend/api/task_orders.py
backend/query/runtime.py
backend/task_system/orders/order_factory.py
backend/task_system/orders/order_registry.py
```

当前流程：

```text
TaskSystemView.sendTaskToChat()
-> createTaskOrder()
-> POST /api/tasks/orders
-> TaskOrderFactory.create_specific_task_order()
-> TaskOrderRegistry.upsert_creation()
-> 前端切到 chat
-> runtime.ts buildTaskOrderIntent()
-> /api/chat
-> backend/query/runtime.py resolves or claims TaskOrderRun
-> run_single_agent_stream()
```

判断：

这个流程已经有任务订单对象，但执行入口错位。特定任务不应该靠主聊天页面启动运行，应该由任务运行台调用 `TaskOrderRun execute`。

### 3.2 图任务入口

相关文件：

```text
frontend/src/components/workspace/views/center/CenterWorkspaceView.tsx
frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
frontend/src/lib/api.ts
backend/api/orchestration.py
backend/runtime/unit_runtime/loop.py
```

当前流程：

```text
CenterWorkspaceView / TaskGraphPublishRunPage
-> startTaskGraphRuntimeLoopRun()
-> POST /orchestration/runtime-loop/task-graphs/{graph_id}/start
-> compile_task_graph_definition_runtime_spec()
-> TaskRunLoop.start_task_graph_run()
-> schedule initial stage
-> TaskGraphRunMonitorPanel
```

判断：

这个流程能跑图任务，但绕过了任务订单系统。因此图任务无法自然继承任务订单、任务执行通道、统一运行限制、通用产物收口和任务台信息流。

### 3.3 前端中心工作区

相关文件：

```text
frontend/src/components/workspace/views/center/CenterWorkspaceView.tsx
frontend/src/components/workspace/views/center/centerWorkspaceHelpers.ts
frontend/src/components/task-graph-monitor/TaskGraphRunMonitorPanel.tsx
```

当前结构：

```text
会话层
图任务层
  左：当前任务图列表和图摘要
  右：任务图运行监控
  下：任务目标输入框
```

判断：

这不是任务运行台，只是图任务启动页。它应该改造成：

```text
会话层
任务运行台
  左：拓扑或执行结构视图
  右：当前节点信息流监控
  下：任务运行输入框，内置“任务域 -> 特定任务”的双层选择
```

### 3.4 系统设置

相关文件：

```text
backend/bootstrap/settings.py
backend/api/config_api.py
frontend/src/lib/api.ts
```

当前已有配置能力：

```text
GET /config/runtime-console
PUT /config/runtime-console
```

当前问题：

已有 `model / embedding / retrieval / document / runtime / soul_image_assets / context` 配置组，但没有任务运行限制配置组。任务并发限制不能放在前端，也不能散落在各个启动函数中。

## 4. 目标架构

### 4.1 统一对象模型

新增标准概念：`TaskExecutionLayer`。

它不是前端 UI 概念，而是任务订单或执行信封中的结构化执行计划。图任务、单 Agent、验证、产物收口都作为执行层存在。

标准层类型：

```text
single_agent_layer
graph_layer
verifier_layer
artifact_layer
human_gate_layer
multi_agent_layer
```

第一期只必须落地：

```text
single_agent_layer
graph_layer
verifier_layer
artifact_layer
```

字段结构：

```python
TaskExecutionLayer = {
    "layer_id": str,
    "layer_type": "single_agent_layer" | "graph_layer" | "verifier_layer" | "artifact_layer",
    "title": str,
    "source_ref": str,
    "depends_on": list[str],
    "executor_policy": dict,
    "input_refs": dict,
    "output_refs": dict,
    "acceptance_policy": dict,
    "metadata": dict,
}
```

落点：

```text
backend/task_system/orders/models.py
```

在 `TaskOrder` 和 `TaskExecutionEnvelope` 中增加：

```python
execution_layers: tuple[dict[str, Any], ...] = ()
```

不新增独立数据库表，先随订单和信封持久化，避免引入额外状态源。

### 4.2 统一执行入口

新增后端入口：

```text
POST /api/tasks/order-runs/{run_id}/execute
```

请求模型落点：

```text
backend/task_system/orders/api_models.py
```

请求结构：

```python
class TaskOrderRunExecuteRequest(BaseModel):
    user_goal: str = Field(default="", max_length=20000)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    selected_layer_id: str = Field(default="", max_length=180)
    execute_background: bool = True
    include_trace: bool = True
    source: str = Field(default="task_workbench", max_length=180)
```

响应结构：

```python
class TaskOrderRunExecuteResponse(BaseModel):
    authority: str
    order: dict[str, Any]
    run: dict[str, Any]
    execution_channel: dict[str, Any] | None
    task_execution_envelope: dict[str, Any] | None
    task_run_id: str
    coordination_run_id: str
    monitor_ref: dict[str, Any]
    events: list[dict[str, Any]]
    task_order_projection: dict[str, Any]
```

执行分发规则：

```text
order_kind=specific_task/ad_hoc_task
-> single agent runner

order_kind=graph_run
-> graph runtime runner

order_kind=graph_node_task
-> node execution runner
```

第一期实现：

1. `specific_task` 走已有 `run_single_agent_stream()` 可复用的执行能力，但入口从 `/api/chat` 迁到 `execute`。
2. `graph_run` 先创建或读取 `TaskOrderRun`，再调用 `TaskRunLoop.start_task_graph_run()`，并把 `task_run_id / coordination_run_id` 回写到 `TaskOrderRun / ExecutionChannel`。
3. `graph_node_task` 暂不作为前端直接启动入口，但模型和分发结构预留，避免后续再次分裂。

新增服务落点：

```text
backend/task_system/orders/order_execution_service.py
```

职责：

```text
load order/run/channel/envelope
enforce runtime limit
dispatch by order_kind and execution_layers
bind TaskOrderRun to TaskRun / CoordinationRun
emit task-order scoped events
return canonical projection
```

禁止事项：

1. 禁止 `execute` 接口重新判断用户意图。
2. 禁止 `execute` 接口绕开已有 `TaskOrderRun` 新建一套隐式运行状态。
3. 禁止图任务从前端直接走旧 `/orchestration/runtime-loop/task-graphs/{graph_id}/start` 作为主路径。

### 4.3 图任务订单创建

新增工厂方法：

```text
backend/task_system/orders/order_factory.py
```

```python
def create_graph_run_order(
    *,
    session_id: str,
    graph_record: dict[str, Any],
    objective: str,
    initial_inputs: dict[str, Any] | None = None,
    source: str = "task_workbench",
    source_ref: str = "",
    idempotency_key: str = "",
) -> TaskOrderCreation:
    ...
```

生成结果：

```text
TaskOrder.order_kind = "graph_run"
ExecutionChannel.channel_kind = "task_graph"
TaskExecutionEnvelope.execution_layers contains graph_layer
TaskOrder.source_ref = "task_system.task_graph:{graph_id}"
```

新增 API：

```text
POST /api/tasks/graph-runs/orders
```

落点：

```text
backend/api/task_orders.py
```

请求模型：

```python
class TaskGraphRunOrderCreateRequest(BaseModel):
    session_id: str
    graph_id: str
    objective: str = ""
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    require_published: bool = True
    idempotency_key: str = ""
```

这个接口只创建订单和运行对象，不直接启动。启动必须调用：

```text
POST /api/tasks/order-runs/{run_id}/execute
```

### 4.4 运行限制

新增后端运行限制配置组：

```text
group_id = "task_runtime"
```

落点：

```text
backend/bootstrap/settings.py
backend/api/config_api.py
frontend/src/lib/api.ts
```

字段：

```text
max_global_running_tasks: number
max_session_running_tasks: number
max_running_runs_per_order: number
max_parallel_graph_nodes: number
overflow_policy: "queue" | "reject"
queue_enabled: boolean
stale_running_timeout_seconds: number
```

默认值：

```text
max_global_running_tasks = 3
max_session_running_tasks = 2
max_running_runs_per_order = 1
max_parallel_graph_nodes = 3
overflow_policy = "reject"
queue_enabled = false
stale_running_timeout_seconds = 1800
```

新增服务：

```text
backend/task_system/orders/runtime_limits.py
```

职责：

```text
read task_runtime config
count active TaskOrderRun records
count graph node active executions when graph runtime starts batches
reject or queue according to policy
mark stale running records before counting
return structured denial reason
```

执行入口必须调用：

```python
TaskRuntimeLimitGuard.require_can_start_order_run(...)
```

前端只能展示限制状态，不能作为限制权威。

### 4.5 统一事件与监控

新增或规范任务运行信息流模型：

```text
TaskRunInformationFlow
```

来源：

```text
TaskOrderRun
ExecutionChannel
TaskExecutionEnvelope
TaskRunLoop trace
CoordinationRun monitor
tool events
todo / plan events
verification events
artifact events
recovery events
```

后端新增查询入口：

```text
GET /api/tasks/order-runs/{run_id}/information-flow
```

落点：

```text
backend/api/task_orders.py
backend/task_system/orders/order_information_flow.py
```

响应结构：

```python
{
    "authority": "task_system.order_run_information_flow",
    "run_id": str,
    "order_id": str,
    "task_run_id": str,
    "coordination_run_id": str,
    "status": str,
    "plan": dict,
    "todos": list[dict],
    "tool_events": list[dict],
    "progress_events": list[dict],
    "verification_events": list[dict],
    "recovery_events": list[dict],
    "artifacts": list[dict],
    "latest_summary": dict,
    "raw_refs": dict,
}
```

注意：

1. 信息流 API 不执行任务。
2. 信息流 API 不从前端本地状态补任务事实。
3. 信息流默认按当前选中节点或执行层聚焦；没有明确节点时，使用当前活跃节点；单 Agent 任务使用 `single_agent_root` 作为默认执行节点。
4. 产物进入当前运行的信息流面板，并必须保留 `run_id / layer_id / node_id` 绑定，避免跨任务混淆。

### 4.6 前端任务运行台

中心工作区从：

```text
会话层 / 图任务层
```

改为：

```text
会话层 / 任务运行台
```

修改落点：

```text
frontend/src/components/workspace/views/center/CenterWorkspaceView.tsx
frontend/src/components/workspace/views/center/centerWorkspaceHelpers.ts
```

建议新增组件：

```text
frontend/src/components/workspace/views/center/task-runtime/TaskRuntimeWorkbench.tsx
frontend/src/components/workspace/views/center/task-runtime/TaskTopologyPanel.tsx
frontend/src/components/workspace/views/center/task-runtime/TaskNodeInformationFlowPanel.tsx
frontend/src/components/workspace/views/center/task-runtime/TaskRunComposer.tsx
frontend/src/components/workspace/views/center/task-runtime/taskRuntimeWorkbenchTypes.ts
```

页面结构：

```text
TaskRuntimeWorkbench
  Left: TaskTopologyPanel
    - graph task: task graph topology
    - single-agent task: single_agent_root node + execution contract summary
    - layered task: layer chain and node/layer relationship
    - running/recent runs can be shown as topology context, not as a separate selector list
  Right: TaskNodeInformationFlowPanel
    - current node/layer progress
    - current node/layer todo/plan
    - current node/layer tool calls
    - current node/layer verification/recovery
    - current node/layer artifacts
  Bottom: TaskRunComposer
    - task domain select
    - specific task select
    - selected task objective
    - run button
    - resume/continue button when a run is selected
```

设计规则：

1. 任务选择不占用左栏，统一放入底部 `TaskRunComposer`。
2. 底部选择器采用双层结构：先选任务域，再选该域下的特定任务；后续图层由特定任务的执行层或追加层决定。
3. 左侧主概念是“拓扑/执行结构”，不是任务列表。
4. 图任务显示真实拓扑图；单 Agent 特定任务显示 `single_agent_root` 执行节点和契约摘要，避免单 Agent 与图任务监控协议分裂。
5. 右侧主概念是“当前节点信息流”，不是泛化总监控；默认聚焦当前活跃节点，用户点击左侧节点后切换监控对象。
6. 任务级摘要和产物可以作为右侧面板的运行头部/底部区域出现，但所有细节必须绑定到当前 `node_id / layer_id / run_id`。
7. 图任务和单 Agent 特定任务都从任务运行台消息框启动。
8. 主会话不再是特定任务默认启动入口。
9. 不把任务定义编辑、任务启动、运行监控混在同一个平面；任务系统管理页继续负责定义，任务运行台负责运行。

### 4.7 前端 API

修改落点：

```text
frontend/src/lib/api.ts
```

新增函数：

```ts
export async function createTaskGraphRunOrder(payload: TaskGraphRunOrderCreatePayload): Promise<TaskOrderProjection>

export async function executeTaskOrderRun(
  runId: string,
  payload: TaskOrderRunExecutePayload
): Promise<TaskOrderRunExecuteResponse>

export async function getTaskOrderRunInformationFlow(runId: string): Promise<TaskRunInformationFlow>
```

保留但降级：

```ts
startTaskGraphRuntimeLoopRun()
```

第一期保留给旧管理页内部或回归测试使用，但前端任务运行台不得使用它。图任务切换完成后，删除旧 UI 中的直接启动调用。

### 4.8 Store 与运行投影

修改落点：

```text
frontend/src/lib/store/types.ts
frontend/src/lib/store/runtime.ts
frontend/src/lib/runtimeWorkProjection.ts
```

新增 store 状态：

```ts
taskRuntimeWorkbench: {
  selectedTaskSource: "specific_task" | "order_run";
  selectedDomainId: string;
  selectedTaskId: string;
  selectedGraphId: string;
  selectedOrderId: string;
  selectedRunId: string;
  selectedLayerId: string;
  selectedNodeId: string;
  informationFlow: TaskRunInformationFlow | null;
  runningRunIds: string[];
}
```

移除或停止主路径使用：

```text
frontend_task_order_intent -> /api/chat
sendTaskToChat() 默认切主会话
CenterWorkspaceView.handleStartGraph() 直接 start graph
```

主会话仍可显示任务摘要和链接，但不能再作为任务运行权威入口。

## 5. 实施阶段

### Phase 0：术语冻结与旧入口标记

目标：

明确新名称和旧路径，不开始大面积改代码。

必须完成：

1. 将前端 `CenterWorkspaceLayer` 从 `"task-graph"` 设计为 `"task-runtime"`。
2. 标记旧主路径：
   - `TaskSystemView.sendTaskToChat()`
   - `CenterWorkspaceView.handleStartGraph()`
   - `startTaskGraphRuntimeLoopRun()`
3. 确认旧路径切换后没有新增“兼容启动壳”。

完成标准：

```text
新文档和代码注释中统一使用“任务运行台 / task-runtime / TaskRuntimeWorkbench”。
```

### Phase 1：后端任务运行限制

目标：

先把并发限制放到后端执行入口之前，避免前端先行改造后无权威限制。

修改文件：

```text
backend/bootstrap/settings.py
backend/api/config_api.py
backend/task_system/orders/runtime_limits.py
backend/tests/config_runtime_regression.py
```

实现内容：

1. `runtime_config_console_payload()` 增加 `task_runtime` group。
2. `set_runtime_config_group()` 允许 `task_runtime`。
3. 新增 `TaskRuntimeLimitPolicy` 和 `TaskRuntimeLimitGuard`。
4. `TaskRuntimeLimitGuard` 从 `state_index` 读取 active runs，状态包括：
   - `created`
   - `running`
   - `waiting_approval`
   - `paused`
5. 超过限制时返回结构化错误：

```python
{
    "code": "task_runtime_limit_exceeded",
    "scope": "global" | "session" | "order",
    "limit": int,
    "active_count": int,
    "policy": "reject" | "queue"
}
```

完成标准：

```text
后端配置台能读取和保存 task_runtime。
限制守卫有单元测试。
执行入口尚未接入也可以，但服务必须独立可测。
```

### Phase 2：统一执行入口，先接特定任务

目标：

让特定任务脱离主聊天启动。

修改文件：

```text
backend/task_system/orders/api_models.py
backend/task_system/orders/order_execution_service.py
backend/api/task_orders.py
backend/query/runtime.py
backend/task_system/orders/order_registry.py
backend/runtime/memory/state_index.py
```

实现内容：

1. 新增 `POST /api/tasks/order-runs/{run_id}/execute`。
2. 在 `order_execution_service.py` 中读取 `TaskOrderRun`。
3. 对 `specific_task` 执行：
   - 调用运行限制守卫。
   - 将 `TaskOrderRun.status` 改为 `running`。
   - 绑定已有 single-agent 执行能力。
   - 回写 `task_run_id` 到 `TaskOrderRun` 和 `ExecutionChannel`。
   - 返回 canonical projection。
4. 主会话 `/api/chat` 中保留普通聊天和用户显式聊天能力，但不再作为特定任务工作台的默认运行路径。

完成标准：

```text
从任务运行台调用 execute 可以启动 specific_task。
TaskOrderRun 能查到 task_run_id。
TaskOrderRun monitor 能读到运行状态。
```

### Phase 3：图任务纳入任务订单

目标：

图任务不再绕过任务订单系统。

修改文件：

```text
backend/task_system/orders/order_factory.py
backend/task_system/orders/api_models.py
backend/api/task_orders.py
backend/api/orchestration.py
backend/runtime/unit_runtime/loop.py
backend/runtime/memory/state_index.py
```

实现内容：

1. 新增 `TaskOrderFactory.create_graph_run_order()`。
2. 新增 `POST /api/tasks/graph-runs/orders`。
3. `POST /api/tasks/order-runs/{run_id}/execute` 支持 `graph_run`。
4. `graph_run` execute 内部调用 `TaskRunLoop.start_task_graph_run()`。
5. `TaskRunLoop.start_task_graph_run()` 接收可选 order refs：

```python
task_order_id: str = ""
task_order_run_id: str = ""
execution_channel_id: str = ""
task_execution_envelope_id: str = ""
```

6. 启动成功后回写：

```text
TaskOrderRun.task_run_id
TaskOrderRun.coordination_run_id
ExecutionChannel.task_run_id
```

完成标准：

```text
图任务从 TaskOrderRun execute 启动。
旧 /orchestration/runtime-loop/task-graphs/{graph_id}/start 不再是前端任务台主路径。
graph_run 能通过 /api/tasks/order-runs/{run_id}/monitor 查到订单绑定。
```

### Phase 4：执行层模型落地

目标：

把“图任务可作为任务后续层”变成结构化能力，而不是 UI 口头描述。

修改文件：

```text
backend/task_system/orders/models.py
backend/task_system/orders/order_factory.py
backend/task_system/orders/order_registry.py
backend/runtime/memory/state_index.py
frontend/src/lib/api.ts
frontend/src/lib/store/types.ts
```

实现内容：

1. `TaskOrder` 增加 `execution_layers`。
2. `TaskExecutionEnvelope` 增加 `execution_layers`。
3. `specific_task` 默认生成 `single_agent_layer`。
4. `graph_run` 默认生成 `graph_layer`。
5. 支持为特定任务追加图层：

```text
POST /api/tasks/orders/{order_id}/execution-layers
```

请求：

```python
{
    "layer_type": "graph_layer",
    "source_ref": "task_system.task_graph:{graph_id}",
    "title": "...",
    "depends_on": ["single_agent_layer_id"],
    "input_refs": {...},
    "acceptance_policy": {...}
}
```

第一期只允许追加 `graph_layer` 和 `verifier_layer`。

完成标准：

```text
单 Agent 特定任务可以显示单层。
特定任务追加图层后，左侧拓扑/执行结构视图显示 layer chain。
图任务直接启动时显示为 graph_run order。
```

### Phase 5：统一信息流 API

目标：

让前端右侧“当前节点信息流”从后端事实读取，不用拼多个旧监控对象。

修改文件：

```text
backend/task_system/orders/order_information_flow.py
backend/api/task_orders.py
backend/runtime/memory/trace_reader.py
backend/runtime/memory/state_index.py
frontend/src/lib/api.ts
frontend/src/components/workspace/views/center/task-runtime/TaskNodeInformationFlowPanel.tsx
```

实现内容：

1. 新增 `GET /api/tasks/order-runs/{run_id}/information-flow`。
2. 从订单、通道、执行信封、task run trace、coordination monitor 合成结构化信息流。
3. 右侧面板按 `run_id / layer_id / node_id` 聚焦显示：
   - 当前节点阶段进度
   - 当前节点 agent todo/plan
   - 当前节点工具调用
   - 当前节点验证和纠错
   - 当前节点产物
   - 当前节点最新总结
4. 旧 `TaskGraphRunMonitorPanel` 可以作为图任务 topology/detail 子组件复用，但不能成为唯一信息流来源。

完成标准：

```text
同一个右侧节点信息流面板能显示 specific_task 的 `single_agent_root` 和 graph_run 的图节点。
没有 task_run_id 时显示 order/run 已创建但未启动。
运行失败时显示失败点和 recovery 信息。
```

### Phase 6：前端任务运行台改造

目标：

把“图任务层”升级为“任务运行台”，图任务和单 Agent 特定任务统一启动。

修改文件：

```text
frontend/src/components/workspace/views/center/CenterWorkspaceView.tsx
frontend/src/components/workspace/views/center/centerWorkspaceHelpers.ts
frontend/src/components/workspace/views/center/task-runtime/TaskRuntimeWorkbench.tsx
frontend/src/components/workspace/views/center/task-runtime/TaskTopologyPanel.tsx
frontend/src/components/workspace/views/center/task-runtime/TaskNodeInformationFlowPanel.tsx
frontend/src/components/workspace/views/center/task-runtime/TaskRunComposer.tsx
frontend/src/lib/api.ts
frontend/src/lib/store/types.ts
frontend/src/lib/store/runtime.ts
```

实现内容：

1. `CenterWorkspaceView` tabs 改为：

```text
会话层
任务运行台
```

2. `TaskRuntimeWorkbench` 读取：
   - task system overview
   - task domains
   - selected domain specific tasks
   - selected task execution layers
   - current/recent order runs
3. 底部 `TaskRunComposer` 提供双层选择：
   - 第一层：任务域。
   - 第二层：该任务域下的特定任务。
   - 如果特定任务绑定了图层，则启动后左侧显示图层拓扑；如果没有图层，则显示 `single_agent_root`。
4. 选择 specific task 后：
   - 创建或复用 specific task order。
   - 启动时调用 `executeTaskOrderRun()`。
5. 直接运行图模板不再作为底部第一层选择；图模板应通过任务的 `graph_layer` 或“追加图层”进入运行台。只有图模板管理页可以跳转创建 `graph_run` order。
6. 左侧 `TaskTopologyPanel`：
   - `graph_layer` 显示 topology。
   - `single_agent_layer` 显示 `single_agent_root` 节点和 contract/executor/acceptance。
   - layered task 显示 layer chain 和节点关系。
7. 右侧 `TaskNodeInformationFlowPanel`：
   - 使用 `selectedNodeId / selectedLayerId / selectedRunId` 查询或过滤 information flow。
   - 默认聚焦当前活跃节点。
   - 用户点击左侧节点后切换信息流。
8. 下方 composer 统一启动、续跑和纠错提交。

完成标准：

```text
用户不进主会话，也能启动特定任务。
用户不进图任务发布页，也能启动图任务。
同一右侧节点信息流面板显示单 Agent 根节点和图任务节点。
```

### Phase 7：旧链路清理

目标：

删除旧壳，不做双主路径。

清理对象：

```text
TaskSystemView.sendTaskToChat()
frontend_task_order_intent as default task start path
CenterWorkspaceView.handleStartGraph()
centerWorkspaceTaskGraphSessionId() 如果只服务旧图启动则删除
buildCenterWorkspaceTaskGraphInitialInputs() 如果迁入新 workbench helper 后删除旧函数
TaskGraphPublishRunPage 中直接 start graph 的主启动按钮
```

处理规则：

1. `/orchestration/runtime-loop/task-graphs/{graph_id}/start` 后端可以暂时保留为内部低层 API 或测试辅助，但前端主路径不能调用。
2. 如果旧 API 只剩测试使用，应在测试迁移后删除。
3. 不新增“兼容旧前端”的第二套启动按钮。
4. 不保留 `sendTaskToChat` 这种名称；如果主会话需要展示任务摘要，函数应改为 `openTaskRunSummaryInChat` 一类的展示行为。

完成标准：

```text
rg "sendTaskToChat|frontend_task_order_intent|handleStartGraph|startTaskGraphRuntimeLoopRun" frontend
```

结果中不应出现任务运行台主路径调用。

### Phase 8：验证

后端测试：

```text
python -m pytest backend/tests/config_runtime_regression.py -q
python -m pytest backend/tests/task_order_entrypoints_regression.py backend/tests/task_order_registry_regression.py -q
```

新增测试：

```text
backend/tests/task_order_execute_regression.py
backend/tests/task_graph_order_run_execute_regression.py
backend/tests/task_runtime_limit_guard_regression.py
backend/tests/task_order_information_flow_regression.py
```

前端测试：

```text
npm test -- src/lib/store/runtime.test.ts src/lib/runtimeWorkProjection.test.ts
npx tsc --noEmit
```

浏览器验证：

```text
http://127.0.0.1:3000
http://127.0.0.1:8003/api
```

必须检查：

1. 固定端口只有一个前端和一个后端监听。
2. 任务运行台底部可以先选择任务域。
3. 任务运行台底部可以选择该任务域下的特定任务。
4. specific task 启动后，左侧出现 `single_agent_root`，右侧当前节点信息流更新。
5. 绑定图层的任务启动后，左侧显示 topology，右侧随当前节点切换信息流。
6. 超过运行限制时后端拒绝，前端展示结构化原因。
7. 产物显示在右侧当前节点信息流中，不丢失 `run_id / layer_id / node_id` 绑定。

## 6. 文件级执行清单

### 后端

```text
backend/task_system/orders/models.py
  - 增加 execution_layers 字段。
  - 保持 TaskOrder / TaskExecutionEnvelope 为任务权威对象。

backend/task_system/orders/api_models.py
  - 增加 TaskOrderRunExecuteRequest / Response。
  - 增加 TaskGraphRunOrderCreateRequest。
  - 增加 TaskExecutionLayer payload 模型。

backend/task_system/orders/order_factory.py
  - 增加 create_graph_run_order()。
  - specific_task 默认生成 single_agent_layer。
  - graph_run 默认生成 graph_layer。

backend/task_system/orders/order_execution_service.py
  - 新增。
  - 统一 execute 分发。
  - 统一绑定 run/channel/envelope/task_run/coordination_run。

backend/task_system/orders/runtime_limits.py
  - 新增。
  - 后端任务运行数量限制。

backend/task_system/orders/order_information_flow.py
  - 新增。
  - 合成右侧信息流。

backend/task_system/orders/order_registry.py
  - 支持 execution_layers 持久化。
  - 支持 run 绑定 task_run_id / coordination_run_id。

backend/runtime/memory/state_index.py
  - 增加按 session/order 查询 active order runs。
  - 增加 update order run/channel binding 方法。

backend/runtime/unit_runtime/loop.py
  - start_task_graph_run 接收 order refs。
  - 将 order refs 写入 diagnostics 或 task run metadata。

backend/api/task_orders.py
  - 新增 graph run order 创建 API。
  - 新增 order-run execute API。
  - 新增 information-flow API。

backend/api/orchestration.py
  - 图启动旧 API 从前端主路径移除后降级。
  - 可内部调用 order_execution_service 或保留为低层 runtime API。

backend/bootstrap/settings.py
  - 增加 task_runtime 配置组。

backend/api/config_api.py
  - 继续复用现有 config endpoint。
```

### 前端

```text
frontend/src/lib/api.ts
  - 增加 createTaskGraphRunOrder()。
  - 增加 executeTaskOrderRun()。
  - 增加 getTaskOrderRunInformationFlow()。
  - 增加 task_runtime config 类型字段。

frontend/src/lib/store/types.ts
  - 增加 taskRuntimeWorkbench 状态。
  - 增加 TaskRunInformationFlow 类型引用。

frontend/src/lib/store/runtime.ts
  - 停止任务运行台走 /api/chat。
  - 增加绑定 selected run/information flow 的 action。

frontend/src/lib/runtimeWorkProjection.ts
  - 以 TaskOrderRun / information-flow 为优先来源。

frontend/src/components/workspace/views/center/CenterWorkspaceView.tsx
  - tab 从 task-graph 改为 task-runtime。
  - 移除直接 graph start 逻辑。

frontend/src/components/workspace/views/center/centerWorkspaceHelpers.ts
  - 拆旧 graph-only helper。
  - 只保留新 workbench 需要的纯函数。

frontend/src/components/workspace/views/center/task-runtime/TaskRuntimeWorkbench.tsx
  - 新增任务运行台总组件。

frontend/src/components/workspace/views/center/task-runtime/TaskTopologyPanel.tsx
  - 新增左侧拓扑/执行结构视图。

frontend/src/components/workspace/views/center/task-runtime/TaskNodeInformationFlowPanel.tsx
  - 新增右侧当前节点信息流。

frontend/src/components/workspace/views/center/task-runtime/TaskRunComposer.tsx
  - 新增统一启动输入框。
  - 内置任务域和特定任务双层下拉框。

frontend/src/components/workspace/views/task-system/TaskGraphPublishRunPage.tsx
  - 移除直接启动作为主能力。
  - 保留发布、检查、跳转到任务运行台。

frontend/src/components/workspace/views/TaskSystemView.tsx
  - 删除 sendTaskToChat 默认路径。
  - 改为 create/open task run in workbench。
```

## 7. 切换规则

### 7.1 允许短暂并存

允许短暂并存的是低层后端 runtime API：

```text
/orchestration/runtime-loop/task-graphs/{graph_id}/start
```

原因：后端测试和内部图运行能力可能仍依赖它。

但它不能作为前端任务运行台的主路径。

### 7.2 不允许并存

不允许并存的是两个用户可见主启动路径：

```text
任务系统页 -> 送到主会话运行
图任务层 -> 直接启动图任务
任务运行台 -> 统一运行
```

最终只能保留：

```text
任务运行台 -> TaskOrderRun execute
```

### 7.3 旧测试处理

旧测试如果只验证旧路径存在，应删除或改写，不保留为“兼容证明”。

旧测试如果验证底层 runtime 能力，应迁移到服务层或低层 API 测试。

## 8. 风险与控制

### 风险 1：single-agent 执行仍绑定主聊天流

控制：

先在 `order_execution_service.py` 做最小可运行接入，如果现有 `run_single_agent_stream()` 强依赖 chat request，则抽出 `run_single_agent_order_run()`，不要让任务运行台伪造 chat message。

### 风险 2：图任务启动能跑，但订单绑定丢失

控制：

`start_task_graph_run()` 必须接收 order refs，并且启动成功后立刻写回 `TaskOrderRun`。

验收：

```text
GET /api/tasks/order-runs/by-task-run/{task_run_id}
```

必须返回 graph_run 的订单投影。

### 风险 3：前端右侧信息流再次拼旧对象

控制：

`TaskNodeInformationFlowPanel` 只接收 `TaskRunInformationFlow` 和当前 `node_id / layer_id`，不直接接 `TaskGraphRunMonitorView` 作为主数据。

### 风险 4：运行限制只在 UI 生效

控制：

所有启动都必须经过 `TaskRuntimeLimitGuard`。前端按钮禁用只是体验，不是安全边界。

### 风险 5：图层概念变成空字段

控制：

执行层必须被 `TaskTopologyPanel` 展示，并被 `order_execution_service.py` 消费。只存不消费视为未完成。

## 9. 验收场景

### 场景 A：单 Agent 特定任务

操作：

```text
打开任务运行台
在底部先选择任务域，再选择该域下的 specific task
输入目标
启动
```

期望：

```text
创建 TaskOrder / TaskOrderRun / ExecutionChannel / Envelope
execute 后 TaskOrderRun.status = running
左侧显示 single_agent_root
右侧 single_agent_root 信息流出现 plan/todo/tool/progress
完成后出现 final summary/artifacts
主会话没有承担运行入口
```

### 场景 B：绑定图层的特定任务

操作：

```text
打开任务运行台
在底部先选择任务域，再选择一个已绑定 graph_layer 的特定任务
输入目标
启动
```

期望：

```text
创建 specific_task TaskOrder，并携带 graph_layer
execute TaskOrderRun
TaskRunLoop.start_task_graph_run 获得 order refs
左侧显示 topology
右侧随当前图节点显示 coordination progress
产物绑定当前 run
```

### 场景 C：特定任务追加图层

操作：

```text
选择 specific task
添加 graph_layer
启动
```

期望：

```text
TaskTopologyPanel 显示 single_agent_layer -> graph_layer
execute 能识别 selected_layer_id 或默认首层
信息流按当前 node/layer 聚焦
```

### 场景 D：运行数量限制

操作：

```text
设置 max_global_running_tasks = 1
启动一个长任务
再启动第二个任务
```

期望：

```text
后端返回 task_runtime_limit_exceeded
前端展示限制原因
不会创建假 running 状态
```

### 场景 E：旧入口清理

检查：

```text
rg "sendTaskToChat|frontend_task_order_intent|handleStartGraph|startTaskGraphRuntimeLoopRun" frontend
```

期望：

```text
任务运行台主路径不出现这些旧启动函数。
```

## 10. 最终完成定义

本次改造完成必须同时满足：

1. 特定任务和图任务都通过 `TaskOrderRun execute` 启动。
2. 图任务可以作为独立 `graph_run`，也可以作为特定任务的 `graph_layer`。
3. 任务运行数量限制由后端配置和守卫执行。
4. 任务运行台替代旧图任务层，主会话不再是特定任务默认启动口。
5. 右侧当前节点信息流通过统一 information-flow API 展示运行事实和产物。
6. 旧的前端直接图启动路径和送主会话启动路径被清理。
7. 后端和前端测试通过，浏览器实际验证通过。

如果实施中发现现有 single-agent runner 无法脱离 `/api/chat`，不能回退到伪造 chat 请求；必须抽出任务运行专用 runner，再继续执行本计划。
