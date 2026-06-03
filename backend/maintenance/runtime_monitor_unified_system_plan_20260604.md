# Runtime Monitor Unified System Plan - 2026-06-04

## Why The Current Design Is Not Acceptable

The monitor subsystem is currently split across two frontend truth sources:

- `RuntimeMonitorController` consumes `/orchestration/runtime-monitor/live` and stores a v1 bucket envelope in global store.
- `RuntimeMonitorConsole` consumes `/orchestration/runtime-monitor/console` directly and stores a signal envelope in component-local state.

This means the right console, detail navigation, graph monitor, and session projection can observe different revisions of runtime state. That is not a mature monitor architecture. A monitor system must have one observation authority, one normalized state contract, one realtime delivery path, and deterministic fallback behavior.

The backend also has a known blind spot: an active turn with `bound_task_run_id` can be hidden when the bound task run is stale, filtered, or not visible. The system should treat the live active turn as the freshest runtime signal, while still linking it to the bound task run for navigation and detail.

## Target Authority Chain

```text
RuntimeEventLog / StateIndex / ActiveTurnRegistry / GraphHarness
-> RuntimeMonitorCollector
-> RuntimeMonitorProjector
-> RuntimeMonitorEnvelope
-> RuntimeMonitorStream
-> Frontend RuntimeMonitorStore
-> Console / Project Lane / Detail / Graph / Chat Projection Views
```

Only the backend collector/projector decides what runtime work exists and what state it is in. The frontend only renders, selects, and navigates from the current monitor envelope.

## Code Review Corrections

The current code creates several implementation hazards that the migration must handle explicitly:

- `frontend/src/lib/store.tsx` starts monitoring through `runtime.startGlobalRuntimeMonitor()` after workspace initialization. The unified controller must preserve this lifecycle entrypoint.
- `RuntimeMonitorController` currently owns graph-run operations as well as global monitor polling. During migration, do not break `taskGraphMonitorBinding`, `taskGraphBoundRunMonitor`, graph auto-advance, continue, stop, and interaction dock flows.
- `RuntimeMonitorEventPayload` currently has no new monitor envelope field. If SSE emits the rebuilt monitor envelope, the TypeScript API contract must be updated in the same phase.
- The current reducer revision parser only recognizes `rtmon:`. The rebuilt monitor should use the normal `rtmon:` revision family, not a versioned prefix.
- The interrupted backend edit that emits both `monitor` and `console` from SSE performs two separate monitor computations. That is a performance and consistency bug. The rebuilt implementation must collect once per event and derive all payload views from the same `now`, item list, and revision.
- `RuntimeMonitorConsole` currently calls `openGlobalRuntimeMonitorTaskRun(signal.task_instance_id || signal.task_run_id || signal.signal_id)`. In the new monitor this must become `openRuntimeMonitorSignal(signal_id)` and must not depend on a separately refreshed v1 item.
- `taskGraphLiveMonitor`, `activeTurnSnapshot`, and `taskGraphBoundRunMonitor` are not all the same kind of state. `activeTurnSnapshot` is session/live-input state; `taskGraphBoundRunMonitor` is graph detail state. They must not be blindly deleted during monitor unification.
- Graph tasks are project-level runtime objects, not ordinary activity rows. They need a dedicated project lane so the UI can show long-running graph progress, node counts, active work orders, and graph controls without burying the project inside a flat activity stream.

## Backend Target Contract

### Clean Replacement Directories

Do not continue building inside the old monitor subsystem as the final structure. Build the replacement in clean folders with normal names, then switch imports and delete the old implementation.

Backend target:

```text
backend/harness/runtime/run_monitor/
  collector.py
  envelope.py
  projector.py
  stream.py
  detail.py
  resource_refs.py
  service.py
```

Frontend target:

```text
frontend/src/lib/run-monitor/
  api.ts
  controller.ts
  reducer.ts
  selectors.ts
  types.ts
  navigation.ts

frontend/src/components/layout/RunMonitorPanel.tsx
frontend/src/components/layout/RunProjectLane.tsx
frontend/src/components/layout/RunActivityLane.tsx
```

The old folders become migration sources only:

```text
backend/harness/runtime/monitoring/
frontend/src/lib/runtime-monitor/
frontend/src/components/layout/RuntimeMonitorConsole.tsx
```

After the new system owns the UI and tests, delete the old folders/files instead of leaving compatibility wrappers. Keep a compatibility endpoint only if another backend caller still needs it, and mark the deletion condition in code.

### One Envelope

Create one monitor envelope for live UI consumption:

```text
authority: runtime_monitor
revision
updated_at
summary
signals
primary
attention
recent
projects
selected/detail refs
```

The current v1 bucket envelope can remain only as an internal compatibility endpoint during migration, not as a second UI truth source.

The backend service must expose one internal method that returns the monitor envelope from a single collection pass:

```text
collect_global_runtime_monitor(now, limit) -> RuntimeMonitorEnvelope
```

The polling endpoint and SSE stream must both use this method. If a temporary v1 endpoint remains, it should be derived from the same collected item list or clearly kept outside the main UI path.

### One Signal Model

Every visible unit of work is normalized to a `RuntimeMonitorSignal`:

- `signal_id`: stable UI identity, usually `task_instance_id` or active `turn_run_id`.
- `task_run_id`: formal task run to open detail for, including `bound_task_run_id` when active turn is bound.
- `source_kind`: `task_run`, `turn_run`, `graph_run`, `diagnostic`.
- `work_kind`: `chat_turn`, `agent_task`, `graph_task`.
- `state`: `active`, `waiting`, `attention`, `stale`, `failed`, `completed`.
- `priority`: deterministic ordering priority.
- `timestamps`: `started_at`, `updated_at`, `last_activity_at`, `elapsed_seconds`.
- `navigation_target`: complete frontend route target.
- `detail_ref`: backend detail lookup target.
- `graph_ref`: graph detail lookup target when `work_kind == graph_task`.
- `raw_refs`: diagnostic identifiers only.

Graph task signals must also be grouped into `projects`. This is a grouping over the same signal identity, not a second data source.

`detail_ref` must be explicit enough for frontend routing:

```text
detail_ref.kind: task_run | turn_run | graph_run | resource | none
detail_ref.task_run_id
detail_ref.turn_run_id
detail_ref.graph_run_id
detail_ref.graph_harness_config_id
detail_ref.resource_ref
```

### Active Turn Rule

Active turn is authoritative for liveness:

- If an active turn has no bound task run, expose it as a live turn signal.
- If it has `bound_task_run_id`, expose it as a live turn signal whose `task_run_id` points to the bound task run and whose `signal_id` remains the active `turn_run_id`.
- Suppress the active turn only when the visible task item already represents the same work and is still live/running.
- Never hide a live active turn merely because the same session already has a stale/waiting task item.

### Stream First, Poll Fallback

The backend already has SSE. It should become the primary monitor delivery path:

- Initial SSE event sends the monitor envelope.
- Runtime event SSE sends `runtime_event` plus a fresh monitor envelope.
- Heartbeat sends `updated_at` only, not a fake monitor state.
- Polling endpoint returns the same monitor envelope and is used for initial fetch fallback, reconnect fallback, and manual refresh.

The v1 `/live` endpoint can remain temporarily for old callers but must not power the main UI after migration.

Do not emit both independently computed old and new envelopes from the same SSE event. If compatibility requires both fields during migration, compute once:

```text
collected = service.collect_global_runtime_monitor(...)
payload = {
  monitor: collected.monitor,
  legacy_monitor: collected.legacy_monitor,
}
```

The preferred final SSE payload field is `monitor`, typed as `RuntimeMonitorEnvelope`. If a compatibility window is needed, use `legacy_monitor` for the old bucket shape and remove it when frontend migration is complete.

## Frontend Target Design

### One Runtime Monitor Store

Move monitor state out of `RuntimeMonitorConsole` local state. The store owns:

- `runtimeMonitorEnvelope`
- `runtimeMonitorRevision`
- `runtimeMonitorStreamStatus`
- `runtimeMonitorSelectedSignalId`
- `runtimeMonitorSelectedTaskRunId`
- `runtimeMonitorSelectedDetail`
- `runtimeMonitorError`
- `runtimeMonitorLastEvent`

