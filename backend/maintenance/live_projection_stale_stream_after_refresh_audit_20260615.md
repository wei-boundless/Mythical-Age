# Live Projection Stale Stream After Refresh Audit - 2026-06-15

## Problem

用户在 `session-b8ad792d3cbd4ae2` 中看到页面长期只显示 `正在思考`。刷新页面后，任务内容重新出现。

这说明后端并非完全没有产出，而是刷新前的前端实时投影链路没有接到当前任务的正确直播信号；刷新后通过历史 timeline / monitor hydrate 才恢复显示。

## Evidence

### Backend live run pointer was stale before refresh

`GET /api/chat/sessions/session-b8ad792d3cbd4ae2/latest-run?workspace_view=chat&active_only=true`

当时返回：

```text
stream_run_id = strun:5f9fe5fd935c4c12adcf0f7e62002760
status = running
active_turn_id = turn:session-b8ad792d3cbd4ae2:27
runtime_task_run_id = taskrun:turn:session-b8ad792d3cbd4ae2:27:f1802787
active_turn_snapshot.turn_id = turn:session-b8ad792d3cbd4ae2:27
```

但 runtime monitor 同时显示真实运行中的任务是：

```text
task_run_id = taskrun:turn:session-b8ad792d3cbd4ae2:30:e74b7685
latest_interaction_turn_id = turn:session-b8ad792d3cbd4ae2:30
latest_event_type = task_model_action_wait_heartbeat
latest_public_progress_note = 正在通过终端一次性读取完整文件（742 行），读完即刻开始编辑，不再反复读取。
```

Broken edge:

```text
backend latest active chat run
-> frontend live stream subscription
```

The frontend was allowed to subscribe to turn 27 while the actual active task was turn 30.

### Refresh recovered by history hydrate

After refresh:

`latest-run?active_only=true` returned the correct active stream:

```text
stream_run_id = strun:bbcd349f17ab450aad06dcc8224ec97a
status = running
active_turn_id = turn:session-b8ad792d3cbd4ae2:30
runtime_task_run_id = taskrun:turn:session-b8ad792d3cbd4ae2:30:e74b7685
```

The old stream was later terminalized:

```text
stream_run_id = strun:5f9fe5fd935c4c12adcf0f7e62002760
status = stopped
terminal_event = turn_completed
```

This matches the user-visible behavior: refresh did not create the content; it forced the frontend to re-query runtime state and stop relying on the stale stream attachment.

## Code Path

### Backend latest-run selection

`backend/api/chat.py`

- `get_latest_chat_run_for_session(...)` selects reconnectable non-terminal runs from `RuntimeRunRegistry`.
- It sorts by `updated_at` through `registry.list_session_runs(...)`.
- It only excludes active-turn steer runs with `_is_active_turn_steer_run(...)`.
- It does not require the selected run to match the current runtime monitor active task or current active turn binding.

Risk:

```text
old orphaned/still-running stream
-> latest-run candidate
-> frontend reconnects to stale stream
```

### Frontend stream reattach

`frontend/src/lib/store/runtime.ts`

- `reattachChatRunForSession(...)` returns early when `activeStreamSessionIds` already contains the session.
- `startRecoveredChatRunStream(...)` also returns early if the session is already marked active.
- `messagesForSessionDetailsRefresh(...)` preserves current messages while a session is active-streaming.

Risk:

```text
session marked active-streaming on stale stream
-> new correct live stream cannot attach
-> history refresh does not replace visible live state
-> placeholder remains until full page refresh/hydrate
```

## Conclusion

This was not a pure render freeze. It was a live projection routing problem:

```text
real task turn 30 emits progress
but frontend subscription is still attached to old turn 27 stream
so current UI has no visible body/tool activity and only keeps model-wait placeholder
refresh rehydrates timeline/monitor and picks up turn 30
```

## Required Fix Direction

1. Backend `latest-run` must prefer a run whose diagnostics match the authoritative active task from runtime monitor / active task index.
2. If a non-terminal chat run is bridged to a task that is no longer the session's active task, it must not be returned as active.
3. Frontend `reattachChatRunForSession(...)` must detect stream/run mismatch and switch streams instead of returning early just because the session is already active.
4. History hydrate must be allowed to replace a stale placeholder when monitor/timeline proves a newer active task exists.
5. The model-wait placeholder should remain transient: it is valid only while attached to the same current turn/task and must retire when a newer turn/task becomes active.

## Implemented Repair

### Backend active run selection

`backend/api/chat.py`

- `get_latest_chat_run_for_session(..., active_only=true)` now reads the authoritative active task id from `RuntimeMonitorService.get_session_live_monitor(...)`, falling back to `ActiveTurnRegistry.resolve_current(...)`.
- When an active task id exists, `latest-run` only returns a chat run whose diagnostics point to that same `runtime_task_run_id`.
- If no candidate matches the authoritative active task, the endpoint returns `204` instead of returning an unrelated old running stream.

Target property:

```text
active task identity
-> latest active chat run selection
-> frontend stream subscription
```

No old task stream may satisfy this edge merely because it is still reconnectable.

### Frontend stream reattach and switch

`frontend/src/lib/api.ts`

- Added `getLatestChatRunForSession(...)`, which calls backend `latest-run?active_only=true`.
- `ChatRun` now exposes optional `diagnostics` so frontend can compare `stream_run_id`, `runtime_task_run_id`, and active turn identity without guessing from display text.

`frontend/src/lib/store/runtime.ts`

- Added per-session `activeChatStreamBindings`:

```text
session_id -> stream_run_id + task_run_id + turn_id
```

- `reattachChatRunForSession(...)` now checks backend latest-run before trusting local cursor or active stream state.
- If backend says there is no current active run (`204`), the frontend releases the current stream and hydrates history instead of preserving a stale placeholder.
- If backend latest-run differs from the current binding, the frontend aborts the stale stream, clears old cursor, hydrates history, and attaches the authoritative run.
- Added `chatStreamEpochBySession` so old aborted SSE callbacks cannot later clear or overwrite a newer stream's state.

Target property:

```text
current stream event
-> stable stream/turn/task binding
-> reconnect compares with backend authority
-> stale stream is retired before display state is reused
```

### Verification

- `python -m py_compile backend/api/chat.py`
- `npx tsc --noEmit --pretty false`
- `git diff --check -- backend/api/chat.py frontend/src/lib/api.ts frontend/src/lib/store/runtime.ts backend/maintenance/live_projection_stale_stream_after_refresh_audit_20260615.md`
- Restarted fixed services:
  - backend: `http://127.0.0.1:8003`
  - frontend: `http://127.0.0.1:3000`
- Confirmed:
  - `http://127.0.0.1:3000` returns 200.
  - `http://127.0.0.1:8003/api/orchestration/runtime-monitor?limit=5` returns 200.

## Remaining Runtime Check

The next live task should be watched for one specific invariant:

```text
latest-run.runtime_task_run_id == runtime-monitor.active_task_run_id
```

If there is no active task, `latest-run?active_only=true` may legitimately return `204`; frontend must then hydrate history and must not keep a model-wait placeholder from an old stream.
