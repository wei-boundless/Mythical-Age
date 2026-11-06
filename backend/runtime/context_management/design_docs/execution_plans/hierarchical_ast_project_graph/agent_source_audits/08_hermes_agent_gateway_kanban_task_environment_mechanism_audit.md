# Hermes Agent 源码机制审查：Gateway Turn / Session Resume / Kanban Task Environment

状态：源码审查记录  
日期：2026-07-03  
源码目录：`D:\AI应用\hermes\hermes-agent-main`

## 1. 审查目标

本报告审查 Hermes Agent 的 turn、session、上下文、checkpoint、Codex app-server 适配和 Kanban 任务系统，重点回答：

- Hermes 如何区分单次用户消息、跨 turn 会话和持久任务；
- 它是否存在类似“任务工作环境”的外部强管理结构；
- 它的任务系统如何持久化状态、运行尝试、事件、上下文和产物；
- 哪些工程机制可作为本项目任务函数、持久任务环境、神经控制层的参考；
- 哪些机制只是聊天增强或运行态控制，不能误认为任务环境。

## 2. 主要审查文件

```text
D:\AI应用\hermes\hermes-agent-main\agent\conversation_loop.py
D:\AI应用\hermes\hermes-agent-main\gateway\session.py
D:\AI应用\hermes\hermes-agent-main\gateway\session_context.py
D:\AI应用\hermes\hermes-agent-main\gateway\run.py
D:\AI应用\hermes\hermes-agent-main\agent\transports\codex_app_server_session.py
D:\AI应用\hermes\hermes-agent-main\agent\transports\codex_event_projector.py
D:\AI应用\hermes\hermes-agent-main\tools\checkpoint_manager.py
D:\AI应用\hermes\hermes-agent-main\agent\tool_executor.py
D:\AI应用\hermes\hermes-agent-main\agent\memory_manager.py
D:\AI应用\hermes\hermes-agent-main\agent\context_engine.py
D:\AI应用\hermes\hermes-agent-main\agent\prompt_builder.py
D:\AI应用\hermes\hermes-agent-main\hermes_cli\kanban_db.py
D:\AI应用\hermes\hermes-agent-main\hermes_cli\checkpoints.py
```

## 3. 核心结论

Hermes 同时存在三套边界：

```text
run_conversation()
= 一次用户消息驱动的 turn loop

Gateway SessionEntry / SessionStore
= 跨 turn 的会话路由、transcript、prompt cache、resume_pending

Kanban Task / task_runs / task_events
= 持久化任务工作环境和多 agent 协作账本
```

其中真正接近本项目“持久任务环境”的不是 `run_conversation()`，也不是普通 gateway session，而是 Kanban：

```text
tasks
-> task_links
-> claim_task(CAS)
-> task_runs
-> worker subprocess
-> heartbeat / timeout / crash / reclaim
-> kanban_complete(summary, metadata, artifacts)
-> task_events
-> downstream build_worker_context()
```

Hermes 的成熟点在于它没有让 LLM 自己“记住任务”。任务状态、运行权、重试、产物摘要、通知 cursor 和失败审计都在 SQLite 控制面里，agent 只作为某个 task run 的执行体进入环境。

## 4. Conversation Loop：turn 是一次执行节拍，不是任务

`agent\conversation_loop.py` 文件头明确写明，`run_conversation()` 是驱动“one user turn”的 3900 行循环。它负责：

- 接收 `user_message` 和 `conversation_history`；
- 构造本 turn 的 `messages`；
- 恢复或构建 system prompt；
- 执行模型调用与工具调用循环；
- 处理中断、空响应、截断、上下文压缩；
- 持久化 session transcript；
- 触发 post-turn memory / skill review。

关键变量：

```text
effective_task_id = task_id or uuid
agent._current_task_id = effective_task_id
messages = list(conversation_history) + current user message
_turn_exit_reason
interrupted
api_call_count
```

注意：这里的 `task_id` 主要用于隔离 VM、浏览器、checkpoint、工具资源，并不是用户意义上的持久任务对象。它更接近：

