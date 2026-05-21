# Runtime Loop Package Layout Plan 2026-05-22

## Scope

Backend only. Ignore stale `docs/`, frontend, and generated runtime artifacts. This round does not continue extracting new business logic. It reorganizes the already split runtime-loop modules into explicit subpackages so the architecture has real directory-level boundaries.

## Current Problem

`backend/orchestration/runtime_loop/` now contains many smaller modules, but they are still flat. The old god files are smaller, yet the package itself is becoming a flat junk drawer. That makes ownership unclear:

- task-run orchestration modules sit beside coordination graph modules;
- professional-mode policies sit beside generic shared protocols;
- graph scheduler/batch runtime modules sit beside model/tool execution helpers;
- memory/timeline/state-index modules are mixed with user-facing runtime entrypoints.

## Target Package Layout

```text
backend/orchestration/runtime_loop/
  task_run/
  coordination/
  professional/
  graph/
  execution/
  contracts/
  memory/
  shared/
```

## File Ownership

### task_run

- `task_run_loop.py` -> `task_run/loop.py`
- `task_run_finalizer.py` -> `task_run/finalizer.py`
- `artifact_path_utils.py` -> `task_run/artifact_paths.py`
- `sandbox_policy.py` -> `task_run/sandbox_policy.py`
- `quality_gates.py` -> `task_run/quality_gates.py`
- `dispatch_plan_compiler.py` -> `task_run/dispatch_plan_compiler.py`
- `task_artifact_materializer.py` -> `task_run/artifact_materializer.py`

### coordination

- `langgraph_coordination_runtime.py` -> `coordination/runtime.py`
- `coordination_memory_helpers.py` -> `coordination/memory_helpers.py`
- `coordination_result_helpers.py` -> `coordination/result_helpers.py`
- `coordination_runtime_payloads.py` -> `coordination/runtime_payloads.py`
- `coordination_flow.py` -> `coordination/flow.py`
- `coordination_trace_adapter.py` -> `coordination/trace_adapter.py`
- `langgraph_coordination_runner.py` -> `coordination/runner.py`
- `langgraph_checkpoint_adapter.py` -> `coordination/checkpoint_adapter.py`
- `langgraph_runtime_kernel.py` -> `coordination/runtime_kernel.py`
- `context_packet_resolver.py` -> `coordination/context_packet_resolver.py`
- `review_gate_verdict.py` -> `coordination/review_gate_verdict.py`

### professional

- `professional_task_run_driver.py` -> `professional/driver.py`
- `professional_goal_contract.py` -> `professional/goal_contract.py`
- `professional_tool_contract_gate.py` -> `professional/tool_contract_gate.py`
- `professional_runtime_policy.py` -> `professional/runtime_policy.py`
- `professional_evidence_closeout.py` -> `professional/evidence_closeout.py`
- `professional_run_session.py` -> `professional/run_session.py`
- `professional_state_machine.py` -> `professional/state_machine.py`

### graph

- `task_graph_scheduler.py` -> `graph/scheduler.py`
- `task_graph_scheduler_models.py` -> `graph/scheduler_models.py`
- `task_graph_batch_runtime.py` -> `graph/batch_runtime.py`
- `task_graph_monitoring.py` -> `graph/monitoring.py`
- `task_graph_run_monitor.py` -> `graph/run_monitor.py`

### execution

- `agent_delegation_executor.py` -> `execution/agent_delegation_executor.py`
- `child_agent_runtime_executor.py` -> `execution/child_agent_runtime_executor.py`
- `node_execution_request.py` -> `execution/node_execution_request.py`
- `node_execution_a2a_payload.py` -> `execution/node_execution_a2a_payload.py`
- `node_handoff_protocol.py` -> `execution/node_handoff_protocol.py`
- `delegation_models.py` -> `execution/delegation_models.py`

### contracts

- `contract_compiler.py` -> `contracts/compiler.py`
- `contract_compiler_models.py` -> `contracts/compiler_models.py`
- `continuation_policy.py` -> `contracts/continuation_policy.py`
- `continuation_inputs.py` -> `contracts/continuation_inputs.py`
- `length_budget_compiler.py` -> `contracts/length_budget_compiler.py`
- `obligation_validation.py` -> `contracts/obligation_validation.py`
- `deliverable_validator.py` -> `contracts/deliverable_validator.py`
- `runtime_assembly_builder.py` -> `contracts/runtime_assembly_builder.py`
- `runtime_assembly_models.py` -> `contracts/runtime_assembly_models.py`

### memory

- `project_supervision.py` -> `memory/project_supervision.py`
- `evidence_packet.py` -> `memory/evidence_packet.py`
- `tool_observation_ledger.py` -> `memory/tool_observation_ledger.py`
- `timeline_ledger.py` -> `memory/timeline_ledger.py`
- `timeline_result_record.py` -> `memory/timeline_result_record.py`
- `trace_reader.py` -> `memory/trace_reader.py`
- `state_index.py` -> `memory/state_index.py`
- `observation_aggregator.py` -> `memory/observation_aggregator.py`

### shared

- `models.py` -> `shared/models.py`
- `events.py` -> `shared/events.py`
- `event_log.py` -> `shared/event_log.py`
- `checkpoint.py` -> `shared/checkpoint.py`
- `artifact_refs.py` -> `shared/artifact_refs.py`
- `protocol_boundary.py` -> `shared/protocol_boundary.py`
- `safety.py` -> `shared/safety.py`
- `action_request.py` -> `shared/action_request.py`
- `resume_decision.py` -> `shared/resume_decision.py`
- `loop_control.py` -> `shared/loop_control.py`
- `model_adoption.py` -> `shared/model_adoption.py`
- `tool_adoption.py` -> `shared/tool_adoption.py`
- `tool_repetition_guard.py` -> `shared/tool_repetition_guard.py`
- `runtime_object_store.py` -> `shared/runtime_object_store.py`
- `stage_projection.py` -> `shared/stage_projection.py`
- `execution_record.py` -> `shared/execution_record.py`
- `context_manager.py` -> `shared/context_manager.py`

## Dependency Rule

Allowed direction:

```text
task_run / coordination / professional
  -> graph / execution / contracts / memory
  -> shared
```

No compatibility wrapper modules should be kept unless a public import path is demonstrably required by external API code. Tests should import the new owner modules.

## Validation

- `python -m py_compile` over all runtime-loop Python files.
- coordination runtime regression.
- task graph registry/scheduler regression.
- professional runtime regression.
- query runtime loop regression.
- writing modular novel graph config regression.
