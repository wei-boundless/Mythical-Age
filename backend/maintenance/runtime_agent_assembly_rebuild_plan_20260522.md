# Runtime Agent Assembly Rebuild Plan - 2026-05-22

## Source Findings

This plan is based on the current backend code, not old docs.

The runtime assembly layer is still structurally confused in four concrete places:

1. `LangGraphCoordinationRuntimeResult.continuation_payload()` builds a clean `runtime_control` object but also returns full `stage_execution_request`, `node_work_order`, `agent_assembly_contract`, and `a2a_payload` at the top level for agent continuation. The same authority object therefore travels through multiple paths.
2. `current_turn_context` currently carries runtime-control material such as raw `a2a_payload` and raw `explicit_inputs`. That makes model-visible context and runtime control state indistinct.
3. `AgentRuntimeChainAssembler.build_runtime()` accepts `agent_assembly_contract`, but it still re-merges raw `task_selection` and `current_turn_context_override` in ad hoc ways. This means stale routing data can override or pollute the current turn unless every caller remembers the right exclusions.
4. GraphModule diagnostics still stores full parent assembly/work-order objects where refs and summaries are enough. That inflates runtime state and increases the chance that parent control data leaks into child runs.

The problem is not just "too many files". The broken system property is that runtime assembly has no hard boundary between:

- control objects used by runtime code;
- model-visible context used to prompt the agent;
- routing/task-selection hints used to assemble the agent runtime;
- diagnostics used for traceability.

## Target Design

Runtime agent assembly must have one canonical boundary module:

`backend/runtime/agent_assembly/boundary.py`

It owns these projections:

- `build_runtime_control_payload(...)`: keeps full control objects for runtime-only consumers.
- `build_model_context_payload(...)`: returns only model-safe context fields.
- `build_task_selection_payload(...)`: returns only routing and assembly identity fields.
- `agent_assembly_contract_from_runtime_control(...)`: recovers the contract from the runtime control plane, not from model context.
- `runtime_control_ref_summary(...)`: produces compact refs for diagnostics.

Hard rules:

1. Agent continuation may use full control objects only through `runtime_control`.
2. `current_turn_context` must not carry `stage_execution_request`, `node_work_order`, `agent_assembly_contract`, `execution_permit`, `runtime_control`, `graph_module_runtime_handle`, raw `a2a_payload`, or unfiltered protocol inputs.
3. `task_selection` must be a routing projection, not a dump of control objects.
4. Assembly contract identity must override stale task-selection agent identity.
5. GraphModule diagnostics may keep refs, standard input diagnostics, and compact summaries, but not full parent assembly contracts.

## Execution Checklist

1. Add `backend/runtime/agent_assembly/boundary.py` and move projection logic there.
2. Update `LangGraphCoordinationRuntimeResult.continuation_payload()` to use boundary projections.
3. Update `TaskRunLoop` continuation helpers to consume `runtime_control` first and stop recovering contracts from model context.
4. Update `AgentRuntimeChainAssembler.build_runtime()` to sanitize task-selection and override payloads through the same boundary.
5. Update GraphModule diagnostics to store assembly refs and compact summaries instead of full contracts.
6. Delete unused snapshot helper methods in `AgentAssemblyContract` if no callers exist.
7. Update regression tests for:
   - no full control objects in model context;
   - no raw `a2a_payload` in agent model context;
   - assembly contract still overrides stale task selection;
   - GraphModule diagnostics use refs/summaries.
8. Run focused tests and compile checks.

## Non-Goals

- Do not refactor task graph semantics.
- Do not touch monitoring/observability.
- Do not touch frontend.
- Do not preserve dead compatibility shells just to avoid deleting old code.

## Validation

Minimum commands:

- `pytest backend/tests/coordination_node_work_order_regression.py backend/tests/node_execution_request_regression.py backend/tests/query_runtime_runtime_loop_regression.py backend/tests/task_graph_permission_boundary_regression.py backend/tests/task_system_api_regression.py -q`
- `pytest backend/tests/langgraph_coordination_runtime_regression.py backend/tests/agent_assembly_models_regression.py backend/tests/runtime_context_prompt_regression.py -q`
- `python -m compileall backend/runtime/agent_assembly backend/runtime/coordination_runtime backend/runtime/unit_runtime backend/runtime/subruntime backend/agent_system/assembly backend/task_system/services`
