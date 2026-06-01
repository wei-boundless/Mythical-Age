# Runtime Prompt Assembly Repair Plan - 2026-06-02

## 1. Problem Statement

The latest real five-floor dungeon E2E run proved that prompt cache prefix stability is working, but it also exposed a runtime assembly problem. The model-visible task execution packet contains repeated protocol instructions, conflicting artifact roots, duplicated tool/fact projections, and an unsafe large-file action path.

This is not a simple prompt wording issue. The broken property is **single authority for runtime-visible execution facts**:

- The task contract owns the deliverable requirement.
- The task environment owns storage and sandbox boundaries.
- The runtime envelope should expose one canonical artifact scope.
- The tool runtime should enforce the same scope that the model sees.
- The prompt compiler should arrange these facts once, in a cache-friendly order.

Today those layers disagree.

## 2. Evidence From Real E2E

Latest trace:

- `storage/runtime_state/prompt_cache_live_tests/five_floor_dungeon_e2e_20260602_040638_b3eb46/trace.json`
- `storage/runtime_state/prompt_cache_live_tests/five_floor_dungeon_e2e_20260602_040638_b3eb46/report.json`

Observed model input shape per task execution invocation:

| Index | Role | Segment | Size |
| --- | --- | --- | --- |
| 0 | system | `global_static` | 1225 chars |
| 1 | system | `task_stable` | 14123 chars |
| 2 | system | `task_prompt_contract` | 414 chars |
| 3 | system | `agent_stable` | 850 chars |
| 4 | system | `environment_stable` | 787 chars |
| 5 | system | `dynamic_projection` | 6315 chars |
| 6 | user | `volatile_task_state` | 1099 -> 7214 chars |

Cache facts:

- Stable prefix hashes stayed equal across calls.
- `cache_breaks` was empty.
- The cache structure was not the cause of task friction.

Runtime friction facts:

- Model called `path_exists` twice for the same missing directory.
- Model then used `terminal mkdir -p ...`.
- Calls 4 and 5 hit `completion_tokens=4096` and failed action protocol validation.
- Protocol repair observations only stored validation errors, not raw invalid model output previews.

## 3. Current Authority Chain

```text
HarnessRuntimeRequest
-> runtime_facade._task_selection_for_runtime()
-> assemble_runtime()
-> runtime_facade._task_run_contract_from_explicit_contract()
-> start_task_lifecycle_from_contract()
-> task_executor._task_sandbox_policy()
-> RuntimeCompiler.compile_task_execution_packet()
-> ModelRuntime.invoke_messages()
-> task_executor._invoke_task_model_action()
-> ToolExecutor / Native tools
-> task_executor._verify_completion()
```

Relevant code:

- `backend/harness/entrypoint/runtime_facade.py`
  - `_task_selection_for_runtime()`
  - `_run_explicit_contract_task_turn()`
  - `_task_run_contract_from_explicit_contract()`
- `backend/harness/runtime/assembly.py`
  - `assemble_runtime()`
  - `_resolve_runtime_task_environment()`
- `backend/task_system/environments/catalog.py`
  - `TaskEnvironmentCatalogItem.runtime_payload()`
- `backend/task_system/environments/spec_resolver.py`
  - `_storage_space_payload()`
- `backend/task_system/environments/default_environments.py`
  - development sandbox currently still declares `runtime_output`.
- `backend/harness/runtime/compiler.py`
  - `compile_task_execution_packet()`
  - `_agent_visible_runtime_projection()`
  - `_runtime_projection_instruction()`
  - `_environment_instruction()`
  - `_environment_model_visible_payload()`
- `backend/harness/runtime/dynamic_context/runtime_delta_projector.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/loop/task_executor.py`
  - `_invoke_task_model_action()`
  - `_task_sandbox_policy()`
  - `_verify_completion()`
  - `_discover_sandbox_artifact_refs()`
