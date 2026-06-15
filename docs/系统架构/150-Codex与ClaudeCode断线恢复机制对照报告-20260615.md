# Codex 与 Claude Code 断线恢复机制对照报告

日期：2026-06-15

## 1. 结论

你的 agent 在断开或 runtime 重启后“像失忆”，不是因为日志完全丢了，而是因为 **可恢复进度没有进入下一轮模型可见上下文，也没有形成可控制的 continuation handle**。

本项目当前事实是：

- `storage/sessions/session-b8ad792d3cbd4ae2.json` 有 31 条公开消息、192 条 API transcript；最后两条用户消息是 turn 30 的“继续推进”和 turn 31 的“继续”，但没有对应 assistant 完成收口。
- turn 30/31 的 runtime 事件和 task_run 文件仍存在。turn 30 事件明确记录 `Write succeeded: fps_game.html`，之后又重新读取文件；turn 31 继续读取 `fps_game.html`，最后出现 `task_run_executor_recovered_after_runtime_start`。
- `runtime_objects/active_turn/session_session-b8ad792d3cbd4ae2.json` 显示 active turn 已是 `terminal`，`terminal_reason=runtime_instance_restarted`，`steerable=false`，但 `session_latest_task_runs/session-b8ad792d3cbd4ae2.json` 仍指向 `taskrun:turn:session-b8ad792d3cbd4ae2:31:38933009`，该 task_run 状态是 `waiting_executor`。

这等于三层权威断开：

```text
公开聊天历史：只有用户说了继续，看不到真实执行进度
runtime 事件日志：知道写了文件、读了哪里、被 runtime restart 打断
active-work 控制层：active turn 已 terminal，不能 steer；latest task_run 又没有被作为可恢复上下文注入
```

成熟 agent 的标准不是靠模型从“继续”两个字里猜任务，而是保存并恢复显式句柄：

```text
session/thread id
-> turn/task_run id
-> persisted transcript/rollout/event log
-> resumable continuation record
-> model-visible recovery packet
-> explicit steer/resume/interrupt control
```

Codex 和 Claude Code 在实现细节上不同，但共同点非常清晰：**恢复必须由持久化会话和显式运行句柄驱动，不由自然语言猜测驱动。**

## 2. 来源边界

### 2.1 本地参考源码

- Codex 源码：`D:\AI应用\openai-codex`
- Claude Code 源码样本：`D:\AI应用\claude-code-nb-main`
- Claude Code 辅助研究资料：`D:\AI应用\Claude-Code-Source-Study-main`

Codex 是 OpenAI Codex 的本地开源仓库，可作为主要参考。

`claude-code-nb-main` 的 README 明确说明它是通过 npm sourcemap 泄露后备份的 Claude Code 源码，不是 Anthropic 官方公开仓库。因此本报告只把它作为工程取证样本使用，并且所有判断都限定为“该源码样本显示的机制”，不把它表述为 Anthropic 官方文档承诺。

### 2.2 本项目取证文件

关键本地证据：

- `D:\AI应用\langchain-agent\storage\sessions\session-b8ad792d3cbd4ae2.json`
- `D:\AI应用\langchain-agent\storage\runtime_state\events\taskrun_turn_session-b8ad792d3cbd4ae2_30_e74b7685.jsonl`
- `D:\AI应用\langchain-agent\storage\runtime_state\events\taskrun_turn_session-b8ad792d3cbd4ae2_31_38933009.jsonl`
- `D:\AI应用\langchain-agent\storage\runtime_state\runtime_objects\active_turn\session_session-b8ad792d3cbd4ae2.json`
- `D:\AI应用\langchain-agent\storage\runtime_state\state_index\session_latest_task_runs\session-b8ad792d3cbd4ae2.json`
- `D:\AI应用\langchain-agent\backend\sessions\__init__.py`
- `D:\AI应用\langchain-agent\backend\runtime\shared\history_assembler.py`
- `D:\AI应用\langchain-agent\backend\harness\entrypoint\runtime_facade.py`
- `D:\AI应用\langchain-agent\backend\harness\entrypoint\current_work_boundary.py`
- `D:\AI应用\langchain-agent\frontend\src\lib\store\runtime.ts`

## 3. Codex 的处理方式

### 3.1 Thread 是可恢复身份，Turn 是执行边界

`D:\AI应用\openai-codex\sdk\typescript\src\codex.ts:9-37` 显示：

