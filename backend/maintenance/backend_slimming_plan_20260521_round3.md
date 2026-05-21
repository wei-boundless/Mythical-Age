# Backend Slimming Plan Round 3 - 2026-05-21

## Scope

Continue backend-only slimming after extracting sandbox policy and quality gates. This pass does not change task graph payload schemas, runtime object payloads, event names, prompt text, or API response shapes.

## Structural Problem

`orchestration/runtime_loop/task_run_loop.py` still contains task graph dispatch compilation helpers. These helpers transform graph payloads and runtime specs into `AgentDispatchPlan` objects. They are pure compilation/normalization logic, not loop lifecycle logic.

Keeping this code in `TaskRunLoop` makes the runtime loop file a catch-all for graph compilation, runtime execution, event persistence, supervision, and recovery.

## Target Design

1. Move task graph dispatch compilation helpers into `orchestration/runtime_loop/dispatch_plan_compiler.py`.
2. Keep `TaskRunLoop` responsible for calling the compiler and persisting resulting runtime objects.
3. Keep behavior and payload shapes identical.
4. Update tests or imports only where they directly reference compiler helpers.

## File-Level Changes

- Add `backend/orchestration/runtime_loop/dispatch_plan_compiler.py`.
- Move these helpers out of `task_run_loop.py`:
  - `_compile_agent_dispatch_plan_from_graph_payload`
  - `_dispatch_graph_payload_from_task_graph_runtime_spec`
  - `_normalize_runtime_graph_payload`
  - `_runtime_spec_from_payload`
  - `_dispatch_nodes_from_payload`
  - `_dict_tuple`
  - `_dispatch_edges_from_payload`
- Import `_compile_agent_dispatch_plan_from_graph_payload` back into `task_run_loop.py`.

## Validation

- Compile the new module and `task_run_loop.py`.
- Run professional task run regression tests.
- Run graph/config regression tests that exercise modular novel graph payloads.
