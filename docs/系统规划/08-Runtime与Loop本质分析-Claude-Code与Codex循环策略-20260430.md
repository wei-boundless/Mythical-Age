# Runtime 与 Loop 本质分析：Claude Code 与 Codex 循环策略

日期：2026-04-30  
定位：本文件只回答一个问题：Agent Runtime 的 loop 到底是什么。它不讨论“query 叫不叫 query”，也不绕“谁管谁”的抽象话，而是拆解 Claude Code 与 Codex 两类成熟实现中的循环策略，并映射到洪荒时代应该怎么做。

---

## 0. 一句话结论

Agent loop 的本质就是：

```text
while not terminal:
  观察当前状态
  构建模型可见上下文
  调模型
  如果模型要行动，就执行行动
  把行动结果回填给模型
  记录事件和状态
  判断继续、等待、完成、失败或中断
```

它不是神秘架构，也不是“多个系统协作”的口号。

它就是一个受状态、预算、权限、上下文窗口、工具结果、错误恢复控制的长期循环。

成熟 agent runtime 的差别不在于有没有 loop，而在于：

```text
1. loop 的状态是否显式。
2. loop 的每一步是否可观察。
3. loop 的工具/权限/压缩/恢复是否内建。
4. loop 是否能持久化和恢复。
5. loop 是否有清晰退出条件。
```

---

## 1. Runtime 和 Loop 的区别

### 1.1 Runtime 是运行环境

Runtime 是让 agent 可以运行的环境和服务集合。

它包含：

```text
model runtime
tool runtime
worker runtime
memory runtime
permission runtime
context runtime
event runtime
checkpoint runtime
executor registry
```

Runtime 提供能力，但不等于循环本身。

### 1.2 Loop 是运行控制流

Loop 是把这些能力按顺序组织起来的控制流。

最小形态：

```python
while True:
    context = build_context(state)
    response = call_model(context)

    if response.final_answer:
        commit(response)
        break

    if response.tool_calls:
        results = run_tools(response.tool_calls)
        state.messages.extend(response.messages)
        state.messages.extend(results)
        continue

    if should_compact(state):
        state = compact(state)
        continue

    if should_wait_approval(state):
        checkpoint(state)
        return "waiting_approval"

    if error:
        recover_or_fail()
```

所以：

```text
Runtime 是能力底座。
Loop 是让能力连续运转的心跳。
```

没有 loop，runtime 只是一堆函数。

---

## 2. Claude Code 的 Loop 策略

Claude Code 的核心循环在设计原则文档 `05-对话循环.md` 中已经拆得很清楚。它的本质是：

```text
AsyncGenerator + while(true) + 显式 State + 多个 continue 点 + 多个 terminal return。
```

### 2.1 为什么是 AsyncGenerator

Claude Code 的 `query()` 返回 `AsyncGenerator`，不是普通 `Promise`。

原因很直接：

```text
loop 运行时间长。
中间会不断产生 token、工具进度、错误恢复、压缩通知。
调用方需要实时消费这些事件。
用户也可能中途 abort。
```

因此 loop 每推进一小段，就可以：

```text
yield stream token
yield tool_use message
yield tool_result
yield retry warning
yield compact notice
yield tombstone
yield final message
```

这说明成熟 loop 不是“等最终结果返回”，而是一个持续产出事件的状态机。

### 2.2 Claude Code 的 State

Claude Code 的循环状态包含：

```text
messages
toolUseContext
autoCompactTracking
maxOutputTokensRecoveryCount
hasAttemptedReactiveCompact
maxOutputTokensOverride
pendingToolUseSummary
stopHookActive
turnCount
transition
```

这里最关键的是 `transition`。

它记录上一次为什么 `continue`：

```text
next_turn
reactive_compact_retry
collapse_drain_retry
max_output_tokens_escalate
max_output_tokens_recovery
stop_hook_blocking
token_budget_continuation
```

这个字段的价值是：

```text
避免无脑 while true。
让每次继续都有原因。
让恢复策略知道前一次做过什么。
防止某些恢复路径无限重复。
```

### 2.3 Claude Code 的单轮流程

每次 while 顶部大概做：