- `startThread()` 开始新 conversation。
- `resumeThread(id)` 通过 thread id 恢复 conversation。
- thread 持久化在 `~/.codex/sessions`。

`D:\AI应用\openai-codex\sdk\typescript\src\events.ts:5-40` 显示：

- `thread.started` 返回可用于后续 resume 的 `thread_id`。
- `turn.started` 到 `turn.completed` / `turn.failed` 是一个完整 turn 的执行范围。

这说明 Codex 不把“聊天窗口里最后一句话”当作恢复身份。恢复身份是 thread id，执行边界是 turn。

### 3.2 Resume / read / compact / steer 是显式 API

`D:\AI应用\openai-codex\sdk\python\src\openai_codex\api.py` 显示：

- `thread_resume(thread_id)` 恢复已有 conversation thread：201-233。
- `Thread.turn()` 启动一个 turn 并返回 `TurnHandle`：574-606。
- `Thread.read(include_turns=True)` 可读取 turn history：610-612。
- `Thread.compact()` 是单独的 compaction 行为：617-618。
- `TurnHandle.steer()` 给当前 active turn 发送额外输入：725-731。
- `TurnHandle.interrupt()` 请求中断 active turn：733-735。

`D:\AI应用\openai-codex\sdk\python\src\openai_codex\generated\v2_all.py:6695-6705` 进一步说明 `turn/steer` 有 `expected_turn_id` 前置条件：如果不匹配当前 active turn，请求失败。

这点对本项目非常关键：成熟 agent 不会让“继续”随便接到任何任务上，而是要求 active turn id 或 task_run id 匹配。

### 3.3 持久化历史是 rollout + metadata，不是实时流缓存

Codex 的 `ThreadStoreConfig` 默认是 local store：`D:\AI应用\openai-codex\codex-rs\core\src\config\mod.rs:533-540`，说明 thread 本地通过 rollout JSONL 和 sqlite metadata 持久化。

`D:\AI应用\openai-codex\sdk\python\src\openai_codex\generated\v2_all.py:6530-6535` 还提到 thread list 默认会扫描 JSONL rollouts 修复 thread metadata。

`D:\AI应用\openai-codex\sdk\python\src\openai_codex\generated\v2_all.py:7767-7771` 说明 `turns` 只在 resume、rollback、fork、read(includeTurns=true) 等响应中填充。

`D:\AI应用\openai-codex\sdk\python\src\openai_codex\generated\v2_all.py:7887-7891` 说明存储在 Turn 里的 ThreadItems 是 lossy 的，因为不是所有 agent interactions 都持久化，比如 command executions。

也就是说，Codex 区分了三种东西：

- 用户可恢复的 conversation / turn history。
- rollout 级别的持久化执行记录。
- 实时工具执行细节，它不一定完整进入 thread items。

这比“把所有 SSE 文本拼成聊天历史”成熟得多。

### 3.4 Fork / interrupt / shutdown 前强制 flush rollout

`D:\AI应用\openai-codex\codex-rs\core\src\agent\control.rs:390-418` 显示，fork 前会先 `ensure_rollout_materialized()` 和 `flush_rollout()`，因为 conversation item persistence 是异步队列，fork 快照前必须落盘。

`D:\AI应用\openai-codex\codex-rs\core\src\agent\control.rs:502-657` 显示，`resume_agent_from_rollout()` 会从 recorded rollout file 恢复已有 agent thread，并递归恢复 open descendant threads；恢复单个 agent 时读取 stored thread history，再用 `InitialHistory::Resumed(ResumedHistory { conversation_id, history, rollout_path })` 启动。

`D:\AI应用\openai-codex\codex-rs\core\src\agent\control.rs:749-756` 显示 shutdown live agent 前也会 materialize + flush rollout。

Codex 的核心做法是：**恢复点必须先被物化和 flush，之后再 fork、resume、shutdown 或继续。**

## 4. Claude Code 源码样本的处理方式

### 4.1 Session identity 和 session 文件路径原子绑定

`D:\AI应用\claude-code-nb-main\bootstrap\state.ts` 显示：

- State 保存 `sessionId`、`parentSessionId`：90-102。
- State 有 `sessionPersistenceDisabled`：154-155、1325-1330。
- State 有 `sessionProjectDir`，它表示包含 `<sessionId>.jsonl` 的目录：218-219。
- `switchSession(sessionId, projectDir)` 原子切换 `sessionId` 和 `sessionProjectDir`，并发出 `sessionSwitched`：456-489。
- `projectRoot` 是稳定项目身份，不会被 mid-session worktree 切换改变：45-50、504-512。

