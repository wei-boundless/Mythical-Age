# Runtime Leftover Chain Cleanup Plan - 2026-05-24

## Problem

The professional long-task lane has already removed the old required-action scheduler and sidecar-driven tool narrowing. The remaining problem is outside that lane:

1. The generic unit runtime still contains forced answer synthesis paths that can turn tool evidence into a canonical final answer without the model owning the closeout.
2. The generic tool runtime still exposes `ToolContractGate`, which is structurally a tool invocation validator but keeps old gate terminology and is called as a gate from `ToolRuntimeExecutor`.

Both conflict with the current design principle:

- The model owns intent, next action, and final answer.
- Runtime owns tool protocol, input validation, permission policy, evidence envelope, and explicit failure observations.
- Runtime must not synthesize a stable answer to hide a model closeout failure.

## Target Design

### Tool Invocation Validation

Replace the remaining generic gate naming with a validator:

- `ToolInvocationValidationDecision`
- `ToolInvocationValidator`
- `tool_invocation_validation`

Allowed responsibilities:

- reject unavailable or out-of-scope tool invocations;
- identify missing required tool inputs;
- identify missing explicit bindings where a tool contract requires them;
- return a model-visible recoverable observation when the model can retry.

Forbidden responsibilities:

- choose the next tool for the model;
- narrow the available tool set based on a runtime plan;
- convert validation failure into a final answer.

### Follow-up Closeout

The generic follow-up path must not create a stable canonical answer from observations. It may:

- ask the model to close out after tool results;
- preserve an already-produced model final answer;
- return a `progress_only` runtime control message when budgets or repetition halt the loop;
- fail artifact validation if a required artifact was not produced.

It must not:

- call a forced synthesis helper;
- turn task summary refs into final user-facing prose;
- mark artifact success as completed when the model closeout failed.

## File-Level Execution Checklist

1. `backend/capability_system/tool_contracts.py`
   - Rename the gate classes to invocation-validation names.
   - Replace `tool_contract_gate` reason strings with `tool_invocation_validation`.

2. `backend/runtime/tool_runtime/tool_executor.py`
   - Stop importing or instantiating `ToolContractGate`.
   - Use `ToolInvocationValidator`.
   - Rename diagnostics and helper functions from contract-decision language to invocation-validation language.

3. `backend/runtime/shared/action_request.py`
   - Replace recoverable contract observation naming with recoverable invocation validation observation.
   - Keep the payload shape model-visible and retry-oriented.

4. `backend/runtime/execution_engine/final_output.py`
   - Remove forced synthesis metadata and builders.
   - Remove artifact success fallback answer builder.
   - Keep budget/repeated-tool progress messages and model-owned selection helpers.

5. `backend/runtime/execution_engine/followup_cycle.py`
   - Remove forced synthesis imports and calls.
   - Budget exhaustion returns progress-only runtime-control output.
   - Repeated tool halt only preserves existing model content or returns progress-only halt message.

6. `backend/runtime/unit_runtime/loop.py`
   - Remove imports and calls for artifact fallback synthesis.
   - Remove artifact success fallback branch.
   - Keep artifact validation fail-closed behavior.

7. Tests and registry metadata
   - Rename/update tests that directly import old validator names.
   - Update catalog field naming away from `tool_contract_mode`.
   - Remove tests asserting forced synthesis is canonical.

## Completion Criteria

- `rg "ToolContractGate|ToolContractDecision|tool_contract_gate|forced_tool_synthesis|artifact_success_fallback|budget_exhausted_force_synthesis|runtime_force_synthesis" backend/runtime backend/capability_system backend/query backend/api backend/tests` has no active-code matches.
- Professional regression tests still pass.
- Tool validation regression tests still prove missing inputs become model-visible recoverable observations.
- Runtime final-output tests prove budget and repeated-tool halts are progress-only, not synthesized stable answers.
