# 2026-06-08 Mature Runtime Backport Integration Plan

## 1. Baseline

- Target baseline: `6c7a6d87` (`2026-06-06 01:24 +0800`, `修复`).
- Source archive: `codex/pre-rollback-6c7a6d87-20260608-075444` at `3aa20f3c`.
- Implementation branch: `codex/mature-harness-projection-memory-vscode-backport`.
- Fixed runtime ports remain unchanged:
  - Frontend: `http://127.0.0.1:3000`
  - Backend: `http://127.0.0.1:8003`
  - Frontend API base: `http://127.0.0.1:8003/api`

The source archive is not a merge target. It contains mature pieces, but it also includes broad prompt, frontend, graph, workspace, and generated-output churn. This migration must backport only selected mature architecture.

## 2. User Constraints

1. VSCode integration may be brought over directly from the source archive.
2. Memory system may be brought over directly from the source archive.
3. The main frontend page and primary workbench shell design may be brought over directly from the source archive.
4. Single-agent harness control must not be copied as a whole. It must be rebuilt on the current baseline, using the source archive as a design and contract reference.
5. Projection system must not be copied as a whole. It must be rebuilt on the current baseline, using the source archive as a design and contract reference.
6. Runtime monitor upgrades are necessary, but they follow the same refactor-only rule as harness and projection. The monitor is a control and projection surface, not a direct-copy module.
7. Obsolete chains must be removed after the replacement path owns the responsibility.
8. Tests must verify real behavior. Do not weaken, skip, or fake tests to make the migration pass.

## 3. Target Authority Chain

The target runtime authority chain is:

```text
RequestFacts
-> RuntimeMemoryContext
-> ModelActionProtocol
-> ActiveTurnRegistry
-> TaskExecutorController
-> ExecutionLoop
-> RuntimeTrace/Facts/Observability
-> PublicProjection
-> FrontendPresentation
```

Layer responsibilities:

| Layer | Owner | Responsibility | Must not do |
| --- | --- | --- | --- |
| Request facts | `harness.runtime.request_facts`, chat API | Capture observable request facts and editor context | Decide current work continuation |
| Memory context | `memory_system.runtime_context_provider` | Provide governed read-only memory context | Rewrite user intent |
| Model action protocol | `harness.loop.model_action_protocol` | Validate model-selected action packet | Execute tools or recover task leases |
| Active turn | `harness.runtime.active_turn` | Own current steerable turn handle per session | Infer public UI state |
| Task executor control | `harness.loop.task_executor_controller` | Schedule, recover, pause, resume, stop task runs | Produce chat UI projection |
| Execution loop | `harness.loop.task_executor` | Execute approved task work and record observations | Re-decide top-level user intent |
| Trace/facts/observability | `backend/runtime/{trace,facts,observability}` | Record runtime facts, spans, and queryable execution state | Decide presentation wording |
| Runtime monitor | `harness.runtime.run_monitor` | Project runtime attention signals and expose authorized monitor actions | Own task execution semantics |
| Public projection | `harness.runtime.*projection*` | Convert internal events and task state to public deltas | Run tools or mutate task state |
| Frontend presentation | `frontend/src/components/chat`, `frontend/src/lib/store` | Render and merge public deltas | Infer hidden runtime state |

## 4. Direct Integration Blocks

### 4.1 Memory System

Allowed operation: direct backport from the source archive, followed by integration fixes.

Primary files:

- `backend/memory_system/**`
- `backend/runtime/memory/state_index.py`
- `backend/runtime/memory/tool_observation_ledger.py`
- `backend/api/memory.py`
- memory-related file API updates that route through `MemoryStorageLayout`

Target properties:

- `MemoryStorageLayout` becomes the single memory storage layout authority.
- Runtime-facing services are constructed through `MemoryRuntimeServices`.
- `RuntimeMemoryContextProvider` supplies memory context for single-agent turns and task execution.
- `RuntimeFactBridge` bridges only governed runtime facts into memory candidates.
- Old `task_durable_memory` code is deleted when no production import remains.

Data policy:

- Code should move to the new `storage/memory/*` layout.
- Existing memory data must not be silently discarded.
- A short migration/read boundary is allowed only to preserve existing user data during cutover.
- No long-term dual memory runtime path may remain.

