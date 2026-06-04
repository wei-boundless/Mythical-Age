# Runtime Monitor Task Management Plan - 2026-06-04

## 结论

当前监控系统的问题不是“实时性不足”，而是缺少用户级管理模型。

现有链路已经做到：

- `backend/api/runtime_monitor.py` 提供统一的 `/api/orchestration/runtime-monitor` 和 SSE `/events`。
- `backend/harness/runtime/run_monitor/service.py` 负责从 `StateIndex`、`EventLog`、`ActiveTurnRegistry`、`GraphHarness` 收集运行态。
- `backend/harness/runtime/run_monitor/signals.py` 已经把任务投影成 `primary`、`attention`、`recent`、`projects`。
- `frontend/src/lib/run-monitor/controller.ts` 已经是前端单一监控控制器，SSE 优先，轮询兜底。
- `frontend/src/components/layout/RunMonitorPanel.tsx` 已经不再独立抓取旧监控源。

但是现有链路仍然缺少四个关键能力：

1. 监控台没有“清出监控台”的概念，只能随着后端信号出现或消失。
2. 监控台没有用户可理解的清理动作，删除、停止、隐藏、归档、维护预览之间的边界没有产品化。
3. 队列容量只靠 `limit` 截断，没有按分类、状态、时间和安全等级做保留策略。
4. 任务系统页面只管理配置资产，缺少运行实例管理域，导致用户只能看到后端开发态信息，不能管理真实任务队列。

目标不是把健康系统、任务记录、图运行和监控字段直接搬到前端。目标是新增一层用户级任务管理模型，让用户能回答四个问题：

- 现在系统正在做什么。
- 哪些任务需要我处理。
- 哪些历史记录能从监控台收走。
- 哪些任务记录能安全删除，哪些必须保留。

## 当前代码事实

### 监控展示链

- `RuntimeMonitorService.collect_global_runtime_monitor()` 返回信号 envelope。
- `RuntimeMonitorService._global_live_items()` 先取最近 task runs，再附加 active turn。
- `RuntimeMonitorProjector.build_global_monitor()` 只保留 running、waiting、diagnostics/action_required/stale；terminal 记录默认不进入全局 live items。
- `build_runtime_monitor_envelope()` 把信号分成：
  - `primary`
  - `attention`
  - `recent`
  - `projects`
  - `signals`
- `RunMonitorPanel` 只渲染项目 lane 和活动 lane，活动最多展示 5 条，项目最多展示 4 条。

问题：这是展示分组，不是管理分类。它没有保存“用户已清理/隐藏”的动作，也没有给每条信号返回后端判定的可用动作。

### 删除和清理权威

- 单任务记录删除权威在 `backend/harness/runtime/task_record_lifecycle.py`。
  - `DELETE /api/orchestration/harness/task-runs/{task_run_id}` 调用它。
  - 它会停止 executor、取消后台任务、清 event log、prompt accounting、execution store、runtime objects、state index。
  - 图节点子任务不能单独删，会返回 `graph_node_task_run_controlled_by_graph_runtime`。
  - 图 root task 会委托 `GraphTaskLifecycleManager` 删除整次 graph run。

- 图任务删除权威在 `backend/harness/graph/lifecycle_manager.py`，但公开 API `DELETE /api/orchestration/harness/graph-runs/{graph_run_id}` 当前只允许 dry-run，真实删除由 session deletion 拥有。

- 批量维护权威在 `backend/health_system/task_record_maintenance.py`。
  - 它做维护预览和 prune。
  - 它保护 active/dynamic/recent/failed-without-report/lineage parent。
  - 这是健康系统维护视角，不是用户监控台视角。

结论：前端不能自己判断能不能删。后端必须给出每条任务的 action availability，前端只展示后端允许的动作。

### 任务系统页面

- `frontend/src/components/workspace/views/TaskSystemView.tsx` 当前管理三个配置域：
  - 环境管理
  - 契约库
  - 节点配置
- 图运行控制分散在 `TaskGraphTopologyPage.tsx`、`TaskGraphRunControlPanel.tsx`、`TaskGraphPublishRunPage.tsx`。
- `RunMonitorController` 同时负责监控连接、导航、图任务绑定、图任务自动推进。

