# Runtime Monitor Unified System Plan - 2026-06-04

## Why The Current Design Is Not Acceptable

The monitor subsystem is currently split across two frontend truth sources:

- `RuntimeMonitorController` consumes `/orchestration/runtime-monitor/live` and stores a v1 bucket envelope in global store.
- `RuntimeMonitorConsole` consumes `/orchestration/runtime-monitor/console` directly and stores a v2 signal envelope in component-local state.

This means the right console, detail navigation, graph monitor, and session projection can observe different revisions of runtime state. That is not a mature monitor architecture. A monitor system must have one observation authority, one normalized state contract, one realtime delivery path, and deterministic fallback behavior.

The backend also has a known blind spot: an active turn with `bound_task_run_id` can be hidden when the bound task run is stale, filtered, or not visible. The system should treat the live active turn as the freshest runtime signal, while still linking it to the bound task run for navigation and detail.

## Target Authority Chain

```text
RuntimeEventLog / StateIndex / ActiveTurnRegistry / GraphHarness
-> RuntimeMonitorCollector
-> RuntimeMonitorProjector
-> RuntimeMonitorEnvelope v2
-> RuntimeMonitorStream
-> Frontend RuntimeMonitorStore
-> Console / Detail / Graph / Chat Projection Views
```

Only the backend collector/projector decides what runtime work exists and what state it is in. The frontend only renders, selects, and navigates from the current monitor envelope.

## Backend Target Contract

### One Envelope

Create one canonical monitor envelope for live UI consumption:

```text
authority: runtime_monitor.v2
revision
updated_at
summary
signals
primary
attention
recent
selected/detail refs
```

The current v1 bucket envelope can remain only as an internal compatibility endpoint during migration, not as a second UI truth source.

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
- `raw_refs`: diagnostic identifiers only.

### Active Turn Rule

Active turn is authoritative for liveness:

- If an active turn has no bound task run, expose it as a live turn signal.
- If it has `bound_task_run_id`, expose it as a live turn signal whose `task_run_id` points to the bound task run and whose `signal_id` remains the active `turn_run_id`.
- Suppress the active turn only when the visible task item already represents the same work and is still live/running.
- Never hide a live active turn merely because the same session already has a stale/waiting task item.

### Stream First, Poll Fallback

The backend already has SSE. It should become the primary monitor delivery path:

- Initial SSE event sends the canonical v2 envelope.
- Runtime event SSE sends `runtime_event` plus fresh canonical v2 envelope.
- Heartbeat sends `updated_at` only, not a fake monitor state.
- Polling endpoint returns the same canonical v2 envelope and is used for initial fetch fallback, reconnect fallback, and manual refresh.

The v1 `/live` endpoint can remain temporarily for old callers but must not power the main UI after migration.

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

### One Controller

`RuntimeMonitorController` should:

- open `EventSource(getRuntimeMonitorEventStreamUrl())` when available;
- mark `streamStatus` as `connecting`, `connected`, `fallback`, or `closed`;
- apply only newer revisions;
- reconnect with bounded backoff;
- fall back to polling only when SSE is unavailable or repeatedly failing;
- provide one `refresh()` that fetches the same v2 envelope used by SSE;
- expose `selectSignal(signal_id)` and `openSignal(signal_id)`.

### Console Is A View, Not A Data Fetcher

`RuntimeMonitorConsole` should:

- not call `getRuntimeMonitorConsole` directly;
- not own timers;
- render `primary` first, then `attention`, then compact `recent`;
- show only the current few active/attention rows, with older rows collapsed;
- call controller/store selection on click.

### Detail Navigation

Clicking a signal should not depend on a separately refreshed v1 monitor item. The v2 signal must contain enough navigation and detail references to open:

- chat/session view;
- task environment view;
- graph monitor view;
- task run detail;
- artifact/resource detail.

## Performance Rules

- SSE is the realtime path; polling is fallback, not parallel load.
- When SSE is connected, no 2.5s monitor polling.
- Heartbeats should not force full detail fetches.
- Detail fetch should be lazy and selected-signal scoped.
- The backend collector must cap scanned recent task runs and graph runs.
- Revision comparison prevents stale snapshots from overwriting fresh state.
- Component rendering should memoize visible signal groups and avoid component-local timers.

## Migration Plan

### Phase 1 - Backend Canonical Envelope

- Promote `signals.py` from console-specific projection to canonical v2 monitor contract.
- Add active turn binding rules.
- Add detail/navigation refs to v2 signals.
- Update SSE to emit v2 envelope.
- Keep `/live` only for temporary compatibility.
- Add tests for active unbound turn, active bound turn, stale bound task plus active turn, ordering, and SSE payload shape.

### Phase 2 - Frontend Store Unification

- Add v2 monitor state to store.
- Replace `RuntimeMonitorConsole` local fetch/timer with store selectors.
- Update `RuntimeMonitorController` to own SSE plus fallback polling.
- Keep old reducer only if needed for old center detail during transition, with a deletion marker.

### Phase 3 - Detail And Navigation On v2

- Make `openSignal` use v2 `navigation_target` and `detail_ref`.
- Replace v1 visible item lookup in click flow.
- Load task/graph detail from the selected v2 signal.
- Ensure chat projection receives runtime events from the same controller.

### Phase 4 - Delete Old UI/Data Path

- Remove v1 store fields that are no longer read.
- Remove old v1 runtime-monitor reducer/selectors/presentation code if no remaining caller exists.
- Keep `/live` backend endpoint only if external callers exist; otherwise delete or mark deprecated with a removal date.
- Remove old tests that protect obsolete bucket UI behavior and replace with v2 behavior tests.

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