- `backend/runtime/tool_runtime/native_tools.py`
  - `NativeWriteFileTool`
  - `NativeTerminalTool`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/harness/loop/model_action_runtime.py`
- `backend/harness/loop/model_action_protocol.py`

## 4. Root Causes

### 4.1 Artifact Root Has Multiple Authorities

The real prompt exposed three artifact roots:

1. Explicit task contract path:
   - `artifacts/prompt_cache_live_e2e/.../five_floor_dungeon/index.html`
   - Source: `backend/scripts/live_five_floor_dungeon_prompt_cache_e2e.py`
2. Environment storage artifact root:
   - `storage/task_environments/development/sandbox/artifacts`
   - Source: `spec_resolver._storage_space_payload()`
3. Runtime envelope artifact root:
   - `runtime_output`
   - Source: development sandbox `ArtifactPolicy(artifact_root="runtime_output")`, projected by `RuntimeDeltaProjector` into the task state boundary.

This breaks a basic mature-agent invariant: the model-visible path, write permission scope, sandbox execution root, and artifact verification root must describe the same target.

### 4.2 Write Scope And Terminal Scope Diverge

`task_executor._task_sandbox_policy()` builds:

- `write_scopes` from environment artifact root and scratch roots.
- `publish_scopes` from environment artifact root.
- `materialized_roots` from explicit contract roots plus publish scopes.

`NativeWriteFileTool.check_permissions()` checks `write_scopes`, so `write_file` to `artifacts/...` is not authorized when the environment root is `storage/task_environments/.../artifacts`.

`NativeTerminalTool` runs inside the sandbox working directory and is not path-scoped the same way. It can create `artifacts/...` in the sandbox, but closeout discovery scans only publish roots, so this output is not a reliable artifact.

### 4.3 Prompt Segments Are Not Fully Separated

Existing maintenance docs already target this structure:

```text
global_static
agent_stable
environment_stable
task_contract
active_skills
tool_index
dynamic_projection
volatile_task_state
```

Current implementation still merges schema, task contract, task environment, and the entire tool catalog into one large `task_stable` JSON segment. That makes the model input harder to inspect and allows duplicated facts to survive.

### 4.4 Runtime Dynamic Projection Contains Stable Or Internal Data

`dynamic_projection` currently includes:

- full allowed operation list,
- full visible tool name list,
- agent prompt refs for other invocation kinds,
- task run internal IDs and origin refs.

Most of that belongs in trace or manifest, not model-visible dynamic context.

### 4.5 Volatile Task State Duplicates Observations

`TaskStateProjector` emits:

- `current_facts`,
- `latest_tool_results`,
- `active_failures`,
- `historical_failures`,
- `work_progress`.

In the real trace, the same `path_exists` observations appeared in both `current_facts` and `latest_tool_results`. Historical system todo output and bare `replacement_ref` records also entered `latest_tool_results`.

This creates prompt growth without adding decision value.

### 4.6 Large File Output Is Forced Through One JSON Action

The current `write_file` tool requires complete `content`. The model must emit a single valid JSON object containing the full HTML file. On DeepSeek with `max_output_tokens=4096`, this is fragile. Calls 4 and 5 likely attempted large writes and were truncated or malformed.

The runtime currently cannot distinguish:

- invalid JSON,
- fenced JSON,
- truncated JSON,
- missing fields,
- wrong schema.

`parse_json_object()` returns `{}` on parse failure, and the repair observation only records validation errors.

## 5. Target Design

### 5.1 Single Artifact Scope

Introduce one canonical model-visible artifact binding for task execution:

```text
TaskEnvironment.storage_space.artifact_root
-> RuntimeArtifactScope
-> normalized TaskRunContract.required_artifacts
-> sandbox_policy.write_scopes / publish_scopes
-> prompt task_contract
-> tool runtime context
-> completion discovery
```

Rules:

- `storage_space.artifact_root` is the default authority for task artifacts.
- `ArtifactPolicy.artifact_root` must not override storage root for development sandbox task execution.
- Required artifact paths must either already be under the canonical artifact root or be normalized into it before the model sees them.
- Original user/requested paths may be retained in diagnostics as `requested_path`, but not as executable model instructions.
- `runtime_output` must not appear in task execution model-visible prompt or runtime boundary unless the environment truly uses it as canonical storage.

### 5.2 Path Contract

For task execution:

```json
{
  "artifact_scope": {
    "artifact_root": "storage/task_environments/development/sandbox/artifacts",
    "publish_scope": "storage/task_environments/development/sandbox/artifacts",
    "write_scope": "storage/task_environments/development/sandbox/artifacts"
  },
  "required_artifacts": [
    {
      "path": "storage/task_environments/development/sandbox/artifacts/<task-suffix>/index.html",
      "requested_path": "artifacts/<task-suffix>/index.html",
      "kind": "html_document"
    }
  ]
}
```

The model receives only the canonical path as the path it should write and verify.

### 5.3 Prompt Message Target

Task execution should become:

```text
0 system global_static
1 system action_schema_static
2 system agent_stable
3 system environment_stable
4 system task_contract_stable
5 system tool_index_stable
6 system dynamic_runtime_boundary
7 system volatile_task_state
```

Notes:

- The final state message should be system-supplied execution state, not user-authored content.
- The actual user request belongs in the task contract or pending user steers, not in a fake user state message.
- Tool catalog appears once.
- Public action state rules appear once.
- Internal IDs stay in trace/manifest, not in model-visible text.

### 5.4 Dynamic Projection Target

Dynamic runtime projection should include only:

- current invocation kind,
- current permission scope,
- artifact scope hash/root if it changed,
- operation authorization hash,
- counts and critical denied groups,
- active policy changes that affect next action.

It should not include:

- full tool list when `tool_index_stable` is present,
- prompt refs for other invocation kinds,
- raw task run origin refs,
- full runtime assembly IDs.

### 5.5 Volatile Task State Target

Task state should include:

- current actionable facts, semantically deduped,
- latest result only when it is not already represented as a current fact,
- compact active failure summary with count and latest observation ref,
- artifact evidence,
- pending user steers and active contract revisions,
- recent progress summary.

It should exclude:

- historical system todo JSON,
- bare replacement refs with no model-actionable meaning,
- duplicate observations with different refs but same tool/path/result,
- raw tool output when a replacement or compact summary exists.

### 5.6 Large Artifact Write Target

Do not rely on one giant JSON `write_file` action for large artifacts.

Preferred runtime structure:

- Extend `write_file` with a chunk-safe protocol:
  - optional `mode=replace|start|append|complete`,
  - optional `chunk_index`,
  - optional `total_chunks`,
  - optional `expected_final_sha256`.
- Each model action remains small and valid JSON.
- The runtime verifies final file size/hash after the last chunk.
- The model-visible schema states when to use chunking.

This is a runtime/tool protocol repair, not just a prompt instruction.

## 6. Execution Plan

### Phase 1 - Artifact Scope Authority Repair

Goal:

- Remove conflicting artifact roots from task execution.
- Make model-visible artifact paths, write scopes, publish scopes, and closeout discovery agree.

Files:

- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/task_executor.py`
- `backend/task_system/environments/default_environments.py`
- `backend/task_system/environments/catalog.py`
- `backend/scripts/live_five_floor_dungeon_prompt_cache_e2e.py`
- tests under `backend/tests/`

