# Turn-Task Binding Runtime Fix Plan

## Problem

TaskRun can carry `turn_id`, and ActiveTurn can be bound to `bound_task_run_id`, but the chat stream bridge currently treats the binding as a late projection concern. The user-visible chat turn can therefore finish or detach before the task bridge attaches, especially if the `turn_completed(task_executor_scheduled)` handoff is missing, filtered, reordered, or malformed.

## Target Architecture

The runtime must treat the task as a child of the originating turn from the moment the TaskRun is created.

```text
TurnRun
-> TaskOriginBinding
-> TaskRun
-> ActiveTurnRegistry
-> ChatTaskBridge
-> Frontend stream/session state
```

`TaskOriginBinding` is the canonical fact. Projection, monitor, queued input, and frontend state consume it; they must not independently infer ownership from terminal text or monitor fallbacks.

## Required Binding Fields

- `session_id`
- `turn_id`
- `turn_run_id`
- `stream_run_id`
- `task_run_id`
- `action_request_ref`
- `source_packet_ref`
- `turn_to_task_context_handoff_ref`
- `origin_kind`
- `authority`

## Implementation Steps

1. Extend the turn-to-task handoff seed with `turn_run_id` and `stream_run_id`.
2. Store `task_origin_binding` in TaskRun diagnostics at creation time.
3. Emit a canonical `task_origin_bound` runtime event on the task event log immediately after the handoff is materialized.
4. Make ActiveTurn binding fail closed for agent-requested chat tasks. A TaskRun must not continue as an independent background task if the originating turn cannot be bound.
5. Move chat bridge creation to the canonical task binding/start event path. `turn_completed(task_executor_scheduled)` remains a semantic turn closeout, not the source of truth for binding.
6. Preserve the existing bridge terminal behavior, but make missing bridge context detectable when an active turn has a live bound task.
7. Reduce frontend dependence on multi-source guessing by allowing `task_origin_bound` to update the stream anchor and active turn snapshot directly.

## Files

- `backend/harness/loop/turn_to_task_context_handoff.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/task_lifecycle.py`
- `backend/api/chat.py`
- `frontend/src/lib/store/events.ts`

## Verification

No new regression test files. Verify by code-path audit and then run the real frontend/backend chain on the fixed ports:

- Backend: `http://127.0.0.1:8003`
- Frontend: `http://127.0.0.1:3000`

Manual runtime check:

1. Send a chat request that starts a TaskRun.
2. Confirm the public stream emits `chat_turn_bound`, `task_origin_bound`, then task bridge events on the same assistant message.
3. Confirm later user input queues with `expected_active_turn_id` and `task_run_id`.
4. Confirm the task terminal closes the same chat turn bridge instead of creating a detached task-only surface.
