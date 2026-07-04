# OpenClaw 源码机制审查：ACP Turn / Session Meta / Task Run / Task Flow

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\openclaw-main`

## 1. 审查目标

本报告只审查 OpenClaw 中和本项目“普通 turn 与持久任务工作环境”有关的机制：

- ACP runtime 如何定义 session 与 turn；
- session 运行态如何串行、取消、超时和恢复；
- task run 与 task flow 的区别；
- task / flow 如何持久化；
- subagent / ACP 子会话如何注册为可跟踪任务；
- 这些机制对本项目“任务函数 / 持久工作环境 / 图任务底座”的启发。

## 2. 主要审查文件

```text
D:\AI应用\openclaw-main\src\acp\runtime\types.ts
D:\AI应用\openclaw-main\src\acp\runtime\session-meta.ts
D:\AI应用\openclaw-main\src\acp\control-plane\manager.types.ts
D:\AI应用\openclaw-main\src\acp\control-plane\manager.core.ts
D:\AI应用\openclaw-main\src\acp\control-plane\session-actor-queue.ts
D:\AI应用\openclaw-main\src\config\sessions\types.ts
D:\AI应用\openclaw-main\src\tasks\task-registry.types.ts
D:\AI应用\openclaw-main\src\tasks\task-flow-registry.types.ts
D:\AI应用\openclaw-main\src\tasks\task-registry.store.sqlite.ts
D:\AI应用\openclaw-main\src\tasks\task-flow-registry.store.sqlite.ts
D:\AI应用\openclaw-main\src\tasks\task-executor.ts
D:\AI应用\openclaw-main\src\tasks\task-domain-views.ts
D:\AI应用\openclaw-main\src\plugins\runtime\runtime-taskflow.types.ts
D:\AI应用\openclaw-main\src\plugins\runtime\runtime-taskflow.ts
D:\AI应用\openclaw-main\src\agents\subagent-spawn.ts
D:\AI应用\openclaw-main\src\agents\tools\sessions-spawn-tool.ts
D:\AI应用\openclaw-main\src\agents\tools\sessions-send-tool.ts
D:\AI应用\openclaw-main\src\agents\session-async-task-status.ts
```

## 3. 运行单元总览

OpenClaw 的结构比单纯 chat agent 更接近“可管理任务系统”：

```text
SessionKey / SessionEntry
-> ACP Runtime Handle
-> per-session actor queue
-> active turn
-> TaskRun record
-> TaskFlow record
-> delivery / progress / terminal summary
```

核心结论：

- `turn` 仍然是 ACP runtime 的一次输入输出过程；
- `activeTurn` 是内存运行态，只保存当前 runtime、handle、abortController、cancelPromise；
- `SessionEntry.acp` 保存 ACP session 的持久运行元数据；
- `TaskRecord` 是具体执行记录；
- `TaskFlowRecord` 是可等待、可阻塞、可恢复、可取消、可挂载多个 task run 的任务控制对象；
- subagent / ACP child session 可以被注册为 task run，但 child session 本身不等于 task flow。

## 4. ACP Runtime：turn 是一次流式运行，不是持久任务

`src\acp\runtime\types.ts` 定义：

```text
AcpRuntimePromptMode = "prompt" | "steer"
AcpRuntimeSessionMode = "persistent" | "oneshot"

AcpRuntimeHandle {
  sessionKey
  backend
  runtimeSessionName
  cwd
  acpxRecordId
  backendSessionId
  agentSessionId
}

