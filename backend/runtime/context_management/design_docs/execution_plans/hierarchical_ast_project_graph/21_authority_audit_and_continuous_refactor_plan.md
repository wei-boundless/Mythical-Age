# 任务图与项目控制网络权威审查及连续推进计划

状态：新推进计划书，接替零散阶段推进  
日期：2026-07-05  
适用范围：`harness`、`graph_system`、`task_system`、`project_network_system`、`project_network_tasks`、`frontend task workbench`

## 1. 本计划解决什么

当前重构已经完成了大量底座工作，但推进方式开始碎片化。继续按单点问题修补，会让新旧结构并行存在：

```text
旧 TaskRun / TaskRunLedger / runtime monitor
新 TaskWorkEnvironment / Episode / WorkProduct / Reducer
GraphSystem work order
ProjectNetwork semantic artifacts
前端 run monitor / task environment 页面
```

本计划重新收束权威链，先审查当前代码中的漏洞和旧结构，再给出连续实施顺序。后续推进必须按本文分阶段完成，每阶段只围绕一个权威边界，不再跨线跳转。

## 2. 当前已经扎稳的部分

### 2.1 TaskEnvironment 事实层已经存在

`backend/task_system/work_environments/models.py` 已经包含：

- `TaskWorkEnvironment`
- `TaskCheckpoint`
- `TaskPlan`
- `TaskTodoItem`
- `TaskStateProposal`
- `TaskContextPackage`
- `TaskControlSignal`

`backend/task_system/reducer.py` 已经把 episode result 归并为：

- work product；
- reducer commit checkpoint；
- plan / todo 事实；
- state proposal 账本；
- task event。

结论：新任务事实层不是空设计，已经可以继续作为 TaskSystem 主干。

### 2.2 Graph node 已经接入任务环境

`backend/task_system/graph_bindings/service.py` 已经提供 `GraphNodeTaskBindingService`，可以把 graph work order 绑定为：

```text
GraphNodeWorkOrder
-> GraphNodeTaskBinding
-> TaskInstance
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> TaskContextPackage
-> TaskReducer
```

结论：图节点不再只是 graph 内部的临时运行片段，它已经能落到任务环境事实层。

### 2.3 GraphSystem 领域硬编码已经明显收缩

`backend/bootstrap/graph_extensions.py` 把写作图、项目网络图的 adapter / context provider / effect handler 注册到扩展层。`GraphSystem` 主要保留算法、调度、work order、transition、checkpoint。

结论：GraphSystem 的方向是对的，下一步不是重写 GraphSystem，而是把剩余运行锚点和调度入口清干净。

### 2.4 ProjectNetworkSystem 已经有统一产物雏形

`backend/project_network_system/semantic_artifact_materializer.py` 已经能生成：

- `unified_control_graph.json`
- `semantic_coordinates.json`
- `deep_network_route_index.json`
- `signal_chain_index.json`
- `link_signal_audit.json`
- 根目录人类报告；
- `PROJECT_NETWORK_REPORTS/files`
- `PROJECT_NETWORK_REPORTS/directories`
- `PROJECT_NETWORK_REPORTS/layers`

结论：物理网络和语义网络已经开始合并，方向正确；问题在生命周期、发布、维护和前端使用闭环还没成熟。

## 3. 代码审查发现的主要漏洞

### 3.1 旧 `TaskRun` 仍是 graph/runtime 根锚点

证据：

- `backend/graph_system/facade.py` 仍直接 `from runtime.shared.models import TaskRun`。
- `GraphSystem.start_run()` 要求 `GraphRuntime root TaskRun` 已持久化。
- `GraphLoopState`、background supervisor、run monitor、event log、retention 仍大量使用 `task_run_id`。

风险：

- TaskEnvironment 已经成为任务事实层，但 GraphRun 根仍落在旧 `TaskRun`。
- 前端和监控容易继续把 `TaskRun` 当作任务真相，而不是 runtime anchor。
- 如果直接删除，会破坏 graph runtime、event log、monitor、retention；如果不迁移，会长期双事实。

