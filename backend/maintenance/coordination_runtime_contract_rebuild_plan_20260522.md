# Coordination + Runtime Agent Assembly Rebuild Plan 2026-05-22

## 0. Scope

Backend only. Do not use stale docs as authority. This plan is based on the current backend code paths for task graph coordination, agent runtime assembly, model/tool execution, permission adoption, GraphModule execution, result acceptance, and recovery.

This is not a directory-only slimming plan. The target is to rebuild the contract boundary around one central agent assembly layer:

- task graph coordination: decide which node runs, with which inputs, under which graph state;
- agent assembly: decide which agent identity/profile/projection/model/context/capabilities/permissions are active;
- execution engine: run one agent/human/sub-runtime with a sealed contract;
- result acceptance: turn execution output into graph state, task result, memory writeback, and trace.

## 1. Real Problem

The system currently has two overlapping runtimes:

1. `LangGraphCoordinationRuntime` owns graph stage state and emits `NodeExecutionRequest`.
2. `TaskRunLoop` owns single-agent execution and then reinterprets the node request through `task_selection`, `current_turn_context`, runtime chain assembly, resource adoption, context assembly, model execution, tool execution, finalizer, and recovery.

The broken system property is not file size. The broken property is that agent assembly is not canonical. The same turn is represented as:

- `stage_execution_request`
- `NodeExecutionRequest`
- `task_selection`
- `current_turn_context`
- `task_operation`
- `task_body_orchestration`
- `agent_runtime_spec`
- `runtime_assembly`
- `ResourcePolicy`
- `RuntimeDirective`
- `RuntimeLoopState`
- `TaskRunLedger`

These are not clean layers. They are overlapping descriptions of the same run. As a result, the code keeps adding fields to defend against missing information from another layer.

Correct end state:

```text
TaskGraphRuntime
  -> WorkOrder
  -> AgentAssemblyContract
  -> ExecutionPermit
  -> ExecutionEngine | HumanExecutionEngine | SubRuntimeExecutionEngine
  -> ExecutionResult
  -> NodeResultCommitter
  -> TaskGraphRuntime.accept_result
```

Direct user turns enter at `DirectWorkOrder`; task graph nodes enter at `NodeWorkOrder`. Both must converge through the same `AgentAssemblyContract` before execution. No layer after agent assembly may infer agent identity, permissions, prompt role, input scope, graph module linkage, or result ownership from loose dicts.

## 2. Technical Source Report

### 2.1 Coordination Builds A Request, Runtime Rebuilds The Run

Current evidence:

- `backend/runtime/coordination_runtime/runtime.py:2376` creates `NodeExecutionRequest`.
- `backend/runtime/unit_runtime/loop.py:4233` converts continuation payload back into `task_selection`.
- `backend/agent_system/assembly/runtime_chain.py:1233` rebuilds runtime using that `task_selection`.
- `backend/agent_system/assembly/runtime_bundle_builder.py:16` builds another orchestration runtime bundle.

Problem:

The graph runtime already knows the node, task ref, agent, inputs, memory/artifact packets, and executor binding. But the single-agent loop still rebuilds the runtime from broad context. This creates double assembly and drift.

Required decision:

Coordination may compile a `NodeWorkOrder`. The agent assembly layer must assemble `AgentAssemblyContract` from that work order. Runtime must not reinterpret node identity or executor type from `task_selection`.

### 2.2 `stage_execution_request` Is Too Wide

Current evidence:

- `backend/runtime/execution/node_execution_request.py:10` contains executor binding, explicit inputs, standard input package, human packet, runtime assembly, a2a payload, artifact policy, stream policy, artifact targets, memory snapshot, artifact packet, revision packet, handoff refs, and timeline policy.

Problem:

This object is simultaneously command, context bundle, prompt material, executor-specific payload, and recovery evidence. It cannot remain the boundary object.

Required decision:

`NodeExecutionRequest` becomes a thin compatibility command during migration. The durable coordination-to-assembly shape becomes `WorkOrder`, and executor-specific details move into typed assembly inputs or sub-runtime work orders.

### 2.3 `current_turn_context` And `task_selection` Are Control-State Bags

Current evidence:

- `backend/agent_system/assembly/runtime_chain.py:140` applies arbitrary overrides into current turn context.
- `backend/runtime/unit_runtime/loop.py:1239` passes `task_selection` both as task selection and context override.
- `backend/runtime/unit_runtime/loop.py:4272` reconstructs a continuation task selection from current turn context keys.

Problem:

These dicts currently carry agent id, projection id, explicit inputs, stage request, graph coordination id, continuation stage id, artifact roots, runtime limits, and a2a payload. They are not a contract; they are an untyped tunnel.

Required decision:

`current_turn_context` may carry user/session/turn signals and non-authoritative hints. It must not be the source of truth for agent identity, executor type, permissions, node input package, or graph state.