Design decisions:

- Task execution envelope artifact root must be derived from `storage_space.artifact_root`.
- Development sandbox must not expose `runtime_output` as the task artifact root.
- Explicit contract artifact paths outside canonical artifact root are normalized before prompt assembly.
- Original path is retained only as diagnostics, not as a second model-visible target.

Implementation checklist:

- Add an artifact scope helper near runtime/task execution code, for example:
  - `backend/harness/runtime/artifact_scope.py`
- Add `canonicalize_required_artifacts(contract, environment_payload)` or equivalent.
- Use it before `RuntimeCompiler.compile_task_execution_packet()` emits model messages.
- Use the same canonical artifacts in `_task_sandbox_policy()`.
- Ensure `write_scopes`, `publish_scopes`, and `_publish_scan_roots()` all include the canonical artifact root.
- Update the live E2E script to request artifacts under canonical environment artifact scope or to assert normalization.
- Remove or override `runtime_output` from development sandbox model-visible task boundary.

Completion criteria:

- Task execution prompt contains only one artifact root.
- `runtime_output` is absent from task execution model-visible prompt for development sandbox.
- `write_file` to the required artifact path is allowed.
- The old unnormalized `artifacts/...` path never appears in model-visible task execution instructions; a direct tool call to that path is denied with a clear repair instruction.

### Phase 2 - Prompt Segment Separation

Goal:

- Make prompt structure match the target architecture and reduce duplicate protocol facts.

