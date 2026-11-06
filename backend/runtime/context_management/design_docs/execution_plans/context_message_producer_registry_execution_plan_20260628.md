# Context Message Producer Registry Execution Plan

## Goal

Make context assembly pluggable at the producer boundary, not only after a `MessageSpec` already exists.

Target chain:

```text
Runtime facts
-> Dynamic context projection
-> Context message producer registry
-> standard MessageSpec[]
-> PromptSourceBundle
-> PromptAssemblyPlan
-> ContextPipeline
-> PhysicalContextPlan
-> ProviderVisibleLedger
-> ProviderPayload
```

The immediate objective is to remove compiler-owned per-context message-spec wiring for active runtime context types. The compiler may still orchestrate invocation packets, but it must not know how attachment, editor, evidence, tool observation, session history, or task-state replay context is projected into message specs.

## Current Flow

Entry point:

- `backend/harness/runtime/compiler.py`
  - Calls `DynamicContextManager.project(...)`.
  - Manually extracts context buckets from `dynamic_runtime_projection`, `volatile_request_projection`, `volatile_state_projection`, and `inherited_start_context_projection`.
  - Manually appends `_attachment_context_message_specs`, `_editor_context_message_specs`, `_read_evidence_context_message_specs`, `_tool_observation_context_message_specs`, `_session_history_tail_context_message_specs`, and `_task_state_replay_message_specs` in each invocation branch.

Standardized downstream:

- `backend/prompt_composition/source_bundle.py`
- `backend/prompt_composition/assembly_plan.py`
- `backend/runtime/context_management/context_pipeline.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/physical_context_plan.py`
- `backend/runtime/context_management/provider_visible_context_ledger.py`

Existing but not active as the producer bus:

- `backend/runtime/context_management/context_candidate_registry.py`

## Authority Problem

| Layer | Current responsibility | Problem | Target responsibility |
| --- | --- | --- | --- |
| `DynamicContextManager` | Projects runtime/session/task/tool/editor facts | Also emits section reports and fixed bucket keys | Observe and normalize runtime facts into projection buckets |
| `compiler.py` | Builds invocation packet and model messages | Knows per-context extractors, source refs, metadata, and spec order | Orchestrate packet creation and call one context producer registry |
| `context_message_producer_registry` | Missing active path | New contexts require compiler edits | Own active producer registration and message-spec projection |
| `context_segment_registry` | Kind defaults | Correct direction | Keep semantic declarations, not producer execution |
| `context_segment_policy` | Lifecycle/cache/commit/replay policy | Correct direction | Keep sole lifecycle policy authority |
| `physical_context_plan` | Physical lane/cache spine | Correct direction | Keep sole physical lane authority |

## Design Principles

1. New context enters through one producer registration point.
2. Producers may select facts and render `MessageSpec`s, but they must not decide physical lane.
3. Lifecycle defaults come from `context_segment_registry` and `context_segment_policy`.
4. Compiler must not own context-specific extraction logic.
5. Existing active behavior must keep the same semantic order:
   - `single_agent_turn`: attachment, turn-state attention, evidence cursor, editor index, read evidence context, session history.
   - `task_execution`: attachment, turn-state attention, evidence cursor, read evidence context, editor index, task-state replay.
   - `tool_observation_followup`: attachment, turn-state attention, editor index, tool transcript delta, read evidence context, session history.
6. No `v2`, no shadow compatibility path, no old helper retained after migration.

## Target Objects

`ContextMessageProducerRequest`

- Invocation kind.
- Source-ref prefix.
- `DynamicContextProjection`.
- Normalized source payload buckets.

`ContextMessageProducer`

- Stable `producer_id`.
- `collect(request) -> tuple[dict, ...]`.
- Emits standard `MessageSpec` only.

`ContextMessageProducerRegistry`

- Registers producers by ID.
- Collects producers in invocation-specific order.
- Emits diagnostics naming active producer IDs and output counts.
- Treats a producer ID referenced by the active order but missing from the registry as a configuration error, not as a silent empty context segment.

`ContextMessageProjection`

- Normalized payloads needed by existing packet code while migration is in progress:
  - `dynamic_payload`
  - `volatile_payload`
  - `inherited_start_context_payload`
  - `current_request_payload`
  - `session_history_payload`
  - `attachment_context_payload`
  - `turn_state_attention_context_payload`
  - `evidence_index_cursor_payload`
  - `editor_context_payload`
  - `tool_observation_context_payload`
- `message_specs`
- `diagnostics`

Producer order:

- Default order is derived from invocation kind.
- A caller may pass an explicit `producer_order` when a context set must be plugged or unplugged deliberately.
- The compiler uses the default order; it does not own per-context producer selection.

## Implementation Plan

### Phase 1: Add Active Producer Registry

Files:

- Add `backend/harness/runtime/context_message_producers.py`.

Change:

- Define request/projection/registry types.
- Move active context extractors and message-spec producers out of `compiler.py`.
- Preserve the existing active message order per invocation.

Verification:

- `python -m py_compile backend/harness/runtime/context_message_producers.py`

### Phase 2: Wire Compiler Through One Standard Entry