Focused tests:

- `backend/tests/formal_memory_store_regression.py`
- `backend/tests/memory_maintenance_agent_regression.py`
- `backend/tests/memory_search_tool_regression.py`
- `backend/tests/runtime_memory_context_provider_regression.py`
- `backend/tests/runtime_fact_memory_bridge_test.py`
- `backend/tests/task_memory_request_profile_contract_regression.py`
- `backend/tests/tool_observation_ledger_regression.py`

### 4.2 VSCode Integration

Allowed operation: direct backport from the source archive, followed by integration fixes and rebuild.

Primary files:

- `backend/api/vscode.py`
- `backend/integrations/vscode_connection/**`
- `backend/api/chat.py` editor-context integration
- `backend/api/sessions.py` open-bound-project integration
- `backend/api/project_workspaces.py` open project integration
- `backend/app.py` router registration
- `extensions/vscode/src/connection/**`
- `extensions/vscode/src/extension.ts`
- `frontend/src/features/vscode-connection/**`
- minimal frontend shell integration needed to display connection status

Target properties:

- VSCode connection state is a bridge into request facts, not an independent runtime decision layer.
- Backend validates project binding and rejects ambiguous multiple-root context.
- Extension heartbeat sends editor context only when a session can be resolved.
- Generated `extensions/vscode/out/**` should be regenerated by `npm run compile` if the repository expects tracked output.

Focused tests:

- `backend/tests/vscode_connection_bridge_regression.py`
- `backend/tests/vscode_project_binding_sandbox_regression.py`
- `npm run compile` in `extensions/vscode`

## 5. Refactor-Only Blocks

### 5.1 Single-Agent Harness Control

Allowed operation: rebuild on the current baseline. Do not directly replace the entire source archive implementation.

Source archive concepts to backport:

- explicit `ActiveTurnRegistry`
- `TaskExecutorController`
- stale executor claim recovery
- model action protocol validation
- native tool binding plan
- runtime-start recovery of interrupted task executors
- task run state view

Current baseline code must remain the structural base unless a file has no legitimate target authority after migration.