```text
TurnExecutionId / ResourceIsolationId
```

不是：

```text
TaskWorkEnvironmentId
```

对本项目的结论：

- 单 agent 的一次进入任务环境，应命名为 `ExecutionEpisode` 或 `TaskRun`；
- 不应把普通 turn id 误用为持久 task id；
- turn loop 可以执行任务，但不拥有任务真相。

## 5. System Prompt Prefix Cache：跨 turn 稳定内容单独持久化

`_restore_or_build_system_prompt()` 做了一个重要设计：继续会话时从 session DB 读取上一 turn 的 system prompt，避免每 turn 重建导致 provider prefix cache miss。

它区分四种状态：

```text
missing
null
empty
present
```

当 stored prompt 存在时，继续会话复用原 prompt；当为空或读取失败时，日志明确指出 prefix cache 会 miss。

对本项目的参考：

- 任务环境的稳定契约、角色定义、环境说明应有可缓存快照；
- 当前 turn 的动态事实不应污染稳定 prefix；
- 如果缓存快照丢失，应显式记录，而不是静默重建造成成本和行为漂移。

## 6. Gateway Session：会话是路由和 transcript 容器

`gateway\session.py` 定义：

```text
SessionSource
SessionContext
SessionEntry
SessionStore
```

`SessionSource` 表示消息来源，含 platform、chat_id、thread_id、user_id、message_id 等，用于路由回复和注入平台上下文。

`SessionEntry` 表示 session key 到 session id 的映射与轻量状态：

```text
session_key
session_id
origin
display_name
platform
chat_type
token usage
last_prompt_tokens
was_auto_reset
suspended
resume_pending
resume_reason
last_resume_marked_at
```

`SessionStore.get_or_create_session()` 做的不是任务调度，而是：

- 根据来源构造 deterministic session key；
- 按 reset policy 决定是否新建 session；
- session suspended 时强制新会话；
- resume_pending 时保留原 session id 和 transcript。

成熟点：

```text
session 是跨 turn 容器；
session 可以 resume transcript；
session 不等于 task；
session key 是路由和隔离边界。
```

对本项目：

- `ConversationSession` 只保存交互历史和路由；
- `TaskWorkEnvironment` 不能塞进 session entry；
- 任务可以关联 session_id，但任务状态不能由 session 状态推断。

## 7. Gateway Runtime Control：运行态 slot + generation 防串线

`gateway\run.py` 的 `GatewayRunner` 用多组结构控制活跃 turn：

```text
_running_agents: session_key -> AIAgent | sentinel
_running_agents_ts
_pending_messages
_queued_events
_session_run_generation
_pending_approvals
_update_prompt_pending
```

关键机制：

- session 开始前先放 `_AGENT_PENDING_SENTINEL`，防止两个消息同时启动同一 session；
- 每次运行 `_begin_session_run_generation()`；
- 异步结果返回前用 `_is_session_run_current()` 检查是否被 `/stop`、`/new` 或新运行取代；
- `_release_running_agent_state()` 带 generation guard，防止旧 run 清掉新 run 状态；
- adapter 的 pending message 被 turn 结束后消费，必要时递归启动 follow-up turn。

这是典型的“运行态控制”，不是持久任务系统。

对本项目：

```text
TaskRun 必须有 generation / lease / owner token；
异步 episode 结束时必须检查当前 owner；
旧 episode 不允许覆盖新 episode 的任务状态。
```

这个机制应进入任务 harness，不应只靠 prompt 要求 agent “不要串线”。

## 8. Resume Pending：恢复是会话续接，不是任务 checkpoint

Hermes 在 gateway drain / restart 时会预先标记活跃 session：

```text
SessionStore.mark_resume_pending(session_key, reason)
```

下一次消息进入同一 session 时：

- `get_or_create_session()` 保留原 session id；
- `_run_agent()` 在用户消息前插入系统 note；
- 如果 transcript 尾部有未处理 tool result，则让 agent 先处理历史尾部；
- 成功完成后 `clear_resume_pending()`。