问题：运行实例管理没有一级位置。任务系统把“配置资产”做成了工作台，但“运行队列和记录清理”仍散在右侧监控台、图页面、健康系统里。

## 目标权威链

```text
RuntimeEventLog / StateIndex / ActiveTurnRegistry / GraphHarness
-> RuntimeMonitorService
-> RuntimeMonitorProjector
-> RuntimeManagementProjector
-> RuntimeMonitorEnvelope
-> RuntimeMonitorActionService
-> Frontend RunMonitorController
-> Monitor Console / Task Run Management Workbench
```

职责划分：

- `RuntimeMonitorService` 只观察和收集运行事实。
- `RuntimeMonitorProjector` 只投影运行状态和展示文本。
- `RuntimeManagementProjector` 负责用户级分类、容量策略、可清理性、动作可用性。
- `RuntimeMonitorActionService` 负责执行 hide、unhide、clear、delete、stop、pause、resume、maintenance preview。
- `TaskRecordLifecycleManager` 仍然是删除任务记录的唯一权威。
- `GraphTaskLifecycleManager` 仍然是图运行删除预览和删除的唯一权威；公开真实删除策略需要单独明确，不能前端绕过。
- 前端只渲染后端返回的分类和动作，不自行判断安全性。

## 用户级分类

监控系统返回的信号继续保留 `primary / attention / recent / projects`，但新增 `management` 投影。目标分类如下：

### 1. 当前行动

对应用户想看的“agent 正在快速处理什么”。

包含：

- active chat turn
- active agent task
- active graph root task
- running graph node summary

规则：

- 不允许自动清出。
- 不允许直接删除。
- 可用动作只允许后端确认后的 pause / stop / open / inspect。
- UI 只显示最近 3 到 5 条，超过折叠成“还有 N 个后台动作”，不能把右栏撑成任务表。

### 2. 需要处理

对应用户需要介入或诊断的任务。

包含：

- waiting approval
- paused
- blocked
- stale
- failed

规则：

- 不允许自动删除。
- stale 和 failed 支持“清出监控台”，但必须保留在记录管理里。
- failed 是否可删除由后端根据健康报告、lineage、graph root 判断。
- UI 需要优先展示明确动作：继续、停止、打开、查看原因、清出监控台。

### 3. 图任务项目

图任务是总任务，不是普通活动行。

包含：

- graph task root signal
- graph run summary
- active node / ready node / blocked node / failed node metrics

规则：

- 在监控台中独立一栏。
- 在任务系统中进入“运行管理 / 图任务项目”页。
- 图任务的清理动作按 project-level 处理：
  - stop/pause/resume 针对 root task。
  - clear/hide 针对监控展示。
  - delete 必须走图生命周期预览，不能只删 root task 后留下 graph state。
- 当前公开 API 只允许 graph run dry-run 删除，所以真实删除动作第一阶段不展示为可执行按钮，只展示“删除预览/需删除绑定会话”。

### 4. 最近完成

对应用户关心刚结束的反馈，但不需要长期占据监控台。

包含：

- completed agent task
- completed chat turn
- completed graph run

规则：

- 自动保留短时间或固定数量。
- 超出容量后自动退出监控台。
- 退出监控台不是删除记录。
- 用户能手动清出。
- 用户能在记录管理页删除符合条件的 terminal task record。

### 5. 记录管理

对应真实持久记录。

包含：

- terminal records
- hidden monitor records
- failed/stale records
- maintenance candidates

规则：

- 不放在右侧监控台主流程里。
- 放到任务系统的“运行管理”域。
- 支持筛选：全部、已完成、失败、需诊断、已清出监控台、可删除、受保护。
- 删除前必须显示后端 preflight，不允许前端直接乐观删除。

## 容量和自动退出策略

必须区分两个动作：

- `evict_from_monitor`：从监控台展示中退出，保留记录。
- `delete_task_record`：删除运行记录和关联账本/事件/执行存储。

默认策略：

```text
active_max = 5
attention_max = 12
project_max = 8
recent_max = 12
recent_ttl_seconds = 30 * 60
hidden_retention_days = 7
record_delete_min_age_seconds = 24 * 60 * 60
```

自动退出只作用于：

- completed
- terminal failed that is not current attention
- stale/diagnostic items after user manually clears them

自动退出不作用于：

