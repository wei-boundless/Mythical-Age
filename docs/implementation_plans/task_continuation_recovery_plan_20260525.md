# Task Continuation Recovery Plan - 2026-05-25

## 1. Problem

Current task order execution only resumes an existing task when the frontend or caller passes an explicit `task_order_id` / `task_order_run_id`.
When the user says "继续", "接着做", or "恢复任务" without explicit ids, `QueryRuntime` falls through to normal task intent classification and may create a new task order, draft, or chat turn.

The missing system property is not a prompt issue. It is a task ownership and continuation recovery issue:

- explicit task references are handled safely;
- implicit continuation intent is not bound to task order state;
- `TaskRunLoop` already has continuation candidate trace hooks, but task-order recovery does not feed a candidate/decision before the loop starts;
- direct user turns and task-order execution can diverge when users expect the main agent to remember the active task.

Correct end state:

- explicit task ids remain authoritative and fail closed when invalid;
- natural continuation language searches same-session task order state;
- a single high-confidence executable candidate can be resumed automatically;
- ambiguous or completed-only candidates do not silently create unrelated new work;
- every recovery decision is auditable in task order diagnostics and stream events.

## 2. Current System Findings

- `backend/query/runtime.py`
  - `_resolve_or_create_task_order()` first checks `_existing_task_order_creation()`.
  - `_existing_task_order_creation()` only looks at explicit refs from `task_selection` / `task_order_intent`.
  - if refs are present but missing, it raises instead of creating legacy orders.
  - if no refs are present, it delegates to `_create_task_order_for_turn()`.
- `backend/task_system/orders/order_registry.py`
  - can reconstruct `TaskOrderCreation` by order id or run id.
  - currently lacks a session-level candidate API for continuation recovery.
- `backend/runtime/memory/state_index.py`
  - stores `task_orders_by_session`, `task_order_runs_by_session`, `conversation_turns_by_session`.
  - `claim_task_order_run_for_execution()` only allows `created` runs with no bound `task_run_id`.
- `backend/runtime/unit_runtime/loop.py`
  - already builds `context_candidates`, but task-order continuation is currently separate from this entrypoint.
  - the runtime loop should not decide which task order to resume; it should consume the selected task-order binding from `QueryRuntime`.
- `backend/continuation/*`
  - already handles memory/material continuation candidates.
  - this plan adds task-order continuation before loop execution; it does not replace memory continuation.

## 3. Design Decisions

1. Recovery belongs in `QueryRuntime`, before `TaskRunLoop.run_single_agent_stream()`.
2. Explicit refs keep priority over natural-language recovery.
3. Natural recovery is only allowed when the message clearly expresses continuation or resume intent.
4. Automatic resume only targets same-session `TaskOrderRun` with status `created`.
5. Completed/failed/cancelled/running/paused runs are not reused automatically in this first phase.
6. If exactly one executable candidate exists and it is recent enough, auto-resume it.
7. If multiple executable candidates exist, return a task-order draft asking for clarification instead of creating a new task.
8. If no executable candidate exists but the user only says "continue", return a task-order draft asking for the target.
9. If the user gives a clear new objective with continuation wording but no executable candidate, create a new task through the existing classifier.
10. No user-facing `task_goal_type` is added for this layer. This is an internal task-order recovery decision.

## 4. Target Flow

```text
QueryRuntime.astream
-> _resolve_or_create_task_order
   -> explicit task_order_id/run_id lookup
   -> if found: claim and use existing
   -> if explicit ref missing: fail closed
   -> if no explicit ref: task continuation recovery
      -> continuation intent?
      -> session candidate scan
      -> selected / clarify / none
   -> create new chat/draft/order only when recovery did not bind or intentionally allows new work
-> TaskRunLoop.run_single_agent_stream consumes selected TaskOrderCreation
```

## 5. File-Level Checklist

- `backend/task_system/orders/continuation_recovery.py`
  - add a small internal decision module.
  - produce candidate and decision dataclasses.
  - score recent same-session task order runs.
  - expose `recover_task_order_continuation(...)`.
- `backend/task_system/orders/order_registry.py`
  - add a session candidate helper if needed.
- `backend/query/runtime.py`
  - call recovery after explicit ref lookup and before creating a new turn.
  - emit recovery decision event when a decision exists.
  - preserve explicit-ref fail-closed behavior.
- `backend/tests/task_order_entrypoints_regression.py`
  - auto-resumes a single created task order when user says "继续".
  - asks for clarification when multiple executable candidates exist.
  - does not auto-resume completed task runs.
  - keeps missing explicit refs fail-closed.

## 6. Validation

- Run targeted tests:
  - `python -m pytest backend/tests/task_order_entrypoints_regression.py backend/tests/task_order_registry_regression.py backend/tests/task_intent_decision_regression.py -q`
- Run compile checks for touched modules.

## 7. Non-Goals

- Do not add a new user-facing mode.
- Do not add a new `task_goal_type` for continuation recovery.
- Do not resume completed task runs in this phase.
- Do not modify the tool loop or permission model.
- Do not infer continuation across sessions.