这个恢复机制成熟但边界清楚：它恢复的是会话和上一 turn 的未处理尾部，不是恢复一套独立任务工作环境。

对本项目：

- `resume_pending` 可参考为 `EpisodeResumeHint`；
- 任务级 resume 还必须有 `TaskRunSnapshot`、work product refs、artifact cursor、lease 状态；
- 不能把 transcript tail 当成任务 checkpoint 的唯一来源。

## 9. ContextVar：并发 session 上下文不能放进进程全局环境

`gateway\session_context.py` 把原先 `os.environ["HERMES_SESSION_*"]` 改成 `contextvars.ContextVar`。

原因写得很清楚：gateway 是 asyncio 并发处理消息，如果用进程全局环境变量，Message A 的 thread id 会被 Message B 覆盖，导致后台通知和工具调用路由错线程。

成熟点：

```text
session-local routing state must be task-local;
legacy env fallback 只用于 CLI/cron/test；
clear_session_vars 后显式返回空，不回退到 stale env。
```

对本项目：

- 神经控制层的当前 task、current node、current output route 必须是 run-local context；
- 不应通过全局变量传递当前任务状态；
- 对工具暴露任务环境时，要用 scoped context 或 explicit handle。

## 10. Codex App-Server Adapter：外部 runtime 是可替换执行引擎

`agent\transports\codex_app_server_session.py` 是 Hermes 接入 Codex app-server 的 adapter。

核心对象：

```text
CodexAppServerSession
TurnResult
CodexEventProjector
```

生命周期：

```text
ensure_started()
-> initialize
-> thread/start
-> run_turn(user_input)
-> turn/start
-> consume item/completed notifications
-> turn/completed
-> TurnResult
```

`TurnResult` 包含：

```text
final_text
projected_messages
tool_iterations
interrupted
error
turn_id
thread_id
should_retire
```

成熟点：

- 一条 Hermes session 拥有一个 Codex thread；
- 每次用户消息是一个 Codex turn；
- Codex event 通过 projector 转为 Hermes messages；
- server-initiated approval 被 adapter 接管；
- 超时、OAuth 失败、post-tool 静默会标记 `should_retire`；
- 外部 runtime wedge 时退休 session，而不是继续复用坏状态。

对本项目：

```text
agent runtime 可以被外部执行引擎替代；
但 task truth 不能寄生在外部 runtime thread 里；
外部 runtime 的 turn result 必须投影为本系统统一 EpisodeEvent / WorkProduct。
```

## 11. Codex Event Projector：事件投影要保持本系统消息不变量

`agent\transports\codex_event_projector.py` 把 Codex 的 item 事件投影为 Hermes 标准消息：

```text
agentMessage      -> assistant message
reasoning         -> stash 到下一 assistant.reasoning
commandExecution  -> assistant tool_call(exec_command) + tool result
fileChange        -> assistant tool_call(apply_patch) + tool result
mcpToolCall       -> assistant tool_call(mcp.server.tool) + tool result
dynamicToolCall   -> assistant tool_call(tool) + tool result
userMessage       -> user message
unknown item      -> opaque assistant note
```

它只在 `item/completed` 时 materialize message，streaming delta 不进入持久 messages。这一点非常重要：

```text
display stream != durable event/message
```

对本项目：

- 神经控制层可以接入不同 agent runtime；
- 每种 runtime 的事件必须投影到统一的任务事件模型；
- 流式 UI、日志、任务事实、最终产物应分层，不应混进一条“messages”。

## 12. Checkpoint Manager：文件安全基础设施，不是任务记忆

`tools\checkpoint_manager.py` 是透明文件系统 checkpoint，不暴露给 LLM。

它在文件变更前自动 snapshot：

```text
write_file
patch
destructive terminal
```

存储方式：

```text
~/.hermes/checkpoints/store/
refs/hermes/<hash16>
indexes/<hash16>
projects/<hash16>.json
```

特点：

- 单 shared git store；
- 跨项目/工作树复用 git objects；
- 每个 project 一个 ref 和 index；
- 每 turn 每目录最多 snapshot 一次；
- 支持 list、diff、restore；
- 有 prune、size cap、orphan cleanup。