这说明 Claude Code 样本里 session 身份、session 文件目录、项目身份是显式状态，不靠 UI 当前目录或最后一条消息猜。

### 4.2 Transcript 是 `<sessionId>.jsonl`，而不是输入框历史

`D:\AI应用\claude-code-nb-main\utils\sessionStorage.ts:202-224` 显示，当前 session 的 transcript 路径是：

```text
projectDir / <sessionId>.jsonl
```

如果是跨项目 resume，会通过 `sessionProjectDir` 保证路径不漂移。

`D:\AI应用\claude-code-nb-main\utils\sessionStorage.ts:247-257` 显示 subagent transcript 也挂在 session 目录下。

`D:\AI应用\claude-code-nb-main\utils\sessionStorage.ts:1128-1260` 显示消息和 metadata 都 append 到 session 文件；message entries 还会去重，并持久化到 remote session ingress。

相比之下，`D:\AI应用\claude-code-nb-main\history.ts:114-119` 和 292-319 显示 `history.jsonl` 是全局 prompt history；`history.ts:443-454` 还会在 interrupt auto-restore 时撤销最近一次 history 写入，避免输入框历史污染真实会话。

结论：Claude Code 样本明确区分：

- prompt history：给上箭头和搜索用。
- transcript/session log：给恢复会话用。
- progress/system/bookkeeping：需要恢复时桥接或过滤。

### 4.3 Resume 会重建模型可见消息，并清理中断污染

`D:\AI应用\claude-code-nb-main\screens\ResumeConversation.tsx:190-224` 显示 resume UI 会调用 `loadConversationForResume()`，拿到 sessionId 后 `switchSession()`，重置 session file pointer，并恢复 cost state。

`D:\AI应用\claude-code-nb-main\screens\ResumeConversation.tsx:254-263` 显示它会恢复 session metadata、worktree，并 `adoptResumedSessionFile()`。

`D:\AI应用\claude-code-nb-main\screens\ResumeConversation.tsx:296-297` 显示恢复后的 `messages` 会作为 `initialMessages` 传入 REPL。

`D:\AI应用\claude-code-nb-main\utils\conversationRecovery.ts:149-248` 显示 resume 反序列化时会：

- 过滤 unresolved tool uses。
- 过滤 orphaned thinking-only assistant messages。
- 过滤只有空白文本的 assistant message。
- 检测 mid-turn interruption。
- 对 interrupted turn 添加 meta continuation message。
- 在最后一条是 user 时插入 API-valid 的 assistant sentinel。

`D:\AI应用\claude-code-nb-main\utils\conversationRecovery.ts:456-586` 显示 `loadConversationForResume()` 会加载最近 session 或指定 session/jsonl，恢复 skill state，反序列化消息，运行 resume hooks，并返回 `turnInterruptionState`、file snapshots、content replacements、context collapse entries、session metadata、worktree state。

这里最值得借鉴的是：**resume 不是把旧 UI 文本显示回来，而是重建下一轮模型实际要看到的消息和运行上下文。**

### 4.4 Remote reconnect 会 requeue session，不让死 worker 挂住会话

`D:\AI应用\claude-code-nb-main\bridge\types.ts:1-2` 显示默认 per-session timeout 是 24 小时。

`D:\AI应用\claude-code-nb-main\bridge\types.ts:162-175` 显示 `reconnectSession(environmentId, sessionId)` 会 force-stop stale worker instances 并 re-queue session；heartbeat 会延长 active work item lease。

`D:\AI应用\claude-code-nb-main\bridge\sessionRunner.ts:287-304` 显示 bridge 启动 child CLI 时带 `--session-id`，并使用 stream-json 输入输出。

`D:\AI应用\claude-code-nb-main\bridge\sessionRunner.ts:368-431` 显示 bridge 解析 child stdout NDJSON，提取 activity，并处理 permission request；interrupt 是 turn-level，由 child 自己处理。

`D:\AI应用\claude-code-nb-main\bridge\sessionRunner.ts:449-470` 显示 session done status 分为 `interrupted`、`completed`、`failed`。

这说明远端/桥接模式下，断线恢复不是“旧进程也许还在”，而是有 lease、heartbeat、stale worker stop、requeue 和 session done status。

