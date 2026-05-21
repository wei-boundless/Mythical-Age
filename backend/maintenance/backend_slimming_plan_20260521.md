# Backend Slimming Plan - 2026-05-21

## Scope

This first slimming pass only touches backend structure. It does not change API response shapes, task graph contracts, prompt wording, storage schemas, or runtime event names.

## Current Structural Problem

`orchestration/runtime_loop/task_run_loop.py` is carrying runtime orchestration plus policy details that are not part of the main loop. The most obvious removable responsibility in this pass is sandbox workspace policy: output scope inference, inherited workspace selection, sandbox root materialization, and continuation matching.

Runtime data folders under `backend/` also create repository noise. They should be treated as generated runtime state, not source structure.

## Target Design For This Pass

1. `TaskRunLoop` remains the owner of run lifecycle and event emission.
2. Sandbox policy calculation moves to a dedicated runtime-loop module.
3. The sandbox module owns pure policy rules and the small lookup needed to inherit previous workspace keys.
4. Existing business behavior remains equivalent: professional runs still emit `runtime_sandbox_prepared`, use the same event payload shape, and keep workspace inheritance for compatible follow-up turns.
5. Backend runtime residue is ignored at the repository boundary so generated files stop appearing as source changes.

## File-Level Changes

- Add `backend/orchestration/runtime_loop/sandbox_policy.py`.
- Update `backend/orchestration/runtime_loop/task_run_loop.py` to delegate sandbox policy preparation.
- Add focused regression tests for sandbox policy behavior.
- Update `.gitignore` for backend generated runtime folders.

## Validation

- Run the new sandbox policy regression tests.
- Run professional runtime tests that assert `runtime_sandbox_prepared` behavior.
- Run a targeted import/compile check for the modified runtime-loop modules.

## Non-Goals

- No API restructuring in this pass.
- No prompt contract changes in this pass.
- No task graph data migration in this pass.
- No deletion of user-authored config or task storage data in this pass.
