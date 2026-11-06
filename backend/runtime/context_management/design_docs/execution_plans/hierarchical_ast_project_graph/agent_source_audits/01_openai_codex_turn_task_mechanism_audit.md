# OpenAI Codex 源码机制审查：Turn / Session / Task 边界

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\openai-codex`

## 1. 审查目标

本报告只审查和本项目“普通 turn 与持久任务工作环境”有关的机制：

- session / thread 如何定义；
- turn 如何启动、运行、打断、完成；
- task 一词在 Codex 源码里实际指什么；
- 子 agent / 多 agent 如何连接；
- 历史、上下文、工具权限和恢复如何落地；
- 哪些机制可作为本项目任务底座设计参考。

## 2. 主要审查文件

```text
D:\AI应用\openai-codex\codex-rs\core\src\session\session.rs
D:\AI应用\openai-codex\codex-rs\core\src\session\turn.rs
D:\AI应用\openai-codex\codex-rs\core\src\session\turn_context.rs
D:\AI应用\openai-codex\codex-rs\core\src\state\turn.rs
D:\AI应用\openai-codex\codex-rs\core\src\tasks\mod.rs
D:\AI应用\openai-codex\codex-rs\core\src\thread_manager.rs
D:\AI应用\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs
D:\AI应用\openai-codex\codex-rs\message-history\src\lib.rs
D:\AI应用\openai-codex\codex-rs\core\src\agent\control.rs
D:\AI应用\openai-codex\codex-rs\core\src\tools\handlers\multi_agents_v2\spawn.rs
D:\AI应用\openai-codex\codex-rs\core\src\tools\handlers\multi_agents_v2\message_tool.rs
```

## 3. 运行单元定义

Codex 的核心运行单元不是“任务”，而是：

```text
Thread / Session
-> ActiveTurn
-> SessionTask
-> TurnContext
-> model/tool loop
-> TurnComplete / TurnAborted
```

`Session` 注释明确说明：

```text
A session has at most 1 running task at a time, and can be interrupted by user input.
```

这里的 task 是内部异步执行任务，不是用户语义任务。`tasks/mod.rs` 进一步定义：

```text
Async task that drives a Session turn.
Implementations encapsulate regular chat, reviews, ghost snapshots, etc.
```

因此 Codex 的成熟边界是：

- `Session` 是长期会话容器；
- `TurnContext` 是单轮运行上下文包；
- `SessionTask` 是驱动当前 turn 的后台异步 runner；
- 用户可见的完成/中断单位是 turn；
- 多 agent 是子 thread / 子 session，不是把一个 turn 扩展成持久任务对象。

## 4. Session 机制

`Session` 持有长期状态：

```text
conversation_id
state: Mutex<SessionState>
active_turn: Mutex<Option<ActiveTurn>>
input_queue
goal_runtime
guardian_review_session
services
```

`SessionConfiguration` 持有：

```text
model / provider
developer_instructions / user_instructions / personality
approval_policy
permission_profile_state
cwd / workspace_roots / codex_home
thread_name
session_source
dynamic_tools
persist_extended_history
```

工程含义：

- 会话级配置稳定存在，turn 只取快照；
- active turn 是互斥资源；
- input queue 支撑运行中 steer / mailbox；
- permission profile 是 session 配置的一部分，但 turn 会拿到投影后的权限；
- cwd / workspace roots 是 session 级运行环境，不是工具临时猜测。

## 5. TurnContext 机制

`TurnContext` 被定义为：

```text
The context needed for a single turn of the thread.
```

它包含：

```text
sub_id
trace_id
model_info
tool_mode
session_telemetry
provider
reasoning_effort / reasoning_summary
session_source / thread_source
environments
cwd
current_date / timezone
developer_instructions / user_instructions / collaboration_mode / personality
approval_policy
permission_profile
network
dynamic_tools
turn_metadata_state
extension_data
turn_skills
turn_timing_state
```

硬裁决：

```text
TurnContext 是当前 turn 的上下文包。
它不是任务记忆，也不是持久任务环境。
```

本项目可借鉴：

- 普通 turn 也应该拥有完整上下文包；
- 任务环境进入执行时，应生成 `TaskContextPackage -> TurnContext/RuntimePacket` 的投影；
- 不应该因为有工具、权限、动态工具、技能、网络代理就把 turn 升级为任务。

## 6. Turn 执行机制

`run_turn()` 做的是当前 turn 的模型/工具循环：

```text
pre-turn compact
record context updates
build skills/plugins injection
run hooks and record input
loop:
  drain pending input when allowed
  clone history for prompt
  run sampling request
  execute tool calls
  handle auto compact
  handle stop hooks
  complete or abort
```

关键点：

- `ModelClientSession` 是 turn-scoped，跨 retry 复用，但不跨任意任务；
- pending input 可以在当前 turn 的后续 sampling 中被消费；
- auto compact 可以 pre-turn 或 mid-turn 触发；
- turn diff tracker 对用户来说是单 turn 生命周期；
- tool call、assistant message、follow-up sampling 都属于当前 turn 内部过程。

成熟标准：

```text
复杂工具循环仍然是普通 turn。
是否有多次 sampling、多个 tool call、mid-turn compact，不构成“任务”。
```

## 7. ActiveTurn 与内部 SessionTask

`state/turn.rs` 定义：

```text
ActiveTurn {
  task: Option<RunningTask>,
  turn_state: Arc<Mutex<TurnState>>,
}

TaskKind = Regular | Review | Compact

