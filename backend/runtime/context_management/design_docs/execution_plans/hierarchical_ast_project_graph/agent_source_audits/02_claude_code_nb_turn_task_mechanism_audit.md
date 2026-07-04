# Claude Code NB 源码机制审查：Conversation Turn 与 Background Task

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\claude-code-nb-main`

## 1. 审查目标

Claude Code NB 派生源码里同时存在：

- conversation / query engine / turn；
- background task；
- task list / todo；
- local agent / remote agent / shell task；
- task output 文件；
-工具上下文、记忆、文件缓存和恢复机制。

本报告重点审查这些机制如何区分，以反推本项目“普通 turn”和“持久任务工作环境”的硬边界。

## 2. 主要审查文件

```text
D:\AI应用\claude-code-nb-main\QueryEngine.ts
D:\AI应用\claude-code-nb-main\Tool.ts
D:\AI应用\claude-code-nb-main\Task.ts
D:\AI应用\claude-code-nb-main\tasks.ts
D:\AI应用\claude-code-nb-main\tasks\LocalAgentTask\LocalAgentTask.tsx
D:\AI应用\claude-code-nb-main\utils\task\framework.ts
D:\AI应用\claude-code-nb-main\tools\TaskCreateTool\TaskCreateTool.ts
D:\AI应用\claude-code-nb-main\tools\TaskCreateTool\prompt.ts
D:\AI应用\claude-code-nb-main\tools\TaskOutputTool\TaskOutputTool.tsx
D:\AI应用\claude-code-nb-main\tools\TaskGetTool\TaskGetTool.ts
D:\AI应用\claude-code-nb-main\tools\TaskStopTool\TaskStopTool.ts
```

## 3. 核心运行定义

`QueryEngine.ts` 对 conversation / turn 给出非常明确的定义：

```text
One QueryEngine per conversation.
Each submitMessage() call starts a new turn within the same conversation.
State (messages, file cache, usage, etc.) persists across turns.
```

这是一条硬标准：

```text
conversation = 长期交互容器
submitMessage = 一个 turn
mutableMessages / file cache / usage = conversation 级跨 turn 状态
```

普通 turn 不是“简单问答”。`submitMessage()` 内部会处理：

- slash command；
- tool permission；
- system prompt；
- memory mechanics prompt；
- file history snapshot；
- transcript persist；
- query loop；
- max turns；
- budget；
- structured output retry；
- compact boundary；
- stream event；
- tool progress；
- final result。

因此复杂执行仍然是 turn。

## 4. QueryEngine 的 turn 机制

`QueryEngine.submitMessage()` 的关键流程：

```text
清空 turn-scoped skill discovery
set cwd
构建 wrappedCanUseTool
读取初始 AppState / model / thinking config
fetchSystemPromptParts
加载 memory mechanics prompt
构建 processUserInputContext
processUserInput
push mutableMessages
recordTranscript(user input)
更新 permission rules
加载 skills/plugins
yield system init message
进入 query()
记录 assistant/user/progress/attachment/system messages
处理 compact boundary
累计 usage
处理 max turns / budget / structured output retry
yield result
```

工程含义：

- `submitMessage()` 是一个完整 turn；
- turn 可以有多轮内部 tool/model 互动；
- turn 可以生成 compact boundary；
- turn 可以写 transcript；
- turn 可以跨多个 SDK message yield；
- turn 结束时输出 result。

成熟裁决：

```text
turn 是交互节拍，不是单次模型请求。
```

本项目应采用同样裁决：

```text
普通 turn 可以包含多次模型请求、多次工具调用、多次状态回写。
只要目标仍服务当前用户输入，仍然是 turn。
```

## 5. Conversation 级状态

`QueryEngine` 持有：

```text
mutableMessages
abortController
permissionDenials
totalUsage
readFileState
discoveredSkillNames
loadedNestedMemoryPaths
```

重要细节：

- `mutableMessages` 跨 turn 保留；
- `readFileState` 跨 turn 保留；
- `totalUsage` 累计；
- `loadedNestedMemoryPaths` 用于避免同一 CLAUDE.md / nested memory 反复注入；
- `discoveredSkillNames` 是 turn-scoped，每次 submitMessage 清空；
- transcript 会在用户输入被接受后立即写入，避免进程被杀后无法 resume。

对本项目记忆架构的直接启发：

```text
稳定事实和已加载记忆必须有去重状态。
不应该每轮把变化很小的事实重新塞进上下文。
```

建议本项目引入：

```text
TaskContextLoadLedger
  loaded_memory_refs
  loaded_file_refs
  loaded_artifact_refs
  stable_context_hashes
  last_projection_epoch