`agent\tool_executor.py` 在工具执行前调用 `ensure_checkpoint()`，失败不阻塞工具执行。

对本项目：

- checkpoint 是工作目录保护层，不是任务状态层；
- 任务环境应引用 checkpoint ref，而不是把 checkpoint 当任务真相；
- 修改代码前的系统级安全快照值得借鉴。

## 13. Memory Manager：记忆是偏好与稳定事实，不是任务账本

`agent\memory_manager.py` 明确设计为 memory provider 编排层：

```text
build_system_prompt()
prefetch_all(query)
queue_prefetch_all(query)
sync_all(user, assistant)
on_turn_start()
on_session_switch()
on_pre_compress()
on_memory_write()
```

`prompt_builder.py` 的 `MEMORY_GUIDANCE` 很关键：

```text
Memory is injected into every turn.
Do NOT save task progress, session outcomes, completed-work logs, or temporary TODO state to memory.
If a fact will be stale in a week, it does not belong in memory.
Procedures and workflows belong in skills, not memory.
```

这与本项目当前记忆优化方向完全一致。

对本项目：

- task progress、review result、artifact path、run summary 应进任务账本或项目网络 store；
- 用户偏好、稳定环境约定、长期工具偏好才进 memory；
- memory 注入每 turn，因此必须小而稳定，不能成为任务状态垃圾场。

## 14. Context Engine：上下文压缩是会话维护，不是任务继续

`agent\context_engine.py` 定义 pluggable context engine：

```text
update_from_response()
should_compress()
compress(messages)
should_compress_preflight()
on_session_start()
on_session_end()
get_tool_schemas()
handle_tool_call()
```

它负责接近 token limit 时压缩 conversation context，默认是 compressor，也允许未来 DAG / LCM 类实现。

对本项目：

- context engine 可以优化 agent 当前可见上下文；
- 它不应拥有任务真相；
- 任务恢复应基于任务 store / event stream / snapshot，而不是仅靠压缩后的聊天摘要。

## 15. Kanban：真正的持久任务工作环境

`hermes_cli\kanban_db.py` 是 Hermes 最值得参考的部分。

模块说明明确写出：

```text
SQLite-backed Kanban board for multi-profile, multi-project collaboration.
board lives at shared Hermes root.
Profiles intentionally collapse onto a shared board.
Schema is intentionally small: tasks, task_links, task_comments, task_events.
Concurrency strategy: WAL mode + BEGIN IMMEDIATE + CAS updates.
```

核心表：

```text
tasks
task_links
task_comments
task_events
task_runs
kanban_notify_subs
```

`Task` 是持久任务对象：

```text
id
title
body
assignee
status
priority
workspace_kind
workspace_path
claim_lock
claim_expires
result
consecutive_failures
worker_pid
max_runtime_seconds
last_heartbeat_at
current_run_id
workflow_template_id
current_step_key
skills
model_override
session_id
```

`Run` 是一次执行尝试：

```text
id
task_id
profile
step_key
status
claim_lock
claim_expires
worker_pid
started_at
ended_at
outcome
summary
metadata
error
```

这正是本项目需要的硬边界：

```text
TaskWorkEnvironment != ExecutionEpisode
Task == 被管理对象
Run == 一次 agent 执行
Event == 可审计事实
Summary/metadata == 下游可消费 handoff
```

## 16. Kanban Claim：任务所有权由系统 CAS 控制

`claim_task()` 做 `ready -> running` 原子迁移：

```text
UPDATE tasks
SET status='running',
    claim_lock=?,
    claim_expires=?,
    started_at=...
WHERE id=?
  AND status='ready'
  AND claim_lock IS NULL
```

成功 claim 后创建 `task_runs` 行，并写 `claimed` event。

它还检查 parent dependencies：

```text
child 不能在 parent 未 done 时进入 running；
如果发现 ready 状态违反父依赖，则降回 todo 并记录 claim_rejected。
```

对本项目：