- active
- waiting approval
- paused
- blocked
- graph project with active child runtime
- failed without health report when health policy要求保留

当队列满时：

- 当前行动永不被挤掉。
- 需要处理永不被 recent 挤掉。
- 最近完成按 `last_activity_at` 从旧到新退出。
- 项目栏按图任务身份去重，同一 project scope 只保留当前 graph run。
- 被退出的 signal 写入 monitor presentation store，记录 `hidden_reason=capacity_evicted`，避免下一次 snapshot 又立刻回来。

## 后端改造

### 新增管理模型

在 `backend/harness/runtime/run_monitor/` 下新增正常命名文件：

```text
management.py
retention_store.py
actions.py
```

不新建带版本号或过渡含义的目录。

`management.py`：

- 输入 `RuntimeMonitorSignal` 和原始 projected item。
- 输出 `RuntimeMonitorManagementEntry`。
- 负责分类、容量策略、动作可用性。

`retention_store.py`：

- 存储 monitor presentation 状态，不存运行事实。
- 使用 JSONL 或 JSON 存在 `ProjectLayout` 的运行数据区。
- 记录：
  - `signal_id`
  - `task_run_id`
  - `graph_run_id`
  - `state`
  - `hidden_reason`
  - `hidden_by`
  - `hidden_at`
  - `expires_at`
  - `source_revision`
- 只影响监控台展示，不影响 `StateIndex`。

`actions.py`：

- 统一处理用户动作：
  - `hide_signal`
  - `unhide_signal`
  - `clear_finished`
  - `delete_task_record`
  - `preview_delete_task_record`
  - `preview_delete_graph_run`
  - `stop_task_run`
  - `pause_task_run`
  - `resume_task_run`
- delete 动作内部必须委托 `TaskRecordLifecycleManager`。
- graph 删除预览委托 `GraphTaskLifecycleManager`；真实图删除在策略明确前不暴露。

### 扩展 envelope

现有 `RuntimeMonitorEnvelope` 增加：

```json
{
  "management": {
    "authority": "runtime_monitor.management",
    "policy": {},
    "summary": {},
    "lanes": {
      "current": [],
      "attention": [],
      "projects": [],
      "recent": [],
      "hidden": []
    },
    "capacity": {},
    "actions": {}
  }
}
```

每条 signal 增加轻量管理字段：

```json
{
  "visibility": {
    "visible": true,
    "lane": "current",
    "hidden": false,
    "hidden_reason": ""
  },
  "actions": [
    {
      "action": "open",
      "enabled": true,
      "label": "打开"
    },
    {
      "action": "clear_from_monitor",
      "enabled": true,
      "label": "清出"
    },
    {
      "action": "delete_record",
      "enabled": false,
      "label": "删除记录",
      "disabled_reason": "active_or_dynamic_runtime"
    }
  ]
}
```

注意：前端不根据 `state` 自行推导按钮，必须读 `actions`。

### 新增 API

在 `backend/api/runtime_monitor.py` 增加：

```text
GET  /api/orchestration/runtime-monitor/management
POST /api/orchestration/runtime-monitor/actions
POST /api/orchestration/runtime-monitor/actions/preflight
```

动作 payload：

```json
{
  "action": "clear_from_monitor",
  "signal_id": "",
  "task_run_id": "",
  "graph_run_id": "",
  "reason": "user_cleared"
}
```

返回必须包含：

- `authority`
- `accepted`
- `action`
- `target`
- `effects`
- `monitor`
- `receipt`

这样前端执行动作后直接刷新同一份 monitor envelope。

### 与健康维护的关系

第一阶段不删除 `HealthTaskRecordMaintenanceService`。

调整方式：

- 监控管理的 `delete_record` 调用 `TaskRecordLifecycleManager`。
- 批量记录维护继续由健康系统执行。
- 任务系统“运行管理 / 清理”页通过健康维护 preflight/prune 执行批量维护，但 UI 文案必须是用户语义：
  - “可删除记录”
  - “受保护记录”
  - “保留原因”
  - “预计清理事件/账本”
- 不把 health-system 的 raw bucket 直接端到监控台。

## 前端改造

### 右侧监控台

`RunMonitorPanel` 保持为实时轻量面板，但结构调整：

