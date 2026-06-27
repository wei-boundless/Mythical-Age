# Interruptible Runtime Control Plan

## 1. Purpose

本计划修复“停止按钮只断前端流，但没有完整处理任务进度、子 agent、记忆连续性和续跑”的结构问题。

目标不是把停止按钮改成更快的 `abort()`，而是建立成熟 agent runtime 的中断控制契约：

```text
user stop intent
-> client transport abort
-> runtime interruption request
-> active work tree control
-> progress checkpoint
-> continuation handle
-> resumable projection
```

默认用户点击聊天输入区的“停止本轮生成”时，应表示“立即断开当前输出并保留可继续状态”。真正不可恢复的终止应作为单独的“终止任务”控制，不应与普通停止输出混在同一个按钮里。

## 2. Current Breakage Or Design Gap

### 2.1 已经连接的部分

- `frontend/src/components/chat/ChatInput.tsx` 会在 streaming 时把主按钮切换为 `stop_stream`，点击后调用 `onStop`。
- `frontend/src/components/chat/ChatPanel.tsx` 把 `onStop` 接到 `stopCurrentStream`。
- `frontend/src/lib/store/runtime.ts` 的 `stopCurrentStream()` 会释放本地 stream boundary，调用 AbortController，并在绑定 TaskRun 时调用后端 stop 接口。
- `frontend/src/lib/api/chatStream.ts` 的 WebSocket consumer 支持 `AbortSignal`，abort 时会关闭 socket 并抛出 `AbortError`。
- 后端已有 `TaskRunControlGateway`，负责 pause/resume/stop/approve 的用户控制入口。
- 后端已有 `AgentRunSupervisor.cancel_stream_run()` 和 `cancel_task_run()`，可以按 stream 或 task 取消运行 cell。
- 后端已有 `ActiveTurnRegistry`，用于维护 session 当前 turn、stream_run、task_run 的绑定。
- 后端已有 `harness.continuation`，可以选择 task continuation 或 interrupted ordinary turn continuation。

### 2.2 关键缺口

1. 前端传输断流曾经只覆盖 WebSocket 阶段。后续物理测试进一步确认：如果停止动作直接 abort `/chat/runs` 创建请求，用户在 run id 返回前点击停止时会丢失 `stream_run_id`，后端只能看到 `missing_terminal_event`，无法收到明确的 `user_stop_from_chat_stream` 控制事实。
2. `stopCurrentStream()` 当前把绑定 TaskRun 的聊天停止映射为后端 hard stop，而不是默认可恢复中断。
3. 后端没有公开的 `stream_run_id` 级中断 API。普通单轮 chat run 只能断前端连接，无法通过控制面明确请求 runtime 进入可恢复中断。
4. 子 agent 是独立 `subagent_task`，但聊天停止没有统一的 work tree cascade policy，容易出现父任务已停、子 agent 仍在跑或进度不可见。
5. 任务进度、runtime control signal、continuation handle、memory/context commit ledger 没有被前端停止按钮统一作为一个事务看待。

## 3. Source Basis

### 3.1 Local Source Evidence

- Frontend button path:
  - `frontend/src/components/chat/ChatInput.tsx`
  - `frontend/src/components/chat/ChatPanel.tsx`
  - `frontend/src/lib/store/runtime.ts`
- Stream transport:
  - `frontend/src/lib/api/client.ts`
  - `frontend/src/lib/api/chatStream.ts`
  - `backend/api/chat_live.py`
- Chat run creation and projection bridge:
  - `backend/api/chat.py`
- Active turn ownership:
  - `backend/harness/runtime/active_turn.py`
- Task control gateway:
  - `backend/harness/runtime/task_run_control_gateway.py`
  - `backend/harness/loop/task_run_execution_control.py`
  - `backend/harness/loop/task_executor.py`
- Runtime cell cancellation:
  - `backend/harness/runtime/agent_run_supervisor.py`
  - `backend/harness/runtime/agent_runtime_cell.py`
  - `backend/harness/runtime/agent_worker_backend.py`