裁决：

```text
TaskRun 暂时保留为 RuntimeAnchor 的 legacy payload。
必须新建 RuntimeAnchor 迁移层，逐步把 graph root / monitor / retention 的语义从 task truth 改成 runtime anchor。
禁止在新 TaskSystem 代码里继续扩大 TaskRun 语义。
```

### 3.2 `TaskRunLedger / TaskStepRun / TaskResult` 是旧任务事实模型

证据：

- `backend/task_system/tasks/run_models.py` 定义 `TaskRunLedger`、`TaskStepRun`、`TaskResult`。
- `backend/tests/task_run_state_machine_regression.py` 仍保护旧 ledger 行为。
- `runtime.shared.artifact_refs`、`memory_system.formal_memory_content` 等仍识别旧 `task_result` payload。

风险：

- 新系统已经有 `AgentExecutionEpisode / EpisodeResult / WorkProduct / TaskCheckpoint`。
- 旧 ledger 会让开发者不知道“任务事实”到底应该读哪套模型。
- 如果继续维护旧 ledger，TaskSystem 会重新膨胀。

裁决：

```text
TaskRunLedger 进入冻结迁移清单。
它只允许作为旧运行记录读取源，不允许成为新任务执行、图节点执行或项目网络审查的写入源。
后续完成替换后删除旧模型和旧测试。
```

### 3.3 TaskEnvironment 有事实层，但没有统一 TaskCommand / Scheduler 主链

证据：

- `TaskEnvironmentRepository` 有 task facts、leases、context packages、control signals，但没有 `task_commands` 或 dead-letter / dispatch queue。
- `backend/api/task_system.py` 直接暴露 prepare/run/control/recovery 多个入口。
- `control_signal_bridge.py` 和 recovery action bridge 会直接把控制动作转成 GraphSystem 调用。

风险：

- 跨 session 任务缺少统一命令账本。
- pause/resume/requeue/recover/prepare/run 都是分散 API 动作，不是同一生命周期。
- 失败后难以回答：这个任务现在是在等调度、等 agent、等用户、等 graph，还是等修复？

裁决：

```text
必须补 TaskCommand + TaskScheduler。
所有任务推进动作先进入命令账本，再由 scheduler 执行。
API 只提交命令和查询投影，不直接成为调度权威。
```

### 3.4 `runtime_facade.py` 正在重新变成大入口

证据：

- `HarnessRuntimeFacade.execute_task_environment_episode()` 同时做 episode 查找、context package 读取、session 创建、message 拼装、runtime assembly、执行、结果归并。
- 同一文件还包含 graph node work order bridge 的 prompt/message/session/runtime assembly 逻辑。

风险：

- Facade 注释说它是 thin API adapter，但实际承担了 task episode executor 和 graph node executor 的大量细节。
- 后续继续加恢复、重试、任务命令，会让 facade 重新拥有任务执行决策。

裁决：

```text
Harness 仍是唯一单 agent 执行权威。
但 task episode bridge / graph node bridge 必须从 runtime_facade.py 拆到 harness 内部专用 executor 模块。
Facade 只做路由和事件流包装。
```

### 3.5 Graph node task sink 初始化错误会被吞掉

证据：

- `backend/harness/runtime/services.py` 的 `_default_graph_node_task_preparation_sink()` 捕获异常后返回 `None`。
- GraphSystem 后续才在 begin/release/record 时抛出缺 sink 错误。

风险：

- 真实初始化问题会变成模糊运行错误。
- 图任务启动时不能 fail fast，后续排查成本高。

裁决：

```text
Graph node task sink 是 graph node 运行必需线。
初始化失败必须显式记录并在 app bootstrap 或 GraphSystem 构造期失败。
不能继续用 None 做隐性降级。
```

### 3.6 ControlSignal 与 RecoveryAction 是重复控制入口

证据：

