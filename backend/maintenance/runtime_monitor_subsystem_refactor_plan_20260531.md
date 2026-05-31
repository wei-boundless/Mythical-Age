# Runtime Monitor Subsystem 重构计划书

日期：2026-05-31  
范围：单 agent harness 运行监控、全局监控、会话监控、TaskGraph 监控、前端监控显示链路  
目标：把监控系统从 `WorkspaceRuntime` 和零散 API 中独立出来，形成边界清晰、单一权威、可验证、可持续扩展的监控子系统。

## 1. 当前问题结论

本次 `graph-run monitor` 404 不是端口问题，也不是单个请求错误，而是监控系统存在重复权威。

现有链路中，前端 `frontend/src/lib/store/runtime.ts` 同时承担：

- 全局 runtime monitor 的 SSE 连接与轮询降级。
- session live monitor 的轮询。
- TaskGraph bound monitor 的轮询。
- GraphRun monitor 的二级详情读取。
- missing graph config 的错误收敛。
- global monitor 选中任务的 detail refresh。
- 页面跳转、工作区绑定、TaskGraph 运行交互。

这导致同一个运行资源会被多个路径读取和解释。某条路径修复了 missing/stale，另一条路径仍可能继续轮询旧资源。

后端方面，`backend/harness/runtime/monitor_projection.py` 已经有 lifecycle/bucket/stale 的雏形，但它没有输出正式的资源可用性契约。`backend/api/orchestration.py` 的 GraphRun monitor 在 graph config 不存在时直接返回 404，前端只能通过试错判断资源是否还可监控。

因此，监控系统需要作为单独子系统重构，而不是继续在 `runtime.ts` 中补丁式加判断。

## 2. 成熟架构标准

监控系统应遵守以下权威链：

```text
Runtime Facts
-> Monitor Projection
-> Resource Availability
-> Monitor Envelope
-> Frontend Monitor Controller
-> UI Selectors
-> Components
```

各层职责如下：

- Runtime Facts：后端 task run、event log、graph run、resource registry 的真实状态。
- Monitor Projection：把运行事实投影成公开监控状态，不做前端 UI 决策。
- Resource Availability：判断附属资源是否存在、是否可读取、是否 stale、是否 missing。
- Monitor Envelope：统一返回给前端的契约，不让前端猜字段含义。
- Frontend Monitor Controller：唯一负责 SSE、poll fallback、detail refresh、missing ref 熔断、visibility backoff。
- UI Selectors：把 monitor state 转成用户可理解的显示模型。
- Components：只展示，不轮询、不推断、不决定资源生命周期。

成熟 agent 的监控系统必须让用户看到：

1. 工具调用/执行状态。
2. agent 的公开观察与判断。
3. 最终结果正文和交付物。

不应把 graph config id、内部 route、404、runtime bucket 这类开发内部信息直接暴露为用户主状态。

### 2.1 统一任务监控原则

监控台必须实时监测所有运行中的任务。普通会话任务、单 agent 长任务、特定任务、图任务都必须进入同一条 runtime monitor 主链。

图任务不是另一种前端监控系统，也不应该拥有独立于会话任务的主状态链。图任务应该被表达为：

```text
MonitorItem 基础任务状态
+ graph_status 图运行状态扩展
```

也就是说：

- 会话任务显示 `MonitorItem.latest_progress`。
- 单 agent 长任务显示 `MonitorItem.latest_progress` 和 artifact 状态。
- 图任务显示同样的 `MonitorItem.latest_progress`，并额外显示 `graph_status`。

监控台主列表不区分“会话监控台”和“图任务监控台”。它只显示任务运行项。用户打开图任务详情时，才展示图状态、节点状态、当前图阶段和可继续动作。

### 2.2 任务实例隔离原则

监控系统必须支持同时运行多个任务。每个任务都必须有独立的任务实例区，类似 session 的隔离方式：

