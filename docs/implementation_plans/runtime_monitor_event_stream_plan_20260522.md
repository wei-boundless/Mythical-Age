# Runtime Monitor Event Stream Plan

## Problem

The current runtime monitor is not truly real time. The backend exposes monitor snapshots, and the frontend refreshes them on a timer. This causes three practical failures:

- A running task can look frozen until the next poll finishes.
- The monitor only becomes visible after slower workspace initialization requests complete.
- Stale detection depends on the latest persisted activity timestamp, so a task that is still executing but not writing events can look inactive.

## Target Design

Use an event-driven monitor channel with snapshot reconciliation.

- Backend `RuntimeEventLog.append()` remains the canonical event write point.
- Each appended runtime event is also published to an in-memory subscriber bus.
- Backend exposes an SSE endpoint for runtime monitor events.
- SSE sends an initial global monitor snapshot, then pushes runtime events with a refreshed global monitor snapshot.
- Frontend subscribes with `EventSource` as soon as the workspace runtime initializes.
- Frontend applies SSE snapshots immediately and refreshes selected task details when the selected task receives an event.
- Polling remains only as a fallback and periodic reconciliation path, not the main monitor mechanism.

## File-Level Execution

1. Add runtime event subscription support to `backend/runtime/shared/event_log.py`.
2. Add an SSE monitor endpoint to `backend/api/orchestration_runtime_loop.py`.
3. Make event publication thread-safe, because task graph stages can append events from background worker threads.
4. Add frontend API helper and types for the monitor event stream in `frontend/src/lib/api.ts`.
5. Update workspace runtime store lifecycle in `frontend/src/lib/store/runtime.ts`.
6. Expose stream connection state in `frontend/src/lib/store/types.ts` and default state.
7. Surface low-noise event stream status in `TaskMonitorDock`.
8. Render elapsed/stale time from local wall-clock ticks so duration display does not depend on backend polling.
9. Add regression coverage for event log subscribers, including cross-thread append delivery.
10. Build and verify the frontend against the real local backend.

## Completion Criteria

- Opening the workbench starts the SSE monitor stream before slow workspace initialization finishes.
- Runtime events update the right monitor list without waiting for the timer.
- Clicking a right-side task opens the center detail view, and selected task detail refreshes on matching runtime events.
- If SSE disconnects, the existing snapshot refresh loop still keeps the monitor usable.
- `npm run build` passes.
- A backend regression test proves appended runtime events are delivered to subscribers.

## Non-Goals

- Do not remove the snapshot endpoint; it is still needed for initial state, reconnect, and correctness repair.
- Do not fake real-time behavior with a shorter polling interval.
- Do not move monitoring into the task loop UI layer; this belongs to the runtime monitor/health-facing infrastructure.