```text
1. 消息预处理
   applyToolResultBudget
   snip compact
   microcompact
   context collapse
   autocompact

2. 组装 system prompt / user context / tools

3. 调用模型流
   for await message of callModel()

4. 流式处理
   yield token / assistant message
   收集 tool_use
   streaming tool execution 可提前启动

5. 判断模型是否需要 follow-up
   没有工具 -> stop hooks -> terminal
   有工具 -> run tools -> tool_result 回填 -> continue
```

最典型的循环是：

```text
model returns tool_use
  -> execute tool
  -> append tool_result
  -> continue
  -> model sees tool_result
  -> maybe call next tool
  -> continue
  -> final answer
  -> terminal
```

所以你说的“while(true)，让 agent 完成任务或者错误才退出”是对的。

工程复杂度在于：这个 while 不是裸 while，而是有一套严格状态、预算、恢复和输出协议的 while。

### 2.4 Claude Code 的退出条件

Claude Code loop 不是一直跑。

退出条件包括：

```text
completed:
  模型没有再请求工具，stop hooks 通过。

aborted_streaming:
  用户中断或 abort signal。

prompt_too_long:
  prompt-too-long 经过 collapse / reactive compact 仍无法恢复。

image_error:
  图片输入或媒体错误不可恢复。

max turns / token budget:
  达到轮次或任务预算。

stop hook preventContinuation:
  hook 明确阻止继续。

unrecoverable API error:
  retry / fallback / compact 后仍失败。
```

成熟点在于：

```text
退出不是随便 break。
每个 terminal reason 都能解释为什么停。
```

### 2.5 Claude Code 的恢复策略

Claude Code 在 loop 内处理恢复，而不是丢给外部。

主要策略：

```text
prompt-too-long:
  context collapse drain -> reactive compact -> surface error

max_output_tokens:
  output token 升级 -> recovery message 续写 -> 最多 N 次

529 / 429:
  withRetry 退避 -> fallback model -> persistent retry / fail

streaming fallback:
  tombstone 废弃消息 -> discard 工具结果 -> 换模型或重试

tool interruption:
  synthetic tool_result error，保持 API 消息结构完整
```

这说明 loop 要负责：

```text
错误分类
恢复尝试
恢复后 continue
恢复失败 terminal
```

### 2.6 Claude Code 的工具循环

工具不是 loop 外部随便跑。

工具循环规则：

```text
1. 模型产生 tool_use。
2. loop 收集 tool_use。
3. 工具执行前走 canUseTool / permission。
4. 按 concurrency_safe 分批。
5. 只读可并发，写入/危险串行。
6. 工具结果必须变成 tool_result。
7. tool_result 回填 messages。
8. continue 到下一轮模型调用。
```

如果工具执行失败或被中断，也必须产生合成 `tool_result`，否则模型 API 的 tool_use/tool_result 配对会坏。

### 2.7 Claude Code 的上下文压缩循环

压缩不是后台闲活，而是 while 内的运行阶段。

顺序是：

```text
轻量裁剪
microcompact
context collapse
autocompact
reactive compact
```

并且有两个约束：

```text
越便宜越先做。
压缩后必须维护 API 消息不变量。
```

这对我们非常重要：如果未来工具/worker/agent 结果进入上下文，压缩不能只按 token 裁剪。

---

## 3. Codex 的 Loop 策略

Codex 的公开源码和本机运行痕迹显示，它的重点不是把 loop 细节都塞进一个文档，而是把 loop 轨迹变成持久化 rollout。

### 3.1 Codex 的核心特点

从本机 `.codex/sessions/**/rollout-*.jsonl` 观察：

```text
每行都有：
  timestamp
  type
  payload
```

类型包括：

```text
session_meta
turn_context
event_msg
response_item
```

`response_item` 包括：

```text
message
reasoning
function_call
function_call_output
```

`event_msg` 包括：

```text
task_started
user_message
agent_message
token_count
exec_command_end
```

这说明 Codex loop 的核心策略是：

```text
loop 每推进一步，都留下可 replay 的事件。
```

### 3.2 Codex 的持久化 loop

Codex 更接近：

```python
while True:
    append(turn_context)

    item = call_model_or_receive_item()
    append(response_item)

    if item.function_call:
        result = execute_function(item)
        append(event_msg(exec_end))
        append(response_item(function_call_output))
        continue

    if item.message_final:
        append(event_msg(agent_message))
        checkpoint_or_index()
        break

    if interrupted_or_error:
        append(event_msg(error))
        checkpoint_or_index()
        break
```