AcpRuntime.runTurn(input): AsyncIterable<AcpRuntimeEvent>
AcpRuntime.cancel(input)
AcpRuntime.close(input)
```

事件类型包括：

```text
text_delta
status
tool_call
done
error
```

成熟点在于：

- runtime handle 是显式句柄，不靠 prompt 推断；
- turn 以 `requestId` 标识；
- runTurn 是事件流，不直接伪装为最终报告；
- cancel / close 是 runtime 接口的一等能力；
- persistent / oneshot 明确区分“保留上游会话状态”和“一次性运行”。

对本项目的含义：

```text
普通 turn 可以很复杂，可以流式、有工具、有取消、有超时；
但只要它没有独立的任务身份、持久状态、产物、恢复点和验收边界，就仍然不是 TaskWorkEnvironment。
```

## 5. Session Meta：持久会话元数据

`src\config\sessions\types.ts` 的 `SessionEntry` 很大，但 ACP 关键字段集中在：

```text
SessionAcpMeta {
  backend
  agent
  runtimeSessionName
  identity
  mode
  runtimeOptions
  cwd
  state: idle | running | error
  lastActivityAt
  lastError
}
```

`src\acp\runtime\session-meta.ts` 负责：

- 根据 `sessionKey` 解析 session store 路径；
- 读取 `SessionEntry.acp`；
- 遍历所有 ACP session entries；
- 通过 `upsertAcpSessionMeta()` 原子更新 ACP meta。

这个设计把“session 能否恢复、现在是否 running/error、使用哪个 backend/agent/cwd/runtimeOptions”放在持久 store，不塞进模型上下文。

对本项目的启发：

```text
任务环境的可恢复身份必须落到系统存储；
agent 可以看到任务摘要和必要句柄，但不能靠上下文文本承担恢复真相。
```

## 6. Actor Queue 与 ActiveTurn：运行态串行控制

`src\acp\control-plane\session-actor-queue.ts` 用 `KeyedAsyncQueue` 对同一个 `actorKey` 串行化操作，并维护 pending count：

```text
run(actorKey, op)
getPendingCountForSession(actorKey)
getTotalPendingCount()
```

`src\acp\control-plane\manager.types.ts` 定义：

```text
ActiveTurnState {
  runtime
  handle
  abortController
  cancelPromise
}
```

`manager.core.ts` 的 `runTurn()`：

- canonicalize sessionKey；
- evict idle runtime handles；
- 进入 `withSessionActor(sessionKey, ...)`；
- ensure runtime handle；
- set session state running；
- 创建 internal AbortController；
- 写入 `activeTurnBySession`；
- 消费 runtime.runTurn 事件流；
- 记录输出、工具调用和进度；
- 成功后 set session state idle；
- 失败后 set session state error；
- finally 清理 activeTurn；
- oneshot 模式完成后 close runtime 并清理 cache。

取消和超时路径也清晰：

- `cleanupTimedOutTurn()` 先 abort，再调用 runtime.cancel；
- oneshot 还会 runtime.close；
- cleanup 超过 grace 会转为 detached cleanup；
- `cancelSession()` 如果有 activeTurn，直接 abort + runtime.cancel；否则进入 actor queue 后对持久 runtime handle 调 cancel。

成熟点：

```text
activeTurn 只代表当前正在跑的一次 turn；
session meta 才代表 session 持久状态；
task registry 才代表任务运行记录；
三者不混用。
```

## 7. TaskRecord：执行记录，不等于完整任务环境

`src\tasks\task-registry.types.ts` 定义：

```text
TaskRuntime = subagent | acp | cli | cron

TaskStatus =
  queued | running | succeeded | failed | timed_out | cancelled | lost

TaskDeliveryStatus =
  pending | delivered | session_queued | failed | parent_missing | not_applicable

