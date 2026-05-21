# Backend Slimming Plan 2026-05-21 Round 4

## Scope

Only backend runtime-loop code is in scope. Do not use stale docs as authority.

## Structural Problem

`TaskRunLoop` still owns too many responsibilities. The worst remaining hotspot is task finalization:

- materializing task artifacts
- recording artifact repository entries
- upserting task and agent run terminal state
- resuming LangGraph coordination from a node result
- updating project supervision and delivery progress
- constructing continuation payloads for the next coordination node

This makes the main loop look like the business logic itself, when it should be the lifecycle shell around specialized services.

## Target Refactor

Create a dedicated task-run finalization service:

- `runtime_loop.task_run_finalizer.TaskRunFinalizer`
- `runtime_loop.task_run_finalizer.FinishedTaskRunResult`

`TaskRunLoop` will retain the public orchestration lifecycle and delegate completion persistence/resume work to the finalizer.

Shared artifact path helpers will move out of `task_run_loop.py` so the finalizer does not import the loop and create circular ownership.

## Implementation Steps

1. Extract workspace/write-result artifact helpers to `artifact_path_utils.py`.
2. Add `TaskRunFinalizer` with explicit runtime dependencies.
3. Move and reshape finalization code into service methods with internal sections:
   - artifact materialization
   - terminal state persistence
   - coordination resume
   - project supervision update
4. Replace `TaskRunLoop._upsert_finished_task_run` with a thin delegation wrapper.
5. Remove finalization-only methods from `TaskRunLoop`.
6. Run focused backend regression tests.

## Non-Goals

- Do not change task graph business rules.
- Do not change prompts or generated content behavior.
- Do not touch frontend.
- Do not restore generated runtime-state files that were intentionally removed from git tracking.
