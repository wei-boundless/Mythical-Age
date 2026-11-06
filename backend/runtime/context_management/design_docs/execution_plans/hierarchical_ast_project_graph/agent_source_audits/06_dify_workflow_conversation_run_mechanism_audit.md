# Dify 源码机制审查：Conversation / Message / WorkflowRun / GraphRuntimeState

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\dify`

## 1. 审查目标

本报告审查 Dify 主体工程中与“普通 turn、会话、图任务、持久运行、暂停恢复”相关的机制：

- conversation / message 如何作为历史容器；
- workflow graph 如何被装配为一次运行；
- WorkflowRun 与 WorkflowNodeExecution 如何持久化；
- pause / resume 如何保存真实运行状态；
- stop / queue / event stream 如何连接；
- 这些机制对本项目图任务和持久任务环境的参考价值。

Dify 不是 coding agent，但它在 workflow run、graph runtime state、pause/resume、node execution trace 上有成熟工程细节，适合作为“图任务运行体系”的对照。

## 2. 主要审查文件

```text
D:\AI应用\dify\api\models\model.py
D:\AI应用\dify\api\models\workflow.py
D:\AI应用\dify\api\core\workflow\workflow_entry.py
D:\AI应用\dify\api\core\app\workflow\layers\persistence.py
D:\AI应用\dify\api\core\app\layers\pause_state_persist_layer.py
D:\AI应用\dify\api\core\app\apps\workflow\app_runner.py
D:\AI应用\dify\api\core\app\apps\workflow\app_generator.py
D:\AI应用\dify\api\core\app\apps\workflow\app_queue_manager.py
D:\AI应用\dify\api\core\app\apps\workflow_app_runner.py
D:\AI应用\dify\api\controllers\web\workflow.py
D:\AI应用\dify\api\services\workflow_event_snapshot_service.py
```

## 3. 核心运行模型

Dify 主体的边界可以概括为：

```text
Conversation
-> Message
-> optional workflow_run_id

