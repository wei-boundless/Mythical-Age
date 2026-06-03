# Runtime Monitor Console Rebuild Plan - 2026-06-04

## Problem

The current monitor console has backend signal authority and frontend presentation mixed through a legacy bucket-shaped contract. This caused a visible failure mode: counts were present, but the right-side monitor body could appear empty or stale. Recent fixes made active `turn_run` visible, but the console is still fragile because the UI directly interprets backend runtime buckets and old CSS overrides decide the visible experience.

The target is not another patch to `TaskMonitorDock`. The target is a new monitor console that collects runtime signals once, normalizes them into a stable UI feed, presents current work clearly, and then deletes the old console component/CSS path.

## Current Chain

Backend:

- `backend/api/runtime_monitor.py`
  - Exposes `/api/orchestration/runtime-monitor/live`, `/events`, `/sessions/{session_id}`, and `/task-runs/{task_run_id}`.
  - Authority: API transport only.

- `backend/harness/runtime/monitoring/service.py`
  - Combines `TaskRun`, active `TurnRun`, runtime run registry, and active turn registry.
  - Authority: collection and global/session selection.

- `backend/harness/runtime/monitoring/projector.py`
  - Projects raw runtime records into `runtime_monitor.v1.item`.
  - Authority: backend presentation facts and lifecycle classification.

- `backend/harness/runtime/monitoring/contract.py`
  - Builds bucket envelope and summary counts.
  - Authority: wire contract.

Frontend:

- `frontend/src/lib/runtime-monitor/controller.ts`
  - Polls snapshots, loads detail, navigates sessions/graphs.
  - Authority: client data lifecycle and navigation.

- `frontend/src/lib/runtime-monitor/reducer.ts`
  - Applies snapshots and selected item state.
  - Authority: client state normalization.

- `frontend/src/lib/runtime-monitor/selectors.ts`
  - Interprets backend monitor items for visibility and display.
  - Hidden decision: decides what counts as visible work after the backend already decided visibility.

- `frontend/src/components/layout/TaskMonitorDock.tsx`
  - Renders bucket metrics and task rows.
  - Hidden decision: bucket tab state can hide active work even when summary counts show work exists.

- `frontend/src/app/globals.css`
  - Contains multiple scattered `runtime-monitor-*` and `task-monitor-*` blocks.
  - Hidden decision: old CSS can visually suppress or distort monitor rows.

## Target Authority Chain

```text
Runtime Records
-> MonitorSignalCollector
-> MonitorSignalProjector
-> MonitorConsoleEnvelope
-> RuntimeMonitorStore
-> MonitorConsoleView
-> Workbench Navigation
```

Responsibilities:

- `MonitorSignalCollector`: reads `TaskRun`, `TurnRun`, `RuntimeRun`, active turn, graph runtime, and diagnostics. It only observes and joins records.
- `MonitorSignalProjector`: normalizes every observable unit into a stable `MonitorSignal` with kind, status, priority, display text, navigation target, timestamps, and detail ref.
- `MonitorConsoleEnvelope`: groups signals into `primary`, `attention`, `recent`, and `counts`. Buckets can remain internally but must not drive UI visibility.
- `RuntimeMonitorStore`: owns polling/SSE and selection. It does not classify runtime meaning.
- `MonitorConsoleView`: renders one current activity stream. It never hides all active signals because a tab is empty.
- `Workbench Navigation`: handles click-through to session, graph, or detail target.

## New Contract

Add a v2 console payload while preserving v1 API during migration:

```json
{
  "authority": "runtime_monitor.console.v2",
  "revision": "rtmon2:...",
  "updated_at": 0,
  "summary": {
    "active": 0,
    "attention": 0,
    "waiting": 0,
    "failed": 0,
    "recent": 0
  },
  "primary": [],
  "attention": [],
  "recent": [],
  "signals": []
}
```

`MonitorSignal` fields:

- `signal_id`: stable id, normally `taskrun:*`, `turnrun:*`, or `grun:*`.
- `source_kind`: `task_run`, `turn_run`, `runtime_run`, `graph_run`, `diagnostic`.
- `work_kind`: `chat_turn`, `agent_task`, `graph_task`.
- `state`: `active`, `waiting`, `attention`, `completed`, `failed`, `stale`.
- `priority`: numeric sort key; active model/tool work first, stale diagnostics after current work.
- `title`: user-facing title; never an internal id unless no public title exists.
- `line`: current progress sentence.
- `detail`: short secondary text such as elapsed time or last update.
- `navigation_target`: session/graph/detail target.
- `timestamps`: `started_at`, `updated_at`, `last_activity_at`.
- `raw_refs`: optional debug refs, not rendered as primary UI text.

## UI Design

Replace the current right dock with a compact console flow:

1. Header
   - Shows current headline: active count or idle.
   - Refresh icon only; no large descriptive copy.

2. Activity Stream
   - First section is always current work.
   - Rows use one-line title, one progress sentence, right-side elapsed/status.
   - Running rows have a subtle left activity rail and live duration.
   - Waiting/attention rows are visible below running rows, not hidden behind tabs.