Files:

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/prompt_segment_plan.py`
- `backend/prompt_library/packs.py`
- `backend/tests/prompt_accounting_ledger_test.py`
- `backend/tests/prompt_cache_prefix_tier_regression.py`

Design decisions:

- `task_stable` must stop carrying schema, tool catalog, and environment payload together.
- Tool catalog becomes its own `tool_index` segment.
- Task contract becomes its own `task_contract_stable` segment.
- Action schema becomes its own compact segment or is folded into `global_static`, but it must appear once.
- Public action state requirements appear once.

Implementation checklist:

- Split `stable_payload` in `compile_task_execution_packet()` into typed payloads:
  - action schema,
  - task contract,
  - tool index,
  - environment compact payload if still needed.
- Remove `Task run model-visible context` from model messages; keep it in `prompt_manifest`/trace diagnostics.
- Remove dynamic projection full `visible_tool_names` when tool index is present.
- Update segment plan tests to assert exact segment kinds/order.
- Add tests that fail when protocol phrases are duplicated above an allowed count.

Completion criteria:

- Prompt message order is deterministic and documented by tests.
- `task_contract_stable` contains task goal, canonical artifacts, completion criteria, and required verification only.
- Tool list appears once.
- Environment root appears once.
- Stable prefix remains stable across repeated invocations.

### Phase 3 - Dynamic And Volatile State Cleanup

Goal:

- Keep dynamic state useful and bounded without hiding actionable facts.

Files:

- `backend/harness/runtime/dynamic_context/runtime_delta_projector.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
- `backend/tests/harness_runtime_facade_regression.py`
- `backend/tests/prompt_accounting_ledger_test.py`

Design decisions:

- Runtime delta projects only changes and hashes, not full stable inventories.
- Task state semantically dedupes observations.
- Historical system records are not model-visible unless they are actionable.
- Protocol repair failures are compacted by code/count/latest ref.

Implementation checklist:

- Add semantic keys for facts:
  - `tool_name + path + status/result`
  - `error_code + tool_name`
- Exclude `system` latest results unless they carry pending user steer, contract revision, artifact evidence, or active blocker.
- Drop bare replacement refs from model-visible state.
- Limit active failures by semantic group, not only count.
- Switch `volatile_task_state` role from `user` to `system`; if provider compatibility fails, stop and report the blocker instead of keeping a hidden legacy role path.

Completion criteria:

- In the five-floor dungeon trace, repeated `path_exists false` appears once as a current fact.
- `volatile_task_state` grows sublinearly and stays under a fixed budget for 6-10 calls.
- Model-visible state does not include raw todo JSON or meaningless replacement-only records.

### Phase 4 - Action Protocol Observability And Large Write Repair

Goal:

- Make protocol failures diagnosable and make large artifact creation reliable.

Files:

- `backend/harness/loop/task_executor.py`
- `backend/harness/loop/model_action_runtime.py`
- `backend/harness/loop/model_action_protocol.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/capability_system/tool_definitions.py`
- `backend/capability_system/units/tools/write_file_tool.py`
- tests under `backend/tests/sandbox_tool_runtime_regression.py`

Design decisions:

- Parse failure must preserve safe diagnostics:
  - raw length,
  - first/last preview,
  - parse error type,
  - whether output appears truncated,
  - provider finish/usage metadata when available.
- Do not expose raw invalid output wholesale to the next model turn.
- Large file writing must use chunk-safe operations instead of one massive JSON payload.

Implementation checklist:

- Replace `parse_json_object()` silent `{}` failure with a structured parse result.
- Thread parse diagnostics into `_model_protocol_repair_observation()`.
- Add raw preview redaction/truncation.
- Extend `write_file` with optional `mode=replace|start|append|complete`, `chunk_index`, `total_chunks`, and `expected_final_sha256`.
- Update tool catalog schema summary.
- Update task execution prompt to tell the model to chunk artifacts above a small threshold.
- Add final hash/size verification.

Completion criteria:

- Invalid model output diagnostics show why parsing failed without leaking full content.
- Five-floor dungeon can write a complete HTML artifact without hitting JSON output truncation.
- Large writes are verified by readback or terminal check.

### Phase 5 - Duplicate Action Guard

Goal:

- Prevent wasteful repeated no-op actions when the current state already contains the same fact.

