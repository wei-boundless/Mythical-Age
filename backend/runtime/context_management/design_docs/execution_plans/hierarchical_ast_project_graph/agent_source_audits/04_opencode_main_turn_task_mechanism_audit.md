# opencode-main 源码机制审查：早期 Go Agent 的 Session / Message / Stateless Task Agent

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\opencode-main`

## 1. 审查目标

opencode-main 是 Go 版本实现，相比 opencode-dev 更早期、更轻量。本报告关注：

- session / message 如何落库；
- agent run 如何处理一个用户请求；
- tool call 和 tool result 如何进入 history；
- cancellation / busy 如何实现；
- `agent` tool 创建的 task session 是什么；
- 它为什么还不能算成熟的持久任务工作环境。

## 2. 主要审查文件

```text
D:\AI应用\opencode-main\internal\session\session.go
D:\AI应用\opencode-main\internal\message\message.go
D:\AI应用\opencode-main\internal\message\content.go
D:\AI应用\opencode-main\internal\llm\agent\agent.go
D:\AI应用\opencode-main\internal\llm\agent\agent-tool.go
D:\AI应用\opencode-main\internal\app\app.go
```

## 3. Session 模型

`internal/session/session.go` 定义：

```text
Session {
  ID
  ParentSessionID
  Title
  MessageCount
  PromptTokens
  CompletionTokens
  SummaryMessageID
  Cost
  CreatedAt
  UpdatedAt
}
```

`Session.Service`：

```text
Create(title)
CreateTitleSession(parentSessionID)
CreateTaskSession(toolCallID, parentSessionID, title)
Get
List
Save
Delete
```

关键点：

- session 是数据库持久对象；
- session 支持 parent session；
- task session 的 id 直接使用 toolCallID；
- title generation 也创建 child session；
- summary 通过 SummaryMessageID 指向某条 message。

成熟度判断：

```text
它有 session tree，但没有 task lifecycle。
CreateTaskSession 更像“为子 agent 工具调用创建一段子会话历史”，不是完整任务环境。
```

## 4. Message / ContentPart 模型

`internal/message/content.go` 定义 message part：

```text
ReasoningContent
TextContent
ImageURLContent
BinaryContent
ToolCall
ToolResult
Finish
```

`Message`：

```text
ID
Role
SessionID
Parts
Model
CreatedAt
UpdatedAt
```

工具相关：

```text
ToolCall {
  ID
  Name
  Input
  Type
  Finished
}

ToolResult {
  ToolCallID
  Name
  Content
  Metadata
  IsError
}
```

FinishReason：

```text
end_turn
max_tokens
tool_use
canceled
error
permission_denied
unknown
```

成熟点：

- message parts 已经结构化；
- tool call / tool result 是 message 历史的一部分；
- finish reason 明确；
- reasoning / text / binary / tool 可共存。

不足：

- tool call 只有 `Finished bool`，没有 pending/running/completed/error 的完整状态；
- tool result 没有 time / attachment / compacted / output ref；
- message part 是 JSON blob，缺少 part-level 独立索引；
- 没有 step-start / step-finish / snapshot / patch 等更细粒度审计事件。

## 5. Agent Run 机制

`internal/llm/agent/agent.go` 的核心接口：

```text
Run(ctx, sessionID, content, attachments...) -> <-chan AgentEvent
Cancel(sessionID)
IsSessionBusy(sessionID)
IsBusy()
Summarize(sessionID)
```

运行流程：

```text
Run
-> 检查 session busy
-> context.WithCancel
-> activeRequests.Store(sessionID, cancel)
-> goroutine processGeneration
```

`processGeneration()`：

```text
读取已有 messages
如果没有消息，异步生成 title
如果有 SummaryMessageID，从 summary message 开始裁剪 history
创建 user message
msgHistory = old messages + user message
loop:
  streamAndHandleEvents
  如果 FinishReasonToolUse 且有 toolResults:
    msgHistory += assistant message + tool message
    continue
  否则返回 final agent event
```

成熟裁决：

```text
这是 turn 内 agent loop。
多次 LLM stream + tool result continuation 仍然属于同一个 Run / 当前请求。
```

这支持本项目硬边界：

```text
不能因为一次请求内部发生工具循环就创建持久任务。
```

## 6. Stream / Tool 处理机制

`streamAndHandleEvents()`：

```text
ctx 写入 sessionID
provider.StreamResponse(ctx, msgHistory, tools)
创建 assistant message
ctx 写入 messageID
for provider events:
  thinking delta -> AppendReasoningContent + Update
  content delta -> AppendContent + Update
  tool_use_start -> AddToolCall + Update
  tool_use_stop -> FinishToolCall + Update
  complete -> SetToolCalls + AddFinish + Update + TrackUsage
```

stream 完成后执行 tool calls：

```text
for toolCall in assistantMsg.ToolCalls():
  找工具
  tool.Run(ctx, ToolCall)
  error -> ToolResult error
  permission denied -> FinishReasonPermissionDenied，并取消后续 tool calls