- `/task-environments/{id}/control-signals` 走 `apply_task_environment_control_signal_bridge()`。
- `/task-environments/{id}/recovery-actions` 走 `_apply_task_environment_recovery_action_bridge()`。
- 两者都会从 task environment detail 找 graph binding，再调 GraphSystem。

风险：

- 同一个任务动作有两套 API、两套 payload、两套处理路径。
- status 只有 pending/handled/failed，不足以表达 queued/running/retryable/dead-letter。
- 不利于前端做统一操作台。

裁决：

```text
ControlSignal 保留为用户意图和外部信号记录。
RecoveryAction 降级为 TaskCommand 的 command_kind。
真正调度和执行统一走 TaskScheduler。
```

### 3.7 ProjectNetwork materializer 过早、过频、过宽

证据：

- `ProjectNetworkBuildService.accept_node_result()` 每次 ingest 到 work product 后直接调用 `ProjectNetworkSemanticArtifactMaterializer.materialize_build()`。
- materializer 每次会重写根目录报告，并对 `PROJECT_NETWORK_REPORTS/files`、`directories`、`layers` 执行清空重建。

风险：

- 大项目中每个节点结果都触发全量 materialize，成本高。
- 部分节点结果可能生成不完整报告，覆盖上一次较完整的人类视图。
- 多 build / 多项目并行时，根目录人类报告没有 active generation 隔离。

裁决：

```text
ingest 只写 work product、channel、evidence、trace 和 dirty signal。
semantic artifact materialize 必须改为 generation publish / explicit materialize 命令触发。
根目录报告只指向 active published generation。
```

### 3.8 ProjectNetwork repair queue 尚未并入任务系统

证据：

- `project_network_system.repository` 已有 repair work item 表。
- `project_network_tasks.repair_runtime_service` 能发布 repair graph。
- 但 repair item 没有通过 TaskCommand / TaskScheduler 统一调度，也没有 git delta maintenance agent 主链。

风险：

- 断链修复、git 变更维护、agent 补网仍是独立能力，不是项目控制系统的日常生命周期。
- 语义网络建好后，修改代码不能稳定触发关系和语义维护。

裁决：

```text
ProjectNetworkMaintenanceSignal -> RepairWorkItem -> TaskCommand -> Graph repair task
必须成为同源闭环。
```

### 3.9 前端没有任务事实工作台闭环

证据：

- `frontend/src/lib/api/taskSystem.ts` 目前没有封装 task environment list/detail/prepare/run/control/recovery API。
- `RunMonitorController` 能按 `task_environment_id` 导航，但 detail 加载仍主要是 task run / turn run / graph monitor。
- `TaskEnvironmentManagementWorkbench` 主要是环境配置，不是任务运行事实工作台。

风险：

- 后端事实层存在，但用户看不到 plan/todo/state proposal/checkpoint/work product 的统一视图。
- 运行恢复、修复、重跑仍靠散落按钮和 run monitor。

裁决：

```text
需要单独的 Task Workbench：
任务列表 -> 任务详情 -> episode/checkpoint/work product -> command/recovery queue -> graph runtime projection。
环境配置页不能承担任务运行工作台。
```

## 4. 旧结构处置清单

| 旧结构 | 当前角色 | 处置 |
| --- | --- | --- |
| `runtime.shared.models.TaskRun` | graph/runtime/event log 根锚点 | 保留为 legacy runtime anchor payload，进入 RuntimeAnchor 迁移 |
| `task_run_id` event scope | event log / monitor / retention scope | 暂保留字段名，新增 runtime_anchor 语义映射 |
| `TaskRunLedger / TaskStepRun / TaskResult` | 旧任务事实模型 | 冻结，迁移读取方，最终删除 |
| `TaskRecordLifecycleManager` | 旧 task record 清理 | 迁移到 RuntimeAnchor lifecycle 后再删除 |
| `control_signal_bridge` | 任务控制到 graph 控制的直接桥 | 改为 TaskCommand handler |
| `recovery-actions` API | 直接恢复 graph 的入口 | 改为提交 recovery command |
| `runtime_facade` task bridge helpers | harness 内部 executor 细节 | 拆出专用 bridge/executor 模块 |
| ProjectNetwork 每节点 materialize | 即时报告生成 | 改为 dirty signal + generation materialize/publish |
| 前端环境管理页承担任务视图 | 配置页混入运行理解 | 新建任务运行工作台 |