### 2.4 Permissions Are Adopted In Multiple Places

Current evidence:

- `backend/runtime/shared/model_adoption.py:16` builds model directive and `ResourcePolicy`.
- `backend/runtime/unit_runtime/loop.py:4890` filters tool instances again.
- `backend/runtime/shared/tool_adoption.py:12` adopts each tool request again.
- `backend/runtime/tool_runtime/tool_executor.py:17` executes after another directive/action/request layer.

Problem:

The system has three related but separate concepts: model-visible tools, operation-gate permissions, and sandbox execution. These should be one sealed `ExecutionPermit`, not three partially overlapping decisions.

Required decision:

Build `ExecutionPermit` once from `AgentAssemblyContract`. Model tool visibility, operation gate, approval state, sandbox mode, and executor dispatch must all consume that permit.

### 2.5 Coordination And TaskRunLoop Have Two State Machines

Current evidence:

- Coordination state carries `node_statuses`, `stage_results`, `terminal_status`, `stage_execution_request`.
- `TaskRunLoop` carries `RuntimeLoopState`, `TaskRunLedger`, `result_refs`, `commit_state`.
- Recovery scans task runs and diagnostics to rebuild graph results in `backend/orchestration/coordination_recovery.py`.

Problem:

The two state machines are synchronized after the fact. This is why recovery code grows: it must guess which task run is a valid node result.

Required decision:

`ExecutionResult` and `NodeResultEnvelope` become the synchronization boundary. Coordination accepts typed node results. Recovery restores typed result candidates, but does not decide business acceptance from loose diagnostics.

### 2.6 GraphModule Is A Special Case Because There Is No Sub-Runtime Contract

Current evidence:

- `backend/runtime/execution/graph_module_runtime.py` builds graph module runtime handles.
- `backend/orchestration/coordination_scheduler.py:230` starts imported graph runs.
- `backend/orchestration/coordination_recovery.py:166` scans imported runs and creates output/failure packets.

Problem:

GraphModule is really "sub-runtime invocation". Because no common sub-runtime contract exists, it is represented through imported task runs, diagnostics, packets, and recovery-specific object writes.

Required decision:

Introduce `SubRuntimeInvocationContract` and `SubRuntimeResultEnvelope`. GraphModule becomes one implementation of sub-runtime execution, not a recovery special case.

### 2.7 Prompt Assembly Still Leaks Control-Layer Language

Current evidence:

- `backend/runtime/shared/context_manager.py:386` renders runtime assembly as "available reference materials" with modes like `refs_only`.
- `backend/runtime/coordination_runtime/runtime.py:3923` builds stage execution messages with generic node wording.
- `backend/runtime/unit_runtime/loop.py:6087` renders standard input package into model text.

Problem:

Agent prompts should express role, responsibility, allowed inputs, forbidden behavior, and output contract. Runtime implementation details are not useful model instructions.

Required decision:

Prompt composition moves behind `PromptComposer`. It may consume contracts, but it must not expose raw contract bookkeeping as if it were role guidance.

### 2.8 Known Immediate Bug

Current evidence:

- `backend/runtime/unit_runtime/loop.py:2399` yields non-`done` executor events.
- `backend/runtime/unit_runtime/loop.py:2403` yields the same non-`done` executor events again.

Problem:

The runtime can duplicate streamed deltas, tool-call requests, or errors.

Required decision:

Fix this in Phase 0 before deeper migration, because it is a real execution bug and will confuse validation.

## 3. Target Architecture

### 3.1 Agent Assembly As The Shared Center

Create `backend/runtime/agent_assembly/`.

Planned files:

- `models.py`
  - `WorkOrder`
  - `DirectWorkOrder`
  - `NodeWorkOrder`
  - `HumanWorkOrder`
  - `SubRuntimeWorkOrder`
  - `AgentAssemblyContract`
  - `AssemblyPort`
  - `MemoryAssemblyBinding`
  - `CapabilityAssemblyBinding`
  - `SoulAssemblyBinding`
  - `PromptAssemblyContract`
  - `OutputBoundaryBinding`
  - `ExecutionPermit`
  - `ExecutionResult`
  - `NodeResultEnvelope`
  - `SubRuntimeInvocationContract`
  - `SubRuntimeResultEnvelope`
- `validation.py`
  - work order and assembly validators
  - missing-field reports
  - fail-closed checks
- `compat.py`
  - temporary adapters from old `NodeExecutionRequest`
  - temporary adapters to old continuation payloads
- `ids.py`
  - stable work order / assembly / permit / result ids
- `assembler.py`
  - converts direct and graph-node work orders into `AgentAssemblyContract`
- `prompt_composer.py`
  - renders role-driven model instructions from `AgentAssemblyContract`
