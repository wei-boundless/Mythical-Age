# Health Monitoring System Plan

Date: 2026-05-22

## 1. Problem Statement

The current project already has runtime traces, task graph monitors, health issues, verification gates, evidence packets, and a health workbench. These resources are enough to support a practical health monitoring system.

The missing layer is not data collection. The missing layer is a health monitoring domain that turns raw runtime facts into health signals, incidents, recovery candidates, and verification actions.

Current failure mode:

- The global runtime monitor endpoint is exposed from `api/orchestration_runtime_loop.py`.
- The frontend right monitor dock reads `/api/orchestration/runtime-loop/live-monitor` directly.
- `runtime-loop` is therefore acting as both execution fact source and monitoring product owner.
- The health system already owns issue/report/command/receipt, verification, evidence, and maintenance, but it does not yet own live runtime health monitoring.

Correct end state:

- Runtime modules expose read-only execution facts.
- `health_system.monitoring` owns interpretation, classification, severity, incidents, recovery candidates, and health-system actions.
- The frontend monitor dock reads health monitoring projections, not raw runtime-loop ownership APIs.
- Health workbench and right monitor dock share the same health signal vocabulary.

## 2. Current Resource Assessment

### 2.1 Existing Facts We Can Reuse

- `runtime.memory.state_index.RuntimeStateIndex`
  - Durable indexes for task runs, coordination runs, project runtime statuses, session live views.
- `runtime.shared.event_log.RuntimeEventLog`
  - Per-task event log with durable runtime event history.
- `runtime.shared.checkpoint.RuntimeCheckpointStore`
  - Latest task checkpoint and recovery boundary data.
- `runtime.memory.trace_reader.RuntimeLoopTraceReader`
  - Existing read-only adapter over state index, events, checkpoints, task graph monitor view.
- `runtime.graph_runtime.run_monitor`
  - Canonical TaskGraph run monitor view.

These are enough for first-class monitoring facts: active task, elapsed time, latest event, event count, checkpoint ref, coordination run, graph state, active node, project runtime state, and failure state.

### 2.2 Existing Health System Resources

- `health_system.models`
  - `HealthIssue`, `HealthManagementCommand`, `HealthManagementReceipt`, `HealthReport`, `VerificationRun`.
- `health_system.registry.HealthRegistry`
  - Main health governance entry.
- `health_system.command_service.HealthCommandService`
  - Command execution for report/analyze/draft/verify/test.
- `health_system.verification_service.HealthVerificationService`
  - Verification profiles, artifact manifests, regression gates.
- `health_system.workbench.HealthWorkbenchBuilder`
  - Workbench aggregation: diagnosis inbox, recovery inbox, failure chains, evidence packets.
- `health_system.evidence_extractor`
  - Runtime trace to evidence packet.
- `health_system.maintenance.test_system.task_graph_health`
  - TaskGraph monitor to health projection.

These are enough for the governance loop after a monitoring signal exists.

### 2.3 Current Frontend Resources

- `frontend/src/components/layout/TaskMonitorDock.tsx`
  - Right dock for real-time runtime monitoring.
- `frontend/src/components/task-graph-monitor/TaskGraphRunMonitorPanel.tsx`
  - Detailed TaskGraph run monitor.
- `frontend/src/components/workspace/views/HealthSystemView.tsx`
  - Health workbench, issues, verification, time statistics.
- `frontend/src/components/health/HealthAgentDock.tsx`
  - Health assistant dock tied to selected health issue/run.

The frontend can support the target UI, but the data contract needs to change. The dock should display health monitoring signals first and raw runtime details second.

## 3. Design Decision

### 3.1 Ownership Boundary

Runtime-loop owns:

- Task execution lifecycle.
- Event append and checkpoint write.
- State index updates.
- Read-only runtime trace and monitor facts.
- Stop/approval control endpoints, because these mutate runtime state.

Health monitoring owns:

- Runtime health policy.
- Signal generation.
- Severity and status classification.
- Stale running detection.
- Blocked/waiting/failed classification.
- Incident projection.
- Recovery candidate projection.
- Conversion to `HealthIssue`.
- Links to health commands, evidence packets, and verification runs.

Frontend owns:

- Low-noise monitoring presentation.
- Drill-down from health signal to task details.
- Actions that call health-system endpoints for issue creation or recovery, and runtime endpoints only for direct runtime control such as stop/approval.

### 3.2 No New Shell Around Old Shell