Workflow
-> WorkflowEntry
-> GraphEngine
-> GraphRuntimeState
-> WorkflowRun
-> WorkflowNodeExecution
-> WorkflowPause / WorkflowPauseReason
```

关键结论：

- `Conversation` 是会话历史容器；
- `Message` 是一次用户/模型交互记录，可挂 `workflow_run_id`；
- `Workflow` 是静态图定义；
- `WorkflowEntry` 是把图、变量池、运行状态和 GraphEngine 组合成一次执行；
- `WorkflowRun` 是图运行的持久事实；
- `WorkflowNodeExecutionModel` 是节点级运行轨迹；
- `WorkflowPause` 保存可恢复的 GraphRuntimeState snapshot；
- stop 用 `task_id` 进入 queue stop flag 和 GraphEngine command channel。

这套结构直接证明：成熟系统不会把“对话消息”当成“任务运行”，也不会靠上下文文本恢复 workflow，而是保存运行态快照。

## 4. Conversation / Message：历史容器与执行引用

`api\models\model.py` 定义 `Conversation`：

```text
id
app_id
app_model_config_id
model_provider
override_model_configs
model_id
mode
name
summary
inputs
system_instruction
status
invoke_from
from_source
from_end_user_id / from_account_id
dialogue_count
created_at / updated_at
```

`Message` 定义：

```text
id
app_id
conversation_id
inputs
query
message
answer
status
error
message_metadata
parent_message_id
agent_based
workflow_run_id
app_mode
```

并且建有：

```text
message_conversation_id_idx
message_workflow_run_id_idx(conversation_id, workflow_run_id)
```

成熟点：

```text
Conversation/Message 只保存交互历史和结果引用；
WorkflowRun 才保存具体执行过程；
Message.workflow_run_id 是桥，不是把 workflow state 塞进 message。
```

对本项目的含义：

```text
普通 turn / chat history 可以引用 task_run_id 或 episode_id；
但 task 的真实状态、节点轨迹、产物和恢复点必须在任务系统中独立保存。
```

## 5. Workflow：静态图定义

`api\models\workflow.py` 的 `Workflow` 保存：

```text
id
tenant_id
app_id
type
kind
version
graph
features
environment_variables
conversation_variables
rag_pipeline_variables
created_by / updated_by
```

`graph_dict` 直接从 `graph` JSON 解码，`get_node_config_by_id()` 按 node id 取节点配置。

这里要注意：

```text
Workflow 是图定义，不是运行实例。
WorkflowRun 才是运行实例。
```

这对我们的图任务系统很重要：图模板、图运行、节点运行、任务产物必须分开，不能把“图配置”直接改造成“任务状态”。

## 6. WorkflowEntry：一次运行的入口

`api\core\workflow\workflow_entry.py` 中 `WorkflowEntry` 负责将静态图与运行态组合：

```text
WorkflowEntry(
  tenant_id
  app_id
  workflow_id
  graph_config
  graph
  user_id
  user_from
  invoke_from
  call_depth
  variable_pool
  graph_runtime_state
  command_channel
)
```

初始化时创建：

```text
GraphEngine(
  workflow_id
  graph
  graph_runtime_state
  command_channel
  GraphEngineConfig(min_workers, max_workers, ...)
  child_engine_builder
)
```

并添加：

```text
ExecutionLimitsLayer
LLMQuotaLayer
ObservabilityLayer
DebugLoggingLayer
```

运行时：

```text
WorkflowEntry.run()
-> iter_dify_graph_engine_events(graph_engine)
-> filter_graph_events(... ResponseStreamFilter)
```

成熟点：

- `GraphRuntimeState` 是本次运行的变量池、输出、步数、token、暂停节点等运行态；
- command channel 与 GraphEngine 绑定，不靠 prompt 控制停止；
- child graph 有独立 child runtime state，但可共享 parent variable pool / execution context；
- 单节点调试和完整图执行有不同入口，但都回到 GraphRuntimeState + GraphEngine。

对本项目图任务的启发：

```text
图任务算法应该是 runtime 层的一等结构；
节点 agent 执行只是图运行中的一种 node execution；
共享状态、变量池、事件流、节点输出要由 graph runtime 管理。
```

## 7. WorkflowRun：持久运行事实

`WorkflowRun` 字段：

```text
id
tenant_id
app_id
workflow_id
type
triggered_from
version
graph
inputs
status
outputs
error
elapsed_time
total_tokens
total_steps
created_by_role
created_by
created_at
finished_at
exceptions_count
```

状态来自 `WorkflowExecutionStatus`，包括运行、成功、失败、停止、暂停等执行态。

成熟点：

- run 保存当次运行使用的 graph、inputs、outputs；
- run 有 created_by_role / created_by；
- run 有 total_tokens / total_steps；
- run 与 pause 是一对零或一关系；
- run 可被 message 通过 `workflow_run_id` 引用。

对本项目的标准：

```text
TaskExecutionEpisode 或 GraphRun 必须保存：
run_id
task_id / graph_id
input snapshot
status
outputs
error
created_by
created_at / finished_at
step count / token usage
```

不能只保存最终 markdown 报告。

## 8. WorkflowNodeExecution：节点级可审计轨迹

`WorkflowNodeExecutionModel` 保存：

```text
id
tenant_id
app_id
workflow_id
triggered_from
workflow_run_id
index
predecessor_node_id
node_execution_id
node_id
node_type
title
inputs
process_data
outputs
status
error
elapsed_time
execution_metadata
created_at
created_by_role
created_by
finished_at
```

索引包括：

```text
workflow_node_execution_workflow_run_id_idx
workflow_node_execution_node_run_idx
workflow_node_execution_id_idx
```

成熟点：

```text
节点级执行不是日志文本；
它有 node_id、node_execution_id、predecessor_node_id、index、inputs、outputs、metadata、status。
```

对我们的“网络级审查”和“信号链路审计”尤其关键：

```text
文件/目录/函数审查节点也必须有 node_execution_id；
每个节点报告需要能追溯输入、输出、父节点、前驱节点、运行状态和错误。
否则无法做层级审核报告和链路信号审计。
```

## 9. PersistenceLayer：GraphEngine 事件到数据库事实

`api\core\app\workflow\layers\persistence.py` 的 `WorkflowPersistenceLayer` 是非常重要的设计：

它作为 `GraphEngineLayer` 监听：

```text
GraphRunStartedEvent
GraphRunSucceededEvent
GraphRunPartialSucceededEvent
GraphRunFailedEvent
GraphRunAbortedEvent
GraphRunPausedEvent
NodeRunStartedEvent
NodeRunSucceededEvent
NodeRunFailedEvent
NodeRunExceptionEvent
NodeRunRetryEvent
NodeRunPauseRequestedEvent
```

图开始时创建 `WorkflowExecution` 并保存；节点开始时创建 `WorkflowNodeExecution`；节点结束时更新 inputs / process_data / outputs / metadata；图结束时更新 run outputs、status、tokens、steps、exceptions。

成熟点：

```text
运行事实由事件驱动的持久化层统一落库；
展示层只读 repository 状态；
GraphEngine 不需要让 UI 或队列层自己拼状态。
```

对本项目应采用的原则：

```text
图任务事件流必须成为事实源；
报告生成、前端展示、断点恢复都只能消费运行事实；
不要让 agent 的文本输出成为唯一事实源。
```

## 10. PauseStatePersistenceLayer：暂停恢复靠快照，不靠上下文记忆

`api\core\app\layers\pause_state_persist_layer.py` 定义：

```text
WorkflowResumptionContext {
  version = "1"
  generate_entity
  serialized_graph_runtime_state
}
```

当收到 `GraphRunPausedEvent` 时：

```text
state = WorkflowResumptionContext(
  serialized_graph_runtime_state = graph_runtime_state.dumps(),
  generate_entity = wrapped generate entity
)
repo.create_workflow_pause(
  workflow_run_id
  state_owner_user_id
  state
  pause_reasons
)
```

`WorkflowPause` 保存：

```text
workflow_id
workflow_run_id
state_object_key
resumed_at
```

`WorkflowPauseReason` 保存：

```text
pause_id
type
form_id
message
node_id
```

成熟点：

- 暂停时保存完整 GraphRuntimeState snapshot；
- pause reason 结构化保存；
- workflow_id 单独保存，避免 app 多版本 workflow 时恢复错版本；
- resume 后不立即删除 pause，而是标记 resumed_at。

这对我们“任务像公司工作，可中断继续”的要求非常关键：

```text
恢复不能靠让 agent 重新读旧上下文；
恢复应该由系统加载 task/graph runtime snapshot，再渲染当前必要契约给 agent。
```

## 11. Resume / Reconnect：事件快照和继续执行

`app_generator.py` 的 `resume()`：

```text
resume(
  app_model
  workflow
  user
  application_generate_entity
  graph_runtime_state
  workflow_execution_repository
  workflow_node_execution_repository
)
```

它将 `graph_runtime_state` 传入 `_generate()`，再进入 `WorkflowAppRunner`。

`WorkflowAppRunner.run()` 如果发现 `_resume_graph_runtime_state`：

```text
graph_runtime_state = resume_state
variable_pool = graph_runtime_state.variable_pool
graph = _init_graph(... graph_runtime_state ...)
```

`workflow_event_snapshot_service.py` 则负责给恢复后的客户端重建事件视图：

- 加载 `WorkflowResumptionContext`；
- 解析 `GraphRuntimeState.from_snapshot()`；
- 读取 paused nodes；
- 重建 workflow_started、node_started、node_finished、human_input_required、workflow_paused 等事件；
- 通过 `task_id` 和 `workflow_run_id` 继续向客户端提供可消费流。

成熟点：

```text
恢复分为两个层面：
1. 执行恢复：GraphRuntimeState snapshot 进入新的 GraphEngine run；
2. 展示恢复：从 WorkflowRun / NodeExecution / Pause 重建事件快照。
```

这说明本项目不能只做“checkpoint 恢复执行”，还必须有“恢复后事件/报告/状态展示”的重放能力。

## 12. Queue 与 Stop

`WorkflowAppQueueManager` 以 `task_id` 包装队列事件：

```text
WorkflowQueueMessage(task_id, app_mode, event)
```

终态事件会停止监听：

```text
QueueStopEvent
QueueErrorEvent
QueueMessageEndEvent
QueueWorkflowSucceededEvent
QueueWorkflowFailedEvent
QueueWorkflowPartialSuccessEvent
```

Web stop API 同时使用两条控制：

```text
AppQueueManager.set_stop_flag_no_user_check(task_id)
GraphEngineManager(redis_client).send_stop_command(task_id)
```

这里有历史兼容痕迹，但成熟方向很明确：

```text
task_id 是对外控制句柄；
GraphEngine command channel 是运行层控制线；
queue event 是展示/响应线。
```

对本项目：

```text
GraphRun stop/cancel 不应通过修改 prompt；
必须有 graph_run_id / task_id 指向 runtime command channel。
```

## 13. 与本项目目标的对应关系

Dify 对我们的关键参考不是 agent 智能，而是图运行工程：

```text
物理层：
  Workflow.graph / nodes / edges