TaskRecord {
  taskId
  runtime
  taskKind
  sourceId
  requesterSessionKey
  ownerKey
  scopeKind: session | system
  childSessionKey
  parentFlowId
  parentTaskId
  agentId
  runId
  label
  task
  status
  deliveryStatus
  notifyPolicy
  createdAt / startedAt / endedAt / lastEventAt
  cleanupAfter
  error
  progressSummary
  terminalSummary
  terminalOutcome: succeeded | blocked
}
```

`src\tasks\task-registry.store.sqlite.ts` 将这些字段落到 `task_runs` 和 `task_delivery_state` 表。

关键判断：

```text
TaskRecord 是一次执行事实的账本。
它能回答“谁发起、谁拥有、哪个 runtime、哪个 child session、现在什么状态、进展摘要是什么、最终结果是什么”。
但它不负责复杂任务的等待、恢复、状态机和多子任务编排。
```

这正是本项目需要避免的误区：不能把一个 run record 当作完整任务工作环境。

## 8. TaskFlowRecord：真正接近“持久任务环境”的控制对象

`src\tasks\task-flow-registry.types.ts` 定义：

```text
TaskFlowSyncMode = task_mirrored | managed

TaskFlowStatus =
  queued | running | waiting | blocked | succeeded | failed | cancelled | lost