创建 role=tool 的 message，包含所有 ToolResult
返回 assistantMsg + tool message
```

工程含义：

- 工具执行在 assistant stream 之后批量发生；
- tool result 进入新 message；
- tool result 再追加回 msgHistory 继续模型循环；
- permission denied 是 finish reason；
- cancellation 会给剩余 tool calls 生成 canceled result。

不足：

- 工具执行状态不够细；
- 没有统一 background job；
- 没有 per-tool persistent state machine；
- 没有 task-level checkpoint；
- 没有 task artifact cursor。

## 7. Busy / Cancel 机制

`agent.activeRequests sync.Map` 保存：

```text
sessionID -> context.CancelFunc
sessionID+"-summarize" -> context.CancelFunc
```

`Run()` 启动前：

```text
if IsSessionBusy(sessionID) return ErrSessionBusy
```

`Cancel(sessionID)`：

```text
LoadAndDelete(sessionID)
cancel()
LoadAndDelete(sessionID+"-summarize")
cancel()
```

成熟点：

- 同 session 互斥；
- cancel 绑定 session id；
- summarize 和 regular run 分开 key。

不足：

- activeRequests 只是内存 map；
- 没有持久 run-state；
- 没有 episode id；
- 没有 cancel propagation 到 child task session；
- 没有 wait/resume/checkpoint。

对本项目：

```text
session busy map 是最低限度。
TaskWorkEnvironment 需要持久 run-state + episode id + child job propagation。
```

## 8. Agent Tool / Task Session

`internal/llm/agent/agent-tool.go` 定义 `agent` 工具。

prompt 描述非常明确：

```text
Launch a new agent...
Each agent invocation is stateless.
You will not be able to send additional messages to the agent.
The agent's outputs should generally be trusted.
The agent can not use Bash, Replace, Edit.
```

执行流程：

```text
解析 prompt
从 ctx 取 parent sessionID / messageID
NewAgent(config.AgentTask, TaskAgentTools)
CreateTaskSession(toolCallID, parentSessionID, "New Agent Session")
agent.Run(ctx, child session.ID, prompt)
阻塞等待 done
读取 child session cost
把 child cost 加回 parent session
返回 child assistant text
```

关键裁决：

```text
这里的 task session 是 stateless subagent invocation。
它不是持久任务工作环境。
```

原因：

- id 等于 toolCallID；
- 生命周期随工具调用结束；
- 不能追加消息；
- 不能恢复；
- 不能独立 pause/resume；
- 不能产生可管理 work product；
- 没有任务记忆；
- 没有验收和 checkpoint。

对本项目：

```text
Subagent invocation 可以作为 ExecutionEpisode 或 ToolInvocation。
不能把它当作 TaskWorkEnvironment。
```

## 9. Non-interactive Run

`internal/app/app.go` 的 `RunNonInteractive()`：

```text
创建 session
AutoApproveSession
CoderAgent.Run(session.ID, prompt)
等待 result
输出 final content
```

工程意义：

- CLI 一次 prompt 也创建 session；
- 非交互运行仍走相同 agent Run；
- 自动审批是 session 级策略；
- 输出只取最终 assistant text。

本项目可借鉴：

```text
后端 CLI 可以创建 TaskWorkEnvironment 或普通 session。
但一次 CLI prompt 不应天然等于持久任务。
```

## 10. 可借鉴机制

建议本项目借鉴：

1. session/message 数据库权威。
2. message parts 承载 reasoning/text/tool/finish。
3. session-level busy 和 cancel 的硬互斥。
4. tool result 进入历史后继续模型循环。
5. parent/child session 表达子 agent 调用的证据链。
6. SummaryMessageID 用于裁剪历史恢复。

## 11. 不应照搬的地方

不建议照搬：

- `CreateTaskSession(toolCallID)` 作为持久任务模型。
- stateless subagent 作为任务系统主形态。
- 只有 activeRequests 内存 map 的运行态管理。
- tool call 只有 Finished bool 的状态模型。
- 把 child agent cost 直接累加给 parent 作为唯一产物回写。

## 12. 对本项目任务设计的硬结论

opencode-main 证明了一个早期 agent 的基本骨架：

```text
Session
-> Message history
-> Agent Run
-> Assistant message stream
-> Tool call/result
-> continue loop
-> finish reason
```

但它也暴露了不足：

```text
没有真正 TaskWorkEnvironment。
没有持久任务生命周期。
没有 episode/checkpoint/work product/artifact cursor。
没有可恢复后台 job。
```

因此，本项目不能停留在 opencode-main 级别。应采用更成熟的目标：

```text
普通 turn 复用 session/message/tool loop。
持久任务另建 TaskWorkEnvironment。
子 agent 调用只是 episode/tool invocation，不是任务本体。
```