Do not simply proxy `/orchestration/runtime-loop/live-monitor` under `/health-system`.

The health endpoint must return a health projection with:

- `summary`
- `signals`
- `incidents`
- `task_runs`
- `selected_detail`
- `recovery_candidates`
- `source_refs`

Raw runtime fields can be nested under `runtime`, but health fields must be first-class.

### 3.3 Health Signal Vocabulary

Initial signal types:

- `runtime.task_running`
- `runtime.task_completed`
- `runtime.task_failed`
- `runtime.task_aborted`
- `runtime.task_waiting_approval`
- `runtime.task_blocked`
- `runtime.task_stale_running`
- `runtime.event_stalled`
- `runtime.checkpoint_missing`
- `task_graph.health_issue`
- `project.runtime_warning`

Initial severities:

- `info`
- `warning`
- `error`
- `critical`

Initial signal statuses:

- `open`
- `acknowledged`
- `linked_issue`
- `resolved`
- `ignored`

### 3.4 Health Manage Agent Rebuild Direction

Do not preserve the old health agent configuration as the target design.

The old configuration is not useful and must be cleared. It is not a compatibility layer and it must not remain as a hidden default.

The target is a real health maintenance agent that is useful inside the monitoring system, not a decorative assistant attached to the health page.

Old configuration handling rules:

- Keep `agent:3` as the registered health-system agent identity.
- Remove the old `health_maintainer_agent` runtime profile.
- Remove old default `flow.health.*`, `workflow.health.*`, `task.health.*`, synthetic task records, and persisted task bindings that only exist for the old health agent.
- Remove fake `skill.health.*` workflow references.
- Remove empty `protocol.health.*` and `topology.health.*` fallback hooks from task assembly.
- Remove old health sample runs/problem nodes that point at old task-system bindings.
- Until the new canonical health agent config exists, all health-agent execution and admission must fail closed with `health_agent_config_not_rebuilt`.
- Do not silently route old health commands through generic task-system defaults.

Allowed retained item:

- `backend/agent_system/registry/agent_registry.py` keeps `agent:3` registered as the health-system agent slot.

Not retained:

- old runtime profile
- old health task flows
- old health workflows
- old task assignment records
- old projection/flow/memory/adoption task bindings
- old health workflow sample data
- old projection templates pointing to removed runtime/workflow ids

### 3.5 Target Health Manage Agent Role

The health manage agent is a bounded health operator:

- Reviews monitoring signals.
- Explains trace and checkpoint evidence.
- Decides whether a signal deserves a health issue.
- Drafts regression cases from real failures.
- Verifies whether a fix actually resolved the issue.
- Produces reports and recommendations through health-system-owned writes.

The agent must not:

- Write or edit project files.
- Run shell or Python.
- Create issues directly as a model-side side effect.
- Start recovery automatically.
- Override runtime lane, agent id, workflow id, or resource policy from user/frontend payloads.

The health system service, not the model, owns writes:

- Create `HealthIssue`.
- Store `HealthReport`.
- Store health agent run result.
- Launch test/verification commands.
- Link signal, issue, report, verification run, and recovery candidate.

### 3.6 New Health Agent Configuration Model

Create a health-agent-owned configuration source instead of scattering behavior across agent defaults, task workflow defaults, runtime lane defaults, and frontend assumptions.

Add:

```text
backend/health_system/agent_config.py
```

This module should be the canonical source for:

- health agent id
- health agent profile id
- default projection id
- supported health actions
- action-to-task mapping
- action-to-flow mapping
- action-to-workflow mapping
- action-to-runtime-lane mapping
- action input/output contracts
- action evidence requirements
- action permission envelope

The old `constants.py` task map can either be replaced by this module or reduced to a compatibility import.

Target actions:

Add a pre-issue monitoring action:

```text
health_action: signal_triage
task_id:       task.health.signal_triage
flow_id:       flow.health.signal_triage
workflow_id:   workflow.health.signal_triage
input:         HealthMonitoringSignal
output:        HealthSignalAssessment
runtime_lane:  runtime_trace_read
```

Required action map:

- `issue_triage` -> `health_issue_read`
- `trace_analysis` -> `runtime_trace_read`
- `case_draft` -> `case_draft_candidate`
- `fix_verification` -> `fix_verification_candidate`
- `signal_triage` -> `runtime_trace_read`

### 3.7 Projection And Prompt Contract

Use a dedicated health maintenance projection as the default. Do not rely on a generic primary projection.