运行层：
  WorkflowEntry / GraphEngine / GraphRuntimeState

事实层：
  WorkflowRun / WorkflowNodeExecution

恢复层：
  WorkflowPause / WorkflowResumptionContext / GraphRuntimeState snapshot

展示层：
  queue event / event snapshot / workflow_run_id
```

我们要做项目语义网络和图任务审查时，也应形成相同分层：

```text
ProjectPhysicalGraph
ProjectSemanticGraph
GraphReviewRun
ReviewNodeExecution
ReviewPause / Checkpoint
ReviewArtifact
ReviewEventSnapshot
```

## 14. 不适合照搬的部分

Dify workflow 节点主要是产品工作流节点，不是 coding agent 的文件级语义审查节点。它的 `WorkflowRun.outputs` 和 `WorkflowNodeExecution.outputs` 对我们还不够：

- 我们需要文件/目录/函数语义坐标；
- 需要调用链、导入链、写入链、数据流链；
- 需要“路标式语义标签”和“信号链路审计”；
- 需要把报告产物和机器可读索引分开；
- 需要 agent 节点的契约、工具权限、输入上下文和审查标准。

因此 Dify 可借鉴 GraphRuntimeState / Run / NodeExecution / Pause，但不能替代我们的项目网络管理系统。

## 15. 本项目应采用的硬标准

基于 Dify 审查，本项目图任务底座应具备：

```text
GraphDefinition:
  graph_id
  graph_type
  nodes
  edges
  version

GraphRun:
  run_id
  graph_id
  task_id
  input_snapshot
  status
  outputs
  error
  total_steps
  token_usage
  created_by
  created_at
  finished_at

GraphNodeExecution:
  node_execution_id
  graph_run_id
  node_id
  node_type
  title
  parent_node_id
  predecessor_node_id
  index
  inputs
  outputs
  process_data
  status
  error
  elapsed_time
  metadata

GraphPause:
  graph_run_id
  graph_id
  runtime_snapshot_ref
  pause_reasons
  resumed_at

EventSnapshot:
  replay graph_started / node_started / node_finished / graph_paused / graph_finished
```

这套机制才能支撑用户要求的：

- 每层语义报告；
- 单文件审查报告；
- 汇总报告；
- 语义路径指引；
- 链路信号审计；
- checkpoint 恢复；
- 分布式子节点回传；
- 后续 agent 按网络快速定位与架构优化。