Primary current files to refactor:

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/runtime/single_agent_host.py`
- `backend/harness/runtime/active_turn.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/loop/task_executor_controller.py`
- `backend/harness/loop/model_action_protocol.py`
- `backend/harness/loop/model_action_runtime.py`
- `backend/harness/loop/active_work.py`
- `backend/harness/loop/admission.py`
- `backend/harness/loop/work_rollout.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/tool_scheduling.py`
- `backend/harness/runtime/native_tool_binding.py`
- `backend/harness/task_run_state_view.py`

Deletion candidates:

- `backend/harness/entrypoint/current_work_boundary.py`
- tests that only protect `current_work_boundary` as an independent decision layer

Deletion criterion:

- The new active-turn and model-action path must own active work continuation.
- No production import may still reference `harness.entrypoint.current_work_boundary`.
- Regression tests must verify active turn conflict, continuation, waiting executor, stop, resume, and recovery behavior.

Focused tests:

- `backend/tests/model_action_protocol_contract_test.py`
- `backend/tests/model_action_runtime_regression.py`
- `backend/tests/task_executor_control_contract_test.py`
- `backend/tests/task_executor_runtime_contract_test.py`
- `backend/tests/task_executor_scheduler_contract_test.py`
- `backend/tests/task_executor_progress_contract_test.py`
- `backend/tests/task_lifecycle_contract_test.py`
- `backend/tests/native_tool_binding_plan_regression.py`
- `backend/tests/runtime_tool_plan_deferred_regression.py`
- `backend/tests/task_native_tool_calls_regression.py`

### 5.2 Projection System

Allowed operation: rebuild on the current baseline. Do not directly replace the whole projection stack.

Source archive concepts to backport:

- single backend public projection authority
- `SingleAgentTaskProjection`
- public timeline event deltas
- task projection attached to scheduled executor handoff
- frontend public timeline merge and presentation
- no frontend hidden-state inference from raw runtime events

Primary current files to refactor:

- `backend/harness/runtime/public_timeline_stream.py`
- `backend/harness/runtime/runtime_monitor_public_projection.py`
- `backend/harness/runtime/session_timeline.py`
- `backend/harness/runtime/session_task_projection.py`
- `backend/harness/runtime/public_todo_timeline.py`
- `backend/harness/runtime/run_monitor/projector.py`
- `backend/harness/runtime/run_monitor/actions.py`
- `backend/api/chat.py`
- `backend/api/runtime_monitor.py`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/PublicTimelineActivity.tsx`
- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/store/publicTimeline.ts`
- `frontend/src/lib/run-monitor/controller.ts`
- `frontend/src/lib/run-monitor/selectors.ts`
- `frontend/src/lib/api.ts`

Deletion candidates:

- `backend/harness/runtime/public_chat_timeline.py`
- `frontend/src/components/chat/PublicRunActivity.tsx`
- `frontend/src/components/chat/PublicRunActivity.test.ts`
- `frontend/src/lib/runtimeVisibilityProjection.ts`
- `frontend/src/lib/runtimeVisibilityProjection.test.ts`

Deletion criterion:

- Backend must emit public timeline deltas or task projections with explicit authority.
- Frontend must render from `public_timeline_delta`, persisted public timeline, and `task_projection`.
- No frontend module may infer activity from raw internal event names after the backend projection is available.

Focused tests:

- `backend/tests/chat_public_stream_contract_test.py`
- `backend/tests/runtime_monitor_public_projection_test.py`
- `backend/tests/session_task_projection_test.py`
- `backend/tests/session_runtime_timeline_contract_test.py`
- `backend/tests/task_observation_projection_contract_test.py`
- `frontend/src/components/chat/PublicTimelineActivity.test.ts`
- `frontend/src/lib/store/publicTimeline.test.ts`
- `frontend/src/lib/store/runtime.test.ts`
- `frontend/src/lib/run-monitor/selectors.test.ts`

### 5.3 Runtime Monitor System

Allowed operation: rebuild on the current baseline. Do not directly replace the full monitor stack or broad workbench UI.

The monitor upgrade is necessary for this phase because the source archive uses it as the shared attention surface for:

- active turn visibility
- waiting executor and scheduled task state
- resume, stop, close, clear, restore, and delete actions
- runtime facts and trace summaries
- public timeline projection during monitor SSE events
- graph task-run monitor detail

Source archive concepts to backport:

- monitor signal envelope with stable authority
- active-turn signal projection
- waiting/scheduled executor priority over stale running residue
- management projection for hidden, restored, terminal, and deleted records
- action receipts for clear, restore, delete, resume, stop, and close runtime
- monitor event SSE hydration through public projection
- frontend selectors that separate attention/activity lane from project lane

Primary current files to refactor:

- `backend/api/runtime_monitor.py`
- `backend/harness/runtime/run_monitor/actions.py`
- `backend/harness/runtime/run_monitor/activity.py`
- `backend/harness/runtime/run_monitor/contract.py`
- `backend/harness/runtime/run_monitor/management.py`
- `backend/harness/runtime/run_monitor/projector.py`
- `backend/harness/runtime/run_monitor/service.py`
- `backend/harness/runtime/run_monitor/signals.py`
- `frontend/src/lib/run-monitor/controller.ts`
- `frontend/src/lib/run-monitor/selectors.ts`
- `frontend/src/components/layout/RunMonitorActionMenu.tsx`
- `frontend/src/components/layout/RunMonitorPanel.tsx`

Limited frontend UI files may be touched only when required by the monitor contract:

- `frontend/src/components/layout/RunActivityLane.tsx`
- `frontend/src/components/layout/RunTaskLane.tsx`
- `frontend/src/components/layout/WorkbenchShell.tsx`

Do not backport unrelated broad workbench layout churn just because it exists in the source archive.

Focused tests:

- `backend/tests/runtime_monitor_projection_test.py`
- `backend/tests/runtime_monitor_public_projection_test.py`
- `backend/tests/runtime_trace_monitor_projection_test.py`
- `frontend/src/lib/run-monitor/selectors.test.ts`
- monitor-related cases in `frontend/src/lib/store/runtime.test.ts`

## 6. Shared Runtime Dependencies

These are required before harness and memory integration:

- `backend/runtime/facts/**`
- `backend/runtime/trace/**`
- `backend/runtime/observability/**`
- `backend/api/runtime_facts.py`
- `backend/api/runtime_trace.py`
- `backend/runtime/shared/event_log.py` updates needed by facts/trace/projectors

Focused tests:

- `backend/tests/runtime_fact_api_test.py`
- `backend/tests/runtime_fact_ledger_store_test.py`
- `backend/tests/runtime_trace_api_test.py`
- `backend/tests/runtime_trace_store_test.py`
- `backend/tests/runtime_observability_kernel_test.py`
- `backend/tests/runtime_trace_monitor_projection_test.py`

## 7. Implementation Phases

### Phase 0: Workspace Control

1. Stop existing frontend/backend dev servers.
2. Keep fixed port policy unchanged.
3. Keep unrelated runtime-generated session directories untouched unless explicitly cleaned.

### Phase 1: Documentation and Branch

1. Create this integration plan.
2. Work only on `codex/mature-harness-projection-memory-vscode-backport`.

### Phase 2: Shared Runtime Foundation

1. Bring over runtime facts, trace, and observability kernel.
2. Register new API routers if needed.
3. Run focused runtime foundation tests.

### Phase 3: Memory Direct Backport

1. Bring over memory system implementation and memory API updates.
2. Integrate with current app runtime construction.
3. Add or preserve only the one-time data transition boundary.
4. Delete obsolete memory runtime files and tests after imports are gone.
5. Run memory-focused tests.

### Phase 4: VSCode Direct Backport

1. Bring over backend VSCode connection store and API.
2. Bring over extension source updates.
3. Bring over frontend connection status surface.
4. Bring over the source archive main page and primary workbench shell design.
5. Compile the VSCode extension.
6. Run VSCode backend tests.

### Phase 5: Harness Control Refactor

1. Add or adapt active-turn registry on the current runtime host.
2. Add task executor controller and claim recovery.
3. Refactor `runtime_facade.py` to route active work through active-turn/control authorities.
4. Refactor model action protocol validation and native tool binding.
5. Delete `current_work_boundary` after no production import remains.
6. Run harness control tests.

### Phase 6: Projection Refactor

1. Add task run state view and task projection.
2. Refactor monitor and chat public projection to emit explicit backend deltas.
3. Refactor frontend store and chat rendering to consume backend projection.
4. Delete old projection chain after no production import remains.
5. Run projection backend and frontend tests.

### Phase 7: Runtime Monitor Refactor

1. Refactor backend monitor projector/action/service on the current baseline.
2. Wire monitor SSE event hydration through the public projection authority.
3. Refactor frontend controller/selectors and only the necessary monitor panel/lane files.
4. Run monitor backend and frontend tests.

### Phase 8: Full Verification

1. Run compile checks.
2. Run focused backend tests.
3. Run focused frontend tests.
4. Run VSCode extension compile.
5. Start backend on `8003` and frontend on `3000`.
6. Verify:
   - backend `/health`
   - frontend `/`
   - capability catalog
   - chat SSE startup
   - runtime monitor stream
   - memory overview endpoint
   - VSCode status endpoint

## 8. Acceptance Criteria

- `rg "current_work_boundary" backend` has no production imports.
- `rg "public_chat_timeline" backend` has no production imports.
- `rg "runtimeVisibilityProjection|PublicRunActivity" frontend/src` has no production imports.
- Memory service construction goes through `MemoryFacade` or `MemoryRuntimeServices`.
- VSCode context is available through backend API and can be reused by a project-bound session.
- Running task projection shows scheduled/waiting executor state as running or waiting, not completed.
- Runtime monitor shows active turns, scheduled executors, waiting states, and authorized actions without stale running residue.
- Frontend does not display raw tool output as assistant prose.
- Focused tests pass.
- Fixed-port startup passes on `127.0.0.1:3000` and `127.0.0.1:8003`.

## 9. Explicit Non-Goals

- Do not backport the full prompt library overhaul in this phase.
- Do not merge unrelated workspace UI redesigns beyond the explicitly allowed main page and primary workbench shell reuse.
- Do not preserve old compatibility paths after the new authority owns the behavior.
- Do not migrate broad graph-runtime prompt changes unless a focused test proves they are required by the selected slices.