3. Compact Counts
   - Counts are secondary, below or beside the stream.
   - Counts are filters only when selected work exists; selecting an empty filter falls back to all active signals.

4. Detail Preview
   - Optional lower area for selected signal detail.
   - It must not replace the activity stream.

Design constraints:

- No stacked cards.
- No large empty body when signals exist.
- No raw internal ids in primary text.
- No hidden tab state that makes the monitor appear dead.
- Monitor must feel like a live activity stream, not a static dashboard.

## Implementation Plan

### Phase 1 - Backend v2 Signal Layer

Add:

- `backend/harness/runtime/monitoring/signals.py`
  - `MonitorSignalCollector`
  - `MonitorSignalProjector`
  - signal sorting and grouping helpers

Update:

- `backend/harness/runtime/monitoring/service.py`
  - Add `list_global_console_monitor(limit=...)`.
  - Use the new collector/projector for `/console`.
  - Keep v1 `list_global_live_monitor` until frontend migration is complete.

- `backend/api/runtime_monitor.py`
  - Add `GET /api/orchestration/runtime-monitor/console`.
  - Add SSE console payload if needed, or reuse snapshot polling first.

Tests:

- Active `turn_run` with no `task_run` appears in `primary`.
- Active `task_run` outranks stale diagnostics.
- Graph waiting items appear in `attention` or `waiting` but do not hide active chat work.
- No signal uses internal ids as title when public title exists.

### Phase 2 - Frontend Store Adapter

Add:

- `frontend/src/lib/runtime-monitor/consoleTypes.ts`
- `frontend/src/lib/runtime-monitor/consoleApi.ts`
- `frontend/src/lib/runtime-monitor/consoleSelectors.ts`

Update:

- `frontend/src/lib/runtime-monitor/controller.ts`
  - Add a console snapshot path with its own state.
  - Do not reuse bucket-derived `displayRuns` as the console source.

- `frontend/src/lib/store/types.ts`
  - Add console monitor state fields.

Tests:

- Console selectors return visible primary signals when active exists.
- Empty selected filter falls back to active signals.
- Stale revision is ignored.

### Phase 3 - New Console Component

Add:

- `frontend/src/components/layout/RuntimeMonitorConsole.tsx`
- `frontend/src/components/layout/runtimeMonitorConsoleFormat.ts`

Replace:

- `WorkbenchShell` should mount `RuntimeMonitorConsole` instead of `TaskMonitorDock`.

UI verification:

- At 1267x910, right panel shows header, current stream, and at least one visible row when backend has any signal.
- At narrow widths, panel collapses without overlapping.
- Long titles truncate cleanly.
- Empty state only appears when `signals.length === 0`.

### Phase 4 - Delete Old Monitor Dock

Delete after v2 is wired and verified:

- `frontend/src/components/layout/TaskMonitorDock.tsx`
- Old `task-monitor-dock*` CSS blocks.
- Old `runtime-monitor-metrics`, `runtime-monitor-list`, `runtime-monitor-row`, and `runtime-monitor-empty` CSS blocks that are not used by health pages.

Do not delete:

- `runtime-monitor-center*` CSS if still used by `HealthSystemView` or orchestration detail pages.
- Backend v1 API immediately. Keep it for trace/detail compatibility until no frontend callers remain.

### Phase 5 - Remove v1 Frontend Dependencies

After the new console is stable:

- Remove `monitorBucketItems` usage from layout code.
- Keep v1 selectors only if health/orchestration pages still require them.
- Remove obsolete tests that only protect bucket-tab behavior.

## Verification Commands

Backend:

```powershell
pytest backend/tests/runtime_monitor_projection_test.py -q
pytest backend/tests/graph_task_runtime_facade_regression.py -q
```

Frontend:

```powershell
cd frontend
npx tsc --noEmit
```

Runtime:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/api/orchestration/runtime-monitor/console?limit=30
```

Browser:

- Start fixed backend `127.0.0.1:8003`.
- Start fixed frontend `127.0.0.1:3000`.
- Open Edge at `http://127.0.0.1:3000/`.
- Confirm `.runtime-monitor-console-row` count is greater than zero when backend summary has active/waiting/attention signals.

## Deletion Criteria

Old code can be deleted only when:

- `WorkbenchShell` no longer imports `TaskMonitorDock`.
- No layout component imports `monitorBucketItems`.
- New console endpoint shows active `TurnRun`, active `TaskRun`, graph waiting, stale diagnostics, and empty state correctly.
- Playwright visual check confirms no blank monitor body when signals exist.
- TypeScript passes.

## Risks

- Health pages may still reuse some `runtime-monitor-*` CSS classes. CSS deletion must be selector-scoped and verified by search.
- Graph runtime detail navigation is mixed into the current controller. The new console should route through existing navigation methods first, then isolate graph auto-advance later.
- SSE can remain on v1 initially; polling v2 every 2.5s is acceptable for the first replacement because monitor display correctness is the priority.