```text
Header: 运行状态 + 实时/轮询 + 管理入口
Current: 当前行动，最多 3-5 行
Projects: 图任务项目，最多 4-8 行
Attention: 需要处理，最多 4-6 行
Recent: 最近完成，最多 3 行，超过折叠
Footer: 打开运行管理
```

要求：

- 不做卡片堆叠。
- 行项目采用 Codex 风格的消息/活动流：左侧状态符号，中间一句进展，右侧短动作。
- 管理动作默认折叠在行尾菜单中，只把最关键动作露出。
- “清出”不写成“删除”，避免用户误解。
- `监控` 不是导航标题堆在右栏，右栏标题应是“运行”或当前 headline。

组件建议：

```text
frontend/src/components/layout/RunMonitorPanel.tsx
frontend/src/components/layout/RunMonitorLane.tsx
frontend/src/components/layout/RunMonitorActionMenu.tsx
frontend/src/components/layout/RunProjectLane.tsx
frontend/src/components/layout/RunActivityLane.tsx
```

样式从 `globals.css` 中收束：

- 若项目暂不引入 CSS module，样式只能集中在 `globals.css` 的单一 monitor 区段。
- 本次改造必须删除不再使用的 `run-monitor-*` 旧块。
- 新样式集中成一段，避免继续在 `globals.css` 末尾追加多个历史层。

### 前端状态和控制器

`RunMonitorController` 目前同时拥有全局监控和图任务控制。第一阶段不强拆，否则风险会扩大。

本次只做明确边界：

- 保留 SSE / refresh / openSignal。
- 新增 `runMonitorManagement` store slice。
- 新增 action 方法：
  - `runMonitorAction(actionPayload)`
  - `preflightRunMonitorAction(actionPayload)`
- action 完成后用后端返回的 `monitor` 更新 store。
- 不在 controller 里写业务安全判断。

后续单独把 graph auto-advance 拆到 `TaskGraphRunController`，但这不是本阶段必要条件。

### 任务系统新增运行管理域

`TaskSystemView` 当前域：

- 环境管理
- 契约库
- 节点配置

新增：

- 运行管理

子页：

```text
工作队列
图任务项目
历史记录
清理预览
```

职责：

- 工作队列：显示 active / waiting / stale / failed，支持打开、停止、继续、清出。
- 图任务项目：按 graph run/project 展示总任务，支持打开图监控、暂停/续跑/停止、删除预览。
- 历史记录：显示 hidden/recent/terminal records，支持筛选和删除 preflight。
- 清理预览：接入健康维护的 dry-run/prune，但用用户语言包装。

重要边界：

- 配置资产管理仍归环境/契约/节点。
- 运行实例管理归运行管理。
- 不把 raw diagnostics、route、graph_harness_config_id 当成主文案。
- 详情允许显示技术标识，但默认折叠为“调试信息”。

## 删除和保留规则

必须删除：

- 任何新改造后不再读取的 monitor CSS 块。
- 旧的重复 selector、presentation helper、无入口组件。
- 新旧并存的 action 推导逻辑；动作只能以后端 `actions` 为准。

必须保留：

- `TaskRecordLifecycleManager`，它是任务记录删除权威。
- `HealthTaskRecordMaintenanceService`，它是批量维护权威。
- `GraphTaskLifecycleManager`，它是图任务生命周期权威。
- `RunMonitorController` 的 SSE 和 graph detail 现有稳定能力，直到有单独图运行控制器替代。

禁止：

- 前端按关键词或状态字符串自行决定“可删除”。
- 把自动退出实现成真实删除。
- active/waiting/paused/blocked 被容量策略挤出主监控。
- 保留另一套监控 UI 链路。
- 使用带版本号的命名。

## 分阶段实施

### Phase 1 - 后端管理投影

1. 新增 `management.py` 和管理 entry 类型。
2. 新增 `retention_store.py`，只记录 presentation hide/evict。
3. `collect_global_runtime_monitor()` 在生成 signals 后套用管理投影。
4. 增加 tests：
   - active 不可清出/不可删除。
   - completed 超容量自动 hidden。
   - hidden signal 不进入右侧默认 lanes，但在 management hidden 中可见。
   - failed without report 不可删除。
   - graph root 返回 graph-level action，不返回普通 delete。

### Phase 2 - 后端动作 API