Files:

- `backend/harness/loop/admission.py`
- `backend/harness/loop/task_executor.py`
- `backend/runtime/tool_runtime/tool_invocation_control.py`
- tests under `backend/tests/harness_runtime_facade_regression.py`

Design decisions:

- Runtime should not rely only on prompt wording to avoid duplicate actions.
- Guard should block exact duplicate tool calls with same args when the previous result is still active and no new fact changed.
- Guard should produce a repair observation, not silently skip.

Completion criteria:

- Repeating `path_exists` for the same path/result produces a model-visible repair observation.
- Legitimate retry after failure correction remains allowed.

### Phase 6 - Live E2E Acceptance

Goal:

- Verify the full task chain, not only cache accounting.

Files:

- `backend/scripts/live_five_floor_dungeon_prompt_cache_e2e.py`
- `backend/scripts/inspect_runtime_prompt_packet.py`
- new script: `backend/scripts/audit_runtime_prompt_trace.py`

Acceptance commands:

```powershell
python backend/scripts/live_five_floor_dungeon_prompt_cache_e2e.py --provider deepseek --model deepseek-v4-pro --max-output-tokens 4096 --timeout-seconds 600
python backend/scripts/inspect_runtime_prompt_packet.py <latest-task-run-id-or-trace>
```

Acceptance criteria:

- Task reaches `completed`, not `aborted`.
- Artifact exists under canonical task environment artifact root.
- Final answer references verified artifact.
- Prompt cache remains effective:
  - stable prefix hashes equal,
  - no cache breaks,
  - post-warm cache hit rate remains high.
- Prompt quality checks pass:
  - one artifact root,
  - no `runtime_output` in development sandbox task prompt,
  - no duplicate tool inventory,
  - no duplicated protocol instruction blocks,
  - volatile state bounded.

## 7. Validation Matrix

| Area | Test |
| --- | --- |
| Artifact root | Unit test canonical artifact binding from explicit contract |
| Sandbox policy | Unit test write/publish/materialized scopes match canonical root |
| Tool permission | `write_file` allowed for canonical artifact path and denied/normalized for noncanonical path |
| Prompt structure | Segment order and segment kinds exact-match test |
| Prompt duplication | Test counts for public action state, tool catalog, artifact root |
| Dynamic state | TaskStateProjector semantic dedupe tests |
| Protocol parse | Invalid/truncated JSON records parse diagnostics |
| Large write | Chunk/append write creates complete file and verifies hash/readback |
| Cache | Prompt prefix regression test remains stable |
| Real E2E | DeepSeek five-floor dungeon completes and records cache accounting |

## 8. Cutover Rules

- No parallel legacy prompt path.
- No hidden compatibility branch that keeps `runtime_output` model-visible for development sandbox task execution.
- Existing trace/manifest diagnostics may keep original request paths and internal refs.
- Model-visible prompt must expose only the new canonical runtime facts.
- Old tests that assert merged `task_stable` structure must be rewritten or deleted in the same implementation slice.

## 9. Risks And Controls

Risk: relocating explicit artifact paths could break tasks that misuse `required_artifacts` for source-code files.

Control:

- Treat `required_artifacts` as published deliverables.
- Source-code edits should be represented by file targets or verification requirements, not artifact publication.
- Add a validation error if a required artifact path is outside canonical artifact root and cannot be normalized.

Risk: changing `volatile_task_state` role from `user` to `system` could affect provider behavior.

Control:

- Make this a measured sub-step with provider E2E comparison.
- If provider compatibility fails, stop implementation and report the blocker; do not keep a hidden legacy prompt role path.

Risk: chunk writing increases step count.

Control:

- Use a chunk size that balances JSON reliability and step budget.
- Allow direct `write_file` for small files.
- Increase task step budget only if the runtime has chunk-write proof and the task genuinely needs it.

## 10. Implementation Order Lock

The implementation must happen in this order:

1. Artifact scope authority repair.
2. Prompt segment separation.
3. Dynamic/volatile state cleanup.
4. Protocol diagnostics and large write repair.
5. Duplicate action guard.
6. Real E2E acceptance.

Do not start with prompt wording. The artifact scope conflict is the first structural bug and must be fixed before prompt cleanup can be trusted.