## 5. 目标权威链

```text
User / Agent Intent
-> TaskAdmissionService
-> TaskCommand
-> TaskScheduler
-> TaskContextBuilder
-> Harness TaskEpisodeExecutor
-> AgentExecutionEpisode
-> TaskReducer
-> TaskWorkEnvironment Facts
-> Projection / Workbench
```

图任务链：

```text
GraphSystem algorithm
-> GraphNodeWorkOrder
-> GraphNodeTaskCommand
-> TaskScheduler
-> Harness graph node executor
-> NodeResultEnvelope
-> GraphLoop accept result
-> TaskReducer checkpoint / work product projection
```

项目控制网络链：

```text
FileManagement physical facts
-> ProjectNetwork build graph tasks
-> Agent semantic work products
-> ProjectNetworkSystem ingest
-> Dirty semantic generation signal
-> Generation materialize / publish command
-> Unified control graph + route index + signal chain + layer reports
-> Repair / git delta maintenance commands
```

## 6. 连续推进阶段

### Phase 1：权威冻结与旧结构护栏

目标：

- 固定新任务事实层为唯一新写入目标。
- 阻止旧 `TaskRunLedger` 继续扩散。
- 标记 `TaskRun` 只是 runtime anchor，不再是 task truth。

实施动作：

1. 新增代码级文档或模块注释，明确 `TaskRun` 的 legacy runtime-anchor 身份。
2. 给 `task_system/tasks/run_models.py` 添加冻结说明，禁止新链路写入。
3. `rg` 审计所有新改代码是否继续 import `TaskRunLedger / TaskResult`。
4. 旧测试按后续迁移删除，不新增新测试文件。

验收：

```text
rg -n "TaskRunLedger|TaskStepRun|project_task_result_from_ledger" backend/task_system backend/harness backend/graph_system -g "*.py"
python -m compileall backend/task_system backend/graph_system backend/harness
```

### Phase 2：建立 TaskCommand 与 TaskScheduler

目标：

把 prepare/run/control/recovery 全部变成统一命令生命周期。

新增模型：

```text
TaskCommand
- command_id
- task_environment_id
- command_kind
- status: queued/running/succeeded/failed/canceled/dead_letter
- requested_by
- idempotency_key
- payload
- result
- error
- attempt_count
- lease_ref
- created_at / updated_at

TaskDispatchRecord
- dispatch_id
- command_id
- episode_id
- runtime_anchor_id / graph_run_id / work_order_id
- status
- started_at / finished_at
```

命令类型：

- `prepare_episode`
- `run_episode`
- `request_pause`
- `request_resume`
- `request_stop`
- `recover_stale_lease`
- `resume_graph_run`
- `requeue_graph_node`
- `dispatch_ready_graph_nodes`
- `materialize_project_network_generation`
- `publish_project_network_generation`
- `repair_project_network_refs`

实施动作：

1. `TaskEnvironmentRepository` 增加 command / dispatch 表。
2. 新建 `TaskScheduler`，只消费 command，不直接接收前端散动作。
3. API 改成提交 command，并返回 command projection。
4. 原 `control-signals` 保留为信号记录，但 handler 改为创建 command。
5. 原 recovery action bridge 改为 command handler。

验收：

- 单个 task environment 可以提交 prepare/run command。
- command 状态从 queued 到 succeeded/failed 可查询。
- 同一 idempotency key 不重复执行。
- active lease 冲突进入 failed 或 delayed，不静默覆盖。

### Phase 3：拆出 Harness task episode executor

目标：

让 `runtime_facade.py` 恢复 thin facade，不再保存任务执行大段逻辑。

实施动作：