- `context_builder.py`
  - prepares compacted model context before execution
- `memory_binder.py`
  - binds memory read/write scopes
- `capability_binder.py`
  - binds tools, operations, MCP routes, and delegated agents
- `soul_binder.py`
  - binds soul/projection/prompt manifest
- `work_order_adapter.py`
  - old payload to work order bridge during migration

Core rules:

- Work orders and assembly contracts are typed dataclasses or equivalent strict models.
- Work orders say what must be done; agent assembly says who/how/with which capabilities it runs.
- Assembly contracts use explicit refs, not `diagnostics`, for ownership.
- `diagnostics` may explain, never decide.
- Empty dicts are not valid placeholders for executor-specific assembly inputs.

### 3.2 Coordination Boundary

Coordination owns:

- graph state;
- node scheduling;
- dependency resolution;
- node input package selection;
- graph-local memory/artifact/revision packets;
- batch and loop routing;
- node result acceptance into graph state.

Coordination does not own:

- model/tool execution;
- model-visible tool list;
- prompt role composition;
- final assistant session commit;
- agent profile fallback;
- sandbox execution policy details.

Target modules:

- `backend/runtime/coordination_runtime/runtime.py`
  - becomes graph state machine plus node work order producer/consumer.
- `backend/runtime/coordination_runtime/work_order_builder.py`
  - new owner for building `NodeWorkOrder`.
- `backend/runtime/coordination_runtime/node_result_committer.py`
  - new owner for accepting `NodeResultEnvelope`.
- `backend/runtime/coordination_runtime/recovery_candidates.py`
  - restores candidates only; does not construct executor-specific results from diagnostics.

### 3.3 Agent Assembly Boundary

Agent assembly owns:

- agent identity and runtime profile;
- projection/soul prompt manifest binding;
- model profile resolution input;
- context section policy;
- memory read/write scope;
- output boundary profile;
- executor role contract.

Target modules:

- `backend/runtime/agent_assembly/assembler.py`
  - builds `AgentAssemblyContract` from `DirectWorkOrder` or `NodeWorkOrder`.
- `backend/runtime/agent_assembly/prompt_composer.py`
  - produces role-contract instructions from `AgentAssemblyContract`.
- `backend/runtime/agent_assembly/context_builder.py`
  - prepares model context and enforces compaction before execution.
- `backend/runtime/agent_assembly/memory_binder.py`
  - resolves memory scopes and working/task durable memory bindings.
- `backend/runtime/agent_assembly/capability_binder.py`
  - resolves operations, visible tools, MCPs, and delegation candidates before permit creation.
- `backend/runtime/agent_assembly/soul_binder.py`
  - resolves soul/projection/prompt manifest.
- `backend/runtime/agent_assembly/result_projector.py`
  - projects execution output to `ExecutionResult`.

Execution target modules:

- `backend/runtime/execution_engine/engine.py`
  - executes model/tool loop using sealed assembly contract and permit.
- `backend/runtime/execution_engine/model_loop.py`
- `backend/runtime/execution_engine/tool_loop.py`
- `backend/runtime/execution_engine/final_output.py`

Existing modules to reduce:

- `backend/agent_system/assembly/runtime_chain.py`
- `backend/agent_system/assembly/runtime_bundle_builder.py`
- `backend/runtime/shared/context_manager.py`
- `backend/runtime/unit_runtime/loop.py`

### 3.4 Permission Boundary

Create `backend/runtime/permissions/`.

Planned files:

- `permit_builder.py`
  - builds `ExecutionPermit`.
- `tool_gateway.py`
  - maps permit to model-visible tools and dispatchable tools.
- `operation_gate_adapter.py`
  - calls existing `OperationGate` from one place.
- `sandbox_gateway.py`
  - resolves sandbox once and attaches it to permit.
- `approval_gateway.py`
  - converts approval requirements to runtime action requests.

Rules:

- The model-visible tool list must be derived from `ExecutionPermit`.
- Tool dispatch must require the same permit.
- Sandbox permission cannot silently add hidden tools unless the permit says so.
- Agent profile capability ceiling and turn-level adopted operations must both be visible in permit diagnostics, but permit fields decide.

### 3.5 Sub-Runtime Boundary

Create a generic sub-runtime invocation shape.

Target modules:

- `backend/runtime/subruntime/graph_module_executor.py`
- `backend/runtime/subruntime/models.py`
- `backend/runtime/subruntime/result_packets.py`

GraphModule target flow:

```text
NodeWorkOrder.executor = subruntime
AgentAssemblyContract.executor = subruntime
SubRuntimeInvocationContract.kind = graph_module
SubRuntimeExecutor.start()
SubRuntimeResultEnvelope
NodeResultCommitter.accept()
```

This removes GraphModule-specific imported-run packet construction from generic recovery.