Files:

- Update `backend/harness/runtime/compiler.py`.

Change:

- Replace per-context extraction and `_xxx_context_message_specs(...)` calls with `build_context_message_projection(...)`.
- Keep compiler-owned runtime boundary/current exact evidence/task contract specs in compiler because they are not generic context producers yet.

Verification:

- Search compiler for removed helper calls.
- `python -m py_compile backend/harness/runtime/compiler.py`

### Phase 3: Delete Old Compiler Helper Structure

Files:

- Update `backend/harness/runtime/compiler.py`.

Change:

- Delete old `_extract_*_context_payload` and `_xxx_context_message_specs` helpers from compiler.
- Delete `_task_state_replay_message_specs` from compiler after moving it to the producer module.
- Keep unrelated provider protocol replay helpers in compiler for this slice.

Verification:

- `rg "_attachment_context_message_specs|_editor_context_message_specs|_tool_observation_context_message_specs|_task_state_replay_message_specs|_extract_editor_context_payload" backend/harness/runtime/compiler.py`
  must return no active matches.

### Phase 4: Export The Standard Producer Surface

Files:

- Update `backend/harness/runtime/__init__.py` only if this package already exposes runtime helpers.
- Otherwise leave exports local to avoid new public API noise.

Change:

- Do not add a parallel public API unless needed by active call sites.

Verification:

- Import through compiler path.

### Phase 5: Runtime Verification

Commands:

```powershell
python -m py_compile backend/harness/runtime/context_message_producers.py backend/harness/runtime/compiler.py backend/runtime/context_management/context_pipeline.py backend/runtime/context_management/context_segment_policy.py backend/runtime/context_management/physical_context_plan.py
```

If fixed runtime ports are touched or server startup changes are required:

- Backend: `http://127.0.0.1:8003`
- Frontend: `http://127.0.0.1:3000`

No regression test files are added.

## Deletion Criteria

Delete old code when:

- Its only role is compiler-local extraction or message-spec projection for a migrated context producer.
- The same behavior is represented by `context_message_producers.py`.
- Active compiler branches call the registry instead of the old helper.

Keep code only when:

- It still owns a non-context-producer concern in this slice, such as provider protocol replay, runtime boundary prompt construction, or current exact evidence injection.

## Completion Definition

This slice is complete when:

- Active compiler branches use one producer projection object for migrated context types.
- Existing migrated context types are registered in one ordered producer registry.
- Downstream `MessageSpec -> ContextPipeline -> PhysicalContextPlan` path is unchanged.
- No active old helper calls remain in `compiler.py`.

## Execution Record 2026-06-28

Status: implemented for the active context-message producer slice.

Implemented:

- Added `backend/harness/runtime/context_message_producers.py`.
- Rewired `single_agent_turn`, `task_execution`, and `tool_observation_followup` in `backend/harness/runtime/compiler.py` through `build_context_message_projection(...)`.
- Deleted migrated compiler-local extractors and message-spec helpers from `compiler.py`.
- Exported the standard producer surface through `backend/harness/runtime/__init__.py` lazy exports because this package already exposes runtime helper surfaces.
- Added an explicit `producer_order` override to the projection builder and made missing ordered producers fail fast.

Compiler responsibilities still intentionally retained in this slice:

- Runtime boundary/current request/current exact evidence/task contract message construction.
- Provider protocol replay and recovery package projection.
- Dynamic context section metadata helper used by non-migrated compiler-owned messages.

Connection correction found during execution:

- The initial producer split for `volatile_request_projection.history` over-normalized session history and could drop top-level `pinned_facts`.
- The split now mirrors the original compiler boundary: it only separates `history` from the current request payload and leaves session-history internals to the session history producer.

Verification completed:

```powershell
python -m py_compile backend/harness/runtime/context_message_producers.py backend/harness/runtime/compiler.py backend/runtime/context_management/context_pipeline.py backend/runtime/context_management/context_segment_policy.py backend/runtime/context_management/physical_context_plan.py
```

```powershell
rg "_attachment_context_message_specs|_evidence_index_cursor_message_specs|_read_evidence_context_message_specs|_editor_context_message_specs|_tool_observation_context_message_specs|_task_state_replay_message_specs|_extract_editor_context_payload|_extract_attachment_context_payload|_extract_turn_state_attention_context_payload|_extract_tool_observation_context_payload|_extract_evidence_index_cursor_payload|_split_volatile_request_payload|_tool_observation_entry_ref|_task_state_replay_entry_ref|_session_history_tail_context_message_specs" backend/harness/runtime/compiler.py
```

Result:

- Compile passed.
- Removed compiler helper search returned no matches.
- A targeted producer smoke confirmed `session_pinned_facts_context` is emitted with the original source ref shape `single_agent_turn_session_history:pinned_facts_context`.
- A targeted registry smoke confirmed missing ordered producers fail fast, while explicit `producer_order=("session_history_context",)` emits only session history context and preserves pinned facts.
- Backend restarted on the fixed project port `http://127.0.0.1:8003`; `/health` returned `{"status":"ok"}` and port `8003` had one listening project backend process.
