# Dify Agent / Agenton 源码机制审查：Run API / Session Snapshot / Layer Lifecycle

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\dify\dify-agent`

## 1. 审查目标

本报告审查 Dify 仓库内 `dify-agent` 子运行时，重点关注：

- agent run 如何定义；
- run 与 session snapshot 的关系；
- scheduler 如何管理运行态；
- Redis run store 如何保存状态和事件；
- Agenton 如何用 layer graph + runtime_state 实现可恢复上下文；
- sandbox 文件访问如何只恢复最小运行环境；
- 这些机制对本项目“任务函数 / 神经控制层 / 持久任务环境”的参考价值。

## 2. 主要审查文件

```text
D:\AI应用\dify\dify-agent\src\dify_agent\protocol\schemas.py
D:\AI应用\dify\dify-agent\src\dify_agent\runtime\runner.py
D:\AI应用\dify\dify-agent\src\dify_agent\runtime\run_scheduler.py
D:\AI应用\dify\dify-agent\src\dify_agent\runtime\event_sink.py
D:\AI应用\dify\dify-agent\src\dify_agent\storage\redis_run_store.py
D:\AI应用\dify\dify-agent\src\dify_agent\protocol\sandbox.py
D:\AI应用\dify\dify-agent\src\agenton\__init__.py
D:\AI应用\dify\dify-agent\src\agenton\compositor\schemas.py
D:\AI应用\dify\dify-agent\src\agenton\compositor\core.py
D:\AI应用\dify\dify-agent\src\agenton\compositor\run.py
D:\AI应用\dify\dify-agent\src\agenton\layers\base.py
```

## 3. 核心结论

Dify Agent 的成熟边界是：

```text
CreateRunRequest
-> RunRecord
-> RunScheduler active asyncio.Task
-> AgentRunRunner
-> Agenton Compositor.enter(...)
-> Pydantic AI run
-> append-only RunEvent stream
-> terminal run_succeeded / run_failed / run_cancelled
-> session_snapshot for next run
```

它清楚区分：

- `RunRecord`：可查询状态；
- `asyncio.Task`：进程内临时运行态；
- `RunEvent`：可回放事件流；
- `CompositorConfig`：可复用 layer graph 计划；
- `CompositorSessionSnapshot`：跨 run 的可序列化状态；
- `resource_context()`：当前 run 内部的 live resource，不可序列化；
- `session_snapshot`：成功 run 的终态产物之一，用于下一次 resume。

这非常接近本项目要建立的“agent 作为输入输出体，任务环境由系统强管理”的方向。

## 4. Run API：公开协议把图、运行态、恢复态分开

`src\dify_agent\protocol\schemas.py` 在文件头注释中明确说明：

```text
composition.layers[].config 是每个 layer 的本次运行配置；
session_snapshot、deferred_tool_results、on_exit 是 per-run resume state 或 exit policy；
它们不属于 graph node definition。
```

`CreateRunRequest`：

```text
composition: RunComposition
purpose: workflow_node | single_step | agent_app | babysit | fasten_preview
idempotency_key
metadata
session_snapshot
deferred_tool_results
on_exit
```

`RunComposition`：

```text
schema_version
layers: RunLayerSpec[]
```

`RunLayerSpec`：

```text
name
type
deps
metadata
config
```

成熟点：

- 模型、history、output 都是 layer，不是全局散乱字段；
- `session_snapshot` 是顶层 per-run resume state；
- deferred tool continuation 是顶层输入，不塞进 composition；
- `on_exit` 决定每个 active layer 是 suspend 还是 delete；
- composition 只描述可重建的 layer graph，snapshot 只描述可恢复状态。

对本项目：

```text
任务函数的输入应分三类：
1. task/graph composition：可复用结构；
2. episode config：本次运行配置；
3. resume snapshot：上次运行留下的状态。
```

不能把这些都混进 prompt 或一个大 JSON。

## 5. RunEvent：终态事件是完整摘要

Run 事件类型：

```text
run_started
pydantic_ai_event
run_succeeded
run_failed
run_cancelled
```

`RunSucceededEventData` 要求：

```text
output 或 deferred_tool_call 必须且只能有一个；
session_snapshot 必须存在。
```

因此成功事件同时承担：

- 最终输出；
- 或外部 deferred tool 请求；
- 下一次可恢复的 session snapshot。

成熟点：

```text
终态事件不是一句“完成了”；
它是完整可消费边界：结果 + 恢复状态。
```

对本项目：

```text
ExecutionEpisodeSucceeded 必须携带：
output_refs / work_products
terminal_summary
next_snapshot_ref
deferred_action 或 no_deferred_action
```

否则 checkpoint 续跑和产物消费会断线。

## 6. RedisRunStore：状态和事件持久，但不持久化 create request

`src\dify_agent\storage\redis_run_store.py` 文件头说明：

```text
Redis 保存 status-only run records 和 per-run event streams。
create-run payloads are never persisted because layer config may include model credentials.
Execution is scheduled in-process; Redis is not a job queue.
```

`RunRecord` 只保存：

```text
run_id
status
created_at
updated_at
error
```

事件流：

```text
run_record_key(prefix, run_id)
run_events_key(prefix, run_id)
XADD event payload
XRANGE by cursor
XREAD for SSE
```

成熟点：

- Redis stream id 是 public cursor；
- polling 和 SSE 都从同一个事件流读取；
- record 和 stream 共用 retention window；
- 事件写入时刷新 record TTL，避免长 run 丢状态；
- 不保存 create request，避免模型凭证、工具凭证落入 run store。

对本项目：

```text
任务事件流必须可回放；
但敏感的 tool config / credential / full prompt 不应进入事件存储。
```

我们需要区分：

```text
RunRecord: 状态索引
RunEventStream: 可回放事件
EpisodeInputContract: 可审计输入摘要
Secret/ToolConfig: 受限存储，不进事件流
```

## 7. RunScheduler：active task 是临时运行态，不是持久任务

`src\dify_agent\runtime\run_scheduler.py` 文件头说明：

```text
scheduler persists a run record, starts an asyncio.Task,
and keeps only a transient active task registry.
Redis remains durable source for status and event streams.
Redis is not a job queue or cross-process handoff.
```

`RunScheduler` 字段：

```text
store
shutdown_grace_seconds
active_tasks: dict[run_id, asyncio.Task]
stopping
runner_factory
layer_providers
plugin_daemon_http_client
_lifecycle_lock
```

`create_run()`：

- 检查 stopping；
- `store.create_run()`；
- 创建 `asyncio.create_task(_run_record(...))`；
- 放入 active_tasks；
- task done 后移除。

`shutdown()`：

- 停止接收新 run；
- 等待 active tasks；
- 超时后 cancel；
- 将未完成 run 标记 failed。

成熟点：

```text
active asyncio.Task 是进程内执行体；
run record / event stream 才是持久事实；
process crash 后 active runs 会丢，需要外部 operator 标记或 retry。
```

对本项目：

```text
BackgroundJob / active fiber 不能等同于 TaskWorkEnvironment；
TaskWorkEnvironment 必须能在 active job 丢失后审计、恢复或补偿。
```

## 8. AgentRunRunner：一次 agent run 的执行函数

`src\dify_agent\runtime\runner.py` 的文件头说明：

```text
runner normalizes public Dify composition into Agenton's graph/config split,
enters a fresh CompositorRun or resumes from snapshot,
renders current Dify system prompts into temporary message_history,
runs pydantic-ai,
applies on_exit,
publishes terminal success/failure event.
```

`AgentRunRunner.run()`：

```text
update_status(running)
emit_run_started
outcome = _run_agent()
emit_run_succeeded(output/deferred_tool_call, session_snapshot)
update_status(succeeded)
except:
  emit_run_failed
  update_status(failed)