```text
task_instance_id
-> monitor item
-> task-local detail state
-> optional graph_status
-> optional child runtime refs
```

规则：

- 一个会话发起的普通任务是一个独立 task instance。
- 一个图任务是一个独立 task instance。
- 图任务内部可以启动多个节点 runtime，但这些节点 runtime 只能代表该图任务的内部进展，不得在监控台主列表中变成多个主任务。
- 监控台主列表按 `task_instance_id` 展示顶层任务。
- 用户可以随时点击任意 task instance 并加载对应隔离实例区。
- 不同 task instance 的 monitor detail、graph status、node output、artifact refs 不得串台。

图任务的顶层实例 id 必须稳定。推荐规则：

```text
task_instance_id = graph_run_id
root_task_run_id = 图任务根 task_run_id
child_task_run_id = 节点 agent runtime 的 task_run_id
```

如果某个非图任务没有 graph run，则：

```text
task_instance_id = task_run_id
root_task_run_id = task_run_id
```

前端不得用 `session_id` 作为任务实例 id，因为一个 session 可以同时或连续发起多个任务。

## 3. 目标文件夹结构

### 3.1 后端新结构

新建：

```text
backend/harness/runtime/monitoring/
  __init__.py
  contract.py
  lifecycle.py
  resource_resolver.py
  projector.py
  service.py
```

职责：

- `contract.py`
  - 定义正式监控契约。
  - 不依赖 FastAPI。
  - 不读取 storage。

- `lifecycle.py`
  - 统一计算 `lifecycle / bucket / terminal / action_required / stale`。
  - 消除前端和多个后端文件各自判断状态。

- `resource_resolver.py`
  - 判断 graph run、graph harness config、artifact、task run monitor 等资源是否存在。
  - 输出 `available / missing / stale / unsupported / forbidden`。
  - 只报告资源状态，不启动任务、不修复任务。

- `projector.py`
  - 替代现有 `monitor_projection.py` 的核心逻辑。
  - 输入 task run + event log + resource resolver。
  - 输出正式 `MonitorItem`。

- `service.py`
  - 聚合 global/session/task-run monitor。
  - 提供 API 层和 SSE 层调用入口。

新建 API：

```text
backend/api/runtime_monitor.py
```

目标 endpoint：

```text
GET /api/orchestration/runtime-monitor/live
GET /api/orchestration/runtime-monitor/events
GET /api/orchestration/runtime-monitor/sessions/{session_id}
GET /api/orchestration/runtime-monitor/task-runs/{task_run_id}
GET /api/orchestration/runtime-monitor/resources/{resource_ref}
```

旧 endpoint 迁移策略：

- `GET /api/orchestration/harness/live-monitor`
- `GET /api/orchestration/harness/monitor-events`
- `GET /api/orchestration/harness/sessions/{session_id}/live-monitor`
- `GET /api/orchestration/harness/task-runs/{task_run_id}/live-monitor`

这些旧 endpoint 在前端完全迁移后删除。计划实施期间不新增二次权威；如需要短暂保留，只允许它们调用新 `RuntimeMonitorService`，不得保留旧 projection 逻辑。

`GET /api/orchestration/harness/graph-runs/{graph_run_id}/monitor` 属于 TaskGraph 运行详情 API。它可以作为图任务调试/编辑器专用 API 保留，但不能再被全局运行监控直接散落调用。全局监控必须通过 runtime monitor resource contract 判断 graph resource 是否可用。

### 3.2 前端新结构

新建：

```text
frontend/src/lib/runtime-monitor/
  types.ts
  api.ts
  resourceRefs.ts
  reducer.ts
  controller.ts
  selectors.ts
  presentation.ts
  runtimeMonitor.test.ts
```

职责：

- `types.ts`
  - 前端监控状态类型。
  - 后端 monitor envelope 类型。
  - resource ref 类型。