### 4.5 Compact 明确保留当前工作和下一步

`D:\AI应用\claude-code-nb-main\services\compact\prompt.ts:61-77` 显示 compact summary 要包含用户请求、文件和代码、错误修复、pending tasks、current work 和 optional next step，并要求 next step 直接对应最近工作和用户明确请求。

`D:\AI应用\claude-code-nb-main\services\compact\prompt.ts:208-263` 显示 partial compact up to prompt 也要求写入 continuing work context。

`D:\AI应用\claude-code-nb-main\services\compact\sessionMemoryCompact.ts:506-565` 显示 resumed session 场景下，如果 session memory 存在但不知道 lastSummarizedMessageId，会走专门的 resumed session case。

`D:\AI应用\claude-code-nb-main\services\compact\compact.ts:1399-1448`、1467-1493、1538-1597 显示 compact 后会恢复最近文件、plan、skill、plan mode、async agent 状态附件。

成熟点是：恢复和压缩的目标不是“尽量短”，而是保证下一轮模型知道 **当前正在做什么、做到了哪里、还有哪些 async work 没取回**。

## 5. 与本项目当前链路的对照

| 维度 | Codex | Claude Code 源码样本 | 本项目当前状态 |
|---|---|---|---|
| 会话身份 | thread id，可 `resumeThread(id)` | sessionId，`switchSession(sessionId, projectDir)` | session_id 存在，但恢复工作不以显式 continuation handle 驱动 |
| 执行边界 | turn started/completed/failed | turn/session done status，interrupted/completed/failed | task_run/active_turn 存在，但 active_turn terminal 后 task_run waiting_executor 没变成模型可见 continuation |
| 持久化载体 | rollout JSONL + sqlite metadata | `<sessionId>.jsonl` + remote events | session JSON + runtime_state events/state_index/work_rollout 分散存在 |
| 继续控制 | `TurnHandle.steer()` + expected turn id | resume/reconnect/requeue + session id | 主要靠前端是否传 `active_turn_input_policy=steer`；terminal active_turn 后断链 |
| 中断恢复 | 从 rollout 读 history，`InitialHistory::Resumed` | resume 反序列化并处理 interrupted turn | runtime 事件有恢复事实，但 `history_assembler` 不注入 |
| 输入历史 | thread items/turns，不等同实时工具细节 | prompt history 与 transcript 分离 | public messages 和 runtime progress 分离，但下一轮主要吃 public messages |
| 压缩/摘要 | compact 独立 API | compact summary 包含 current work / next step | `compressed_context` 可进入 history，但 task_run progress 不稳定进入 |
| 防误接 | expected_turn_id precondition | sessionId/projectDir 原子切换，worker lease | `policy != steer` 时允许 new independent turn |

## 6. 本项目的具体断裂点

### 6.1 模型历史只装载公开 user/assistant 消息

`D:\AI应用\langchain-agent\backend\sessions\__init__.py:160-167` 的 `load_session_for_agent()` 只从 session payload 的 `messages` 中取 `_agent_message()`。

`D:\AI应用\langchain-agent\backend\runtime\shared\history_assembler.py:24-56` 的 `assemble_runtime_history()` 只保留 role 为 `user` / `assistant` 且有 content 的消息。

`D:\AI应用\langchain-agent\backend\harness\entrypoint\runtime_facade.py:348-369` 中，默认 `raw_history = request.history or self.session_manager.load_session_for_agent(request.session_id)`，然后交给 `assemble_runtime_history()`。

结果是：runtime event、task_run progress、work_rollout、file_state、latest waiting task 这些事实不会自然进入下一轮模型上下文。

这就是“日志里有进度，agent 却像不知道”的直接原因。

### 6.2 active_work 只从 active_turn 取，terminal 后没有可控上下文

`D:\AI应用\langchain-agent\backend\harness\entrypoint\runtime_facade.py:1079-1096` 的 `_active_work_context_from_active_turn()` 只在 active_turn 存在、绑定 task_run、task_run 非 terminal、且 runtime kind 是 `single_agent_task` 时返回 active work。

当前 session 的 active_turn 文件显示：

```text
state=terminal
terminal_reason=runtime_instance_restarted
steerable=false
bound_task_run_id=taskrun:turn:session-b8ad792d3cbd4ae2:31:38933009
```

所以 `_active_work_context_from_active_turn()` 不会提供可 steer 的 active work。

