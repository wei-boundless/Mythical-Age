# Current Turn Capability And Long Run Evidence Plan - 2026-05-24

## Problem

The runtime still has repeated capability gates. `operation_requirement`, `execution_permit`, `resource_policy`, and the final tool gateway all merge or filter tool visibility. That makes `agent_todo` unstable because a later layer can silently drop it after an earlier layer allowed it.

Long system-eval runs also write the turn artifact only after the SSE stream finishes. If a long task hangs or the outer process times out, the run keeps only `scenario_started`, even when the model already selected a task and wrote files.

## Target Structure

1. `CurrentTurnCapabilityPlan` is the single current-turn authority for operations and model-visible tools.
2. `execution_permit` remains an identity/contract envelope, not an independent tool-policy recomputation layer.
3. `resource_policy` remains the operation adoption decision, but the final model-visible tool set is resolved once from the capability plan.
4. `tool_gateway` consumes the capability plan and only materializes tool instances.
5. Long-runner turn artifacts are written incrementally as partial evidence during SSE collection.

## Implementation Steps

1. Add `backend/runtime/capabilities/current_turn_capability_plan.py`.
   - Normalize operation refs and tool names.
   - Collect requested operations from operation requirement, execution permit, and resource policy.
   - Convert operation refs to tool names through tool definitions.
   - Keep explicit permit visible tools authoritative when present.
   - Produce diagnostics showing source operations/tools and filtered tools.

2. Wire the runtime loop.
   - Build the capability plan after `resource_policy`.
   - Store it in `task_operation["current_turn_capability_plan"]`.
   - Feed it to `tool_instances_for_policy_and_permit`.
   - Use its model-visible tools when building `runtime_capability_state`.
   - Add diagnostics to `model_response_runtime_adopted`.

3. Simplify final tool materialization.
   - Update `tool_gateway` to consume a supplied capability plan.
   - Keep the old function entrypoint only as a caller-compatible wrapper, but route all logic through the plan.
   - Do not re-merge arbitrary hidden permissions inside the gateway.

4. Persist long-run evidence during streaming.
   - Add an event callback to `collect_sse_events`.
   - In `long_runner`, write `turn-XX-SESSION.partial.json` before the request and after each event.
   - Update progress/partial result with the partial artifact path while the turn is running.
   - Rename or rewrite the final artifact when the turn completes.

5. Validate.
   - Add focused tests for `agent_todo` reaching the final tool instance list through the capability plan.
   - Add a partial-artifact test for event-by-event long-run evidence.
   - Run the existing affected regression tests.