- `api.ts`
  - 只封装 runtime monitor API。
  - 不继续把监控 API 塞进 `frontend/src/lib/api.ts`。

- `resourceRefs.ts`
  - 规范化 `task_run`、`session`、`graph_run`、`artifact` 等资源引用。
  - 提供稳定 key。
  - 所有 missing ref 熔断必须使用这里的 key。

- `reducer.ts`
  - 合并 snapshot。
  - 应用 SSE event。
  - 处理 stale revision。
  - 处理 missing/terminal 后的状态收敛。
  - 不发请求，不读 store。

- `controller.ts`
  - 唯一调度器。
  - 管理 SSE、poll fallback、visibility backoff、detail refresh、missing resource cache。
  - 对外提供 `start / stop / refresh / openWork / bindGraphRun / clearGraphRun / evaluate / continue`。

- `selectors.ts`
  - 给 UI 使用的只读 projection。
  - 组件不得绕过 selector 直接解释 monitor envelope。

- `presentation.ts`
  - 用户可见文案和状态格式化。
  - 替代散落的 runtime monitor 文案逻辑。

- `runtimeMonitor.test.ts`
  - 覆盖 controller、reducer、resource ref、stale/missing 收敛。

## 4. 后端契约设计

### 4.1 MonitorEnvelope

统一响应结构：

```json
{
  "authority": "runtime_monitor.v1",
  "scope": "global | session | task_run | resource",
  "revision": "string",
  "updated_at": 0,
  "summary": {},
  "items": [],
  "buckets": {},
  "selected": null,
  "events": []
}
```

### 4.2 MonitorItem

每个运行项必须包含：

```json
{
  "task_run_id": "string",
  "session_id": "string",
  "task_instance_id": "string",
  "root_task_run_id": "string",
  "title": "用户可见标题",
  "kind": "chat_turn | agent_run | task_graph",
  "lifecycle": "running | waiting | action_required | paused | completed | failed | stale",
  "bucket": "running | completed | failed | diagnostics",
  "is_live": true,
  "terminal": false,
  "action_required": false,
  "stale": false,
  "diagnostic_reasons": [],
  "latest_progress": {
    "tool_status": "",
    "observation": "",
    "judgment": "",
    "summary": "",
    "agent_brief": ""
  },
  "graph_status": null,
  "child_runtime_refs": [],
  "navigation_target": null,
  "resource_refs": [],
  "primary_resource_ref": null,
  "artifact_refs": []
}
```

重点：

- `kind` 由后端明确给出，前端不得根据 graph id 猜。
- `task_instance_id` 是监控台主列表和详情隔离的稳定主键。
- `root_task_run_id` 是该任务实例的根 task run。
- `latest_progress` 是用户显示所需结构，不是内部事件名。
- `resource_refs` 包含 graph run、artifact、trace 等附属资源。
- `graph_status` 只在 `kind = "task_graph"` 时存在；普通会话任务和单 agent 任务必须为 `null`。
- `child_runtime_refs` 只表达子 runtime 进展，不生成监控台主列表项。
- `navigation_target` 由后端或 selector 明确给出，点击监控台时前端只执行导航，不重新推断跳转目标。

### 4.2.1 GraphStatus

图任务扩展状态：

```json
{
  "graph_id": "string",
  "graph_title": "用户可见图任务名称",
  "graph_lifecycle": "created | running | waiting | action_required | completed | failed | stale",
  "active_node_id": "string",
  "active_node_label": "用户可见节点名称",
  "active_node_status": "running | waiting | completed | failed",
  "ready_node_count": 0,
  "running_node_count": 0,
  "completed_node_count": 0,
  "failed_node_count": 0,
  "blocked_node_count": 0,
  "current_stage_summary": "当前图阶段的用户可见摘要",
  "next_action_label": "继续执行 | 等待审批 | 查看问题 | 已完成",
  "node_statuses": []
}
```

规则：

