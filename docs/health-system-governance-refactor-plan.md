# Health System Governance Refactor Plan

## Goal

Refactor the health system from a mixed testing, experiment, and diagnostic workbench into an agent runtime governance center.

The health system will manage:

- Task risk
- System risk
- Token usage
- Runtime efficiency

It will no longer own system testing, experiment running, long scenario management, regression sample promotion, or validation harness workflows.

## Target Authority Chain

```text
Task records
  -> Runtime monitor
      -> Health governance
```

### Task Records

Task records are the factual ledger. They record task runs, task orders, sessions, agents, tools, artifacts, errors, token usage, duration, and lifecycle status.

They do not decide risk level.

### Runtime Monitor

The runtime monitor observes live state: running tasks, waiting tasks, failed tasks, stuck tasks, SSE state, sandbox state, backend availability, and task graph monitor state.

It does not own long-term governance analysis.

### Health Governance

Health governance consumes task records and runtime monitor signals. It creates risk events, task health records, token pressure summaries, efficiency metrics, and recommendations.

It does not run tests or experiments.

## New Health Domains

### Overview

Show the current operational health of the agent system:

- Highest risk
- Running task count
- Waiting task count
- Failed task count
- Token pressure
- Efficiency pressure
- Recent risk events

### Task Health

Show task records as the main health object:

- `task_run_id`
- `session_id`
- `task_order_id`
- `title`
- `status`
- `risk_level`
- `duration_seconds`
- `agent_count`
- `tool_call_count`
- `error_count`
- `token_total`
- `latest_risk_event`

### System Risk

Show operational risks:

- Backend/API availability
- Frontend stream health
- Runtime monitor stream status
- Docker or sandbox availability
- Model service issues
- Tool execution failures

### Token Usage

Show token cost by:

- Task
- Session
- Agent
- Model
- Context pressure

### Runtime Efficiency

Show performance and waste signals:

- Duration
- Idle time
- Retry count
- Loop count
- Tool wait time
- Tokens per output
- Efficiency score

## API Boundary

Keep health system API focused on governance:

```text
GET /api/health-system/overview
GET /api/health-system/tasks
GET /api/health-system/tasks/{task_run_id}
GET /api/health-system/risks
GET /api/health-system/system-risks
GET /api/health-system/token-usage
GET /api/health-system/efficiency
GET /api/health-system/recommendations
```

Remove health-system maintenance API exposure:

```text
/api/health-system/maintenance/test-system/*
/api/health-system/maintenance/experiments/*
```

Testing and experiment infrastructure can later become a separate verification system if needed. It must not remain under the health system authority.

## Frontend Boundary

Rewrite the health system page around five primary views:

- Overview
- Task Health
- System Risk
- Token Usage
- Runtime Efficiency

Remove health UI for:

- Verification center
- Test profiles
- Test runs
- Managed test cases
- Long scenarios
- Regression samples
- Experiment runs

Raw traces must only appear in expandable details. The first-level UI must show semantic operational information.

## Implementation Steps

1. Add this plan as the implementation contract.
2. Audit existing backend health endpoints, task records, runtime monitor, and token sources.
3. Implement a health governance builder that reads task records and monitor data.
4. Replace health system API with governance endpoints.
5. Rewrite frontend health system API types and page layout.
6. Delete obsolete test-system and experiment UI/API references from the health system surface.
7. Update or remove tests that protect the old health maintenance authority.
8. Add focused tests for the new governance overview.
9. Run backend tests, frontend type check, and browser verification.

## Verification

Backend:

```powershell
pytest backend/tests/health_workbench_regression.py
pytest backend/tests/health_management_control_plane_regression.py
```

Frontend:

```powershell
cd frontend
npx tsc --noEmit --pretty false
npm test -- --run
```

Browser:

- Open `http://127.0.0.1:3000`
- Enter the health system
- Confirm the page centers on task health, system risk, token usage, and efficiency
- Confirm no test-system or experiment management pages remain visible