1. 新增 `runtime_monitor/actions` preflight 和 execute API。
2. 接入 `TaskRecordLifecycleManager`。
3. 接入 graph delete preview。
4. action 后返回最新 monitor envelope。
5. 增加 tests：
   - clear_from_monitor 只写 retention，不删 task run。
   - delete_record 调用 lifecycle 并清 event/prompt accounting。
   - graph node child task delete 返回 conflict。
   - graph root delete 行为与现有生命周期一致。

### Phase 3 - 前端监控台管理

1. 更新 API types。
2. 增加 run monitor management actions。
3. 改造 `RunMonitorPanel` lanes。
4. 增加 `RunMonitorActionMenu`。
5. 删除被替代的 monitor CSS。
6. 增加 tests：
   - lanes 按后端 management lane 展示。
   - row action 只展示后端 enabled action。
   - clear action 调 API 后应用返回 monitor。
   - hidden/recent 不误显示为 active。

### Phase 4 - 任务系统运行管理域

1. `TaskSystemView` 新增 domain `runs`。
2. 新增 `RunManagementWorkbench`。
3. 接入 monitor management API 和 health maintenance preflight。
4. 图任务项目独立页接入 `RunProjectLane` 同一套数据。
5. 历史记录页支持筛选、清出、恢复显示、删除预览。

### Phase 5 - 实测和清理

1. 后端测试：

```powershell
pytest backend/tests/runtime_monitor_projection_test.py backend/tests/task_record_lifecycle_regression.py -q
```

2. 新增后端测试文件后运行：

```powershell
pytest backend/tests/runtime_monitor_management_test.py -q
```

3. 前端测试：

```powershell
cd frontend
npx tsc --noEmit
npx vitest run src/lib/store/runtime.test.ts
```

4. 固定端口真实启动：

```powershell
Start-Process -FilePath "C:\Users\admin\.conda\envs\agent\python.exe" -ArgumentList @("run_uvicorn.py", "--host", "127.0.0.1", "--port", "8003") -WorkingDirectory "D:\AI应用\langchain-agent\backend" -WindowStyle Hidden
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

5. 浏览器验证：

- SSE connected 时不持续 2.5 秒轮询。
- active 任务出现在当前行动。
- completed 超容量后退出右侧监控。
- 手动清出后任务记录仍能在运行管理 / 历史记录找到。
- 删除 preflight 显示保护原因。
- 图任务项目进入独立栏，不混进普通活动行。

## 自检：遗漏和冲突

### 不与现有统一监控冲突

本方案不重建第二条监控流。`management` 是 `RuntimeMonitorEnvelope` 的扩展，不是新的 monitor source。

### 不与健康系统冲突

健康系统继续做批量维护和健康治理。右侧监控台不直接展示 health raw bucket。任务系统运行管理页通过健康维护 preflight 执行维护预览，但必须包装成用户语义。

### 不与任务删除权威冲突

真实删除仍由 `TaskRecordLifecycleManager` 和 `GraphTaskLifecycleManager` 执行。前端和 monitor management 都不直接删 store。

### 不与图任务项目语义冲突

图任务按 project-level 展示和管理。当前公开 graph delete API 只允许 dry-run，因此第一阶段不显示真实 graph delete 按钮，避免用户点了后必定失败。

### 不与 prompt cache / token 统计冲突

清出监控台只写 presentation retention，不触碰 prompt accounting ledger。删除任务记录才会 prune prompt accounting，且必须经 lifecycle。

### 不与 Codex 风格反馈冲突

右侧监控台只展示事实进展和动作，不替 agent 说“我将要”。任务内反馈仍由会话投影负责，监控台负责“系统观察到的运行状态”。

## 验收标准

- 用户能手动清出已完成/失败/停滞任务，且不会误删记录。
- 右侧监控台有分类：当前行动、项目、需要处理、最近完成。
- 队列满时 terminal/recent 自动退出监控台，active/attention 不被挤掉。
- 任务系统有运行管理域，能管理工作队列、图任务项目、历史记录和清理预览。
- 每个动作都来自后端 `actions`，前端没有自己的安全判断。
- 删除记录前有 preflight 或后端保护错误。
- 不出现带版本号的命名和第二套监控数据源。
- 旧 CSS 和旧组件残留被搜索确认后清掉。