- `graph_status` 是普通任务状态的附加层，不替代 `lifecycle/bucket/latest_progress`。
- 主监控台列表只需要显示 `graph_status.current_stage_summary` 的短摘要。
- 图详情面板可以读取 `node_statuses` 展示图拓扑状态。
- `graph_run_id`、`graph_harness_config_id`、work order id 不进入用户主显示，只能进入开发详情。
- 如果 graph config missing，`graph_status.graph_lifecycle = "stale"`，并通过 resource availability 标记 missing；前端不得继续轮询 GraphRun monitor。

### 4.2.2 ChildRuntimeRef

节点 runtime 是 agent 发起的真实 runtime，也必须可监控。但它属于图任务实例内部，不是顶层任务。

```json
{
  "task_run_id": "string",
  "node_id": "string",
  "node_label": "用户可见节点名称",
  "runtime_kind": "agent_runtime",
  "lifecycle": "running | waiting | completed | failed | stale",
  "latest_progress": {
    "tool_status": "",
    "observation": "",
    "judgment": "",
    "summary": ""
  },
  "artifact_refs": []
}
```

规则：

- 子 runtime 可以在图任务详情页直接监控。
- 子 runtime 的输出进入当前节点输出面板。
- 子 runtime 不在全局监控台主列表中重复出现。
- 如果用户从节点输出面板点击子 runtime，可以打开节点 runtime 详情，但仍停留在当前 graph task instance 内。

### 4.2.3 NavigationTarget

监控台点击行为必须由标准 navigation target 描述：

```json
{
  "target_kind": "session | graph_task | task_instance | runtime_detail",
  "workspace_view": "chat | task-system | orchestration",
  "session_id": "string",
  "task_instance_id": "string",
  "task_run_id": "string",
  "graph_run_id": "string",
  "graph_id": "string",
  "mode": "conversation | graph_monitor | runtime_detail",
  "focus_node_id": "string"
}
```

点击规则：

- 会话发起的任务：
  - `target_kind = "session"`
  - 跳转到会话区。
  - 加载对应 `session_id`，并选中该任务实例。

- 图任务：
  - `target_kind = "graph_task"`
  - 跳转到图监控区。
  - 加载对应 `task_instance_id = graph_run_id`。
  - 展示拓扑图状态监控和当前节点输出状态。

- 图任务节点 runtime：
  - 不作为监控台主列表跳转目标。
  - 只在图任务详情内作为 `child_runtime_ref` 打开。

### 4.3 MonitorResourceRef

```json
{
  "ref": "graph_run:grun:xxx",
  "kind": "graph_run | task_run | session | artifact | trace",
  "id": "string",
  "label": "用户可见名称",
  "availability": {
    "state": "available | missing | stale | unsupported | forbidden",
    "reason": "",
    "checked_at": 0
  },
  "detail_endpoint": "/api/orchestration/runtime-monitor/resources/..."
}
```

关键规则：

- GraphRun config missing 是 `availability.state = "missing"`，不是让前端碰 404 后再猜。
- terminal task run 可以有 static monitor，但不能触发动态轮询。
- diagnostics bucket 可以展示，但不能被自动当作活跃运行续刷。

## 5. 前端 Controller 设计

### 5.1 单一调度器

`RuntimeMonitorController` 内部维护：

```text
running: boolean
eventSource: EventSource | null
pollTimer: number | null
reconnectTimer: number | null
detailTimer: number | null
inFlight:
  global: boolean
  detailRef: string
missingResourceRefs: Set<string>
selectedWorkRef: string
latestRevision: string
```

旧 `WorkspaceRuntime` 不再直接持有：

- `globalRuntimeMonitorTimer`
- `globalRuntimeMonitorEventSource`
- `globalRuntimeMonitorReconnectTimer`
- `globalRuntimeMonitorDetailRefreshTimer`
- `taskGraphMonitorTimer`
- `orchestrationMonitorTimer`
- `missingTaskGraphMonitorRefs`