### 6.3 latest task 只能变成 read-only recent_work_outcome

`D:\AI应用\langchain-agent\backend\harness\entrypoint\runtime_facade.py:483-487` 中，只有 `active_work_context is None` 时才调用 `_recent_work_outcome_from_latest_task()`。

`D:\AI应用\langchain-agent\backend\harness\entrypoint\runtime_facade.py:1187-1268` 明确写着：这是 read-only result，不要把它当 active work，不要 resume，除非 runtime 暴露 current active-work context。

这意味着，即使 latest task_run 是 `waiting_executor`，也只可能成为“只读说明”，不会自动成为可续跑工作。

### 6.4 current_work_boundary 在非 steer 时放行新独立 turn

`D:\AI应用\langchain-agent\backend\harness\entrypoint\current_work_boundary.py:197-240` 显示：

- active_work 不是 `harness.runtime.active_turn_context` 时，非 steer 策略下允许 `new_independent_turn_allowed`。
- active_work terminal 时，非 steer 策略下也允许 `new_independent_turn_allowed`。
- policy 不是 `steer` 时，即使有 active_work，也返回 `new_independent_turn_allowed`，reason 为 `active_work_control_requires_steer_policy`。

这对普通新请求是合理的，但对“runtime restart 后 waiting_executor 的最新任务”不够。它缺少第三种权威状态：

```text
live active turn -> steer
recoverable task run -> resume
no recoverable current work -> new independent turn
```

现在只有 live steer 和 independent 两档。

### 6.5 前端只把 created/running 当作 steer 条件

`D:\AI应用\langchain-agent\frontend\src\lib\store\runtime.ts:3476-3521` 的 `shouldQueueActiveTurnInput()` 会先要求 `activeTurnSnapshot.state` 是 `running_task`、`waiting_executor`、`waiting_approval`、`waiting_safe_boundary` 之一。

但如果 monitor 存在且 task_run id 匹配，它进一步要求：

```text
executionRuntimeKind == single_agent_task
route.kind != task_graph_run
status in ["created", "running"]
controlState not paused/stopped
```

`waiting_executor` 没在 status 白名单里。也就是说，前端文案可能显示“等待继续”，但发送输入时未必会走 steer/control 链路。

在当前 session 中 active_turn 又是 `terminal`，因此用户发送“继续”更容易被后端当成新独立 turn，而不是续跑 taskrun 31。

## 7. 推荐设计方向

### 7.1 新增唯一权威：ContinuationRecord / RecoveryPacket

建议新增一个明确的恢复记录，名字可以是 `ContinuationRecord` 或 `RecoveryPacket`。它不是 assistant final message，也不是 UI 提示，而是 runtime/state 层的规范对象。

建议字段：

```text
continuation_id
session_id
task_run_id
previous_turn_id
previous_active_turn_id
state: live | waiting_executor | runtime_restarted_waiting_resume | paused | blocked | terminal_read_only
resume_allowed: boolean
resume_strategy: same_run_resume | new_turn_resume | ask_user_confirm | unavailable
user_visible_goal
latest_progress
last_completed_step
next_recommended_step
task_contract_ref
work_rollout_ref
event_cursor
artifact_refs
model_visible_summary
control_version
authority
```

来源优先级：

```text
active_turn_registry
-> state_index.session_latest_task_runs
-> task_run state view
-> task_run event tail / latest step summary
-> work_rollout
-> session public history
```

关键原则：

- runtime 事实可以恢复成 continuation record。
- continuation record 必须进入下一轮 model-visible context。
- 用户继续操作必须带 `continuation_id` 或 `task_run_id`，不能只靠“继续”文本。
- 不能伪造 assistant final message 来填补聊天历史空洞。

### 7.2 把 current work 分成三类

目标边界：

```text
LiveActiveWork
- 有 active_turn_id
- steerable=true
- expected_turn_id 匹配
- 允许 append instruction / interrupt / pause / stop

RecoverableWork
- 没有 live active turn
- 有 latest task_run_id
- task_run waiting_executor / paused / runtime_restarted_waiting_resume
- 有 recovery packet
- 允许显式 resume

RecentWorkOutcome
- terminal / failed / completed / interrupted result
- 只读
- 可解释状态，不可 resume
```

`current_work_boundary` 应该分别裁决：

```text
policy=steer  -> 只控制 LiveActiveWork
policy=resume -> 只恢复 RecoverableWork
policy=auto   -> 不能凭文本自动恢复；如果 UI 没带 handle，则 ask_user 或独立 turn
```