```

`_run_agent()`：

- validate output/history/ask_human layer composition；
- normalize composition；
- build compositor；
- validate layer exit signals；
- `async with compositor.enter(configs, session_snapshot) as run`；
- apply exit signals；
- build message history from current system prompts + stored history；
- resolve model layer；
- resolve tools；
- run pydantic-ai；
- append only `result.new_messages()` to history layer；
- produce output or deferred tool call；
- require `run.session_snapshot` after exit。

成熟点：

```text
current system prompts are temporary message_history inputs;
successful runs append only new messages to history;
session_snapshot comes from layer runtime_state after exit;
output contract and deferred tool continuation are explicitly validated.
```

对本项目记忆架构很重要：

```text
不变的系统提示、契约、当前上下文，不应反复写入记忆；
跨 episode 需要保留的是 layer runtime_state / new_messages / artifacts / semantic deltas。
```

这和用户之前指出的“事实变化很小不应反复插入记忆”完全一致。

## 9. Agenton Compositor：结构图与运行态快照分离

`src\agenton\__init__.py` 说明：

```text
Agenton composes reusable stateless layer graph plans,
creates a fresh CompositorRun for each invocation,
hydrates and advances serializable layer runtime_state through run slots,
emits session snapshots,
never serializes resources, handles, clients, cleanup callbacks.
```

`CompositorConfig`：

```text
schema_version
layers: LayerNodeConfig[]
```

`LayerNodeConfig`：

```text
name
type
deps
metadata
```

`CompositorSessionSnapshot`：

```text
schema_version
layers: LayerSessionSnapshot[]
```

`LayerSessionSnapshot`：

```text
name
lifecycle_state
runtime_state
```

并且 `LifecycleState.ACTIVE` 会被拒绝进入外部 snapshot。

成熟点：

```text
Graph config = 可复用结构；
Session snapshot = 有序 layer 状态；
Live resource = 当前 invocation 内部资源；
三者边界严格。
```

这对我们“神经控制层”非常关键：

```text
神经控制层应该保存可恢复的控制状态和路由状态；
不应保存当前打开的文件句柄、进程、客户端、临时工具对象。
```

## 10. Layer 生命周期：NEW / ACTIVE / SUSPENDED / CLOSED

`src\agenton\layers\base.py` 定义：

```text
LifecycleState:
  NEW
  ACTIVE
  SUSPENDED
  CLOSED