这些全部迁入 `RuntimeMonitorController`。

### 5.2 状态更新

controller 不直接拼 UI 文案，只更新 monitor state：

```text
applySnapshot(envelope)
applyEvent(eventEnvelope)
selectWork(workRef)
clearSelection()
bindResource(resourceRef)
markMissing(resourceRef, reason)
```

UI 文案由 `selectors.ts` + `presentation.ts` 生成。

### 5.3 轮询规则

统一规则：

- SSE connected：低频校准 poll，默认 60 秒。
- SSE fallback：常规 poll，默认 2.5 秒至 5 秒。
- document hidden：降低 poll 频率，默认 90 秒。
- selected dynamic work：允许 detail refresh。
- terminal/static/stale/missing：停止 detail refresh。
- missing resource：同一个 ref 不再重复请求，直到 monitor revision 改变或用户手动刷新。

### 5.4 页面交互规则

组件只能调用：

```text
runtimeMonitor.openTaskInstance(taskInstanceId)
runtimeMonitor.navigateToMonitorItem(taskInstanceId)
runtimeMonitor.refresh()
runtimeMonitor.bindGraphRun(binding)
runtimeMonitor.clearGraphRun()
runtimeMonitor.continueSelected()
runtimeMonitor.evaluateSelected()
```

组件禁止：

- 直接 `getGraphRunMonitor`。
- 自己 `setInterval` 轮询 monitor。
- 根据 `graph_harness_config_id` 判断是否打开 graph monitor。
- 根据 task id 前缀或 graph id 自己猜跳转区域。
- 把 404 作为正常控制流。

### 5.5 监控台实时显示规则

监控台由 `RuntimeMonitorController` 实时驱动，数据来源优先级：

```text
SSE runtime_monitor_event
-> runtime monitor snapshot
-> selected task detail
-> resource detail
-> poll fallback
```

显示规则：

- 任何运行任务只要进入 backend `MonitorEnvelope.items`，监控台就能看到。
- 监控台主列表按 `bucket/lifecycle/updated_at` 排序，不按任务类型拆分。
- 会话任务和图任务使用同一个 row 组件。
- 图任务 row 可以增加一个轻量图状态标记，例如当前节点、已完成节点数、等待审批。
- 图任务详情使用 `graph_status` 渲染图状态，而不是再次直接请求 GraphRun monitor。
- SSE 断开时，poll fallback 继续更新同一份 monitor state，不能生成第二份状态。

### 5.6 监控台点击与任务区跳转

点击监控台 row 的流程：

```text
用户点击 row
-> controller.openTaskInstance(task_instance_id)
-> selector 读取 item.navigation_target
-> router 执行标准跳转
-> task instance detail cache 加载
-> 对应 workspace 显示隔离实例区
```

跳转目标：

- `navigation_target.target_kind = "session"`：
  - `activeWorkspaceView = "chat"`
  - 切换到 `session_id`
  - 选中对应 `task_instance_id`
  - 会话流和任务监控状态同屏显示

- `navigation_target.target_kind = "graph_task"`：
  - `activeWorkspaceView = "chat"` 或后续独立任务区 view
  - `centerWorkspaceTarget.layer = "task-graph"`
  - `centerWorkspaceTarget.mode = "monitor"`
  - 加载 `task_instance_id / graph_run_id / graph_id`
  - 打开图任务实例区

图任务实例区必须包含两个主面板：

```text
左侧：拓扑图状态监控
  - 节点状态
  - 当前节点
  - ready/running/completed/failed 数量
  - 可继续动作

右侧：当前节点输出状况
  - 当前节点 agent runtime 进展
  - 工具调用状态
  - agent 观察与判断
  - 节点产物/错误/等待用户动作
```

当前代码已经存在初步入口：

