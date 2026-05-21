# Backend API Control-Plane Slimming Plan 2026-05-22

## Problem

`backend/api/orchestration.py` is still carrying multiple backend surfaces in one file:

- agent/profile/group configuration
- orchestration catalog and runtime option previews
- delegation catalog previews
- runtime-loop trace, monitor, artifact, approval, stop endpoints
- task graph run start
- coordination run dispatch/resume/continue/rewind
- graph-module recovery and stage execution helpers

This makes the file a structural bottleneck. The business logic is not necessarily wrong, but the ownership boundary is wrong: runtime-loop control endpoints are mixed with orchestration configuration and graph coordination recovery code.

## Current Slice

Extract runtime-loop control-plane endpoints into `backend/api/orchestration_runtime_loop.py`.

This slice moves endpoints that directly delegate to `runtime.query_runtime.task_run_loop` and do not need the heavy graph coordination helper stack in `api/orchestration.py`.

Moved surface:

- session task-run listing
- session live monitor
- task-run trace
- task-run live monitor
- task-graph monitor read/evaluate
- monitor decisions
- task-run artifacts
- task-run memory receipts
- task-run approval resolution
- project runtime status
- task-run stop

## Non-Goals For This Slice

- Do not move graph start yet.
- Do not move coordination-run resume/continue/rewind yet.
- Do not alter endpoint paths or response payload shape.
- Do not keep duplicate routes in both files.

## Completion Criteria

- `backend/api/orchestration.py` no longer owns runtime-loop query/control endpoints.
- `backend/app.py` registers the new router.
- Compile checks pass for backend API/runtime/task-system packages.
- Runtime-loop and orchestration regression tests pass.

## Implemented Status

Completed in this slice:

- Added `backend/api/orchestration_runtime_loop.py` for runtime-loop trace, monitor, artifacts, memory receipts, approval, project runtime status, and stop endpoints.
- Added `backend/api/orchestration_catalog.py` for orchestration catalog, agent/group/profile configuration, runtime options, delegation catalog, dry-run, previews, resource inventory, and plan mode.
- Reduced `backend/api/orchestration.py` to task graph run start plus coordination run monitor/dispatch/resume/continue/rewind API handlers.
- Moved coordination execution service logic out of the API layer into:
  - `backend/orchestration/coordination_scheduler.py`
  - `backend/orchestration/coordination_replay.py`
  - `backend/orchestration/coordination_rewind.py`
  - `backend/orchestration/coordination_recovery.py`
  - `backend/orchestration/coordination_control.py` as a small aggregation facade.
- Updated tests that were coupled to `api.orchestration` private helpers so they now target the owning service modules.

Completed in the follow-up consolidation slice:

- Consolidated recovery quality checks in `backend/orchestration/coordination_recovery.py` so breakpoint recovery now calls the canonical `runtime.unit_runtime.quality_gates._stage_business_acceptance` path instead of maintaining separate review-gate and chapter-draft recovery gates.
- Removed the old local recovery helpers for review verdict recovery and chapter draft heading/word checks.
- Added `backend/runtime/execution/graph_module_runtime.py` as the single builder/normalizer for GraphModule runtime handles.
- Updated `backend/runtime/coordination_runtime/runtime.py` and `backend/orchestration/coordination_scheduler.py` to consume the shared GraphModule handle builder instead of duplicating field/default logic.
- Updated recovery quality tests to target the new owner module rather than the old `api.orchestration` private helper path.

Size check after this slice:

- `backend/api/orchestration.py`: about 34 KB, down from about 159 KB before this slice.
- Runtime-loop API is about 11 KB.
- Catalog/configuration API is about 30 KB.
- The largest remaining orchestration service file is `coordination_recovery.py` at about 38 KB after the recovery-gate consolidation.
- `coordination_scheduler.py` is about 21 KB after GraphModule handle construction was moved to `runtime/execution/graph_module_runtime.py`.

Validation passed:

- `python -m compileall -q backend/api backend/orchestration backend/runtime backend/task_system backend/tests`
- `python -m pytest backend/tests/task_system_api_regression.py` -> 28 passed.
- `python -m pytest backend/tests/query_runtime_runtime_loop_regression.py backend/tests/orchestration_cutover_regression.py backend/tests/runtime_recovery_idempotency_regression.py` -> 13 passed.
- `python -m pytest backend/tests/langgraph_coordination_runtime_regression.py` -> 34 passed.
- `python -m pytest backend/tests/chapter_draft_quality_gate_regression.py backend/tests/review_gate_verdict_regression.py backend/tests/task_system_api_regression.py` -> 39 passed.
- `python -m pytest backend/tests/node_execution_request_regression.py backend/tests/node_handoff_protocol_test.py backend/tests/chapter_draft_quality_gate_regression.py backend/tests/review_gate_verdict_regression.py` -> 21 passed.
- `python -m pytest backend/tests/task_system_api_regression.py backend/tests/langgraph_coordination_runtime_regression.py` -> 62 passed.

Notes:

- A single combined run of the above long tests exceeded a 300 second timeout before returning a result. The same test set passed when split into smaller groups.
- Route scan shows `/orchestration/*` endpoints are now distributed across `orchestration.py`, `orchestration_runtime_loop.py`, and `orchestration_catalog.py` with no duplicate route definitions found by path scan.

## Next Structural Targets

After this slice, the remaining work is no longer mainly in `api/orchestration.py`. The next structural targets are:

- Split `backend/orchestration/coordination_recovery.py` further if graph-module packet construction and generic completed-stage recovery continue to grow.
- Move GraphModule packet construction out of `coordination_recovery.py` if it keeps accumulating imported-run output/failure packet details.
- Audit remaining tiny utility duplication (`_safe_int`, `_dedupe_strings`, path/hash helpers) and only extract where it removes real cross-module drift.
- Consider renaming `backend/api/orchestration.py` to a narrower task graph coordination API module after frontend/import callers are checked.
- Continue slimming `backend/api/task_system.py`, now the largest API file.