1. 新建 `backend/harness/entrypoint/task_environment_episode_bridge.py`。
2. 迁移：
   - `_task_episode_for_execution`
   - `_task_episode_context_package`
   - `_task_episode_user_message`
   - `_task_episode_runtime_contract`
   - `_record_task_episode_execution_result`
   - task episode work product 投影。
3. 新建 `backend/harness/entrypoint/graph_node_work_order_bridge.py`，迁移 graph node work order message/runtime/session/result projection。
4. `HarnessRuntimeFacade` 只保留方法转发。

验收：

```text
runtime_facade.py 不再包含 task episode / graph node bridge 的长 helper。
Harness 仍是唯一模型执行入口。
TaskSystem 不 import harness executor。
```

### Phase 4：Graph node 执行接入 TaskCommand

目标：

GraphSystem 仍决定 ready work orders，但节点执行必须通过 TaskScheduler 可审计地进入任务环境。

实施动作：

1. `GraphSystem.execute_work_order()` 不直接 begin/release task lease。
2. GraphSystem 为 work order 创建或提交 `graph_node_run` command。
3. TaskScheduler 调用 GraphNodeTaskBindingService 准备环境和 episode。
4. Harness graph node executor 执行后返回 executor result。
5. GraphNodeTaskBindingService 归并为 EpisodeResult / WorkProduct / checkpoint。
6. GraphSystem 只接受 NodeResultEnvelope，推进 loop。

验收：

- 每个 graph node work order 都有 command、dispatch、episode、checkpoint。
- 图节点失败后能从 command/detail 找到阻塞原因。
- 并发限制由 GraphSystem algorithm + TaskScheduler lease 共同约束，不由领域任务私自开线程。

### Phase 5：RuntimeAnchor 迁移

目标：

把旧 `TaskRun` 从“任务真相”降级为“运行锚点兼容 payload”。

新增概念：

```text
RuntimeAnchor
- runtime_anchor_id
- anchor_kind: graph_run / single_turn / task_episode / background
- legacy_task_run_id
- session_id
- task_environment_id
- graph_run_id
- status
- control_state
- event_scope_ref
```

实施动作：

1. GraphRuntime start 写 RuntimeAnchor，同时保留 legacy TaskRun。
2. GraphRun root 改为 `runtime_anchor_id`，`task_run_id` 只作为 legacy alias。
3. Run Monitor 查询 RuntimeAnchor projection。
4. Retention / lifecycle / task_record cleanup 改名为 runtime anchor lifecycle。
5. 前端类型从 task run detail 逐步改成 runtime anchor detail。

验收：

- Graph run 可以通过 runtime_anchor_id 查到运行态。
- 旧 task_run_id API 只作为兼容查询，不作为新写入主链。
- 新任务环境不再需要创建旧 TaskRun 才能表达任务 truth。

### Phase 6：ProjectNetwork generation 与维护闭环

目标：

项目网络不再每节点全量 materialize，而是进入可发布、可维护、可修复的资产生命周期。

实施动作：

1. `accept_node_result()` 只做 ingest，不自动全量 materialize。
2. 新增 dirty signal：
   - `semantic_facts_changed`
   - `route_index_dirty`
   - `signal_chain_dirty`
   - `link_audit_required`
3. `ProjectNetworkGenerationManager` 负责：
   - materialize candidate；
   - validate；
   - publish；
   - rollback；
   - human report root 指向 active generation。
4. `link_signal_audit` 生成 repair work items。
5. git delta 维护：
   - changed files -> impacted refs；
   - impacted refs -> repair work items；
   - repair work items -> TaskCommand；
   - repair graph -> ProjectNetwork ingest。

验收：

- 文件级、目录级、层级、根级报告都来自同一个 active generation。
- deep route index 和 signal chain index 都引用同一 unified control graph。
- 断链能进入 repair queue，并能生成 repair graph task。

### Phase 7：前端任务工作台

目标：

把后端任务事实变成可操作产品界面。

页面结构：