- `CenterWorkspaceTarget` 能表达 `layer = "task-graph"` 和 `mode = "monitor"`。
- `openGlobalRuntimeMonitorTaskRun` 已经能把图任务导向中心图任务层。
- 后续重构需要把这个入口改为 `navigation_target` 驱动，并补充 `task_instance_id / graph_run_id / focus_node_id`。

### 5.7 多任务实例缓存

前端 runtime-monitor state 需要维护独立实例缓存：

```text
instancesById: Record<task_instance_id, RuntimeTaskInstanceState>
selectedTaskInstanceId: string
```

`RuntimeTaskInstanceState`：

```text
taskInstanceId
rootTaskRunId
kind
sessionId
graphRunId
graphId
monitorItem
detail
graphStatus
childRuntimeRefs
selectedNodeId
nodeOutputsById
artifactRefs
lastLoadedAt
loading
error
```

规则：

- 多个任务可以同时存在于 `instancesById`。
- 点击监控台只是切换 `selectedTaskInstanceId`，不得清空其他实例状态。
- session 切换不等于 task instance 切换；一个 session 可以有多个 task instance。
- graph task instance 切换不等于 graph editor selection；运行实例和图定义是两类状态。
- 每个图任务实例独立保存当前节点、节点输出、图状态和 child runtime detail。

## 6. 迁移步骤

### 阶段 1：后端 contract 与 service

新增 `backend/harness/runtime/monitoring/`。

执行项：

1. 写 `contract.py`，定义 contract builder 与字段规范。
2. 写 `lifecycle.py`，迁移 lifecycle/bucket/stale 规则。
3. 写 `resource_resolver.py`，实现 graph config、graph run、task run、artifact 的 availability 判断。
4. 写 `projector.py`，从旧 `TaskRunMonitorProjector` 迁移事实投影。
5. 写 `service.py`，提供 global/session/task-run/resource monitor 查询。
6. 新增 `backend/api/runtime_monitor.py` endpoint。
7. 旧 `single_agent_host` 改为使用新 service。

删除/收敛：

- `backend/harness/runtime/monitor_projection.py` 的决策逻辑迁走后删除或改成仅导出新 projector，不允许保留第二套规则。

验证：

```text
python -m pytest backend/tests/runtime_monitor_projection_test.py
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py
```

需要新增测试：

- graph config missing 输出 resource availability missing。
- stale task run 不进入 active dynamic poll。
- task graph run 的 kind 由后端明确输出。

### 阶段 2：前端 runtime-monitor 文件夹

新增 `frontend/src/lib/runtime-monitor/`。

执行项：

1. 写 `types.ts`。
2. 写 `resourceRefs.ts`。
3. 写 `api.ts`，接新 runtime monitor endpoint。
4. 写 `reducer.ts`，实现 snapshot/event/detail 合并。
5. 写 `controller.ts`，迁移 SSE、poll、detail refresh、missing ref cache。
6. 写 `selectors.ts`，替代 `runtimeWorkProjection.ts` 中的推断逻辑。
7. 写 `presentation.ts`，迁移 `runtimeMonitorFormat.ts` 中的显示逻辑。

删除/收敛：

- `runtimeWorkProjection.ts` 不再根据 `has_graph_run` 猜类型。
- `runtimeMonitorFormat.ts` 不直接处理 backend raw item。
- `store/runtime.ts` 中 monitor 私有字段和方法全部迁出。

验证：

```text
npm test -- --run src/lib/runtime-monitor/runtimeMonitor.test.ts
npm test -- --run src/lib/store/runtime.test.ts
npm run lint
npx tsc --noEmit
```

### 阶段 3：WorkspaceRuntime 接入新 controller

执行项：