Required projection contract:

```text
projection_id: xuannv__health_maintainer
role:          health maintenance reviewer
mode:          evidence-first system health diagnosis
boundary:      read evidence, judge risk, propose next action
forbidden:     write code, run shell, auto-repair, invent evidence
```

Prompts must describe a real role, not implementation labels.

Good:

```text
你是一名系统健康诊断员。
你只负责评估当前监测信号是否代表真实故障、退化或证据不足。
你需要指出证据、判断严重性、说明是否应该登记健康问题，并给出下一步验证建议。
你不负责修改代码、执行命令或替实现方辩护。
```

Bad:

```text
这是 health signal triage 节点。
根据 signal 执行 runtime_monitor。
```

### 3.8 Health Skills: Keep Only Real Skills

Create real skills only if they contain useful operating procedure.

Required skills:

- `skill.health.signal_triage`
- `skill.health.trace_analysis`
- `skill.health.issue_triage`
- `skill.health.case_draft`
- `skill.health.fix_verification`

Each skill must include:

- when to use it
- allowed evidence
- forbidden behavior
- expected output fields
- decision criteria
- examples of insufficient evidence

If a skill is only a title with no procedure, do not register it.

### 3.9 Health Review Graph

Build a real health review graph instead of relying on empty default protocol/topology hooks.

- Add `protocol.health.repair_review`.
- Add `topology.health.repair_review`.
- Add or derive `graph.health.repair_review`.

This graph is not a repair executor. It is a health review workflow:

- signal or issue intake
- evidence sufficiency check
- trace analysis
- severity and ownership decision
- optional case draft
- optional fix verification
- final report projection

The graph must not run code or mutate project files.

### 3.10 Health Manage Agent Trigger Rules

No automatic model calls for every signal in the first implementation.

Allowed triggers:

- User clicks a monitoring signal and chooses agent analysis.
- User converts a signal into a health issue, then starts issue triage.
- A failed verification run is selected for trace analysis.
- A health issue has enough evidence and the user requests case draft.
- A fix or verification run exists and the user requests fix verification.

Later automation may be added only after signal quality is proven.

### 3.11 Health Manage Agent Output Contracts

Add `HealthSignalAssessment` with fields like:

- `verdict`
- `severity`
- `confidence`
- `subject_type`
- `subject_ref`
- `evidence_refs`
- `root_cause_candidates`
- `missing_evidence`
- `recommended_action`
- `issue_recommendation`
- `recovery_candidate_refs`
- `verification_needed`

Agent outputs must be stored as health-system artifacts:

- Signal analysis result links to `signal_id`.
- If converted to issue, `HealthIssue.runtime_trace_refs` includes task run refs and checkpoint refs.
- Reports link to both the health agent run and the original signal.

## 4. Target Backend Structure

Add:

```text
backend/health_system/monitoring/
  __init__.py
  models.py
  policies.py
  runtime_projection.py
  signal_builder.py
  service.py
```

### 4.1 `models.py`

Define small dataclasses:

- `HealthMonitoringSummary`
- `HealthSignal`
- `HealthIncident`
- `HealthRecoveryCandidate`
- `HealthMonitoredTaskRun`
- `HealthMonitoringSnapshot`

These models should serialize with `to_dict()`.

### 4.2 `policies.py`

Own thresholds and classification rules:

- stale running threshold
- event stall threshold
- waiting approval threshold
- max monitor result limit
- status severity map

The first version can use static defaults. Do not make settings UI until there is a real need.

### 4.3 `runtime_projection.py`

Convert runtime-loop facts into health monitoring task projections.

Inputs:

- `runtime.query_runtime.task_run_loop.trace_reader`
- `state_index`
- `event_log`
- existing runtime live monitor methods

Outputs:

- normalized task run health facts
- source references
- optional task graph health projection

### 4.4 `signal_builder.py`

Apply policy to task facts.

Responsibilities:

- classify status
- detect stale running
- detect stalled event stream
- detect missing checkpoint for active task
- promote task graph health issues into health signals
- derive recovery candidates

### 4.5 `service.py`

Public health monitoring service.

Methods:

- `build_overview(limit: int = 40) -> dict`
- `get_task_run_detail(task_run_id: str) -> dict | None`
- `list_signals(limit: int = 100) -> dict`
- `create_issue_from_signal(signal_id: str, payload: dict) -> dict`

`create_issue_from_signal` should use `HealthRegistry.create_issue` and must include runtime refs in `runtime_trace_refs`.