The console, center detail, graph monitor, and chat projection all read this store.

### Graph Task Project Lane

Graph tasks should be displayed as a dedicated project lane. A graph task represents a project-level runtime: it owns a graph run, a session, node work orders, child task runs, artifacts, and long-running progress. It should not be flattened into the same few-line activity list as a tool call or a single chat turn.

The frontend monitor store should expose separate selectors:

- `selectRuntimeMonitorActivityLane()` for active turns, tool execution, waiting tasks, stale tasks, failures, and recent completions.
- `selectRuntimeMonitorProjectLane()` for graph tasks and graph runs.

The project lane should render compact project monitors:

- graph title / project title;
- graph run status;
- current stage or active node summary;
- ready/running/completed/failed/blocked node counts;
- active work order count;
- latest event time;
- continue/refresh/open controls;
- navigation target into the task environment graph monitor.

The project lane still reads the same monitor revision as the activity lane. It must not introduce another polling source.

Existing store fields must be migrated in a controlled order:

- `globalRuntimeMonitor`, `globalRuntimeMonitorRevision`, `globalRuntimeMonitorSelectedTaskInstanceId`, `globalRuntimeMonitorSelectedTaskRunId`, `globalRuntimeMonitorSelectedLiveMonitor`, `globalRuntimeMonitorSelectedGraphMonitor`, and `runtimeMonitorInstancesById` are the old global monitor state.
- `taskGraphBoundRunMonitor`, `taskGraphMonitorBinding`, `taskGraphMonitorLoading`, `taskGraphMonitorActionLoading`, `taskGraphAutoAdvanceEnabled`, `taskGraphAutoAdvancePending`, `taskGraphMonitorError`, and `taskGraphRunInteractionOpen` are graph-detail/control state. Do not delete them until signal selection can hydrate the same graph detail and all graph pages read the new selectors.
- `activeTurnSnapshot` remains the chat-input/live-steering snapshot. It can be updated from monitor events, but it is not a replacement for the runtime monitor envelope.
- `taskGraphLiveMonitor` is session/current-task detail used by `ChatPanel`; it should either be replaced by selected monitor detail or intentionally kept as session detail state.

### One Controller

`RuntimeMonitorController` should:

- open `EventSource(getRuntimeMonitorEventStreamUrl())` when available;
- mark `streamStatus` as `connecting`, `connected`, `fallback`, or `closed`;
- apply only newer revisions;
- reconnect with bounded backoff;
- fall back to polling only when SSE is unavailable or repeatedly failing;
- provide one `refresh()` that fetches the same monitor envelope used by SSE;
- expose `selectSignal(signal_id)` and `openSignal(signal_id)`.

The controller must own exactly one live connection:

- `start()` opens SSE when `EventSource` exists.
- first snapshot may be fetched by HTTP only to avoid an empty UI while SSE connects;
- while SSE is connected, no periodic full monitor polling is scheduled;
- on SSE error, close the source, mark `fallback`, then poll with bounded reconnect attempts;
- on `stop()`, close EventSource, clear timers, clear reconnect state, and avoid leaving `streamStatus` as connected.

Tests currently assert that no SSE stream is opened. Those tests must be replaced, not preserved.

### Console Is A View, Not A Data Fetcher

`RuntimeMonitorConsole` should:

- not call `getRuntimeMonitorConsole` directly;
- not own timers;
- render `primary` first, then `attention`, then compact `recent`;
- show only the current few active/attention rows, with older rows collapsed;
- call controller/store selection on click.

### Detail Navigation

Clicking a signal should not depend on a separately refreshed old monitor item. The signal must contain enough navigation and detail references to open:

- chat/session view;
- task environment view;
- graph monitor view;
- task run detail;
- artifact/resource detail.

Graph detail remains a separate heavy view. The global monitor envelope should carry enough `graph_ref` to open or refresh `getGraphRunMonitor(...)`, but it should not embed the entire graph detail payload into every monitor snapshot.

For project-lane rendering, the monitor envelope should include compact graph metrics on project signals when they are already available from the projector. Expensive graph detail remains lazy-loaded by `graph_ref`.

