# opencode-dev 源码机制审查：Session / Message Parts / Run State / Background Job

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\opencode-dev`

## 1. 审查目标

opencode-dev 是较新的 TypeScript / Effect 架构。本报告只关注：

- session 如何建模；
- message / part 如何承载 turn 内事件；
- run-state 如何保证 session 运行互斥和取消；
- background job 如何定义；
- tool call 状态如何持久化；
- 哪些机制可用于本项目任务工作环境与 graph runtime 设计。

## 2. 主要审查文件

```text
D:\AI应用\opencode-dev\packages\opencode\src\session\session.ts
D:\AI应用\opencode-dev\packages\opencode\src\session\message-v2.ts
D:\AI应用\opencode-dev\packages\opencode\src\session\processor.ts
D:\AI应用\opencode-dev\packages\opencode\src\session\run-state.ts
D:\AI应用\opencode-dev\packages\opencode\src\background\job.ts
```

已定位但尚未完全展开的后续相关文件：

```text
D:\AI应用\opencode-dev\packages\opencode\src\tool\task.ts
D:\AI应用\opencode-dev\packages\opencode\src\tool\task_status.ts
D:\AI应用\opencode-dev\packages\opencode\src\session\llm.ts
D:\AI应用\opencode-dev\packages\opencode\src\session\compaction.ts
D:\AI应用\opencode-dev\packages\opencode\src\session\projectors.ts
D:\AI应用\opencode-dev\packages\opencode\src\session\projectors-next.ts
```

## 3. Session 数据模型

`session.ts` 的 `Info` 是持久 session 模型：

```text
id
slug
projectID
workspaceID
directory
path
parentID
summary
cost
tokens
share
title
agent
model
version
time.created / updated / compacting / archived
permission
revert
```

硬结构特征：

- session 有 project / workspace 归属；
- session 可以有 parentID，支持 child session；
- session 有 summary / cost / tokens；
- session 有 model / agent；
- session 有 permission ruleset；
- session 有 revert 信息；
- session 时间字段包含 compacting / archived。

这说明 opencode 把 session 作为长期可管理对象，而不是一次请求。

## 4. Session Service 接口

`Session.Service` 暴露：

```text
create
fork
remove
get
list
messages
children
updateMessage
getPart
updatePart
updatePartDelta
findMessage
```

成熟点：

- session 创建、fork、children 是一等接口；
- message / part 更新是 session 权威服务职责；
- delta 更新单独存在，支持流式增量；
- fork 会复制 messages / parts 并重映射 id；
- remove 会取消 background jobs 并删除 child sessions。

对本项目：

```text
TaskWorkEnvironment 也应拥有 service 接口，不应只是数据库表。
至少需要 create / fork-or-resume / remove / inspect / list / artifacts / children / update_work_product / update_checkpoint。
```

## 5. MessageV2 与 Part 模型

`message-v2.ts` 把会话内容拆成 message + part。

主要 part 类型：

```text
text
reasoning
file
agent
compaction
subtask
retry
step-start
step-finish
snapshot
patch
tool
```

工具 part 状态：

```text
ToolStatePending:
  status=pending
  input
  raw

ToolStateRunning:
  status=running
  input
  title
  metadata
  time.start

ToolStateCompleted:
  status=completed
  input
  output
  title
  metadata
  time.start/end/compacted
  attachments

ToolStateError:
  status=error
  input
  error
  metadata
  time.start/end
```

成熟点：

- tool call 是持久 part，不是临时日志；
- tool call 生命周期显式；
- output 可被 compact；
- attachments 是一等字段；
- step-start / step-finish 让模型执行过程有结构边界；
- subtask part 独立记录 prompt / description / agent / model / command。

对本项目非常关键：

```text
ExecutionEpisode 的 trace 不应只是文本日志。
应该有结构化 part/event：
  step_start
  tool_call_pending/running/completed/error
  reasoning_summary
  artifact_attached
  checkpoint_created
  work_product_emitted