- Subagent lifecycle:
  - `backend/harness/agent_control/controller.py`
  - `backend/runtime/tool_runtime/tool_control_plane.py`
  - `backend/harness/runtime/tool_plan.py`
- Continuation and memory continuity:
  - `backend/harness/continuation/selector.py`
  - `backend/harness/continuation/recovery_boundary.py`
  - `backend/harness/continuation/recovery_packet.py`
  - `backend/runtime/context_management/context_commit_record.py`
  - `backend/runtime/context_management/provider_visible_context_ledger.py`
  - `backend/harness/loop/turn_to_task_context_handoff.py`

### 3.2 Local Design Principles

- `RuntimeRun` 只记录 transport/chat stream，不应自己决定任务语义。
- `TaskRun` 记录任务生命周期，但不应覆盖当前 turn 归属。
- `ActiveTurn` 是当前 turn 权威，控制命令必须校验 turn/task/session 绑定。
- Runtime control signal 必须由 gateway 发布、执行器观察、执行器消费，不能由 UI 直接改状态。
- Continuation 必须来自真实 checkpoint 和 diagnostics，不能通过前端猜测“上一条还没完成”来恢复。
- 上下文连续性是续跑权威来源；task/executor 状态只提供“任务是否断开、是否可原地调度”的运行事实，不能替 agent 做“是否继续任务”的语义裁决。
- 所有意外情况都必须流出为 runtime signal：断流、任务断开、子 agent 中断、context stale、checkpoint 不完整、executor 不可达，都应进入 agent 可见的实时信号/下一轮上下文，而不是只写日志、只给前端 toast，或只改内部状态。
- Output commit 和 memory/context commit 必须与中断区分。中断不能伪造最终回答，也不能丢掉已记录进度。

## 4. Recommended Design Direction

采用“双控制面”但单一语义入口：

```text
Frontend Runtime Store
  owns immediate transport abort and visible state release

Backend Runtime Interruption Gateway
  owns runtime interrupt semantics, work tree policy, checkpoint, continuation
```

前端允许立刻断流，但不能把本地 abort 当成后端任务停止。后端允许中断 runtime，但不能靠 WebSocket 断开推断用户意图。两者通过同一个 `interrupt_active_work` 契约连接。

## 5. Target Authority Chain

| Layer | Owner | Responsibility | Forbidden |
| --- | --- | --- | --- |
| observe | `ChatInput` / `ChatPanel` | 捕获用户点击停止 | 不决定 hard stop 还是 resumable interrupt |
| normalize | `frontend/src/lib/store/runtime.ts` | 读取 current session、active stream binding、active turn snapshot | 不伪造 task progress |
| transport | `frontend/src/lib/api/chatStream.ts` / `client.ts` | 立即释放可见输出流并 abort WebSocket/replay/live consume loop；保留 run creation 响应用于取得控制句柄 | 不丢弃 `stream_run_id`，不声明后端任务已停 |
| decide | backend interruption gateway | 根据 active turn/task/run 决定 interrupt target | 不绕过 ActiveTurn 校验 |
| authorize | `ActiveTurnRegistry` + task control gateway | 校验 expected turn/task/session | 不接受 stale stream/task 控制 |
| execute | `TaskRunControlGateway` + `AgentRunSupervisor` | 暂停/中断 root task、subagent task、stream cell | 不直接删除进度 |
| record | event log + runtime signal + continuation + context ledger | 写 checkpoint、control signal、agent-facing runtime signal、continuation handle | 不把 interrupted 当 completed，不吞掉异常事实 |
| present | stream projection + frontend reducer | 显示已中断、可继续、子 agent 状态 | 不合成最终 assistant answer |

## 6. Fixed Execution Flow

### 6.1 Default Chat Stop: resumable interrupt