1. 在 `WorkspaceRuntime` constructor 中创建 `RuntimeMonitorController`。
2. 原 action 改为委托：
   - `startGlobalRuntimeMonitor`
   - `refreshGlobalRuntimeMonitor`
   - `openGlobalRuntimeMonitorTaskRun`，后续命名为 `openRuntimeTaskInstance`
   - `selectGlobalRuntimeMonitorTaskRun`，后续命名为 `selectRuntimeTaskInstance`
   - `bindTaskGraphMonitorRun`
   - `clearTaskGraphMonitorRun`
   - `evaluateBoundTaskGraphMonitor`
   - `continueBoundTaskGraphRun`
3. 删除旧 monitor timers 和旧轮询方法。
4. `dispose()` 调用 controller dispose。

验收 grep：

```text
rg "getGraphRunMonitor\\(" frontend/src
```

允许结果：

```text
frontend/src/lib/runtime-monitor/api.ts
frontend/src/lib/api.ts
```

不允许结果：

```text
frontend/src/lib/store/runtime.ts
frontend/src/components/**
```

### 阶段 4：组件改为 selector 订阅

执行项：

1. `TaskMonitorDock` 使用 runtime-monitor selectors。
2. `RuntimeRunSummary` 使用用户显示 projection，不读取内部 event 字段。
3. `CenterWorkspaceView` 只读取 selected task instance projection；图任务实例显示 `graph_status`。
4. `TaskGraphRunInteractionDock` 改为图任务实例详情面板的一部分，只接收 controller selection/detail，不直接解释 raw monitor。
5. `TaskGraphPublishRunPage` 的运行交互改为调用 runtime monitor actions。

删除/收敛：

- 组件内禁止任何 monitor `setInterval`。
- 组件内禁止直接调用 monitor API。

验收：

```text
rg "setInterval\\(" frontend/src/components
rg "getGraphRunMonitor\\(" frontend/src/components
rg "live-monitor" frontend/src/components frontend/src/lib/store
```

### 阶段 5：旧 endpoint 与旧测试清理

执行项：

1. 前端完全迁移后，删除旧 harness monitor endpoint 或让其只作为新 service 的别名过渡。
2. 删除保护旧内部结构的测试。
3. 保留行为测试：
   - 全局监控首包。
   - SSE 断开后 poll fallback。
   - missing graph config 不重复请求。
   - stale run 进入 diagnostics，不进入动态 detail poll。
   - 用户打开任务后能看到正确进展。
   - 页面切换不丢失当前运行状态。

禁止：

- 为了兼容旧链路保留两套 projection。
- 为了测试通过 mock 掉 controller 核心行为。
- 在组件里重新加直接轮询。

## 7. 用户可见显示设计

monitor selector 输出：

```text
primaryStatus
secondaryStatus
toolStatus
agentObservation
agentJudgment
finalResult
artifactRefs
needsUserAction
canContinue
canPause
canStop
graphStatus
taskInstanceId
navigationTarget
childRuntimeRefs
selectedNodeOutput
```

显示顺序：

1. 当前动作：例如“正在读取文件”“正在调用搜索”“正在生成图像”。
2. agent 观察：例如“已找到入口文件，但缺少资源引用”。
3. agent 判断：例如“需要继续搜索项目路径，而不是判定阻塞”。
4. 结果正文或交付物。

图任务显示补充：

```text
主状态：同普通任务，显示 agent 当前工作状态。
图状态：显示当前节点、图生命周期、节点完成/运行/失败数量。
详情态：显示图拓扑状态和可继续动作。
```

图任务不能把图状态放在主任务状态之前。主任务状态回答“agent 正在做什么”，图状态回答“图流程走到哪里”。

监控台点击行为：

```text
会话任务 -> 会话区，定位 session 与任务实例
图任务 -> 图监控区，定位 graph task instance
节点 runtime -> 图任务详情内部节点输出面板
```

多任务实例行为：

```text
监控台可以同时列出多个 task instance
点击任意实例加载隔离详情
切换实例不销毁其它实例缓存
同一 session 下多个任务不能互相覆盖状态
```