ExitIntent:
  DELETE
  SUSPEND
```

`Layer` 的核心原则：

- layer instance 是 invocation-scoped mutable business state；
- `runtime_state` 是唯一跨调用 snapshot 的可变数据；
- live resource 应进入 `resource_context()`；
- `on_context_create()` 处理首次进入；
- `on_context_resume()` 处理从 suspended 恢复；
- `on_context_suspend()` 处理挂起；
- `on_context_delete()` 处理删除。

`CompositorRun`：

- enter 时从 NEW 调 create，从 SUSPENDED 调 resume；
- exit 时根据 exit_intent 调 suspend 或 delete；
- exit 后 snapshot；
- 如果还有 ACTIVE layer，不允许 snapshot；
- prompts/tools/user_prompts 按 layer 图顺序聚合。

成熟点：

```text
这是“任务函数”的工程化形态：
agent run 只是进入一组 layer，layer 提供资源、prompt、tools、user prompts 和 runtime_state。
```

对本项目：

```text
TaskWorkEnvironment 可以拆成多 layer：
  physical_project_graph
  semantic_project_graph
  ast_index
  artifact_store
  review_contract
  tool_policy
  memory_scope
  graph_execution_state
```

每个 layer 都应有：

```text
config
runtime_state
resource_context
create/resume/suspend/delete
visible prompt/tool projection
```

## 11. SandboxLocator：只恢复最小运行环境

`src\dify_agent\protocol\sandbox.py` 说明：

```text
Sandbox file APIs must rebuild only the minimum runtime needed to re-enter a prior shell session:
dify.execution_context + dify.shell.
Credential-bearing plugin layers are excluded.
```

`SandboxLocator`：

```text
composition
session_snapshot
```

构建 locator 时：

- 必须有非空 session_snapshot；
- 从 composition 中提取非敏感 layer spec；
- 必须包含 `execution_context` 和 `shell`；
- `shell` 必须依赖 execution_context；
- snapshot layers 必须按相同顺序包含这些 layer；
- LLM / tools 等敏感 layer type 被禁止进入 locator。

成熟点：

```text
文件访问不需要恢复整个 agent；
只恢复能进入 sandbox shell 的最小 layer 子图。
```

这对本项目深度网络工具很重要：

```text
读取项目文件、查看 AST、读取语义索引时，不必重建完整 agent task；
可以用最小 Locator：
  project_id
  physical_graph_layer
  semantic_graph_layer
  file_scope / ast_scope
  snapshot_ref