```

它不是语义记忆，而是上下文装载账本，用来防止重复注入。

## 6. ToolUseContext 机制

`Tool.ts` 的 `ToolUseContext` 非常关键，它不是简单把工具函数暴露给模型，而是给工具提供完整运行上下文：

```text
options: commands/tools/mcpClients/agentDefinitions/model/thinking
abortController
readFileState
getAppState / setAppState
setAppStateForTasks
handleElicitation
nestedMemoryAttachmentTriggers
loadedNestedMemoryPaths
dynamicSkillDirTriggers
discoveredSkillNames
file history updater
attribution updater
agentId / agentType
fileReadingLimits / globLimits
contentReplacementState
renderedSystemPrompt
```

硬工程含义：

```text
工具上下文是 agent 与系统环境的接口层。
它暴露句柄、缓存、限制、状态更新函数，而不是把所有信息塞给模型。
```

本项目任务环境应借鉴：

```text
TaskWorkEnvironment
不等于 prompt 文本。
它应该向 ExecutionEpisode 投影 resource handles、state handles、artifact refs、memory refs、permission scope 和 context ledger。
```

## 7. Background Task 定义

`Task.ts` 定义后台任务类型：

```text
TaskType =
  local_bash
  local_agent
  remote_agent
  in_process_teammate
  local_workflow
  monitor_mcp
  dream

TaskStatus =
  pending
  running
  completed
  failed
  killed
