# Request Pipeline Cleanup Plan - 2026-05-24

## Problem

The request pipeline still contains duplicated interpretation layers. `IntentFrame`,
`IntentDecision`, `TaskUnderstandingFrame`, `runtime_assembly_hint`, and
runtime-chain operation selection all compete with the newer request/task contract
layers. The broken property is ownership, not file size.

## Target Boundary

1. `RequestSignals` collects weak current-turn signals only.
2. `TurnBinding` / current-turn context binds explicit inputs and continuation
   candidates. Restore produces candidates, not business decisions.
3. `TaskGoalSpec` owns user outcome, deliverables, constraints, and failure shape.
4. `TaskRequirementContract` is the first hard task contract.
5. `ExecutionShape` chooses recipe from an ordered policy chain.
6. `OperationRequirement` is the only pre-permit operation requirement source.
7. `RuntimeSpec` binds agent identity, prompt, model, memory scope, and visible tools.
8. `ExecutionPermit` owns executable permission boundaries.
9. `RuntimeLoop` executes and recovers; it does not reinterpret intent.
10. `OutputBoundary` presents validated results.

## Cleanup Decisions

- Delete `IntentFrame` and `IntentDecision` from the active request path.
- Delete `runtime_assembly_hint` as a decision input.
- Delete runtime-chain operation selection. Operation requirements must be derived
  inside task assembly from recipe, task binding, skill scope, and operation policy.
- Demote `TaskUnderstandingFrame` into goal evidence, then remove it from public
  task-goal payloads.
- Rename unclear API concepts in the active path:
  - `query_understanding` becomes request signals in new code and diagnostics.
  - `route_hint` becomes source/material hint in later API cleanup.

## Execution Order

1. Remove old intent imports and construction from `AgentRuntimeChainAssembler`.
2. Change continuation collection/decision to consume `RequestSignals`.
3. Stop passing `runtime_assembly_hint` through current-turn context and task
   assembly decisions.
4. Stop passing `runtime_required_operations` from the runtime chain.
5. Remove `TaskUnderstandingFrame` from `TaskGoalSpec` output and keep only
   goal evidence/hypothesis data.
6. Update tests that assert old public structures.
7. Run focused regression tests for request intent, task goal, runtime assembly,
   and orchestration boundaries.

## Completion Criteria

- The main request path has no active dependency on `IntentFrame`,
  `IntentDecision`, or `runtime_assembly_hint`.
- Runtime chain no longer maps request hints to operation ids.
- Task goal payload no longer exposes `TaskUnderstandingFrame`.
- Tests assert the new hard boundaries rather than old compatibility fields.