### 7.3 下一轮模型上下文必须注入 RecoveryPacket

`history_assembler` 不应该只装载公开聊天消息。它需要接收一个上游已裁决的 `recovery_packet`，并把它作为结构化上下文注入 runtime packet 或 session_context。

建议模型可见描述不是开发说明，而是 agent 可直接理解的任务状态，例如：

```text
你正在恢复一个被运行时重启打断的本地代码任务。
当前可恢复任务是：修复 fps_game.html 的血包可见性、怪物模型、地图与回血据点。
已确认进度：上一轮已成功写入 fps_game.html，并重新读取了写入后的文件；随后运行时重启，任务停在等待继续调度状态。
你只能在用户明确要求继续该任务，且收到的 continuation_id / task_run_id 匹配时继续执行。
继续时先核对最新文件状态和待验证项，不要从头重复读取已确认信息。
```

这里要注意：这是给 agent 的角色/任务状态 prompt，不是“这是 runtime 节点”的开发说明。

### 7.4 前端需要区分 steer 和 resume

建议替换当前单一 `shouldQueueActiveTurnInput()` 语义：

```text
classifyCurrentWorkInput()
-> live_steer
-> recoverable_resume
-> new_turn
-> ask_confirm
```

发送请求时应显式带：

```text
active_turn_input_policy: "steer" | "resume" | "auto"
expected_active_turn_id
expected_task_run_id
expected_continuation_id
```

当 monitor status 是 `waiting_executor` 且 recovery cause 是 runtime restart 或 executor missing 时，UI 应该进入 `recoverable_resume`，而不是因为 status 不在 `["created", "running"]` 就退回普通新 turn。

### 7.5 持久化恢复检查点，不写假 assistant 收口

turn 30/31 没有 assistant final，这是事实。不能为了让聊天历史好看就写一条“已完成”的 assistant 消息。

正确做法是写结构化 checkpoint：

```text
type: recovery_checkpoint
session_id
task_run_id
interrupted_at_event_offset
reason: runtime_instance_restarted
latest_public_progress_note
resume_allowed
model_visible_summary
authority: harness.runtime.continuation
```

公开聊天层可以投影为状态提示，但不应混入 assistant canonical answer。

## 8. 权威链路设计

目标权威链：

```text
Observe:
  active_turn_registry, state_index, task_run event log, work_rollout, session history

Normalize:
  ContinuationRecordBuilder 统一 live / recoverable / terminal 状态

Retrieve:
  RecoveryPacketContextLoader 读取最近 event tail、progress、artifact refs

Decide:
  CurrentWorkBoundary 根据 policy + expected ids 裁决 steer/resume/new_turn

Authorize:
  ActionPermit 只允许匹配 continuation 的 resume 或 active turn control

Assemble:
  RuntimeStartPacket 注入 model-visible RecoveryPacket

Execute:
  task_executor_controller resume/schedule 明确记录 reason=user_continue

Recover:
  runtime restart 只生成 recovery checkpoint，不伪造完成；可恢复时等待显式 resume

Record:
  recovery_checkpoint、task_run state、public projection 统一从同一 ContinuationRecord 派生

Present:
  前端显示“运行时重启后待续跑”，点击继续发送 expected_continuation_id
```

## 9. 分阶段实施计划

这部分涉及 runtime / state / API contract / frontend 协议，按项目规则，后续真正改代码前需要你确认计划。

### Phase 1：建立 ContinuationRecord 投影

目标：把 active_turn、latest task_run、event tail 统一成一个可检查对象。