TaskFlowRecord {
  flowId
  syncMode
  ownerKey
  requesterOrigin
  controllerId
  revision
  status
  notifyPolicy
  goal
  currentStep
  blockedTaskId
  blockedSummary
  stateJson
  waitJson
  cancelRequestedAt
  createdAt / updatedAt / endedAt
}
```

`src\tasks\task-flow-registry.store.sqlite.ts` 将 flow 落到 `flow_runs` 表，字段包括：

```text
flow_id
sync_mode
owner_key
controller_id
revision
status
goal
current_step
blocked_task_id
blocked_summary
state_json
wait_json
cancel_requested_at
created_at
updated_at
ended_at
```

成熟点：

- `revision` 支持并发更新冲突控制；
- `stateJson` 是 flow 自身状态；
- `waitJson` 是等待恢复条件；
- `blockedTaskId` / `blockedSummary` 明确记录阻塞来源；
- `cancelRequestedAt` 把取消请求持久化；
- `syncMode=managed` 表示 flow 接受系统/插件主动管理；
- `task_mirrored` 表示单 task 的镜像 flow。

这比“给 agent 一段任务 prompt”成熟得多，因为 flow 是有身份、有生命周期、有状态、有恢复点的控制对象。

## 9. Task Executor：run 与 flow 的硬边界

`src\tasks\task-executor.ts` 暴露：

```text
createQueuedTaskRun()
createRunningTaskRun()
startTaskRunByRunId()
recordTaskRunProgressByRunId()
completeTaskRunByRunId()
failTaskRunByRunId()
markTaskRunLostById()
retryBlockedFlowAsQueuedTaskRun()
retryBlockedFlowAsRunningTaskRun()
runTaskInFlow()
cancelFlowById()
cancelDetachedTaskRunById()
```

核心机制：

- detached `acp/subagent` task 会自动创建 one-task flow；
- managed flow 才允许 `runTaskInFlow()` 创建子 task；
- flow 已请求取消或已终态时，不允许再创建子 task；
- blocked flow 只有在最新 task 是 `succeeded + terminalOutcome=blocked` 时才允许 retry；
- cancel flow 会先标记 `cancelRequestedAt`，再取消所有 active child tasks；
- 子 task 全部 settle 后，flow 才进入 cancelled。

这说明成熟系统不是“有个任务列表”就够了，而是要有：

```text
task run lifecycle
flow lifecycle
owner access
revision conflict
blocked retry
child task cancellation
delivery status
terminal summary
```

## 10. Plugin Runtime TaskFlow：给外部控制者的受限 API

`src\plugins\runtime\runtime-taskflow.types.ts` 定义 `BoundTaskFlowRuntime`：

```text
bindSession(sessionKey)
createManaged()
get()
list()
findLatest()
resolve()
getTaskSummary()
setWaiting()
resume()
finish()
fail()
requestCancel()
cancel()
runTask()
```

`runtime-taskflow.ts` 的实现特点：

- 先用 sessionKey 绑定 ownerKey；
- 所有 get/list/resolve/runTask 都按 ownerKey 限权；
- `setWaiting/resume/finish/fail/requestCancel` 都要求 `expectedRevision`；
- 只能修改 `syncMode=managed` 且属于该 owner 的 flow；
- `fromToolContext()` 可以从工具上下文绑定当前 session。

这对本项目的“任务函数”非常关键：

```text
任务函数不应只是 prompt 模板；
它应该是 agent 被放入某个 TaskWorkEnvironment 时，系统提供的一组受限状态 API、产物 API、恢复 API、子任务 API。
```

## 11. Subagent / ACP Spawn：子会话可以成为 task run

`src\agents\tools\sessions-spawn-tool.ts` 支持：

```text
runtime = subagent | acp
mode = run | session
thread
cleanup
cwd
resumeSessionId
streamTo
attachments
```

对 ACP spawn：

- `resumeSessionId` 只允许 runtime=acp；
- `streamTo=parent` 只允许 runtime=acp；
- spawn 成功且有 `childSessionKey/runId` 时，注册 subagent run；
- 如果注册失败，会尝试删除 child session，但明确承认已经启动的 ACP run 可能仍会在后台完成。

`src\agents\session-async-task-status.ts` 通过 task registry 查找当前 session 的 active task，并输出：

```text
async: true
active: true
existingTask: true
status
taskId / runId
progressSummary
sourceId
```

成熟点：

```text
子 agent 是 session / run / task registry 的组合；
它不是靠父上下文里反复粘贴状态维持；
父 agent 看到的是句柄、状态和摘要。
```

## 12. 对本项目的严肃启发

OpenClaw 的源码对本项目有三个强约束意义。

第一，必须把普通 turn、execution episode、task run、task work environment 分开：

```text
Turn = runtime 的一次输入输出
ExecutionEpisode = agent 进入任务环境的一次运行片段
TaskRun = 可持久追踪的一次执行记录
TaskFlow / TaskWorkEnvironment = 可等待、恢复、取消、重试、挂载子任务的持久控制对象
```

第二，任务环境需要系统 API，不只是任务 prompt：

```text
create / get / list / resolve
setWaiting / resume / finish / fail
requestCancel / cancel
runChildTask
recordProgress
writeArtifact
readArtifactSummary
```

第三，任务状态必须有 owner 和 revision：

```text
ownerKey 限定谁可以看和改；
expectedRevision 防止并发覆盖；
blockedTaskId / waitJson 使恢复有真实位置；
terminalSummary 使最终产物可消费。
```

## 13. 不适合照搬的部分

OpenClaw 的 session store 过于宽泛，`SessionEntry` 承载大量渠道、模型、TTS、heartbeat、compaction、plugin debug、ACP meta 字段。

本项目不应照搬这种大对象，而应拆成：

```text
SessionState
TaskWorkEnvironment
ExecutionEpisode
TaskRun
Artifact
MemoryScope
ControlBinding
```

另外，OpenClaw 的 task flow 是通用异步任务控制结构，不直接提供项目语义网络、AST 物理层和语义索引层。因此对我们的“深度项目网络”而言，它只能作为任务控制底座参考，不能替代项目网络管理系统。

## 14. 本项目应采用的标准

基于 OpenClaw 审查，本项目的任务机制最低标准应是：

```text
TaskWorkEnvironment {
  taskId / environmentId
  ownerAgent / requester
  status
  revision
  goal
  currentStep
  state
  waitCondition
  blockedBy
  childRuns
  artifacts
  memoryScope
  cancelRequestedAt
  createdAt / updatedAt / endedAt
}

ExecutionEpisode {
  episodeId
  taskId
  agentProfile
  inputContract
  allowedTools
  status
  progress
  outputRefs
  terminalSummary
}
```

并且必须提供受控 API：

```text
task.create
task.resume
task.set_waiting
task.record_progress
task.spawn_child_run
task.write_artifact
task.finish
task.fail
task.cancel
```

这套结构才配得上“任务像公司里的工作，而 agent 是进入任务环境工作的执行者”这个目标。