## 4. Fixed Execution Flow

### 4.1 Direct Single-Agent User Turn

```text
User turn
  -> DirectWorkOrderBuilder.build()
  -> AgentAssemblyAssembler.build()
  -> PermissionGateway.build_execution_permit()
  -> ExecutionEngine.run()
  -> ExecutionResult
  -> TaskRunFinalizer.commit()
```

### 4.2 Task Graph Node

```text
LangGraphCoordinationRuntime.route_next()
  -> NodeWorkOrderBuilder.build()
  -> AgentAssemblyAssembler.build()
  -> PermissionGateway.build_execution_permit()
  -> ExecutionEngine.run()
  -> NodeResultEnvelope
  -> LangGraphCoordinationRuntime.accept_node_result()
```

### 4.3 Human Node

```text
NodeWorkOrder.executor = human
AgentAssemblyContract.executor = human
  -> HumanWorkPacketBuilder
  -> wait/resume
  -> NodeResultEnvelope
  -> LangGraphCoordinationRuntime.accept_node_result()
```

### 4.4 GraphModule Node

```text
NodeWorkOrder.executor = subruntime
AgentAssemblyContract.executor = subruntime
  -> SubRuntimeInvocationContract(kind=graph_module)
  -> GraphModuleExecutor
  -> SubRuntimeResultEnvelope
  -> NodeResultEnvelope
  -> LangGraphCoordinationRuntime.accept_node_result()
```

## 5. Migration Strategy

### 5.1 Shadow Mode

First introduce new contracts and build them alongside old payloads.

Rules:

- No behavior change in shadow mode.
- Every old `NodeExecutionRequest` gets a corresponding `NodeWorkOrder` and `AgentAssemblyContract`.
- Add tests that compare old request identity to new work order / assembly identity.
- Any mismatch must be reported as validation failure, not hidden in diagnostics.

### 5.2 Cutover Mode

After shadow tests pass:

- `TaskRunLoop` accepts `AgentAssemblyContract` as primary execution input.
- `stage_execution_request` is accepted only through `compat.py`.
- Graph node execution no longer rebuilds agent identity from `task_selection`.
- Tool visibility and dispatch both consume `ExecutionPermit`.

### 5.3 Cleanup Mode

After cutover tests pass:

- Remove old compatibility helpers.
- Remove private re-export facade patterns that only keep old import paths alive.
- Remove GraphModule packet construction from generic recovery.
- Remove business-specific writing/chapter logic from runtime packages.
- Delete tests that only validate old payload shape, replacing them with contract tests.

No indefinite compatibility layer is allowed.

## 6. Phased Execution Plan

### Phase 0: Stabilize Obvious Runtime Bug

Goal:

Fix duplicated non-`done` event yielding before contract migration.

Files:

- `backend/runtime/unit_runtime/loop.py`
- existing or new regression test under `backend/tests/`

Work:

- Remove duplicated non-`done` yield in the main model execution branch.
- Add a regression that one content delta/tool call/error event is emitted once.

Completion criteria:

- Streaming delta count is not doubled.
- Tool-call request event count is not doubled.
- Existing runtime loop tests still pass.

### Phase 1: Add Agent Assembly Models In Shadow Mode

Goal:

Introduce work order and agent assembly contracts without changing runtime behavior.

Files:

- add `backend/runtime/agent_assembly/__init__.py`
- add `backend/runtime/agent_assembly/models.py`
- add `backend/runtime/agent_assembly/validation.py`
- add `backend/runtime/agent_assembly/ids.py`
- add `backend/runtime/agent_assembly/compat.py`
- add `backend/runtime/agent_assembly/work_order_adapter.py`
- update `backend/runtime/__init__.py`

Work:

- Define strict work order and assembly fields.
- Add validators for required work identity, executor, agent, graph, permission request, ports, and result ownership.
- Add old-payload adapters.

Completion criteria:

- `NodeExecutionRequest -> NodeWorkOrder -> AgentAssemblyContract -> compat payload` round trip works for agent, human, and graph module requests.
- No coordination or runtime behavior changes yet.

### Phase 2: Coordination Produces `NodeWorkOrder`

Goal:

Move node work production out of loose `stage_execution_request`.

Files:

- add `backend/runtime/coordination_runtime/work_order_builder.py`
- update `backend/runtime/coordination_runtime/runtime.py`
- update `backend/runtime/execution/node_execution_request.py`
- update `backend/runtime/coordination_runtime/trace_adapter.py`

Work:

- Build `NodeWorkOrder` at the same point where `NodeExecutionRequest` is currently created.
- Store work order ref in coordination state.
- Keep old request payload only as compatibility output.

Completion criteria:

- Coordination checkpoint contains work order identity.
- Existing continuation still works.
- New tests prove graph route to node work order is deterministic.