涉及文件建议：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/entrypoint/current_work_boundary.py`
- 新增 `backend/harness/continuation/recovery_packet.py` 或同等模块
- `backend/tests/continuation_recovery_packet_test.py`

完成标准：

- 当前 session 样本能生成 `runtime_restarted_waiting_resume`。
- terminal completed task 只能生成 read-only outcome。
- active live turn 仍生成 live active work，不受影响。

### Phase 2：扩展 current_work_boundary 策略

目标：把 live steer 和 recoverable resume 分开。

涉及文件建议：

- `backend/harness/entrypoint/current_work_boundary.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/active_work.py`
- `backend/tests/current_work_boundary_recovery_test.py`

完成标准：

- `policy=steer` 且 expected active turn 不匹配时拒绝。
- `policy=resume` 且 expected task_run / continuation 匹配时允许 resume。
- `policy=auto` 且只有自然语言“继续”但没有 handle 时不静默恢复。

### Phase 3：把 RecoveryPacket 注入模型上下文

目标：下一轮模型能看到真实进度，而不是只看到“继续”。

涉及文件建议：

- `backend/runtime/shared/history_assembler.py`
- `backend/harness/entrypoint/runtime_facade.py`
- runtime prompt/context assembly 相关测试

完成标准：

- turn 31 之后新 turn 的 model history/session_context 包含 user_visible_goal、latest_progress、resume constraints。
- 注入文本是 agent 可执行的任务状态说明，不是开发节点说明。
- 不写假 assistant final。

### Phase 4：前端区分 live steer / recoverable resume

目标：UI 点击继续或发送继续时带上正确 handle。

涉及文件建议：

- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/api.ts`
- 相关 runtime store 测试

完成标准：

- `waiting_executor + runtime_instance_restarted` 显示为可续跑状态。
- 请求带 `expected_task_run_id` / `expected_continuation_id`。
- stale stream / terminal active_turn 不阻止 latest recoverable task hydrate。

### Phase 5：恢复调度与状态投影闭环

目标：用户明确继续后，后端真正 schedule 之前的 waiting_executor task_run。

涉及文件建议：

- `backend/harness/loop/task_executor_controller.py`
- `backend/harness/entrypoint/runtime_facade.py`
- runtime monitor projector / session live view 相关模块

完成标准：

- resume 成功后 task_run 从 `waiting_executor` 进入 running。
- schedule 失败时返回结构化失败，不退化成普通新 turn。
- runtime monitor 和 chat projection 都来自同一 continuation state。

## 10. 验证矩阵

| 场景 | 期望 |
|---|---|
| active_turn terminal + latest_task_run waiting_executor | 生成 RecoverableWork，不生成 LiveActiveWork |
| 用户点击继续且 expected_continuation_id 匹配 | 走 resume，不开新 task_run |
| 用户只输入“继续”但 UI 没带 handle | ask_user 或状态说明，不盲目续跑 |
| active_turn running 且 expected_turn_id 匹配 | 走 steer |
| expected_turn_id 不匹配 | 拒绝控制，不接错任务 |
| latest task completed | 只生成 RecentWorkOutcome |
| runtime event 有进度但 public messages 无 assistant final | 注入 recovery checkpoint，不伪造 assistant final |
| 前端 monitor status waiting_executor | classify 为 recoverable_resume |
| stale stream 还指向旧 run | hydrate latest task_run，不让旧 stream 抢控制 |
| 当前 session 样本回放 | turn 31 后“继续”能恢复到 taskrun 31 的上下文 |

## 11. 禁止捷径

- 禁止只在 prompt 里加“你要记得之前进度”。
- 禁止根据中文“继续”二字直接猜测恢复哪个任务。
- 禁止把 runtime event log 直接整段塞进模型。
- 禁止写一条假的 assistant final 来补历史。
- 禁止同时保留“latest task read-only outcome”和“recoverable task resume”两套互相竞争的恢复判断。
- 禁止让前端显示“等待继续”，但请求仍按普通新 turn 发送。
- 禁止 runtime restart 自动续跑有副作用工具，除非之后补齐 provider request 幂等、工具副作用审计和用户授权边界。

## 12. 最终判断

Codex 的成熟点是 thread/turn/rollout 和 expected turn id：恢复有显式身份，控制有前置条件，fork/interrupt/shutdown 前会 flush rollout。

Claude Code 源码样本的成熟点是 sessionId/jsonl transcript、resume 反序列化、worker reconnect/requeue、prompt history 与 transcript 分离，以及 compact 中保留 current work/next step。

本项目现在已经有 runtime_state、event log、task_run、active_turn、session_live view 这些材料，但缺少把它们收束成唯一恢复权威的 `ContinuationRecord`。所以断开后不是“真的失忆”，而是 **记忆存在于 runtime 侧，模型下一轮看不到；可恢复任务存在于 state_index 侧，current_work_boundary 又不允许把它当 active work 控制**。

后续应优先做结构修复：建立 ContinuationRecord / RecoveryPacket，扩展 current_work_boundary 的 resume 策略，并让前端携带 expected continuation handle。这样才接近 Codex / Claude Code 这类成熟 agent 的断线恢复标准。