内部信息只能进入开发详情区，不进入主状态：

- task_run_id
- graph_harness_config_id
- raw lifecycle reason
- raw event type
- route.kind
- internal monitor URL

## 8. 风险与处理

### 风险 1：短期新旧 endpoint 并存

处理：旧 endpoint 只能调用新 service，不允许保留旧 projection 逻辑。迁移完成后删除前端调用，再删除旧 endpoint。

### 风险 2：TaskGraph 调试页面仍需要 graph monitor 详情

处理：GraphRun detail 可以作为资源详情存在，但必须由 runtime monitor resource ref 进入，而不是组件自己拼 URL。

### 风险 3：`runtime.ts` 太大，迁移容易破坏会话 stream

处理：先只迁 monitor 子系统，不同时改 chat stream、session recovery、task environment。每个阶段跑 store 测试和端到端端口实测。

### 风险 4：后端 resource availability 检查增加开销

处理：resource resolver 只做轻量存在性检查，并随 monitor snapshot 缓存到 revision 周期。不要每个 frontend poll 都深度扫描 storage。

## 9. 最终验收标准

静态验收：

```text
rg "getGraphRunMonitor\\(" frontend/src
rg "setInterval\\(" frontend/src/components
rg "live-monitor" frontend/src/lib/store frontend/src/components
rg "has_graph_run \\|\\|.*graph_run_id" frontend/src
```

期望：

- monitor API 调用集中在 `frontend/src/lib/runtime-monitor/api.ts`。
- 组件无 monitor 轮询。
- store/runtime 无 monitor 定时器。
- 前端不再通过 `has_graph_run || graph_run_id` 猜 work kind。

测试验收：

```text
python -m pytest backend/tests/runtime_monitor_projection_test.py
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py
npm test -- --run src/lib/runtime-monitor/runtimeMonitor.test.ts
npm test -- --run src/lib/store/runtime.test.ts
npm run lint
npx tsc --noEmit
```

运行验收：

1. 固定后端 `http://127.0.0.1:8003`。
2. 固定前端 `http://127.0.0.1:3000`。
3. 打开页面后全局监控正常首包。
4. 运行一个普通对话，监控不误启动 TaskGraph。
5. 运行一个长任务，用户能看到工具状态、agent 观察判断、最终交付物。
6. 人为制造 missing graph config，前端只显示一次 missing resource，不重复打 graph monitor 404。
7. 页面切换、刷新、SSE 断开重连后，监控状态不串台。
8. 运行一个图任务，监控台主列表实时显示该任务；打开详情后额外显示图状态。
9. 同一会话内先普通对话再启动图任务，监控台能同时区分两个任务，但显示体系一致。
10. 同时启动两个图任务，监控台显示两个独立 task instance，点击任意一个都能加载对应图监控区。
11. 图任务详情页显示拓扑图状态和当前节点输出；节点 runtime 进展能在该图任务实例内直接监控。
12. 点击会话发起的任务跳转到对应会话；点击图任务跳转到对应图监控区。

## 10. 实施原则

- 新文件夹不是旧逻辑容器，必须建立新权威。
- 旧逻辑迁移完成就删除，不用兼容作为保留理由。
- 后端负责事实和资源可用性，前端负责调度和展示。
- 组件只订阅 selector，不拥有监控生命周期。
- 任何 missing/stale/terminal 都必须是正式状态，不是异常兜底。
- 图任务必须接入普通任务监控主链，只允许额外增加 `graph_status`，不允许建立第二套图任务监控台。
- 图任务是一个独立 task instance；节点 runtime 是该实例的内部进展，不是全局主任务。
- 监控台点击必须走 `navigation_target`，不允许组件根据字段自行猜跳转位置。
- 多任务必须按 `task_instance_id` 隔离，不能按 session 或 graph definition 覆盖实例状态。
- 实测必须使用固定端口，不允许换端口绕过问题。
