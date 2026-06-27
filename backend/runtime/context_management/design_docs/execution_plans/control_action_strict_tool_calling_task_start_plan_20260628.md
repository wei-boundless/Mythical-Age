# Control Action Strict Tool Calling Task Start Plan

## 1. Problem

The broken session was not caused by Codex itself. The failure came from the local task-start protocol around `request_task_run`.

The model understood that the work needed a durable task lifecycle, but the runtime exposed mixed instructions:

- ordinary tools were available through provider-native tool calls;
- control actions were described as action objects;
- `request_task_run` was sometimes interpreted as a provider tool call and sometimes rejected as an action-object-only control action;
- repair feedback then exposed a large canonical `TaskRunContract` skeleton, which pushed the model into malformed `container_contract` fragments and DSML wrappers.

The structural issue is therefore not only "JSON is too complex". The deeper issue is mixed authority and mixed transport:

```text
model decides semantic action
provider transport constrains action shape
backend validates and normalizes
task lifecycle starts from canonical runtime contract
```

These jobs currently overlap.

## 2. Source Findings

### Codex

Local source: `D:/AI应用/openai-codex`.

- `codex-rs/tools/src/responses_api.rs` defines `ResponsesApiTool` with `name`, `description`, `strict`, `parameters`, and optional output schema.
- `codex-rs/tools/src/tool_spec.rs` serializes function tools into the provider tool payload.
- `codex-rs/core/src/tools/handlers/plan_spec.rs` exposes `update_plan` as a compact schema: `explanation` plus `plan[{step,status}]`.
- `codex-rs/core/src/tools/handlers/goal_spec.rs` exposes `create_goal` and `update_goal` as small schemas; runtime owns goal state and usage accounting.

Codex does not ask the model to write a full internal lifecycle contract for plans or goals.

### Claude Code

Local source: `D:/AI应用/claude-code-nb-main`.

- `Tool.ts` centralizes tool authority: `inputSchema`, `outputSchema`, `strict?`, `validateInput`, `checkPermissions`, concurrency, interruption, and deferral.
- `utils/api.ts` turns tool schemas into provider payloads and adds `strict: true` only when the tool and model/provider support it.
- `Task.ts` defines task identity and state as runtime-owned state.
- `tools/TaskCreateTool/TaskCreateTool.ts` creates tasks through a small strict object: `subject`, `description`, optional `activeForm`, `metadata`.
- `tools/TodoWriteTool/TodoWriteTool.ts` uses `strict: true` with a compact `{ todos }` input; runtime owns storage and cleanup.

Claude Code treats task state as runtime state. The model submits compact intent through tool/function schemas.

## 3. Target Design

Use provider strict tool/function calling for control actions, but keep control actions separate from ordinary capability tools.

```text
ordinary tools:
  read_file / edit_file / terminal / web_search
  -> capability/tool execution plane

control actions:
  respond / ask_user / block / request_task_run / active_work_control / resume_recoverable_work
  -> model action/control plane
```

`request_task_run` becomes a strict provider control action with a compact `TaskStartIntent`. The backend normalizes that intent into canonical `TaskRunContract + WorkModeContract`.

The model should not author the full canonical lifecycle contract during a normal chat turn.

## 4. Compact Task Start Intent

The model-facing control action should carry:

```json
{
  "public_progress_note": "why this needs durable task lifecycle",
  "public_action_state": {
    "current_judgment": "current boundary judgment",
    "next_action": "enter task execution"
  },
  "entry_reason": "why this cannot fit in the current turn",
  "primary_mode": "goal|plan|todo|investigation|recovery|monitor|open_work",
  "minimum_viable_next_step": "first executable step after task creation",
  "working_scope": {
    "target_objects": [],
    "workspace_refs": [],
    "source_refs": [],
    "excluded_scope": [],
    "known_constraints": []
  },
  "acceptance": {
    "mode": "checkpoint|user_review|best_effort|strict|none_yet",
    "criteria": [],
    "final_answer_requirements": []
  },
  "mode_payload": {}
}
```

Backend normalization fills the canonical container fields, primary work mode record, lifecycle defaults, feedback defaults, memory defaults, and acceptance contract.

## 5. Authority Chain

```text
RuntimeAssembly
-> ToolCallContract
-> ControlActionSchema
-> ProviderToolSidecar
-> ModelActionRequest
-> ActionPermit
-> TaskRunContract normalization
-> TaskLifecycle start
```

Rules:

- Provider strict schema constrains model output shape.
- `ModelActionRequest` remains the single action request type consumed by admission and lifecycle code.
- `TaskRunContract` remains backend-owned canonical runtime state.
- Repair feedback points to compact intent fields, not a giant internal contract skeleton.
- Ordinary tools and control actions may share provider transport, but never share semantic authority.

## 6. Implementation Plan

1. Add `backend/harness/runtime/control_action_schema.py`.
   - Define control action names.
   - Define provider-native function bindings for allowed control actions.
   - Define compact `request_task_run` schema.
   - Convert provider-native control calls into `ModelActionRequest` payloads.

2. Update `backend/harness/runtime/tool_call_contract.py`.
   - Add `provider_tool_selection` as a control-action submission mode.
   - Keep ordinary tool submission independent.
   - Expose hidden transport policy for control action provider tools.

3. Update `backend/harness/runtime/provider_tool_schema.py`.
   - Support per-tool `strict: true` in provider tool bindings.

4. Update `backend/runtime/model_gateway/lightweight_chat_model.py`.
   - Preserve per-tool strict flags in provider payloads.

5. Update `backend/harness/loop/single_agent_turn.py`.
   - Include provider-native control action tools in `_native_tools_for_packet`.
   - Parse native control action calls into `ModelActionRequest`.
   - Allow a single native control action to proceed through admission.
   - Reject mixed ordinary tool and control action calls in the same model decision.
   - Set provider strict-tool extensions only when strict control actions are present.

6. Update `backend/harness/loop/model_action_protocol.py`.
   - Accept compact task start intent as `task_run_contract_seed`.
   - Normalize compact intent into canonical `TaskRunContract + WorkModeContract`.

7. Update `backend/harness/runtime/compiler.py` and repair text.
   - Replace giant `request_task_run` skeleton guidance with compact intent guidance.
   - Keep canonical contract details backend-facing.

## 7. Cutover Rules

- New primary path: provider-native strict control action.
- Existing action-object parsing can remain as fallback for non-provider or recovery paths, but it must use the compact intent shape.
- Legacy task seed conversion is not the target path. It should stop appearing in prompt guidance and be removable after the compact path is stable.
- No system path may infer `request_task_run` from plain natural language.

## 8. Validation

Do not add regression test files for this change.

Use:

- static code inspection of the action path;
- `python -m compileall` for touched backend modules;
- if running the app is needed, use the fixed local ports:
  - frontend `http://127.0.0.1:3000`
  - backend `http://127.0.0.1:8003`