Forbidden:

- Do not add more fields to `stage_execution_request` to solve contract gaps.

### Phase 3: Agent Assembly Becomes The Single Assembly Layer

Goal:

Create one agent runtime assembly path.

Files:

- add `backend/runtime/agent_assembly/assembler.py`
- add `backend/runtime/agent_assembly/context_builder.py`
- add `backend/runtime/agent_assembly/prompt_composer.py`
- add `backend/runtime/agent_assembly/memory_binder.py`
- add `backend/runtime/agent_assembly/capability_binder.py`
- add `backend/runtime/agent_assembly/soul_binder.py`
- update `backend/agent_system/assembly/runtime_chain.py`
- update `backend/agent_system/assembly/runtime_bundle_builder.py`
- update `backend/runtime/shared/context_manager.py`

Work:

- Build `AgentAssemblyContract` from `NodeWorkOrder`.
- Direct user turns also get `DirectWorkOrder -> AgentAssemblyContract`.
- Stop using `current_turn_context` as agent identity authority.
- Prompt composer must render role instructions, not runtime bookkeeping.

Completion criteria:

- Agent id/profile/projection/model source is visible and unique.
- A task graph node cannot silently switch agent through stale context.
- Prompt snapshot contains role/task/output instructions, not raw control-plane labels as primary guidance.

### Phase 4: Build Unified `ExecutionPermit`

Goal:

Unify tool visibility, operation gate, sandbox, and approval.

Files:

- add `backend/runtime/permissions/__init__.py`
- add `backend/runtime/permissions/permit_builder.py`
- add `backend/runtime/permissions/tool_gateway.py`
- add `backend/runtime/permissions/operation_gate_adapter.py`
- add `backend/runtime/permissions/sandbox_gateway.py`
- add `backend/runtime/permissions/approval_gateway.py`
- update `backend/runtime/shared/model_adoption.py`
- update `backend/runtime/shared/tool_adoption.py`
- update `backend/runtime/unit_runtime/sandbox_policy.py`
- update `backend/runtime/tool_runtime/tool_executor.py`

Work:

- Build permit before model execution.
- Derive model-visible tools from permit.
- Dispatch tools only if permit admits the request.
- Keep OperationGate, but call it from one gateway.

Completion criteria:

- The same permit explains model-visible tools and tool dispatch decisions.
- A denied operation cannot become visible through sandbox hidden-tool behavior.
- Tool authorization regression tests pass and include model-visible/dispatch consistency checks.

### Phase 5: Extract `ExecutionEngine`

Goal:

Reduce `TaskRunLoop` to task-run lifecycle orchestration.

Files:

- add `backend/runtime/execution_engine/__init__.py`
- add `backend/runtime/execution_engine/engine.py`
- add `backend/runtime/execution_engine/tool_loop.py`
- add `backend/runtime/execution_engine/model_loop.py`
- add `backend/runtime/execution_engine/final_output.py`
- update `backend/runtime/unit_runtime/loop.py`
- update `backend/runtime/professional_runtime/driver.py` if needed

Work:

- Move model call loop, tool follow-up loop, observation aggregation, repeated-tool halt, and forced synthesis out of `TaskRunLoop`.
- Engine consumes `AgentAssemblyContract + ExecutionPermit` and returns `ExecutionResult`.
- `TaskRunLoop` remains owner of task run start/checkpoint/finalizer.

Completion criteria:

- `TaskRunLoop.run_single_agent_stream` is no longer the owner of model/tool inner loop.
- Existing streaming behavior is preserved.
- Tool result follow-up tests pass.

### Phase 6: Result Boundary And Coordination Acceptance

Goal:

Use typed result envelopes instead of recovery guessing.

Files:

- add `backend/runtime/coordination_runtime/node_result_committer.py`
- update `backend/runtime/coordination_runtime/runtime.py`
- update `backend/orchestration/coordination_recovery.py`
- update `backend/runtime/unit_runtime/finalizer.py`
- update `backend/runtime/memory/trace_reader.py`

Work:

- `ExecutionResult` becomes `NodeResultEnvelope` for graph nodes.
- Coordination accepts envelopes directly.
- Recovery restores result candidates but does not decide from `diagnostics`.
- Result refs, artifact refs, output refs, final outputs are normalized once.

Completion criteria:

- Direct result acceptance and recovered result acceptance produce the same graph state.
- `diagnostics` no longer contains authoritative commit markers.
- Review gate and artifact acceptance tests pass.

### Phase 7: Sub-Runtime And GraphModule Rebuild

Goal:

Replace GraphModule special casing with sub-runtime invocation.

Files:

- add `backend/runtime/subruntime/__init__.py`
- add `backend/runtime/subruntime/models.py`
- add `backend/runtime/subruntime/graph_module_executor.py`
- add `backend/runtime/subruntime/result_packets.py`
- update `backend/runtime/execution/graph_module_runtime.py`
- update `backend/orchestration/coordination_scheduler.py`
- update `backend/orchestration/coordination_recovery.py`

Work:

- Create `SubRuntimeInvocationContract`.
- Move GraphModule start/packet/result logic behind sub-runtime executor.
- Recovery reads sub-runtime result envelope instead of reconstructing packet from imported run diagnostics.

Completion criteria:

- GraphModule output and failure paths pass.
- `coordination_recovery.py` no longer owns GraphModule packet construction.
- GraphModule identity is not stored as arbitrary diagnostics keys.

### Phase 8: Remove Business Hardcoding From Runtime

Goal:

Move writing-specific/chapter-specific rules out of platform runtime.

Files:

- update `backend/runtime/coordination_runtime/runtime.py`
- update `backend/orchestration/coordination_replay.py`
- add or update task/writing policy owner module under task system or capability system
- update writing graph tests

Work:

- Move `chapter_draft`, `memory_commit_chapter`, chapter batch boundary, and default revision text into task-specific policy.
- Runtime consumes policy generically.

Completion criteria:

- Runtime packages do not contain chapter-specific branching.
- Writing behavior remains covered by regression tests.

### Phase 9: Delete Old Shells

Goal:

Remove compatibility layers once cutover is complete.

Files:

- `backend/orchestration/coordination_control.py`
- compatibility helpers in `backend/runtime/agent_assembly/compat.py`
- old private helper import paths in tests
- stale tests that validate old private structures

Work:

- Delete fake facades and unused old payload branches.
- Replace old tests with contract-level tests.

Completion criteria:

- No old compatibility imports are required by tests.
- No private `_coordination_*` helper facade is used as a public boundary.
- Full targeted runtime/coordination test matrix passes.

## 7. File-Level Execution Checklist

### New Packages

- `backend/runtime/agent_assembly/`
- `backend/runtime/execution_engine/`
- `backend/runtime/permissions/`
- `backend/runtime/subruntime/`

### Existing Files To Change