1. User clicks stop.
2. Frontend immediately releases visible stream state and aborts local live consumption:
   - active WebSocket stream
   - pending reconnect delay or replay loop
   - replay consumption after the run id is known
   - `/chat/runs` creation response must not be discarded by the stop-stream abort path, because the client needs its `stream_run_id` to send the authoritative interruption request.
3. Frontend marks stream connection as `stopped` or new `interrupted`, but does not mark task terminal.
4. Frontend sends `POST /chat/runs/{stream_run_id}/interrupt` when `stream_run_id` is known. If the user clicked stop before run creation returned, the store records an epoch-bound pending interruption and sends this request immediately after the run id arrives.
5. Backend validates:
   - stream_run belongs to session
   - active turn matches expected turn if provided
   - task_run matches active turn if task-bound
6. Backend chooses target:
   - task-bound turn: publish task interrupt/pause signal through `TaskRunControlGateway`.
   - ordinary single-turn stream: cancel stream run cell and record interrupted turn continuation.
   - subagent tree: apply cascade policy to child task runs.
7. Backend writes:
   - runtime control signal
   - agent-facing runtime signal for every unexpected condition
   - task or turn interruption event
   - continuation handle
   - progress checkpoint / latest event offset
   - task disconnection facts for the next agent turn
8. Frontend refreshes session continuation and run monitor.
9. UI shows “已中断，可继续” with progress and child agent state.
10. User continue action keeps the context chain intact. The next agent turn receives the task disconnection facts and decides, under contract, whether to resume the original task, replan, explain status, or request more evidence.

### 6.2 Explicit Hard Terminate

Hard terminate remains available from run monitor/task controls. It may call current stop behavior, but it must be labeled and projected as terminal/read-only.

## 7. Data Model Changes

### 7.1 New Control Payload

```json
{
  "mode": "interrupt_for_resume",
  "reason": "user_stop_from_chat",
  "expected_active_turn_id": "",
  "expected_task_run_id": "",
  "cascade_subagents": "interrupt_for_resume"
}
```

Allowed `mode`:

- `interrupt_for_resume`: default chat stop. Preserve progress and continuation.
- `hard_stop`: explicit terminal stop. Not used by the chat input primary stop button.

Allowed `cascade_subagents`:

- `interrupt_for_resume`: pause or checkpoint children when possible.
- `hard_stop`: terminate children for explicit hard stop only.
- `leave_running`: only allowed for diagnostic/admin use, not default UI.

### 7.2 New Backend Response

```json
{
  "ok": true,
  "accepted": true,
  "stream_run_id": "strun:...",
  "session_id": "session:...",
  "mode": "interrupt_for_resume",
  "active_turn": {},
  "task_control": {},
  "stream_control": {},
  "subagent_controls": [],
  "continuation": {},
  "checkpoint": {},
  "authority": "api.chat.runtime_interruption"
}
```

## 8. Module Plan

### 8.1 Frontend Transport And Store

Files:

- `frontend/src/lib/api/client.ts`
- `frontend/src/lib/api/chatStream.ts`
- `frontend/src/lib/api/orchestration.ts`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/store/types.ts`
- `frontend/src/components/chat/ChatInput.tsx`

Actions:

- Keep the merged AbortSignal fix so API creation and WebSocket consumption share the same abort path.
- Replace chat primary stop semantics from “hard stop bound task” to “interrupt active work for resume”.
- Add API client for chat run interruption.
- Preserve current hard-stop task control as a distinct monitor action.
- Add visible state for resumable interruption and continuation handle.

### 8.2 Backend Chat Runtime Control

Files:

- `backend/api/chat.py`
- `backend/harness/runtime/active_turn.py`
- `backend/harness/runtime/single_agent_host.py`
- `backend/harness/runtime/task_run_control_gateway.py`
- `backend/harness/runtime/session_timeline.py`

Actions:

- Add `POST /chat/runs/{stream_run_id}/interrupt`.
- Resolve stream run to session and active turn.
- For bound task, call resumable pause/interruption path instead of hard stop.
- For pure stream run, call `cancel_runtime_run_cells` and record interrupted turn continuation.
- Return continuation selection in the response.

### 8.3 Task And Subagent Work Tree

Files:

- `backend/harness/agent_control/controller.py`
- `backend/harness/runtime/task_run_control_gateway.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/runtime/run_monitor/projector.py`

Actions:

- Add descendant discovery for subagent task runs owned by the root task.
- Apply cascade policy with explicit results per child.
- Ensure child controls produce runtime control signals, not silent status edits.
- Project child statuses back into monitor and chat timeline.

### 8.4 Continuation And Memory Continuity

Files:

- `backend/harness/continuation/selector.py`
- `backend/harness/continuation/recovery_boundary.py`
- `backend/harness/continuation/recovery_packet.py`
- `backend/runtime/context_management/context_commit_record.py`
- `backend/runtime/context_management/provider_visible_context_ledger.py`
- `backend/harness/runtime/dynamic_context/manager.py`

Actions:

- Ensure user interrupt creates a continuation handle for ordinary turns and task runs.
- Ensure continuation contains checkpoint/event cursor, active turn/task refs, latest visible progress, memory/context refs, and subagent summary.
- Expose two separate facts:
  - `context_resume_available`: whether the context/recovery package is fresh enough for continuity.
  - `same_run_executable`: whether the old task executor can be resumed in place.
- The agent-facing contract must say that task disconnection facts are observations, not semantic decisions; the agent chooses the next action within permissions.
- Add an agent-facing runtime signal stream for interruption anomalies:
  - root stream cancelled
  - root task pause rejected
  - subagent cascade rejected
  - context recovery package missing/stale
  - runtime cell unavailable
  - checkpoint event cursor unavailable
- Preserve provider visible context ledger and session context commit record.
- Prevent interrupted runs from writing final assistant output or pretending completion.

## 9. Phase Plan

### Phase 0: Transport Abort Correctness

Goal: make frontend direct断流真实覆盖 visible/live stream without losing the backend control handle.

Completed change:

- `apiRequest()` merges caller abort signal with timeout abort signal.
- `streamChat()` reports `onRunCreated` as soon as the backend returns a run.
- Chat stop records an epoch-bound pending interruption if the user stops before `stream_run_id` is available.
- The live stream consume path remains abortable, but the stop-stream abort path must not discard the `/chat/runs` response before the client can send `/interrupt`.

Completion criteria:

- User stop during `/chat/runs` creation window releases the UI immediately, still obtains `stream_run_id`, and sends `/chat/runs/{stream_run_id}/interrupt`.
- User stop during WebSocket stream closes socket.
- User abort is not wrapped as request timeout.

### Phase 1: Runtime Interruption API

Goal: add backend control endpoint for stream-level interruption.

Inputs:

- `stream_run_id`
- `session_id` from stored run
- expected active turn/task ids from frontend if available

Outputs:

- accepted/rejected control result
- continuation selection
- checkpoint summary

Prohibited:

- Do not infer session from frontend only.
- Do not mark hard terminal for default chat stop.
- Do not emit final answer content.

### Phase 2: Frontend Stop Rebinding

Goal: make chat stop call the new interruption endpoint after local abort.

Inputs:

- current session id
- active chat stream binding
- active turn snapshot

Outputs:

- visible interrupted state
- continuation action state
- refreshed monitor

Prohibited:

- Do not call `stopOrchestrationHarnessTaskRun` from primary chat stop.
- Do not queue the next user message until active turn is either interrupted/resumable or terminal.

### Phase 3: Subagent Cascade

Goal: root task interruption controls child/subagent work in a visible, recoverable way.

Inputs:

- root task_run_id
- child task runs from diagnostics and agent control index
- cascade policy

Outputs:

- child control result list
- aggregated progress/checkpoint
- monitor projection

Prohibited:

- Do not leave child task running silently under a stopped parent.
- Do not hard-stop children for default chat stop.

### Phase 4: Continuation And Memory Integrity

Goal: prove interrupted work can continue with memory and progress intact.

Inputs:

- latest event cursor
- task/turn diagnostics
- context commit record
- provider visible context ledger
- subagent summaries

Outputs:

- continuation handle
- model-visible recovery packet
- resumed runtime packet

Prohibited:

- Do not resume from guessed chat text.
- Do not use stale active turn after expected id mismatch.
- Do not expose raw private execution state as memory.

### Phase 5: Cleanup Old Semantics

Goal: remove old “chat stop equals hard stop task” path.

Actions:

- Keep hard stop only in explicit task/run monitor controls.
- Rename internal frontend action if useful: `stopCurrentStream` -> `interruptCurrentStream`.
- Remove duplicated stopped-state fallbacks once the interruption projection is authoritative.

## 10. File-Level Checklist

| File | Action | Done Condition |
| --- | --- | --- |
| `frontend/src/lib/api/client.ts` | Merge timeout and caller abort signal | External abort reaches fetch without timeout wrapping |
| `frontend/src/lib/api/chatStream.ts` | Surface created run before live consumption | Early stop can still acquire `stream_run_id` and call interrupt |
| `frontend/src/lib/api/orchestration.ts` | Add chat interruption API client or new `chat.ts` API module | Frontend can call stream interrupt endpoint |
| `frontend/src/lib/store/runtime.ts` | Rebind chat stop to interrupt, not hard stop; preserve epoch-bound pending interruption before run id returns | Local visible abort plus backend interrupt request |
| `backend/api/chat.py` | Add interruption endpoint | Stream/task/turn ownership checked |
| `backend/harness/runtime/task_run_control_gateway.py` | Add resumable interrupt facade if pause is not expressive enough | One gateway owns task user control |
| `backend/harness/runtime/single_agent_host.py` | Expose stream interruption helper if needed | Stream cell cancellation records recoverable interruption |
| `backend/harness/agent_control/controller.py` | Add child task cascade helper | Subagent controls are explicit and visible |
| `backend/harness/continuation/selector.py` | Include user-interrupted records | Continue button receives stable handle |
| `backend/harness/runtime/session_timeline.py` | Project interrupted/resumable state | UI does not synthesize state from local abort |

## 11. Validation

Per project rule, validation should prioritize careful code inspection and real runtime execution rather than adding new regression test files.

Required checks:

- Static compile/type check for changed frontend modules.
- Backend import/compile check for changed Python modules.
- Real CLI startup on fixed ports:
  - frontend `http://127.0.0.1:3000`
  - backend `http://127.0.0.1:8003`
- Manual runtime scenario:
  - stop during `/chat/runs` creation window, including delayed run creation response before run id reaches the store
  - stop during ordinary stream
  - stop during task-bound stream
  - stop while subagent task is active
  - continue after interruption
- Inspect event log and monitor:
  - runtime control signal exists
  - continuation handle exists
  - active turn mismatch is rejected
  - no final commit is written for interrupted work

## 12. Prohibited Shortcuts

- Do not treat frontend `abort()` as backend task stop.
- Do not hard-stop resumable work from the chat primary stop button.
- Do not let subagents continue invisibly after parent interruption.
- Do not create continuation from guessed UI state.
- Do not make the frontend fabricate task progress or memory continuity.
- Do not keep old hard-stop chat path as a compatibility fallback after the interruption path is wired.

## 13. Expected Outcome

After implementation:

- Stop is immediate to the user because transport abort is local and synchronous.
- Runtime receives an explicit interruption request instead of inferring from disconnect.
- Task progress remains visible and checkpointed.
- Subagent work is interrupted or checkpointed under an explicit cascade policy.
- Memory/context continuity survives because continuation handles are recorded by backend authority.
- The user can continue from the interruption without replaying stale chat output or losing task state.