Codex 的重点：

```text
不是只保存 checkpoint。
而是保存 rollout，让整个 loop 可以被 inspect / replay / resume。
```

### 3.3 Codex 的三层持久化

从本机观察：

```text
rollout JSONL:
  事实轨迹。

state_5.sqlite:
  threads
  thread_goals
  thread_spawn_edges
  thread_dynamic_tools
  agent_jobs
  agent_job_items
  jobs

session_index.jsonl / history.jsonl:
  快速入口和用户历史索引。
```

这说明 Codex 的 loop 策略不是简单“存状态”：

```text
EventLog 负责重放。
StateDB 负责索引和查询。
SessionIndex 负责快速入口。
```

对我们来说：

```text
RuntimeEventLog 是必须的。
RuntimeCheckpoint 只是加速恢复，不是唯一真相。
RuntimeStateIndex 是列表/查询/恢复入口。
```

### 3.4 Codex 的 turn_context

本机 rollout 里的 `turn_context` 包含：

```text
turn_id
cwd
current_date
timezone
approval_policy
sandbox_policy
permission_profile
file_system_sandbox_policy
```

这说明 loop 每轮要快照环境：

```text
当前目录
日期时区
审批策略
沙盒策略
权限 profile
```

这些不是执行器临时读配置，而是当前 loop 运行的一部分。

### 3.5 Codex 的 dynamic tools / spawned threads

本机 SQLite 有：

```text
thread_dynamic_tools
thread_spawn_edges
agent_jobs
agent_job_items
```

这说明 Codex loop 支持：

```text
动态工具集合
子线程/子 agent 关系
批量 agent job
item-level 状态
```

这些都不是外部系统自己跑，而是进入 thread / rollout / state index。

---

## 4. Claude Code 与 Codex 的差异

### 4.1 Claude Code 更强调“在线循环策略”

Claude Code 的文档和源码重点是：

```text
while true 怎么跑。
怎么流式 yield。
怎么执行工具。
怎么压缩。
怎么恢复错误。
怎么处理 stop hooks。
怎么处理 fallback。
```

它更像：

```text
online control loop
```

### 4.2 Codex 更强调“持久化循环轨迹”

Codex 的运行痕迹重点是：

```text
session_meta
turn_context
event_msg
response_item
state index
thread goals
spawn edges
dynamic tools
agent jobs
```

它更像：

```text
event-sourced persistent loop
```

### 4.3 两者共同点

共同点才是我们要学的本质：

```text
1. 都是统一 loop。
2. 都不是一次请求一次回答。
3. 都让模型输出动作，再把动作结果喂回模型。
4. 都把工具/函数调用视为 loop 内阶段。
5. 都有上下文治理。
6. 都有权限/沙盒/审批约束。
7. 都有流式事件。
8. 都需要退出条件。
9. 都需要错误恢复。
10. 都需要某种历史/状态持久化。
```

---

## 5. 对洪荒时代的直接结论

### 5.1 我们要做的不是普通 workflow runner

普通 workflow runner 是：

```text
step A -> step B -> step C -> done
```

Agent loop 是：

```text
while true:
  model decides next action
  runtime validates action
  runtime executes action
  runtime returns observation
  model continues
  until terminal
```

所以我们的 `TaskRunLoop` 不能只是“执行预设步骤”。

它必须支持：

```text
模型驱动下一步动作
工具结果回填
循环继续
压缩后继续
审批等待后继续
错误恢复后继续
预算耗尽后退出
```

### 5.2 编排系统要管整个 loop

这不是“谁管谁”的抽象争论，而是 loop 的自然结果。

因为 while 内要串起来：

```text
任务目标
上下文
投影
模型调用
工具调用
权限
压缩
输出
写回
恢复
```

所以 loop owner 必然要管所有阶段的调用顺序。

正确说法：

```text
OrchestrationSystem.TaskRunLoop 管整个当前运行循环。
其他系统提供专业函数。
loop 决定什么时候调用它们，以及调用后的结果如何进入下一轮。
```

### 5.3 TaskRunLoop 的伪代码

洪荒时代应该落成类似：