```text
Task Workbench
- 任务列表：status / active plan / focus todo / latest checkpoint
- 任务详情：facts / episodes / work products / events
- 命令队列：queued / running / failed / dead-letter
- Graph runtime projection：graph run / node / checkpoint / repair action
- ProjectNetwork projection：generation / route index / signal audit / repair queue
```

实施动作：

1. `frontend/src/lib/api/taskSystem.ts` 增加 task environment API 封装。
2. `frontend/src/lib/api/types.ts` 增加 TaskEnvironment detail/list/command 类型。
3. 新建 task runtime workbench，不混入环境配置页。
4. RunMonitor 点击 task environment signal 时进入任务详情，而不是只进 session shell。

验收：

- 用户能看到每个任务当前计划、todo、state proposal、checkpoint。
- 用户能提交 resume/requeue/repair command。
- graph node 失败能一跳定位到 episode result 和 work product。

### Phase 8：旧结构删除与最终收口

目标：

删除不再有权威的旧代码，避免兼容壳长期污染系统。

删除条件：

- RuntimeAnchor 已覆盖 monitor / retention / graph root。
- TaskCommand 已覆盖 control/recovery/prepare/run。
- TaskWorkEnvironment facts 已覆盖 TaskRunLedger 的读取需求。
- ProjectNetwork generation manager 已覆盖自动 materialize。

待删除或迁移对象：

- `task_system/tasks/run_models.py`
- 旧 `task_run_state_machine_regression` 相关测试文件；
- `TaskRecordLifecycleManager` 中只服务旧 TaskRun 的逻辑；
- direct recovery bridge；
- runtime_facade 中迁移后的 helper 残留。

验收：

```text
rg -n "TaskRunLedger|TaskStepRun|project_task_result_from_ledger" backend -g "*.py"
rg -n "task_system\\.tasks\\.run_models" backend -g "*.py"
rg -n "direct.*recovery|control_signal_bridge" backend -g "*.py"
```

结果必须是无运行主链引用；有保留引用必须写明迁移期限。

## 7. 验证纪律

本项目不通过新增回归测试文件制造安全感。每个阶段验证采用：

```text
python -m compileall <changed backend packages>
rg <old-path-or-old-symbol>
真实 API smoke
固定端口后端/前端检查
必要时真实启动 graph run / task command / project network build
```

涉及运行链路时必须检查：

```text
backend:  http://127.0.0.1:8003/health
frontend: http://127.0.0.1:3000
frontend API base: http://127.0.0.1:8003/api
```

禁止：

- 保留旧链路作为暗兼容；
- mock 掉核心执行；
- 直接写产物假装测试通过；
- 用自然语言报告反解析为结构事实；
- 让 API 绕过 TaskCommand 直接改运行状态。

## 8. 下一步执行顺序

下一轮从 Phase 1 开始，不再跳到项目网络或前端单点优化：

```text
1. 冻结旧 TaskRunLedger / TaskResult 主链。
2. 建 TaskCommand / TaskScheduler。
3. 抽出 Harness task episode bridge。
4. 让 graph node 通过 TaskCommand 执行。
5. 再做 RuntimeAnchor 迁移。
6. 最后收束 ProjectNetwork generation / repair / frontend workbench。
```

这条顺序的原因：

- 没有 TaskCommand，恢复、修复、图节点运行都会继续散。
- 没有 RuntimeAnchor，TaskRun 无法干净降级。
- 没有 generation lifecycle，项目网络报告会继续过早覆盖。
- 没有前端工作台，后端事实层无法变成可控产品能力。

## 9. 当前结论

系统不是没搭起来，而是已经进入“必须收束权威”的阶段。

当前最硬的事实是：

```text
TaskEnvironment facts 已经可用；
Graph node binding 已经接入；
ProjectNetwork unified artifacts 已经有雏形；
但 TaskCommand/Scheduler、RuntimeAnchor migration、ProjectNetwork generation lifecycle、前端任务工作台都没有闭环。
```

后续推进必须以 TaskCommand 为中心，把分散 API 和桥接器收成一条任务操作系统主链；否则继续修任何单点，都会重新回到断断续续。
