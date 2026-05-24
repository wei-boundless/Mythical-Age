# Remove Model-Turn Sidecar Plan 2026-05-24

## Goal

Make main-model-owned understanding the only request understanding path. Remove the model-turn sidecar branch instead of keeping it behind an environment switch.

## Principles

- The main agent owns interaction intent, action intent, task goal type, target objects, constraints, planning need, and todo need.
- Runtime may record facts and expose capabilities, but must not run a hidden parallel model to decide the turn.
- There must be one understanding authority in the current turn chain.
- No compatibility shell for the old sidecar path.

## Scope

1. Remove `SYSTEM_DISABLE_MODEL_TURN_SIDECAR` and the branch that chooses between sidecar and main-model-owned decision.
2. Remove `_structured_sidecar_invoker` and model-turn sidecar diagnostics from `runtime/unit_runtime/loop.py`.
3. Delete the model-turn decision sidecar invoker module if it has no non-sidecar role.
4. Remove or rename generic structured sidecar plumbing if it is now unused.
5. Clean tests and stubs that simulate the old sidecar route.
6. Run targeted static checks and search for remaining executable sidecar references.

## Expected Result

The current-turn chain always builds a main-model-owned decision from the model-visible request context and task selection. Any remaining `sidecar` text must be historical docs only or deleted test history, not executable runtime.