- `backend/runtime/unit_runtime/loop.py`
- `backend/runtime/execution/node_execution_request.py`
- `backend/runtime/coordination_runtime/runtime.py`
- `backend/runtime/coordination_runtime/trace_adapter.py`
- `backend/runtime/coordination_runtime/context_packet_resolver.py`
- `backend/runtime/shared/context_manager.py`
- `backend/runtime/shared/model_adoption.py`
- `backend/runtime/shared/tool_adoption.py`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/runtime/unit_runtime/sandbox_policy.py`
- `backend/runtime/unit_runtime/finalizer.py`
- `backend/runtime/execution/graph_module_runtime.py`
- `backend/orchestration/coordination_scheduler.py`
- `backend/orchestration/coordination_recovery.py`
- `backend/orchestration/coordination_replay.py`
- `backend/agent_system/assembly/runtime_chain.py`
- `backend/agent_system/assembly/runtime_bundle_builder.py`

### Tests To Add Or Update

- add `backend/tests/runtime_stream_event_dedup_regression.py`
- add `backend/tests/agent_assembly_models_regression.py`
- add `backend/tests/work_order_to_agent_assembly_regression.py`
- add `backend/tests/execution_permit_gateway_regression.py`
- add `backend/tests/coordination_node_work_order_regression.py`
- add `backend/tests/coordination_node_result_envelope_regression.py`
- add `backend/tests/graph_module_subruntime_contract_regression.py`
- update `backend/tests/node_execution_request_regression.py`
- update `backend/tests/langgraph_coordination_runtime_regression.py`
- update `backend/tests/tool_authorization_regression.py`
- update `backend/tests/review_gate_verdict_regression.py`
- update writing graph quality/replay tests after business hardcoding moves

## 8. Validation Matrix

Minimum validation after each phase:

```text
python -m compileall -q backend/runtime backend/orchestration backend/agent_system backend/task_system backend/tests
```

Targeted regression groups:

```text
python -m pytest backend/tests/node_execution_request_regression.py
python -m pytest backend/tests/langgraph_coordination_runtime_regression.py
python -m pytest backend/tests/task_system_api_regression.py
python -m pytest backend/tests/tool_authorization_regression.py
python -m pytest backend/tests/review_gate_verdict_regression.py
python -m pytest backend/tests/task_graph_scheduler_regression.py
```

New contract-specific groups:

```text
python -m pytest backend/tests/runtime_stream_event_dedup_regression.py
python -m pytest backend/tests/agent_assembly_models_regression.py
python -m pytest backend/tests/work_order_to_agent_assembly_regression.py
python -m pytest backend/tests/execution_permit_gateway_regression.py
python -m pytest backend/tests/coordination_node_work_order_regression.py
python -m pytest backend/tests/coordination_node_result_envelope_regression.py
python -m pytest backend/tests/graph_module_subruntime_contract_regression.py
```

Behavioral invariants:

- a task graph node cannot execute under a different agent than its work order / assembly contract;
- model-visible tools equal permit-visible tools;
- a tool request cannot dispatch without the same permit admitting it;
- recovered node result equals direct node result acceptance;
- GraphModule success and failure use the same sub-runtime envelope shape;
- `diagnostics` removal from control-state paths does not change final graph state;
- direct single-agent execution and graph-node execution converge through the same agent assembly layer and execution engine.

## 9. Anti-Patterns Forbidden During Implementation

- Do not solve contract gaps by adding more keys to `diagnostics`.
- Do not make a new facade that only re-exports old private helpers.
- Do not keep `current_turn_context` as agent identity authority.
- Do not let `stage_execution_request` carry prompt materials, runtime assembly, GraphModule private state, and recovery markers.
- Do not add another GraphModule-specific recovery branch.
- Do not write prompts as developer/runtime descriptions.
- Do not keep old tests only to preserve obsolete private helper paths.
- Do not leave compatibility adapters after cutover.

## 10. Ideal Rebuild Hard Constraints

These constraints are stricter than normal refactor guidelines. They exist because the target system must complete long tasks and allow free composition of agents, task graphs, capabilities, memory, permissions, and sub-runtimes.

### 10.1 Long-Task Completion Constraints

1. Every long task must have a durable execution spine.

   A task cannot be represented only by stream events or temporary context. It must have stable records for graph state, work order, agent assembly contract, execution permit, execution result, result commit, checkpoint, and finalization.

2. Resume must restore; it must not decide.

   Recovery code may restore candidate contracts/results/checkpoints. It may not infer acceptance, agent identity, permissions, or graph routing from `diagnostics`, filenames, prompt text, or latest timestamp alone.

3. Every execution step must be idempotent or explicitly non-replayable.

   Tool calls, model calls, sub-runtime calls, memory writes, artifact writes, and result commits must carry replay policy. Re-running after crash must either reuse a completed result or fail closed with a clear manual recovery state.

4. Long tasks must progress through typed milestones, not loose status strings.

   Required milestones:

   - contract_created
   - permit_issued
   - execution_started
   - observation_recorded
   - result_projected
   - result_committed
   - graph_state_accepted
   - finalization_completed

5. Context compaction must happen before execution, not after diagnostics.

   If token pressure is high or critical, the runtime must compact or reject before model invocation. A report that says `needs_compaction=True` after the context has already been used is not sufficient.

6. A task cannot be marked completed without a validated deliverable boundary.

   For graph nodes, completion requires `NodeResultEnvelope` accepted by the graph. For direct tasks, completion requires `ExecutionResult` accepted by finalizer. For artifact-producing nodes, required artifact refs must be materialized and validated.

7. Stale, duplicate, partial, and failed outputs are event outcomes, not terminal task states.

   Runtime terminal state may be completed, failed, blocked, waiting_for_human, or waiting_for_subruntime. Values like `stale_result_ignored` and `duplicate_commit_ignored` must live in result/event handling, not as graph/task terminal status.

8. Memory and artifact writes must be transactional at the assembly contract level.

   The system must know which work order and assembly contract authorized a write, which result caused it, and whether the write was committed, rejected, archived, or invalidated. Invalidating a node must invalidate downstream writes by ref, not by path guessing.

9. Long-running sub-runtimes must expose progress and final result through the same envelope family.

   GraphModule, human execution, worker delegation, and future sub-runtimes must all converge into `ExecutionResult` or `NodeResultEnvelope`. They may have executor-specific work order payloads, but not executor-specific commit paths.

10. Finalization must be monotonic.

   A later recovery, trace refresh, monitor decision, or background continuation cannot downgrade or overwrite a committed final result unless a new explicit rewind/invalidation contract exists.

### 10.2 Free-Composition Constraints

1. Composition must happen through work orders and assembly contracts, not inheritance of ambient context.

   An agent, node, graph module, tool, memory packet, or capability can be composed only if its input/output/permission contracts are compatible at the `AgentAssemblyContract` boundary. `current_turn_context` and `task_selection` may provide hints, but cannot authorize composition.

2. Every composable unit must declare ports.

   Required port classes:

   - input ports
   - output ports
   - artifact ports
   - memory read ports
   - memory write ports
   - permission ports
   - lifecycle ports

3. Agent identity must be sealed by agent assembly before execution.

   After `AgentAssemblyContract` is created, no downstream layer may switch `agent_id`, `agent_profile_id`, projection, model profile, or allowed operations by reading stale context, task selection, or diagnostics.

4. Permissions are compositional intersection, not additive union.

   Effective permission equals the intersection of agent profile ceiling, node/task requirement, graph policy, runtime lane, approval state, sandbox policy, and user/session permission mode. No layer may add capabilities after `ExecutionPermit` is issued.

5. Model-visible tools and dispatchable tools must come from the same permit.

   A tool cannot be visible to the model unless dispatch can later evaluate it against the same permit. A tool cannot dispatch if it was not admitted by the same permit family.

6. Prompt composition must be role-contract driven.

   Prompt text must answer:

   - who the agent is;
   - what the agent is responsible for;
   - what inputs are authoritative;
   - what outputs are required;
   - what actions are forbidden;
   - when to stop or ask for human intervention.

   It must not expose runtime bookkeeping as primary instruction.

7. Business-specific policies must be plug-ins to contracts, not branches in runtime.

   Writing chapters, reviewing outlines, committing chapter memory, or other domain behavior must live in task/capability/policy modules. Runtime may execute policies generically, but must not hardcode business node ids.

8. GraphModule is not special.

   A graph module is one sub-runtime implementation. The same sub-runtime contract must be usable for future nested graphs, worker swarms, external MCP workflows, or human review workflows.

9. Direct tasks and graph-node tasks must converge before execution.

   Direct user execution and task graph node execution may have different work order builders, but both must produce `AgentAssemblyContract + ExecutionPermit` before entering model/tool execution.

10. Every adapter must have an expiry.

   Compatibility adapters are allowed only in migration phases. Each adapter must have:

   - owner file;
   - source old shape;
   - target new work order or assembly contract;
   - tests;
   - cutover condition;
   - deletion phase.

### 10.3 Information Design Constraints

1. `diagnostics` is observational only.

   It may contain why, source, counts, timings, warnings, and debug reports. It may not contain authoritative identity, commit state, permission state, accepted/rejected decisions, graph routing decisions, or recovery markers.

2. `current_turn_context` is not a storage layer.

   It may carry current user/session hints and non-authoritative display context. It may not carry hidden control state for continuation, graph result acceptance, tool authorization, or memory writeback.

3. `stage_execution_request` is not the durable contract.

   During migration it may exist as compatibility payload. The durable shape is `NodeWorkOrder` plus `AgentAssemblyContract`.

4. Ref families must be distinct.

   The system must not blur:

   - artifact refs;
   - execution result refs;
   - task result refs;
   - graph result refs;
   - checkpoint refs;
   - memory refs;
   - commit refs.

   If a packet ref is used as an artifact ref fallback, that is a design failure.

5. IDs must be deterministic where replay depends on them.

   Work order ids, assembly contract ids, execution permit ids, idempotency keys, sub-runtime invocation ids, and node result ids must be deterministic from stable contract inputs.

6. Runtime output must not leak protocol artifacts.

   Final user-visible output may reference artifacts and conclusions, but must not expose internal packets, runtime directives, graph bookkeeping, tool-call protocol, or developer-like node descriptions.

### 10.4 Testing Constraints

1. Every new boundary gets contract tests before migration.

2. Every cutover phase gets old-vs-new equivalence tests.

3. Every long-task path must have crash/retry/recovery coverage.

4. Every permission path must test both visibility and dispatch.

5. Every sub-runtime path must test success, failure, blocked, waiting_for_human, and recovery.

6. Tests may not preserve old private helper paths just for compatibility.

7. No test may fake a result that the runtime could not actually produce.

## 11. Final Target Directory Shape

```text
backend/runtime/
  agent_assembly/
    models.py
    validation.py
    ids.py
    compat.py              # temporary, removed after cutover
    work_order_adapter.py  # temporary old payload bridge
    assembler.py
    context_builder.py
    prompt_composer.py
    memory_binder.py
    capability_binder.py
    soul_binder.py
    result_projector.py
  coordination_runtime/
    runtime.py
    work_order_builder.py
    node_result_committer.py
    recovery_candidates.py
    trace_adapter.py
    runtime_payloads.py
    context_packet_resolver.py
  permissions/
    permit_builder.py
    tool_gateway.py
    operation_gate_adapter.py
    sandbox_gateway.py
    approval_gateway.py
  execution_engine/
    engine.py
    model_loop.py
    tool_loop.py
    final_output.py
  subruntime/
    models.py
    graph_module_executor.py
    result_packets.py
  unit_runtime/
    loop.py                # task-run lifecycle only, not model/tool inner loop
    finalizer.py
    artifact_materializer.py
    quality_gates.py
```

## 12. Execution Lock

Implementation must proceed in phase order. The only allowed exception is a blocking compile/test failure discovered inside a phase. If that happens, correct the structural issue inside the same phase instead of adding a patch branch that bypasses the plan.

The first implementation action after this plan should be Phase 0, not another split.