RunningTask {
  done
  kind
  task: Arc<dyn AnySessionTask>
  cancellation_token
  handle
  turn_context
  turn_extension_data
}
```

`TurnState` 持有单轮临时状态：

```text
pending_approvals
pending_request_permissions
pending_user_input
pending_elicitations
pending_dynamic_tools
pending_input
mailbox_delivery_phase
granted_permissions
tool_calls
has_memory_citation
token_usage_at_turn_start
```

这个结构说明：

- pending approval / pending user input / dynamic tool response 属于 turn，不属于长期任务；
- granted permission 可以在当前 turn 内被合并；
- token usage 用 turn start 差值计算；
- mailbox delivery phase 控制子 agent 消息是否还折叠进当前 turn。

对本项目的直接启发：

```text
TaskWorkEnvironment 不能吞掉 turn-scoped waiters。
审批、请求用户输入、动态工具返回、当前轮 token 差值仍然应该归 ExecutionEpisode / TurnState 管。
```

## 8. 中断与替换机制

Codex 新 turn 启动前会：

```text
spawn_task()
-> abort_all_tasks(TurnAbortReason::Replaced)
-> clear_connector_selection()
-> start_task()
```

中断路径：

```text
turn_interrupt_inner()
-> 校验 active turn id
-> pending_interrupts 记录请求
-> submit Op::Interrupt
-> Session.abort_turn_if_active / abort_all_tasks
-> cancellation_token.cancel()
-> 等待 grace period
-> task.handle.abort()
-> 写 interrupted marker
-> emit TurnAborted
```

成熟标准：

- 中断目标必须绑定 active turn id；
- 已终止 turn 不能重复中断；
- startup interrupt 和 turn interrupt 分开；
- 中断不是删除历史，而是写入可见的 interrupted marker；
- fork active history 时可合成同样的 interrupted marker。

对本项目：

```text
任务恢复不能靠“重播旧对话假装没中断”。
需要 EpisodeAborted / continuation_hint / checkpoint / interrupted marker。
```

## 9. 历史与持久化

`message-history/src/lib.rs` 是全局 append-only message history：

```text
~/.codex/history.jsonl
{"session_id":"<uuid>","ts":<unix_seconds>,"text":"<message>"}
```

实现要点：

- JSONL；
- advisory lock；
- 单次完整行写入；
- 支持 max_bytes；
- 超过 hard cap 后截到 soft cap；
- 可以按 log id + offset lookup。

ThreadManager 还通过 thread store / rollout 保存完整会话历史，并支持：

```text
resume_thread_from_rollout
fork_thread
fork_thread_from_history
ForkSnapshot::TruncateBeforeNthUserMessage
ForkSnapshot::Interrupted
```

对本项目：

- 普通会话 history 和任务 work product store 应分离；
- task event log 应 append-only；
- task artifact 可按 ref / offset 读取；
- 中断恢复应基于 checkpoint / event history，而不是模型猜测。

## 10. 多 Agent 机制

Codex 多 agent V2 机制是：

```text
spawn_agent tool
-> AgentControl.spawn_agent_with_metadata
-> 新 thread / forked thread
-> SessionSource::SubAgent
-> AgentPath / agent nickname / role
-> InterAgentCommunication mailbox
```

关键工程细节：

- `spawn_agent` 参数含 `task_name`，但实际作为 agent path / canonical task name；
- `fork_turns` 支持 `none | all | N`；
- full-history fork 会保留 reference context；
- truncated fork 会过滤非稳定 items；
- 子 agent 和父 agent 共享 `AgentControl`；
- status、close、resume、message 都通过 control plane；
- `followup_task` 是 send_message + trigger_turn，不是创建持久任务实体。

成熟裁决：

```text
多 agent 的可恢复控制靠 thread/session tree + mailbox + registry。
它不是把所有子工作压进父 turn，也不是把每个消息都变成任务。
```

## 11. Tool / Permission 控制边界

工具调用拿到的是：

```text
session
turn
payload
call_id
```

例如 `exec_command`：

- 从 turn environment 解析 cwd；
- 使用 turn approval policy；
- 使用 session permission profile 的运行时投影；
- sticky turn permissions 会在当前 turn 内继续生效；
- write_stdin 是已有 exec session 的传输，不是新任务。

对本项目：

```text
工具权限必须 episode/turn-scoped。
任务环境只提供权限边界和资源 scope，不应该跳过统一 tool authorization path。
```

## 12. 可借鉴机制

建议本项目借鉴：

1. `Session -> ActiveTurn -> TurnContext -> run_turn` 的硬分层。
2. 同一 session 同时最多一个 active turn 的互斥控制。
3. turn-scoped waiters：approval / user input / dynamic tool / token usage。
4. 中断写 marker，恢复基于持久历史和 checkpoint。
5. fork 支持完整历史、最近 N turn、interrupted snapshot。
6. 多 agent 作为 thread tree + mailbox + registry，而不是父 turn 内的普通函数。
7. 工具调用统一走 turn context / session services，不为任务另开权限链。

## 13. 不应照搬的地方

不建议照搬：

- 把内部异步 runner 也命名为业务任务；
- 只靠 thread history 表达长期任务；
- 把 `task_name` 作为子 agent path 的命名方式直接迁入本项目；
- 将用户语义任务、内部 Tokio task、todo、subagent message 混用同一 `Task` 概念。

## 14. 对本项目任务设计的硬结论

Codex 源码支持以下裁决：

```text
普通 turn 可以很复杂。
复杂 tool loop、mid-turn compact、pending input、审批、子 agent mailbox，都仍然可以属于 turn。
```

任务必须另有独立架构意义：

```text
TaskRun / TaskWorkEnvironment
必须拥有独立身份、生命周期、存储、记忆、产物、checkpoint、恢复和验收。
```

同时必须保留：

```text
TaskWorkEnvironment
-> ExecutionEpisode
-> TurnContext / RuntimePacket
-> single-agent runtime
```

不能让任务系统变成第二套 agent runtime。

