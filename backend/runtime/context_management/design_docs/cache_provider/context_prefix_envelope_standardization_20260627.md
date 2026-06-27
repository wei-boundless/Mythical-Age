# Context Prefix Envelope Standardization

Date: 2026-06-27

## Goal

Standardize model-visible injected context so runtime, memory, task, evidence, and natural-language prompt sections use one explicit envelope protocol instead of mixed free-text prefixes.

The target is not a cosmetic title change. The target is a Codex-style contextual fragment boundary that is:

- readable by the model;
- parseable by the runtime;
- stable for cache and replay planning;
- auditable through `kind`, `source_ref`, `cache_role`, `prefix_tier`, and `validity_scope`;
- independent from display titles.

## Current Problem

The runtime currently exposes several prefix styles to the model:

- runtime payload fragments as `Title\n{compact_json}`;
- role and environment prompt fragments with Chinese text prefixes such as `当前职责：` and `当前任务环境：`;
- bracketed section labels such as `【任务环境提示：...】`;
- provider protocol `prefix=True`, which is an assistant completion prefix and not a context prefix.

The internal cache architecture is already strong. `cache_role`, `prefix_tier`, context segment policy, physical context lanes, and provider payload manifests are the correct authority layers. The weak point is the model-visible rendering boundary. A title line is not a durable fragment marker.

## Source Comparison

Local source evidence outside this project:

- Codex source: `D:/AI应用/openai-codex/codex-rs/core/src/context/user_instructions.rs`
  - model-visible AGENTS.md fragments use role `user`;
  - the stable start marker is `# AGENTS.md instructions for `;
  - the body is rendered as `directory + "\n\n<INSTRUCTIONS>\n" + text + "\n"`;
  - the end marker used by classification is `</INSTRUCTIONS>`.
- Codex layout tests: `D:/AI应用/openai-codex/codex-rs/core/tests/suite/agents_md.rs`
  - the test looks for messages that start with `# AGENTS.md instructions for `;
  - root and nested AGENTS.md docs are concatenated from project root to cwd.
- Codex memory filtering: `D:/AI应用/openai-codex/codex-rs/memories/write/src/phase1.rs`
  - marked AGENTS fragments are detected by stable start/end markers and excluded from memory writing.
- Claude Code local source: `D:/AI应用/claude-code-nb-main/utils/messages.ts`
  - `wrapInSystemReminder(content)` renders `<system-reminder>\n${content}\n</system-reminder>`;
  - attachment-origin messages are idempotently wrapped;
  - later normalization relies on `startsWith('<system-reminder>')`.
- Claude Code local prompt constants: `D:/AI应用/claude-code-nb-main/constants/prompts.ts`
  - the model is explicitly told that tool results and user messages may include `<system-reminder>` tags, and that those tags are automatically added by the system.

Confirmed mature-agent pattern:

- model-visible injected context should have a stable, recognizable wrapper;
- the wrapper should be usable by runtime code as a discriminator, not only by humans as a title;
- the wrapper should keep provenance and validity obvious to the model;
- physical/cache policy should remain separate from textual wrapper choice.

The target envelope borrows the stable marker idea from Codex and Claude Code, but uses a project-specific `context_fragment.v1` protocol because this project has multiple context lanes (`runtime`, `memory`, `task`, `evidence`, `skills`) and needs attributes such as `kind`, `source_ref`, `cache_role`, `prefix_tier`, and `validity_scope`.

## Format Tradeoff

| Format | Strength | Weakness | Decision |
| --- | --- | --- | --- |
| Codex `# AGENTS.md instructions for ...` + `<INSTRUCTIONS>` | Extremely readable, stable for AGENTS.md, easy prefix detection. | Specialized for project instructions; not enough metadata for runtime/memory/evidence lanes. | Keep as reference pattern, not copy directly. |
| Claude Code `<system-reminder>` | Simple, idempotent, good discriminator for system-injected reminders. | Too broad; does not encode cache role, source, validity, or semantic lane. | Borrow the explicit tag boundary, not the generic tag name. |
| Old project `Title\n{json}` | Compact and easy to parse in happy path. | Title is not a protocol; fragile when preambles are added; weak model-visible ownership; hard to distinguish display title from cache identity. | Stop emitting. Keep narrow read-only parser during cutover. |
| New `<context_fragment protocol="context_fragment.v1" ...>` | Explicit protocol identity, model-readable provenance, parseable payload, deterministic body, cache attributes visible without moving cache authority. | Intentionally changes visible bytes once, so old provider cache entries are invalidated. | Adopt as canonical injected-context envelope. |

## Target Authority Chain

| Layer | Authority | Target responsibility |
| --- | --- | --- |
| Prompt composition | assemble | Render one canonical envelope around injected context. |
| Runtime compiler | assemble | Choose `kind`, role, source, cache scope, and payload; it does not own envelope syntax. |
| Context segment policy | normalize | Classify sections, cache roles, replay policy, and physical lane. |
| Prompt segment plan | normalize | Parse payload from canonical envelopes for stable-prefix validation. |
| Provider payload manifest | record | Parse canonical payloads for tool/catalog/cache checks. |
| Model gateway | execute/record | Treat provider tool schemas as sidecars, not message-prefix context. |

## Canonical Envelope

Use a single XML-like wrapper:

```text
<context_fragment kind="current_runtime_boundary" title="Current Runtime Boundary" role="system" cache_scope="none" cache_role="volatile" prefix_tier="volatile" source_ref="task_execution_runtime_delta">
{"payload":{"...":"..."}}
</context_fragment>
```

Rules:

- `kind` is the protocol identity.
- `title` is human-readable only.
- `source_ref`, `cache_scope`, `cache_role`, `prefix_tier`, and `validity_scope` are attributes when known.
- Natural-language section renderers do not own final cache policy; their envelopes may omit cache attributes, while the surrounding message spec and physical context policy remain the cache authorities.
- JSON payload is deterministic and compact.
- Natural-language prompt sections use the same envelope with text payloads.
- Existing `prefix=True` remains provider assistant completion prefix and must not be described as context prefix.

## Implementation Slices

### 1. Add envelope renderer/parser

File:

- `backend/prompt_composition/context_envelope.py`

Responsibilities:

- render context fragments;
- escape XML attributes and text safely;
- parse canonical envelope payloads;
- expose helpers for detecting canonical context fragments.

### 2. Route runtime payload fragments through the envelope

File:

- `backend/prompt_composition/runtime_fragments.py`

Change:

- replace `Title\n{json}` rendering with canonical `<context_fragment ...>` rendering;
- keep metadata keys for traceability, but add envelope metadata;
- make `title` display-only.

### 3. Route natural-language prompt sections through the envelope

File:

- `backend/prompt_composition/section_renderer.py`

Change:

- wrap agent role, personality, task contract, environment, and lifecycle instructions in canonical envelopes;
- preserve the existing Chinese role/task wording inside payload text;
- avoid developer-node descriptions.

### 4. Update payload parsers

Files:

- `backend/harness/runtime/prompt_segment_plan.py`
- `backend/runtime/model_gateway/provider_payload.py`

Change:

- parse canonical envelope JSON first;
- retain a narrow legacy parse path only as a recovery reader for already-materialized context during the cutover;
- do not continue emitting legacy `Title\nJSON`.

### 5. Wrap current-turn text injections

File:

- `backend/harness/runtime/compiler.py`

Change:

- wrap `lifecycle_runtime_guidance` in the canonical envelope;
- unwrap nested lifecycle instruction text before rewrapping, so model-visible content does not contain escaped nested envelopes;
- wrap `active_skills` in the canonical envelope;
- keep `graph_node_completion_prefix` outside the envelope because it is an assistant completion prefix for provider chat-prefix mode, not injected context.

### 6. Clarify assistant completion prefix

Files:

- `backend/prompt_composition/message_specs.py`
- existing call sites that set `prefix=True`

Change:

- annotate `prefix=True` metadata as `assistant_completion_prefix`;
- keep it separate from context prefix terminology.

## Cutover Rule

New runtime output must emit only canonical envelopes for injected context. Legacy titled JSON is read-only recovery input for previously materialized entries, not an active output format.

## Validation

No new regression test files are required for this pass. Validation is by:

- reading changed runtime paths;
- checking all runtime payload rendering goes through the envelope;
- checking parsers can read the new canonical format;
- running syntax/import-level checks only if needed to catch implementation mistakes;
- avoiding any fake output, skipped assertions, or hardcoded pass behavior.

Executed validation:

```powershell
python -m py_compile backend\harness\runtime\compiler.py backend\prompt_composition\context_envelope.py backend\prompt_composition\runtime_fragments.py backend\prompt_composition\section_renderer.py backend\prompt_composition\message_specs.py backend\prompt_composition\__init__.py backend\harness\runtime\prompt_segment_plan.py backend\runtime\model_gateway\provider_payload.py backend\runtime\context_management\provider_visible_context_ledger.py
```

Result: passed.

Runtime probe:

- `lifecycle_runtime_guidance` now renders first line as `<context_fragment protocol="context_fragment.v1" kind="lifecycle_runtime_guidance" ...>`;
- `active_skills` now renders first line as `<context_fragment protocol="context_fragment.v1" kind="active_skills" ...>`;
- nested stable lifecycle text is unwrapped before current-turn lifecycle guidance is wrapped.

Cache/physical probe:

- same input produced the same stable prefix hash across two segment plans;
- same input produced the same physical cache spine hash across two physical plans;
- stable `tool_index_stable` remained in `global_static_prefix`;
- volatile `active_skills` remained in `never_replay_tail`;
- `stable_after_tail_violations` stayed empty.

## Cache And Physical Assembly Safety

This change does not move physical context lanes. `physical_context_plan.py` and `context_segment_policy.py` remain the authorities for lane ordering, cache spine participation, replay policy, and prefix tier normalization.

The model-visible content bytes intentionally changed from `Title\nJSON` to `<context_fragment ...>JSON</context_fragment>`. That means old provider-side prefix cache entries can miss once after the cutover. This is expected and correct. After the cutover, deterministic JSON ordering and stable attributes preserve cache consistency for identical inputs.

`provider_visible_context_ledger.py` schema is bumped to v2 so old provider-visible ledger entries are rebuilt instead of silently mixing old and new visible formats.

## Out Of Scope

- Rewriting cache tier or physical lane architecture.
- Changing provider native tool sidecar semantics.
- Reworking frontend display.
- Adding compatibility branches that keep two active rendering formats alive.