```python
async def run_task(task_run_id):
    state = load_or_create_loop_state(task_run_id)

    while True:
        append_event("loop_iteration_started", state)

        if state.should_stop():
            append_event("task_run_completed", state)
            return state.terminal

        if state.needs_approval:
            write_checkpoint(state)
            append_event("waiting_approval", state)
            return "waiting_approval"

        context_snapshot = context_manager.prepare(state)

        if context_snapshot.needs_compaction:
            state = compact_context(state, context_snapshot)
            append_event("context_compacted", state)
            write_checkpoint(state)
            continue

        projection = soul_system.project(state.task, context_snapshot)
        directive = orchestration_policy.next_directive(state, projection)

        gate = operation_gate.check(directive, state.turn_context)
        append_event("operation_gate_checked", gate)

        if gate.requires_approval:
            state.needs_approval = True
            state.approval_state = gate.approval_state
            write_checkpoint(state)
            continue

        if not gate.allowed:
            state = handle_denial(state, gate)
            write_checkpoint(state)
            return "blocked"

        result = await executor_registry.dispatch(directive)
        append_event("executor_finished", result)

        context_manager.record_result(state, result)

        if result.needs_model_followup:
            state.transition = "next_turn"
            write_checkpoint(state)
            continue

        output = output_boundary.apply(result)
        commit = commit_gate.check(output)
        append_event("commit_gate_checked", commit)
        write_checkpoint(state)

        if commit.completed:
            return "completed"

        state.transition = "continue_after_commit"
```

这才是我们要做的 loop。

---

## 6. 当前我们缺什么

按 loop 本质重新看，我们缺的不是“更多系统”，而是 while 内必须有的状态和阶段。

### 6.1 缺 LoopState

需要：

```text
messages / model_visible_items
turn_count
transition
current_step
pending_tool_calls
pending_approvals
token_pressure
compaction_state
result_refs
commit_state
terminal_reason
```

### 6.2 缺 LoopEvent

需要：

```text
loop_iteration_started
context_prepared
model_called
model_item_received
tool_call_requested
operation_gate_checked
tool_result_received
context_compacted
approval_waiting
output_finalized
commit_checked
checkpoint_written
loop_terminal
```

### 6.3 缺 Tool/Worker/Agent Observation 回填机制

工具结果不是“完成后给用户看”。

它必须先变成 observation，回填给模型：

```text
tool_use -> tool_result -> next model call
worker_request -> worker_result -> next model call
agent_spawn -> agent_result -> parent loop observation
```

### 6.4 缺 terminal reason 体系

必须明确：

```text
completed
waiting_approval
blocked_by_gate
budget_exhausted
max_turns
context_unrecoverable
executor_failed
user_aborted
commit_failed
```

### 6.5 缺恢复 continue 点

需要：

```text
continue_after_tool_result
continue_after_worker_result
continue_after_compaction
continue_after_approval
continue_after_fallback
continue_after_output_recovery
```

没有 transition，while true 就会变成黑盒。

---

## 7. 最终设计口径

现在必须把口径说透：

```text
是的，loop 就是 while(true)。
是的，编排层要管整个 loop。
是的，其他系统都要被 loop 调用。
是的，loop 要一直跑到任务完成、等待、错误、预算耗尽或用户中断。
```

但成熟 loop 不是裸 while。

成熟 loop 是：

```text
while(true)
  + explicit LoopState
  + AsyncGenerator/event stream
  + OperationGate preflight
  + ContextManager
  + compaction strategy
  + tool/worker/agent observation回填
  + retry/fallback/recovery
  + EventLog
  + Checkpoint
  + terminal reason
```

洪荒时代下一步要做的，就是把当前 model-only lane 改造成这个最小 loop。

---

## 8. 第一阶段落地定义

第一阶段只要求 model-only，但必须按 loop 形态做。

```text
QueryRuntime
  -> TaskRunLoop.run()
     while True:
       prepare context
       build projection
       issue model directive
       operation gate check
       stream model result
       output boundary
       commit gate
       checkpoint
       terminal completed
```

即使第一阶段没有工具，也要有：

```text
LoopState
LoopEvent
transition
terminal_reason
checkpoint
event log
```

这样第二阶段加 tool 时，只是多一个：

```text
tool_use -> tool_result -> continue
```

而不是再造一套工具链。