## 5. API Plan

Add health-owned endpoints in `backend/api/health_system.py` or a new `backend/api/health_monitoring.py`.

Preferred: create `backend/api/health_monitoring.py` to keep `health_system.py` from becoming larger.

Endpoints:

```text
GET  /api/health-system/monitoring/overview?limit=40
GET  /api/health-system/monitoring/signals?limit=100
GET  /api/health-system/monitoring/task-runs/{task_run_id}
POST /api/health-system/monitoring/signals/{signal_id}/issue
```

Register router in `backend/app.py` with tag `health-monitoring`.

Keep existing runtime endpoints temporarily:

```text
/api/orchestration/runtime-loop/live-monitor
/api/orchestration/runtime-loop/task-runs/{task_run_id}/live-monitor
/api/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor
```

But frontend should migrate to health monitoring endpoints for global dock data.

## 6. Frontend Plan

### 6.1 API Types

Update `frontend/src/lib/api.ts`:

- Add `HealthMonitoringSnapshot`
- Add `HealthMonitoringTaskRun`
- Add `HealthSignal`
- Add `HealthIncident`
- Add `HealthRecoveryCandidate`
- Add:
  - `getHealthMonitoringOverview`
  - `getHealthMonitoringTaskRun`
  - `listHealthMonitoringSignals`
  - `createHealthIssueFromSignal`

### 6.2 Store

Update `frontend/src/lib/store/runtime.ts` and state types:

- Rename global monitor state from runtime-only naming to health-monitor naming.
- Keep old internal names only if migration becomes too large, but API source must change.
- Poll `getHealthMonitoringOverview`.
- Load selected task detail from `getHealthMonitoringTaskRun`.

### 6.3 Right Monitor Dock

Update `frontend/src/components/layout/TaskMonitorDock.tsx`:

- Top summary shows health state, not just task counts.
- Primary list shows tasks grouped by signal severity:
  - active issues
  - waiting/blocked
  - running
  - completed
- Row should show:
  - task title
  - health status
  - elapsed time
  - latest signal
  - owner/project if available
- Detail panel should show:
  - health signals
  - recovery candidates
  - raw runtime details
  - embedded `TaskGraphRunMonitorPanel` when available

### 6.4 Health Workbench

Update `HealthSystemView.tsx` only after backend projection is stable:

- Add a compact “实时监测” section using the same `HealthSignal` vocabulary.
- Diagnosis inbox should consume incidents/signals where useful.
- Recovery inbox should show recovery candidates from monitoring when a task is currently blocked or stale.

## 7. Migration Rules

Allowed overlap:

- Runtime endpoints remain for trace/detail and direct runtime control.
- Existing `TaskGraphRunMonitorPanel` remains reused.

Not allowed:

- Do not add more global health interpretation inside `TaskRunLoop`.
- Do not make the frontend infer health severity from raw status alone after the health API exists.
- Do not create fake monitoring events for UI testing.
- Do not create duplicate issue stores for monitoring incidents.

Cutover rule:

- The right monitor dock is considered migrated when its global polling source is `/api/health-system/monitoring/overview`.

Cleanup rule:

- After cutover, remove unused frontend global runtime monitor types/functions if they are no longer referenced.
- Keep runtime detail APIs only when used by task graph monitor or direct debugging.

## 8. Execution Phases

### Phase 1: Backend Health Monitoring Core

Files:

- Update `backend/agent_system/profiles/runtime_profile_registry.py`
- Update `backend/task_system/registry/flow_registry.py`
- Update `backend/task_system/registry/workflow_registry.py`
- Update `backend/task_system/services/assembly_builder.py`
- Update `backend/health_system/execution_planner.py`
- Update `backend/health_system/runtime_admission.py`
- Update `backend/health_system/registry.py`
- Update `backend/soul/projection_templates.py`
- Clean `storage/orchestration/agent_runtime_profiles.json`
- Clean old health records from `storage/tasks/*.json`
- Add `backend/health_system/monitoring/models.py`
- Add `backend/health_system/monitoring/policies.py`
- Add `backend/health_system/monitoring/runtime_projection.py`
- Add `backend/health_system/monitoring/signal_builder.py`
- Add `backend/health_system/monitoring/service.py`
- Add `backend/health_system/monitoring/__init__.py`

Completion criteria:

- `agent:3` remains registered.
- No default or persisted `health_maintainer_agent` profile remains.
- No default or persisted old `flow.health.*`, `workflow.health.*`, or `task.health.*` orchestration config remains.
- Health agent execution/admission fails closed until `backend/health_system/agent_config.py` is rebuilt.
- A service can build an overview from current runtime facts.
- Signals include stale running, failed, aborted, waiting approval, blocked, and completed states.
- Output includes source refs back to runtime task runs and checkpoints.

### Phase 2: Health Monitoring API

Files:

- Add `backend/api/health_monitoring.py`
- Update `backend/app.py`
- Add or update backend tests.

Completion criteria:

- `GET /api/health-system/monitoring/overview` returns real task monitoring facts.
- `GET /api/health-system/monitoring/task-runs/{task_run_id}` returns detail or 404.
- `POST /api/health-system/monitoring/signals/{signal_id}/issue` creates a real `HealthIssue`.

### Phase 3: Frontend Dock Cutover

Files:

- Update `frontend/src/lib/api.ts`
- Update `frontend/src/lib/store/types.ts`
- Update `frontend/src/lib/store/core.ts`
- Update `frontend/src/lib/store/runtime.ts`
- Update `frontend/src/components/layout/TaskMonitorDock.tsx`
- Update `frontend/src/app/globals.css` only for necessary low-noise presentation changes.

Completion criteria:

- Right dock reads health monitoring API.
- Active signals are visible without opening health workbench.
- Task detail still embeds TaskGraph monitor when available.
- UI stays low-noise and practical.

### Phase 4: Health Workbench Integration

Files:

- Update `frontend/src/components/workspace/views/HealthSystemView.tsx`
- Optionally update `backend/health_system/workbench.py`

Completion criteria:

- Health workbench can show live monitoring incidents alongside diagnosis/recovery inbox.
- Signal-to-issue path is visible and usable.
- Recovery candidates are visible for stale/blocked tasks.

### Phase 5: Cleanup and Validation

Files:

- Remove unused frontend runtime monitor API functions/types if no longer referenced.
- Update `docs/implementation_plans/global_runtime_monitor_plan_20260522.md` with superseded note.
- Add regression coverage for endpoint ownership.

Completion criteria:

- No frontend polling of `/orchestration/runtime-loop/live-monitor`.
- Runtime-loop has no new health classification logic.
- Tests and build pass.

## 9. Validation Matrix

Backend:

- `python -m py_compile` for new health monitoring modules and affected API files.
- Targeted pytest:
  - health monitoring service builds overview from seeded runtime state.
  - stale running signal is generated.
  - failed task signal is generated.
  - issue creation from signal writes a real health issue.
  - task detail returns graph health projection when available.

Frontend:

- `npm run build`.
- Browser validation on `http://localhost:3000/`.
- Confirm right monitor dock renders:
  - summary
  - task rows
  - signal severity
  - selected task detail
  - embedded task graph monitor.

Runtime smoke:

- Start project stack.
- Call:
  - `/health`
  - `/api/health-system/monitoring/overview`
  - `/api/health-system/monitoring/signals`
  - one selected task detail endpoint.

## 10. Main Risks

### Risk: Stale `running` tasks produce noisy alerts

Control:

- First version should mark stale signals as `warning`, not `critical`.
- Critical only when failed/aborted/blocking state is explicit.

### Risk: Health workbench becomes noisy

Control:

- Right dock shows real-time operational signals.
- Health workbench shows incidents and actionable diagnosis/recovery items.
- Do not dump every signal into the issue list.

### Risk: API duplication

Control:

- Runtime-loop APIs remain raw fact/control APIs.
- Health monitoring APIs are projection/governance APIs.
- The frontend should prefer health monitoring APIs for product UI.

### Risk: Creating issues too aggressively

Control:

- First version does not auto-create issues.
- User action or health command creates issues from signals.
- Later automation can be added only after signal quality is proven.

## 11. Non-Goals For First Implementation

- No visual office/map animation layer.
- No automatic remediation loop.
- No external alert integrations.
- No long-term metrics database.
- No configuration UI for thresholds.
- No WebSocket requirement; polling is acceptable for first version.

## 12. Final Target

After this plan is implemented, the project should have a mature first-version health monitoring architecture:

- Runtime-loop records and exposes facts.
- Health monitoring interprets facts into signals.
- Health system turns signals into issues, reports, commands, recovery candidates, and verification.
- Frontend gives a low-noise, actionable monitor dock and a deeper health workbench.