```

`TaskStateBase`：

```text
id
type
status
description
toolUseId
startTime
endTime
totalPausedMs
outputFile
outputOffset
notified
```

这是成熟 background task 的最小骨架：

- 独立 id；
- 类型；
- 生命周期；
- 输出文件；
- 增量读取 offset；
- 通知状态；
- kill 控制面。

本项目 `TaskRun` 至少需要同等级字段：

```text
task_run_id
task_type / work_kind
status
description / objective
owner / caller
started_at / ended_at
artifact_root
output_refs
output_offsets or cursor
notified / consumed
checkpoint_refs
```

## 8. Task Registry 与 Task 类型

`tasks.ts` 注册：

```text
LocalShellTask
LocalAgentTask
RemoteAgentTask
DreamTask
LocalWorkflowTask
MonitorMcpTask
```

`Task` 接口当前只保留：

```text
name
type
kill(taskId, setAppState)
```

源码注释说明 spawn/render 不是多态调用点，kill 是真正共享接口。

工程含义：

```text
任务类型可以多样，但控制面必须收敛。
```

本项目应避免每种图任务/项目网络任务各自定义一套生命周期。应统一：

```text
create / start / pause / resume / cancel / checkpoint / list / inspect / collect_artifacts
```

领域差异放到 adapter / contract / work product，不放到生命周期主链。

## 9. Task Output 机制

`utils/task/framework.ts` 和 `TaskOutputTool` 体现了成熟的任务输出策略：

```text
任务输出写入 outputFile。
运行中只读取 delta。
每个 task 保存 outputOffset。
完成任务由具体 task 类型自己发完成通知。
TaskOutputTool 已标注 deprecated，建议直接 Read output file。
```

关键细节：

- `generateTaskAttachments()` 只读取 running task 的增量；
- 状态更新只 patch offset，不把 stale task snapshot 写回；
- terminal task 被消费后可以 evict；
- 完成通知不在通用 poll 中生成，避免和 task 类型自己的完成回调 race；
- `TaskOutputTool` 支持 block / non-block，但提示已建议直接读 output file。

对本项目非常重要：

```text
任务产物不能每次全部塞入上下文。
上下文应保留 artifact ref / semantic summary / cursor。
重内容应写 artifact store，由工具按需读取。
```

项目语义网络也应如此：

```text
根报告、人读 markdown、层级报告、文件报告 = artifact。
语义坐标、路标、链路信号 = index/ref。
agent 当前上下文 = 摘要 + 必要 ref + 当前层输入。
```

## 10. TaskCreate 与 Todo Task

`TaskCreateTool` 不是后台执行任务，而是 structured task list / todo：

```text
subject
description
activeForm
metadata
```

prompt 中建议在复杂多步任务、plan mode、用户明确要求 todo、多任务输入时创建任务列表。

注意：这和后台任务不同。

成熟裁决：

```text
Todo task = 计划/协作管理对象。
Background task = 可运行、可停止、可输出、可通知的后台工作对象。
Conversation turn = 当前 submitMessage 的交互节拍。
```

本项目必须避免混用：

```text
PlanItem / TodoItem
TaskRun / TaskWorkEnvironment
ExecutionEpisode
GraphNodeWorkOrder
```

四者应分别命名、分别建模。

## 11. LocalAgentTask 机制

`LocalAgentTask` 的 `registerAsyncAgent()` 创建后台 agent：

```text
initTaskOutputAsSymlink(agentId, getAgentTranscriptPath(agentId))
create abort controller
create task state
status running
agentId / prompt / selectedAgent / agentType
retrieved false
lastReportedToolCount / lastReportedTokenCount
isBackgrounded true
pendingMessages
retain / diskLoaded
register cleanup
registerTask
```

还有 foreground agent 可以运行一段时间后 background：

```text
registerAgentForeground()
-> task state isBackgrounded false
-> backgroundSignal
-> autoBackgroundMs
```

成熟点：

- agent task 有自己的 transcript；
- outputFile 可以是 transcript symlink；
- parent abort controller 可以级联中断 child；
- foreground / background 是显示和控制状态，不改变任务身份；
- cleanup 和 evict 分开。

本项目可借鉴：

```text
ExecutionEpisode 可以前台运行，也可以被任务环境托管继续。
TaskWorkEnvironment 的身份不应因为 UI 是否展示而变化。
```

## 12. 中断与恢复

`QueryEngine`：

```text
interrupt() -> abortController.abort()
```

background task：

- TaskStopTool 调用 `stopTask()`；
- LocalAgentTask / shell task 通过各自 abort controller 或 process kill；
- terminal status 后可 evict；
- task output 文件保留供读取；
- transcript 预写入用户输入，避免 kill-mid-request 后无法 resume。

成熟裁决：

```text
turn interrupt 和 task stop 是两个控制面。
```

本项目应明确：

- `interrupt_episode`：停止当前 agent episode；
- `pause_task`：保留任务环境，等待恢复；
- `cancel_task`：取消任务环境；
- `resume_task`：新 episode 进入同一 task environment；
- `read_task_artifact`：读取任务产物。

## 13. 可借鉴机制

建议本项目借鉴：

1. `QueryEngine per conversation / submitMessage per turn` 的明确定义。
2. `mutableMessages + readFileState + usage` 作为跨 turn 状态。
3. `loadedNestedMemoryPaths` 这种上下文去重 ledger。
4. `ToolUseContext` 暴露资源句柄，而不是堆 prompt 文本。
5. `TaskStateBase` 的 id/type/status/outputFile/outputOffset/notified。
6. 任务输出文件 + 增量 offset，而不是反复注入全文。
7. foreground/background 只影响管理与展示，不改变任务身份。
8. todo task 和 background task 分开。

## 14. 不应照搬的地方

不建议照搬：

- `TaskCreateTool` 的“3 步以上就建 task”规则作为本项目持久任务规则。它适合 todo，不适合 TaskWorkEnvironment。
- 把 `AppState` 作为本项目任务状态权威。本项目应由后端 task store / runtime store 做权威。
- 把 task output tool 作为唯一读取方式。更成熟方向是 artifact ref + read artifact/file。
- 把前端 UI 展示状态混入任务生命周期核心模型。

## 15. 对本项目任务设计的硬结论

Claude Code NB 支持以下裁决：

```text
普通 turn = submitMessage。
Conversation 级状态可以跨 turn。
Background task = 独立 id + status + output + stop/control + notification。
Todo task = 计划管理对象，不等于后台执行任务。
```

本项目应定义：

```text
Turn
  当前用户输入的交互节拍。

Conversation / Session
  跨 turn 的对话容器和缓存状态。

TaskWorkEnvironment
  持久工作环境，具有独立生命周期、存储、记忆、产物、checkpoint 和控制面。

ExecutionEpisode
  agent 进入任务环境的一次执行片段。

WorkProduct / Artifact
  任务产物，重内容落盘，模型上下文保留摘要与 ref。
```