```

工具可以脱离工具槽位膨胀，但必须有受控 locator。

## 12. 与本项目的设计映射

Dify Agent / Agenton 给本项目的标准映射：

```text
RunComposition
-> TaskFunctionComposition

RunLayerSpec
-> TaskEnvironmentLayerSpec

CompositorSessionSnapshot
-> TaskEnvironmentSnapshot

RunScheduler.active_tasks
-> ExecutionEpisode active job

RedisRunStore RunRecord
-> EpisodeRunRecord

RunEvent stream
-> EpisodeEventLog

RunSucceededEventData
-> EpisodeTerminalResult

SandboxLocator
-> ProjectNetworkLocator
```

我们要构建的三层项目控制系统可以这样落地：

```text
物理层 layer:
  file tree
  git state
  AST/deep AST index

语义层 layer:
  module semantic labels
  directory summaries
  function/class responsibilities
  call/import/dataflow relationship annotations

神经控制层 layer:
  task graph run state
  agent node contracts
  allowed tools
  context projection policy
  artifact/report refs
  repair/maintenance queues
```

Agent 进入任务时，系统不是把全量东西塞给它，而是通过 layer 投影：

```text
prompt projection
tool projection
resource locator
runtime_state snapshot
event stream
artifact refs
```

## 13. 对“记忆架构”的直接结论

Dify Agent 的 history 处理给了一个明确标准：

```text
当前系统提示和当前 contract 临时进入 message_history；
成功后只把 new_messages 写回 history layer；
session_snapshot 保存 runtime_state；
output/artifact 单独成为 terminal result。
```

本项目应据此避免：

- 把不变事实每轮写入记忆；
- 把工具结果长文本写入长期记忆；
- 把当前上下文投影误当成持久记忆；
- 把 active resource 或工具句柄写进 snapshot；
- 把完整 create request / prompt / credential 写进 run store。

更合理的记忆结构：

```text
StaticContractStore:
  agent role / task contract / environment contract

ProjectSemanticStore:
  变化慢的语义索引，按版本/hash维护

EpisodeHistory:
  只保存本次 run 新产生的关键消息/决策/错误

ArtifactStore:
  报告、索引、审计表、代码片段引用

SnapshotStore:
  可恢复 runtime_state，不含 live resource

EventLog:
  可回放运行事件，不含敏感 config
```

## 14. 不适合照搬的部分

Dify Agent 当前 scheduler 明确不是分布式 job queue，process crash 后 active runs 会丢失，需外部 operator 标记或 retry。这对本项目的大规模审查任务不够。

我们不能照搬它的 process-local scheduler 作为最终形态。至少需要：

```text
durable run lease
heartbeat
stale active run recovery
checkpoint-based retry
worker concurrency limit
parent graph backpressure
artifact completeness check
```

另外，Agenton layer graph 是通用 layer 编排，不包含项目物理图、AST 深化图、语义网络和代码关系提取算法。我们只能借鉴它的分层、snapshot、lifecycle、resource boundary。

## 15. 本项目应采用的硬标准

基于 Dify Agent / Agenton 审查，本项目的任务函数底座应包含：

```text
TaskFunctionComposition:
  schema_version
  layers:
    name
    type
    deps
    metadata
    config_ref

TaskEnvironmentSnapshot:
  schema_version
  layers:
    name
    lifecycle_state: new | suspended | closed
    runtime_state_ref / runtime_state_json

ExecutionEpisode:
  episode_id
  task_id
  composition_ref
  snapshot_in_ref
  status
  event_stream_ref
  snapshot_out_ref
  terminal_result_ref

EpisodeTerminalResult:
  output_refs
  deferred_action
  session_snapshot_ref
  terminal_summary
```

并采用 layer 生命周期：

```text
create
resume
suspend
delete
```

同时必须坚持：

```text
结构图不保存运行资源；
snapshot 不保存 active 状态；
event stream 可回放；
terminal success 必须含 next snapshot；
敏感工具配置不进 run store；
文件/AST/语义网络工具使用最小 locator；
active background job 不是任务环境。
```