- 图任务节点调度必须由系统 claim；
- agent 不能靠 prompt 自称“我负责这个节点”；
- parent/child readiness 应由调度器检查，不由 agent 猜。

## 17. Kanban Completion：产物摘要和结构化 metadata 是任务边界

`complete_task()` 做：

- `running|ready|blocked -> done`；
- 清除 claim；
- 结束 active run；
- 写 `summary`、`metadata`、`result`；
- 写 `completed` event；
- 验证 `created_cards`，防止 agent 幻觉创建子任务；
- 扫描 prose 中疑似 phantom task id，写 advisory event；
- 触发 dependents ready recompute。

成熟点：

```text
完成不是一句 final answer；
完成是状态迁移 + run close + summary + metadata + event + dependency recompute。
```

对本项目：

- 审查图任务的单文件/目录/系统级输出必须写入结构化 work product；
- 报告 Markdown 是人读产物，不能替代 `summary/metadata/events`；
- 下游节点应读取 parent run 的 summary/metadata，而不是回读全部对话。

## 18. Kanban Worker Contract：prompt 是角色契约，不是开发说明

`prompt_builder.py` 的 `KANBAN_GUIDANCE` 写给 worker agent，内容包含：

- 先调用 `kanban_show()` 定向获取任务上下文；
- 工作必须在 `$HERMES_KANBAN_WORKSPACE`；
- 长任务要 `kanban_heartbeat()`；
- 需要人判断就 `kanban_block()`；
- 完成时 `kanban_complete(summary, metadata)`；
- 发现后续工作就创建 child task；
- orchestrator mode 只负责拆解，不执行下游工作。

这符合用户对本项目 agent prompt 的要求：它不是“这是某个 runtime 节点”，而是直接告诉 agent 你是谁、负责什么、怎么交付、何时阻塞。

对本项目：

- 审查 agent 契约必须围绕角色、输入、输出、裁决标准和失败处理；
- 任务系统应提供 `show_task / heartbeat / complete / block / create_child` 等稳定工具；
- 不应把任务生命周期隐藏在自然语言里。

## 19. Hermes 对本项目的直接参考

应借鉴：

```text
1. Task 与 Run 分离
2. Run 有 claim_lock / claim_expires / worker_pid / heartbeat
3. 完成必须写 summary + metadata + terminal event
4. 事件流是任务审计账本
5. parent dependency readiness 由系统检查
6. session/context/memory 不承担任务真相
7. runtime result 需要投影成统一消息/事件
8. resume_pending 是会话恢复标记，不等于完整任务 checkpoint
9. ContextVar / scoped handle 防止并发串线
10. agent prompt 必须是可执行任务契约
```

不应照搬：

```text
1. Kanban 的 board UI / CLI 形态不适合作为本项目 graph harness 的最终模型；
2. Hermes 的 task 仍偏人工看板，不是严格图程序；
3. workflow_template_id/current_step_key 只是前向兼容字段，不是成熟图算法运行时；
4. transcript-based resume 不足以支撑复杂任务恢复；
5. checkpoint 是文件保护，不是任务状态恢复。
```

## 20. 对本项目任务机制的结论

Hermes 证明了一条成熟边界：

```text
普通 turn:
    当前消息进入 agent loop，结束后回写 transcript。

session:
    跨 turn 的历史、路由、prompt cache、resume hint。

task environment:
    持久任务对象 + 运行尝试 + 事件账本 + 工作空间 + 产物摘要 + 失败恢复。
```

本项目如果要把图任务做成“时空任务运行体系”，不能只增强 prompt 或 session。应该建立：

```text
TaskWorkEnvironment
ExecutionEpisode / TaskRun
TaskEventStream
WorkProduct / Artifact
Lease / Claim / Generation
Structured Handoff Summary
Graph/Tree Algorithm Adapter
```

其中 agent 是被调度进入某个任务环境的一次执行体；系统负责真相、状态、依赖、恢复和产物索引。这个方向与 Hermes 的成熟工程实践一致，也比“普通 turn + 聊天记忆”更适合深度网络、语义索引和项目控制系统。