## Performance Rules

- SSE is the realtime path; polling is fallback, not parallel load.
- When SSE is connected, no 2.5s monitor polling.
- Heartbeats should not force full detail fetches.
- Detail fetch should be lazy and selected-signal scoped.
- The backend collector must cap scanned recent task runs and graph runs.
- Revision comparison prevents stale snapshots from overwriting fresh state.
- Component rendering should memoize visible signal groups and avoid component-local timers.

## Migration Plan

### Phase 1 - Backend Monitor Envelope

- Build `backend/harness/runtime/run_monitor/` as the new monitor package.
- Promote signal projection from console-specific projection to the normal monitor contract.
- Use `authority: runtime_monitor`.
- Add `projects` grouping for graph task / graph run project-level monitors.
- Add active turn binding rules.
- Add detail/navigation refs to monitor signals.
- Add one internal collection method so `/console`, `/events`, and any temporary compatibility payload derive from the same item list and `now`.
- Update SSE to emit the monitor envelope without double-collecting.
- Keep `/live` only for temporary compatibility.
- Add tests for active unbound turn, active bound turn, stale bound task plus active turn, ordering, detail refs, graph refs, and SSE payload shape.

### Phase 2 - Frontend Store Unification

- Update `RuntimeMonitorEventPayload` and API types before wiring the controller.
- Keep normal `rtmon:` revision parsing for rebuilt snapshots.
- Add monitor state to store.
- Add separate activity-lane and project-lane selectors.
- Replace `RuntimeMonitorConsole` local fetch/timer with store selectors.
- Update `RuntimeMonitorController` to own SSE plus fallback polling.
- Keep old reducer only if needed for old center detail during transition, with a deletion marker and no direct UI ownership.

### Phase 3 - Detail And Navigation

- Make `openSignal` use `navigation_target` and `detail_ref`.
- Replace v1 visible item lookup in click flow.
- Load task/graph detail from the selected signal.
- Ensure chat projection receives runtime events from the same controller.
- Migrate `TaskGraphRunInteractionDock`, `TaskGraphTopologyPage`, and `TaskGraphPublishRunPage` to selectors that can read the project lane and graph detail from the unified monitor controller without depending on stale global monitor revisions.

### Phase 4 - Delete Old UI/Data Path

- Remove v1 store fields that are no longer read.
- Remove old v1 runtime-monitor reducer/selectors/presentation code if no remaining caller exists.
- Keep `/live` backend endpoint only if external callers exist; otherwise delete or mark deprecated with a removal date.
- Remove old tests that protect obsolete bucket UI behavior and replace with monitor behavior tests.
- Confirm `ChatPanel`, `PublicRunActivity`, task graph pages, health pages, and orchestration pages do not import old monitor selectors before deleting them.

### Phase 5 - Real Verification

- Run backend monitor tests.
- Run frontend typecheck and store tests.
- Start backend on `127.0.0.1:8003` and frontend on `127.0.0.1:3000`.
- Use browser verification to confirm:
  - SSE connects.
  - no periodic monitor polling while SSE is connected.
  - active bound turn appears as active.
  - console and detail show the same revision.
  - clicking a signal opens the correct session/task/graph target.
  - graph monitor controls still continue/stop/refresh the bound graph run.
  - chat input steering still uses the correct `activeTurnSnapshot`.

## Current Partial Edits

The interrupted work already made local edits to:

- `backend/api/runtime_monitor.py`
- `backend/harness/runtime/monitoring/service.py`
- `backend/harness/runtime/monitoring/projector.py`
- `backend/tests/runtime_monitor_projection_test.py`

These edits should be treated as unreviewed partial work. During implementation they must either be folded into the unified design and tested, or replaced. They are not an acceptable final state by themselves.

## Acceptance Criteria

- There is exactly one frontend monitor state authority.
- The right console is not independently fetching monitor state.
- SSE is the primary live update path.
- Polling happens only as fallback or manual refresh.
- Active turn liveness cannot be hidden by stale bound task state.
- Console, center detail, and graph monitor share the same monitor revision.
- Old monitor code is deleted when it no longer owns a real responsibility.
