# Backend Slimming Plan Round 2 - 2026-05-21

## Scope

This pass continues backend-only slimming. It does not change task graph schemas, API responses, prompt text, runtime event names, or acceptance result payload shapes.

## Current Structural Problem

`orchestration/runtime_loop/task_run_loop.py` still owns a large block of quality and acceptance rules:

- stream and artifact policy extraction
- length budget quality gates
- stage business acceptance
- sectioned chapter/batch quality gates
- review verdict handoff

These are business validation rules, not runtime-loop lifecycle mechanics. Keeping them inside the loop makes the loop harder to reason about and encourages future feature patches to land in the same oversized file.

## Target Design For This Pass

1. `TaskRunLoop` remains the lifecycle owner.
2. Runtime quality/acceptance rules move to a dedicated module.
3. Existing private helper imports remain available from `task_run_loop.py` during this pass, so current tests and call sites keep working while implementation ownership moves.
4. The quality gate module owns text metrics, section parsing, review-gate acceptance, stream policy extraction, and artifact policy extraction.

## File-Level Changes

- Add `backend/orchestration/runtime_loop/quality_gates.py`.
- Update `backend/orchestration/runtime_loop/task_run_loop.py` to import these functions instead of defining them inline.
- Keep backwards-compatible aliases in `task_run_loop.py` for existing tests during this pass.
- Keep or migrate targeted quality-gate tests.

## Validation

- Run length budget and chapter draft quality-gate regressions.
- Run review gate verdict regressions.
- Run model response stream policy regression.
- Re-run professional task run regressions because they exercise business acceptance from the real runtime path.