```

## 6. SessionProcessor 机制

`processor.ts` 的核心职责是把 LLM stream 转成持久 message parts。

`ProcessorContext` 包含：

```text
assistantMessage
sessionID
model
toolcalls
shouldBreak
snapshot
blocked
needsCompaction
currentText
reasoningMap
```

关键 Handle：

```text
updateToolCall(toolCallID, update)
completeToolCall(toolCallID, output)
process(streamInput)
```

关键流程：

```text
pre-capture snapshot
handle reasoning-start/delta/end
ensure tool call part
update tool part input/running/completed/error
publish part delta
mark blocked when permission/question rejected
detect compaction need
emit step boundaries and usage
```

成熟点：

- snapshot 在 LLM stream 前捕获，避免 provider 内部 tool 提前执行导致快照太晚；
- tool result 不只是返回给模型，也落成持久结构；
- permission / question rejection 会改变 processor blocked 状态；
- reasoning delta 和 tool delta 都有增量更新通道；
- session service 是写入权威。

对本项目：

```text
任务运行不应只保存最终报告。
必须保存可审计的 episode event parts。
```

尤其项目语义网络构建场景：

- 文件审查 agent 的每个输入文件应成为 evidence part；
- 语义标签输出应成为 work_product part；
- 链路判断应成为 relation_signal part；
- 系统建线应成为 deterministic_edge part；
- agent 赋义应成为 semantic_edge_annotation part。

## 7. Run State 机制

`run-state.ts` 定义 session 运行状态服务：

```text
assertNotBusy(sessionID)
cancel(sessionID)
ensureRunning(sessionID, onInterrupt, work)
startShell(sessionID, onInterrupt, work, ready)
```

内部：

```text
runners: Map<SessionID, Runner<MessageV2.WithParts>>
onIdle -> delete runner, status idle
onBusy -> status busy
onInterrupt
```

取消时：

```text
cancelBackgroundJobs(background, sessionID)
existing.cancel
status idle
```

`cancelBackgroundJobs()` 会级联取消：

- job.id == sessionID；
- job.metadata.sessionId 指向当前 session；
- job.metadata.parentSessionId 指向当前 session；
- 新取消的 job 如果带 sessionId，会继续进入 pending 集合，形成传播。

成熟点：

- session busy 是显式状态，不靠隐式锁；
- cancel 先处理 background jobs，再取消 runner；
- background job 与 session 通过 metadata 建关联；
- 取消是图状传播，不只是单 id。

对本项目：

```text
TaskWorkEnvironment 需要运行状态服务：
  assertNotBusy(task_run_id)
  cancel(task_run_id)
  ensureRunning(task_run_id, episode_work)
  cancelChildJobs(task_run_id)
```

Graph node 执行也应走统一 run-state，而不是每个 adapter 自己判断是否 busy。

## 8. BackgroundJob 机制

`background/job.ts` 定义：

```text
Status = running | completed | error | cancelled

Info:
  id
  type
  title
  status
  started_at
  completed_at
  output
  error
  metadata

StartInput:
  id
  type
  title
  metadata
  run: Effect<string, unknown>

Interface:
  list
  get
  start
  wait
  cancel
```

关键实现：

- jobs 存在 `SynchronizedRef<Map<string, Active>>`；
- start 是 uninterruptible mask；
- 如果同 id running，返回已有 snapshot；
- run fork 到 scope；
- success -> completed + output；
- failure -> error；
- interrupt-only -> cancelled；
- wait 支持 timeout；
- cancel interrupt fiber 后 finish cancelled。

成熟标准：

```text
BackgroundJob 是轻量后台执行单元。
它有 id/type/status/output/error/metadata/control API。
```

本项目可借鉴：

```text
ProjectNetworkBuildJob / GraphMaterializationJob / SemanticReviewJob
可以作为 BackgroundJob，但不能替代 TaskWorkEnvironment。
```

区别：

- BackgroundJob 是运行中的 effect/fiber；
- TaskWorkEnvironment 是持久工作环境；
- 一个 TaskWorkEnvironment 可以产生多个 background jobs / episodes；
- background job 完成后 output 是产物或事件，不是任务本体。

## 9. Fork 与 Children

`session.ts` 支持：

```text
create(parentID)
fork(sessionID, messageID?)
children(parentID)
```

fork 会：

- 新建 child session；
- 复制原 session 的 messages；
- 对 message id / part id 做新映射；
- 可按 messageID 截断。

对本项目：

```text
任务恢复和分支不能只复用同一个数据库行。
需要支持 fork task environment / fork episode context / fork graph branch。
```

项目语义网络中：

- 审查任务可以 fork 出修复任务；
- 维护任务可以 fork 出局部 re-review；
- graph node 可以 fork 后比较不同语义判断；
- 但最终发布必须由 curator 合并。

## 10. 可借鉴机制

建议本项目借鉴：

1. Session / Message / Part 的结构化事件模型。
2. ToolState pending/running/completed/error 的生命周期。
3. StepStart / StepFinish / Snapshot / Patch part。
4. SessionRunState 的 assertNotBusy / cancel / ensureRunning。
5. BackgroundJob 的 id/type/status/output/error/metadata/wait/cancel。
6. background job metadata 关联 session / parent session，并支持级联取消。
7. fork / children 作为 session 管理基础能力。
8. delta update 作为流式 UI 和审计基础。

## 11. 不应照搬的地方

不建议照搬：

- 直接把 opencode 的 session 当成本项目任务。我们的任务需要独立 work environment、记忆、产物和验收。
- 只用 BackgroundJob 表达长期任务。BackgroundJob 太轻，只适合运行态 effect。
- 让 every tool output 都直接进入模型上下文。应区分 event store、artifact store、context projection。
- 把 Effect 架构整体迁入。本项目可借鉴接口形态和状态机，不必复制技术栈。

## 12. 对本项目任务设计的硬结论

opencode-dev 支持以下成熟裁决：

```text
长期可管理对象 = Session。
当前运行互斥 = RunState / Runner。
后台执行 = BackgroundJob。
模型输出和工具调用 = Message Part / ToolState。
```

落到本项目：

```text
TaskWorkEnvironment = 长期可管理对象。
ExecutionEpisodeRunState = 当前运行互斥与取消。
BackgroundJob = 轻量异步运行单元。
EpisodeEventPart = 审计和恢复的结构化事件。
WorkProduct / Artifact = 可消费产物。
```

这比“任务函数”更硬，也比“复杂 turn 就创建 task”更成熟。

