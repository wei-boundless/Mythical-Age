# Source-Backed Prompt Architecture Audit - 2026-06-08

## 1. Purpose

This document records the local-source comparison and the second-pass audit for the current prompt/runtime architecture.

The goal is not to polish wording. The target is a mature agent control architecture where:

- the model can understand the current request in context;
- the system exposes the environment, permissions, tools, memory and current work as explicit runtime facts;
- prompt assembly has clear precedence and state-triggered fragments;
- the main agent owns semantic judgment and final synthesis;
- the harness owns environment projection, execution, observation and enforcement;
- stale summaries, memories, previous tasks and tool noise cannot overrule the current user turn.

This is based on local reference source, not generic web summaries.

## 2. Local Source References

### Codex local source

- `D:/AI应用/openai-codex/codex-rs/protocol/src/prompts/base_instructions/default.md`
  - Identity and capability framing.
  - Repository instruction scope.
  - Preamble/update discipline.
  - Planning discipline.
  - Task execution persistence.
  - Validation and final answer rules.
- `D:/AI应用/openai-codex/codex-rs/core/templates/model_instructions/gpt-5.2-codex_instructions_template.md`
  - Final answer formatting separated from tool/runtime specifics.
- `D:/AI应用/openai-codex/codex-rs/core/templates/compact/prompt.md`
  - Context checkpoint compaction is a small, single-purpose handoff.
- `D:/AI应用/openai-codex/codex-rs/ext/memories/src/prompts.rs`
  - Memory read path is injected as a dedicated developer instruction, not merged into every environment prompt.

### Claude Code local source

- `D:/AI应用/claude-code-nb-main/utils/systemPrompt.ts`
  - Effective system prompt has explicit precedence:
    `override > coordinator > agent > custom > default`, with append prompt at the end unless override is used.
- `D:/AI应用/claude-code-nb-main/tools/AgentTool/prompt.ts`
  - Fresh subagents start with zero context.
  - Parent must brief them like a capable colleague entering the room.
  - Parent must not delegate understanding.
  - Parent must not predict or fabricate fork/subagent results.
- `D:/AI应用/claude-code-nb-main/tools/TaskCreateTool/prompt.ts`
  - Task tracking is gated by complexity, new instructions and completion, not always-on bookkeeping.
- `D:/AI应用/claude-code-nb-main/memdir/teamMemPrompts.ts`
  - Memory, plan and tasks are explicitly separated.
  - Memory is for future conversations; tasks are for current work; plans are for approach alignment.

## 3. Mature Architecture Invariants

The local Codex and Claude Code sources point to the same engineering shape:

1. Stable constitution comes first.
   - The base prompt should define identity, collaboration posture, instruction precedence, planning, execution, validation and answer boundaries.
   - It should not describe itself as "request judgment layer" or "runtime node".

2. Prompt precedence must be explicit.
   - Different prompt sources are not equal.
   - Override, mode/coordinator, agent role, runtime protocol, environment boundary, lifecycle fragments, tool guidance, skill guidance and project append instructions need deterministic ordering.

3. Lifecycle fragments should be state-triggered.
   - Active-work rules should be visible when active work exists or an active-work action is available.
   - Tool recovery rules should be visible when the turn has tool observations or is a tool-observation followup.
   - Memory handoff rules should be visible when memory context, compaction or memory maintenance is in scope.
   - A general environment should not carry every lifecycle rule on every turn.

4. Tools should own capability contracts.
   - Tool prompt text should explain when to use a tool, what it can and cannot do, input constraints and failure semantics.
   - Runtime protocol should not repeat every tool rule.

5. Main agent keeps final authority.
   - Subagents produce evidence and scoped findings.
   - The parent agent must synthesize, decide and answer.
   - A subagent result is not automatically the final answer.

6. Memory is not current truth.
   - Memory can supply candidates and context.
   - Current files, tool observations and latest user messages remain higher authority.
   - Memory writes must be evidence-backed and should not store temporary task state as durable user/project memory.

7. Numeric confidence is not a mature model decision interface.
   - Agent and worker prompts should not ask the model to output self-rated confidence.
   - Evidence quality may still exist, but it should be named as `source_strength`, `retrieval_score`, `parse_quality` or `verification_status`, and must be derived from evidence or deterministic system scoring.

## 4. Current Runtime Flow

Current chat turn path:

```text
api.chat.ChatRequest
-> _query_request_from_payload()
-> HarnessRuntimeFacade.astream()
-> assemble_runtime()
-> active/current work candidate lookup
-> turn_input_facts
-> session_emphasis
-> runtime memory context
-> runtime_branch projection
-> _run_single_agent_turn()
-> run_single_agent_turn()
-> RuntimeCompiler.compile_single_agent_turn_packet()
-> model invocation
-> action parsing / protocol repair
-> tool execution or control action
-> tool observation followup or final answer
-> memory maintenance after commit
```

Key files:

- `backend/api/chat.py`
  - `ChatRequest` is strict with `extra="forbid"`.
  - The API normalizes editor context and project binding, then creates a harness request.
- `backend/harness/entrypoint/runtime_facade.py`
  - Builds runtime assembly.
  - Collects active work/current work/recent outcome.
  - Builds turn input facts and memory context.
  - Dispatches single-agent turn or explicit task lifecycle.
- `backend/harness/runtime/assembly.py`
  - Resolves runtime profile, environment, prompt refs, tool exposure and operation authorization.
- `backend/harness/runtime/compiler.py`
  - Builds packet messages, stable payload, dynamic payload, output contract and prompt manifest.
- `backend/harness/loop/single_agent_turn.py`
  - Invokes the model, parses actions, repairs protocol errors, schedules tools and emits final events.
- `backend/harness/loop/active_work.py`
  - Validates current-work control relation and denies ambiguous/independent control.
- `backend/memory_system/runtime_context_provider.py`
  - Builds model-visible memory context payload.
- `backend/memory_system/maintenance.py`
  - Runs model-backed memory maintenance proposals after commit.

## 5. Authority Map

| Layer | Current owner | Legitimate role | Hidden or risky decision | Target action |
| --- | --- | --- | --- | --- |
| API request | `backend/api/chat.py` | Normalize request and editor binding | Should not infer intent | Keep strict; no prompt logic here |
| Runtime facade | `backend/harness/entrypoint/runtime_facade.py` | Assemble environment, active work, memory and branch | `_current_work_context_from_latest_task()` can reintroduce latest task as current work candidate | Keep, but ensure turn facts clearly mark active vs latest resumable vs recent outcome |
| Runtime assembly | `backend/harness/runtime/assembly.py` | Resolve profile, environment, tools and prompt refs | Environment prompt refs are copied wholesale | Add lifecycle selector before compiler consumes refs |
| Prompt assembly | `backend/prompt_library/assembly.py` | Resolve packs/resources and validate scope | No explicit prompt precedence beyond list order | Add `PromptAssemblyPolicy` and manifest precedence diagnostics |
| Environment registry | `backend/task_system/environments/default_environments.py` | Define resource and boundary prompts | Mounts all general lifecycle prompts into every general turn | Move state lifecycle prompts out of always-on environment refs |
| Runtime protocol | `backend/prompt_library/packs.py` | Define action protocol per invocation | Overlaps with lifecycle prompts | De-duplicate into compact runtime base + action protocol |
| Lifecycle prompts | `backend/prompt_library/general_lifecycle_prompts.py` | Teach model current-turn judgment | Correct wording, wrong mounting granularity | Keep content as source material; mount by state |
| Tool guidance | `backend/prompt_library/tool_prompts.py` | Explain visible tool contracts | Good direction, should be first-class in assembly diagnostics | Keep and strengthen per-tool contracts |
| Subagent tools | `backend/capability_system/tools/tool_units/subagent_control_tool.py` | Start/wait/list/close child agents | Already includes fresh specialist and no prediction guidance | Add "never delegate understanding" and one-message parallel guidance |
| Worker prompts | `backend/prompt_library/worker_prompts.py` | Define specialist roles | Several prompts still require `confidence` | Replace with evidence quality/limitations/verdict fields |
| Memory manager | `backend/prompt_library/agent_prompts.py`, `backend/memory_system/maintenance.py` | Propose memory/session updates | Mostly mature; still needs clearer memory vs plan vs todo taxonomy | Keep manager, refine prompt and schemas |
| Durable recall | `backend/memory_system/durable.py` | Select useful memory notes | Prompt asks model for `confidence` | Replace with `selection_reason`, `needs_verification`, `evidence_status` |
| Runtime compiler | `backend/harness/runtime/compiler.py` | Build final model packet | Does not select lifecycle fragments by state | Add selection layer before environment/agent/context instruction assembly |
| Single turn loop | `backend/harness/loop/single_agent_turn.py` | Execute model decision and recover protocol | Native active_work_control still preserves `confidence` arg | Strip or reject model confidence in control action payload |

## 6. Detailed Findings

### P0. Lifecycle prompts are mounted as a general environment bundle

Evidence:

- `backend/task_system/environments/default_environments.py` mounts every `environment.general.lifecycle.*` prompt for `env.general.workspace`.
- `backend/tests/task_environment_registry_regression.py` currently asserts that the model input contains active-work, tool-observation and memory lifecycle text in the general environment packet.

Why this matters:

- The model sees active-work control text even when no active work exists.
- The model sees tool-observation recovery text before any tool observation exists.
- The model sees memory handoff text even when no memory action is available.
- This makes the prompt louder than the actual runtime state.

Target:

- General environment should expose resource identity and boundary rules.
- Runtime/lifecycle selector should expose lifecycle fragments only when the state calls for them.

### P0. Prompt assembly lacks explicit precedence

Evidence:

- `backend/prompt_library/assembly.py` resolves pack refs, appends explicit refs, de-duplicates and validates scope.
- It does not encode a source precedence model like Claude Code's `buildEffectiveSystemPrompt()`.

Why this matters:

- Agent role, environment boundary, lifecycle prompts and tool guidance are all just ordered text.
- Future coordinator/mode prompts, override prompts, or project append instructions can silently conflict.
- Prompt manifest shows stable refs but not authority order or supersession reason.

Target:

```text
override
-> coordinator/mode
-> agent role
-> runtime base/protocol
-> environment boundary
-> lifecycle state fragments
-> tool guidance
-> skill guidance
-> project/user append instructions
```

### P1. Runtime protocol and lifecycle prompts overlap

Evidence:

- `backend/prompt_library/packs.py` `RUNTIME_SINGLE_AGENT_TURN_PROMPT` already explains request judgment, active work, task handoff, tool observations, memory and finalization.
- `backend/prompt_library/general_lifecycle_prompts.py` separately explains the same lifecycle stages.

Why this matters:

- The model receives duplicate semantic instructions from different owner layers.
- Future edits can fix one copy and leave the other stale.

Target:

- Runtime protocol owns schema, action types and transport rules.
- Lifecycle fragments own state-specific judgment guidance.
- Agent role owns collaboration posture and final responsibility.

### P1. Active work/current work is structurally safer now, but the prompt should mirror the state

Evidence:

- `backend/harness/loop/active_work.py` validates `relation_to_current_work` and denies ambiguous current-work controls.
- `backend/harness/runtime/compiler.py` only enables `active_work_control` when `active_work_context` exists.
- However, environment lifecycle prompt still includes active-work guidance even when the action is unavailable.

Target:

- If `active_work_context` exists: mount active-work lifecycle fragment and expose `active_work_control`.
- If absent: expose a compact negative fact in runtime projection, not the full active-work control prompt.

### P1. Subagent design is close, but specialist outputs still carry confidence

Evidence:

- `backend/capability_system/tools/tool_units/subagent_control_tool.py` already says a fresh specialist needs a complete brief and that parent must not predict child results.
- `backend/prompt_library/rules.py` requires web researcher `confidence`.
- `backend/prompt_library/worker_prompts.py` requires `confidence` in web/PDF/table worker outputs.

Why this matters:

- A mature agent should explain evidence strength and limitations, not invent a scalar confidence.
- Numeric confidence becomes a false authority signal when it comes from the model.

Target:

- Worker outputs should use:
  - `evidence_refs`
  - `limitations`
  - `open_questions`
  - `verification_status`
  - `source_strength` only when evidence-derived
  - `recommended_parent_action`
- Remove model self-confidence from worker prompt contracts.

### P1. Memory system is directionally mature, but memory prompts should be scoped

Evidence:

- `backend/agent_system/profiles/runtime_profile_registry.py` registers `memory_system_agent`.
- `backend/prompt_library/agent_prompts.py` defines a natural memory manager role.
- `backend/memory_system/maintenance.py` runs model-backed memory maintenance proposals only.
- `backend/memory_system/runtime_context_provider.py` filters model-visible memory sections.

Risk:

- `MEMORY_STATE_HANDOFF_PROMPT` is currently part of the always-mounted general lifecycle environment.
- Durable memory recall prompt in `backend/memory_system/durable.py` still asks the model for `confidence`.
- Memory store and evidence systems have legitimate internal confidence/quality fields; these need naming separation from model self-confidence.

Target:

- Keep memory manager and compactor as dedicated agents.
- Main agent receives memory as candidate context only.
- Replace recall selector `confidence` with decision reason and verification requirement.
- Keep deterministic retrieval/parse quality fields only when they are system-computed or evidence-derived.

### P2. Version suffix policy needs a scoped migration rule

User constraint: new prompt IDs should not use `.v1`.

Current state:

- New general lifecycle IDs already avoid `.v1`.
- Existing runtime, worker, tool and environment prompt IDs still contain `.v1`.

Target rule:

- New prompt resources created by this refactor must not use `.v1`.
- Touched lifecycle resources should move to suffix-free IDs during cutover.
- Existing unrelated `.v1` IDs should be cleaned in a dedicated prompt ID migration, not mixed into the lifecycle selector patch unless the same refs are touched.

This avoids a huge unrelated rename while still obeying the new design for all newly introduced prompt architecture.

## 7. Target Prompt Library Shape

Recommended resource families:

```text
runtime.base.constitution
runtime.turn.action_protocol
runtime.task.execution_protocol
runtime.observation.followup_protocol
runtime.compaction.semantic_checkpoint

agent.role.main_interactive.single_turn
agent.role.main_interactive.task_execution
agent.role.context_compactor.semantic_checkpoint
agent.role.memory_manager.maintenance

environment.general.workspace.orientation
environment.general.workspace.boundary

lifecycle.turn.context_intake
lifecycle.turn.request_judgment
lifecycle.turn.environment_alignment
lifecycle.turn.action_selection
lifecycle.state.active_work_control
lifecycle.state.task_run_handoff
lifecycle.state.user_steer_contract_revision
lifecycle.state.tool_observation_recovery
lifecycle.state.memory_state_handoff
lifecycle.turn.finalization

tool.guidance.read_file
tool.guidance.write_file
tool.guidance.terminal_powershell
tool.guidance.subagent
tool.guidance.browser
tool.guidance.web_fetch

memory.recall.selector
memory.context.runtime_view
memory.maintenance.proposal_schema
```

No new IDs in this target shape use `.v1`.

## 8. Lifecycle Selection Matrix

| Fragment | Mount condition | Owner | Notes |
| --- | --- | --- | --- |
| `lifecycle.turn.context_intake` | single-agent turn, task execution where user/history is visible | runtime lifecycle selector | Always useful as authority ordering |
| `lifecycle.turn.request_judgment` | single-agent turn | runtime lifecycle selector | Should be concise; no layer self-description |
| `lifecycle.turn.environment_alignment` | environment/tool boundary visible | runtime lifecycle selector | Uses current environment projection |
| `lifecycle.turn.action_selection` | any model turn with action schema | runtime lifecycle selector | Tied to allowed actions |
| `lifecycle.state.active_work_control` | `active_work_context` present and `active_work_control` allowed | runtime lifecycle selector | Not environment-default |
| `lifecycle.state.task_run_handoff` | `request_task_run` allowed | runtime lifecycle selector | Teaches contract seed quality |
| `lifecycle.state.user_steer_contract_revision` | active work, pending user steers or task contract revision context | runtime lifecycle selector | Avoid always-on noise |
| `lifecycle.state.tool_observation_recovery` | tool observation followup or latest tool observations present | runtime lifecycle selector | Must attach to observation facts |
| `lifecycle.state.memory_state_handoff` | memory context visible, memory maintenance, or compaction scope | memory/runtime lifecycle selector | Not general environment |
| `lifecycle.turn.finalization` | any user-visible final response path | runtime lifecycle selector | Can stay compact and always available |

## 9. Environment Prompt Controller Design

Additional design decision: prompts should be environment-shaped. A task environment should own a complete prompt strategy, but it should not statically dump every prompt into every model turn.

Target composition:

```text
general environment base
+ user-selected task environment overlay
+ current invocation runtime protocol
+ state-triggered lifecycle fragments
+ visible tool guidance
+ visible memory/compaction guidance
=> PromptMountPlan
```

### 9.1 General environment is the default base

`env.general.workspace` is the default environment and the base for all task environments.

It owns:

- general workspace orientation;
- general resource and boundary rules;
- general context authority ordering;
- general current-request judgment;
- general finalization standards;
- the common tool/permission explanation frame.

It does not own:

- choosing a specialist task environment for the user;
- mounting all task-environment prompts permanently;
- replacing runtime action protocol;
- replacing agent profile;
- deciding user intent before the model turn.

### 9.2 Other task environments are overlays

Specialized task environments should overlay the general base instead of replacing it.

Examples:

```text
general.workspace.base
+ coding.workspace.overlay
```

```text
general.workspace.base
+ writing.graph_node.overlay
```

An overlay may add or narrow:

- domain role posture;
- artifact acceptance criteria;
- domain tool guidance;
- file/storage boundaries;
- lifecycle policy;
- finalization policy.

An overlay must not remove:

- runtime action protocol;
- latest user request authority;
- tool observation authority;
- permission boundary;
- active-work relation guard;
- memory candidate-only rule.

### 9.3 Environment switching is user-controlled

Environment switching should come from the user, UI/session setting, project binding or task entrypoint. The model should not silently switch environments.

Recommended rules:

- Default to `env.general.workspace`.
- When the user explicitly chooses a task environment, the system records `selected_environment_id`.
- Runtime assembly mounts the selected environment overlay on top of the general base.
- The model may see the current selected environment and a future switch-request affordance, but it cannot claim the environment has already switched.

### 9.4 General environment may reserve a switch-request interface, but it is not implemented yet

The general environment may define a future interface such as:

```text
environment_switch_request
```

This would mean the main agent believes another task environment may fit better and is requesting user/UI confirmation.

This phase does not implement it:

- no new action type;
- no new API route;
- no frontend switch control;
- no model-controlled environment switching;
- no runtime branch behavior change.

Only the design and prompt constraints are documented for now.

### 9.5 EnvironmentPromptController output

The controller should output a structured mount plan rather than raw prompt text:

```text
PromptMountPlan
- base_environment_id
- selected_environment_id
- base_prompt_refs
- overlay_prompt_refs
- lifecycle_prompt_refs
- tool_guidance_refs
- memory_prompt_refs
- precedence_report
- rejected_refs
- diagnostics
```

`RuntimeCompiler` should consume this plan instead of guessing which environment refs belong in a given turn.

## 10. Implementation Blueprint

### Phase 1. Add prompt assembly precedence diagnostics

Files:

- `backend/prompt_library/models.py`
- `backend/prompt_library/assembly.py`
- `backend/prompt_library/manifest.py`
- `backend/harness/runtime/compiler.py`
- `backend/tests/prompt_rule_system_regression.py`
- `backend/tests/prompt_library_registry_regression.py`

Changes:

- Add prompt layer/precedence metadata.
- Make manifest report prompt source order and supersession/append behavior.
- Keep behavior initially equivalent except diagnostics and validation.

Completion criteria:

- Existing prompt assemblies still resolve.
- Manifest can answer which layer produced each prompt section.
- Tests assert precedence order, not only stable ref list.

### Phase 2. Introduce EnvironmentPromptController and lifecycle selector

Files:

- `backend/prompt_library/general_lifecycle_prompts.py`
- `backend/task_system/environments/default_environments.py`
- `backend/task_system/environments/spec_resolver.py`
- `backend/harness/runtime/assembly.py`
- `backend/harness/runtime/compiler.py`
- `backend/tests/task_environment_registry_regression.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`

Changes:

- Make the general environment the default base.
- Mount other task environments as overlays only.
- Add a controller/selector that receives invocation kind, allowed actions, active work, memory context, tool observations and recent outcome.
- Assemble lifecycle refs separately from base environment refs and overlay refs.
- Document the future environment switch-request interface, but do not implement action/API/UI switching in this phase.

Completion criteria:

- No active-work prompt appears when no active work exists.
- Tool recovery prompt appears only for observation/followup state.
- Memory handoff prompt appears only when memory/compaction/maintenance state is visible.
- Stable payload reports base environment refs, overlay environment refs and lifecycle refs separately.
- Manifest reports `base_environment_id=env.general.workspace` and the user-selected `selected_environment_id`.

### Phase 3. De-duplicate runtime protocol and lifecycle wording

Files:

- `backend/prompt_library/packs.py`
- `backend/prompt_library/agent_prompts.py`
- `backend/prompt_library/rules.py`
- `backend/tests/prompt_library_registry_regression.py`

Changes:

- Runtime prompt becomes action protocol and transport authority.
- Lifecycle prompts become judgment guidance.
- Agent role prompt becomes work posture and synthesis responsibility.

Completion criteria:

- No duplicate active-work/tool-observation/memory paragraphs across runtime and lifecycle prompts.
- Runtime prompt still fully defines legal JSON/native action behavior.

### Phase 4. Subagent prompt maturation and confidence cleanup

Files:

- `backend/prompt_library/rules.py`
- `backend/prompt_library/worker_prompts.py`
- `backend/capability_system/tools/tool_units/subagent_control_tool.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/tests/search_specialist_split_regression.py`
- `backend/tests/worker_prompt_registry_regression.py`
- `backend/tests/subagent_control_regression.py`

Changes:

- Add "never delegate understanding" to subagent guidance.
- Remove model self-confidence from worker prompt required outputs.
- Strip or reject `confidence` from active-work native control payload.
- Keep evidence-derived quality under clearer names where needed.

Completion criteria:

- `rg -n "confidence" backend/prompt_library backend/harness/loop/single_agent_turn.py` shows no model-decision confidence requirement.
- Retrieval/PDF/internal quality fields remain only where they are evidence/system quality metrics.

### Phase 5. Memory selector and memory taxonomy cleanup

Files:

- `backend/prompt_library/agent_prompts.py`
- `backend/memory_system/durable.py`
- `backend/memory_system/maintenance.py`
- `backend/memory_system/runtime_context_provider.py`
- `backend/tests/memory_maintenance_agent_regression.py`
- `backend/tests/memory_system_contracts_regression.py`

Changes:

- Memory manager prompt explicitly distinguishes:
  - current reply,
  - current task state,
  - todo,
  - plan,
  - session recovery summary,
  - durable memory.
- Durable recall selector stops asking model for confidence.
- Memory context continues to be candidate-only and verification-required.

Completion criteria:

- No memory prompt asks the model for self-rated confidence.
- Tests still prove memory cannot override latest user message or tool observation.

### Phase 6. Full runtime verification

Focused commands:

```powershell
python -m pytest backend/tests/prompt_library_registry_regression.py backend/tests/task_environment_registry_regression.py
python -m pytest backend/tests/dynamic_prompt_context_projection_test.py backend/tests/prompt_rule_system_regression.py
python -m pytest backend/tests/search_specialist_split_regression.py backend/tests/worker_prompt_registry_regression.py backend/tests/subagent_control_regression.py
python -m pytest backend/tests/memory_maintenance_agent_regression.py backend/tests/memory_system_contracts_regression.py backend/tests/context_compaction_budget_regression.py
python -m pytest backend/tests/harness_runtime_facade_regression.py backend/tests/active_turn_authority_regression.py
```

Runtime smoke checks after implementation:

- Start backend on `127.0.0.1:8003`.
- Start frontend on `127.0.0.1:3000`.
- Single direct answer turn.
- Single read-only tool turn.
- Active-work status question.
- Active-work continue.
- New independent question while active work exists.
- Task-run handoff.
- Tool observation failure and recovery.
- Memory context visible but not authoritative.
- Context compaction worker invocation.
- Memory maintenance after commit.

## 11. Cutover Rules

1. No compatibility shadow path for lifecycle mounting.
   - Once selector is introduced, environment default should stop carrying state lifecycle refs.

2. No hidden fallback that re-adds all lifecycle prompts.
   - Missing lifecycle prompt should fail diagnostics visibly instead of silently restoring old behavior.

3. No model self-confidence fields in prompt contracts.
   - If a schema still needs quality information, rename and define whether it is evidence-derived or system-computed.

4. No new `.v1` prompt IDs.
   - Touched prompt resources should use suffix-free target IDs.

5. Tests must protect behavior, not old internal shape.
   - Tests that currently assert all lifecycle prompts are always present must be rewritten to assert selector behavior.

6. Environment switching must be user/session controlled.
   - The main agent may request a switch, but it cannot silently switch environments.
   - The autonomous switch interface is design-only in this phase.

7. Non-general task environments are overlays only.
   - Overlays may add or narrow environment behavior, but cannot replace the general base, runtime protocol or permission boundary.

## 12. Current Status

Already solid:

- Prompt library exists.
- Agent role prompts exist.
- Context compactor agent exists and is tool-restricted.
- Memory manager exists and proposes writes rather than directly overwriting state.
- Active-work relation validation exists.
- Subagent lifecycle tools exist and already include fresh specialist / no prediction guidance.

Needs refactor before calling the architecture mature:

- Prompt precedence policy.
- Lifecycle state selector.
- Runtime/lifecycle de-duplication.
- Remaining model self-confidence cleanup.
- Memory taxonomy refinement.
- Tests rewritten away from always-mounted lifecycle assumptions.

## 12. Next Engineering Decision

The recommended next implementation slice is Phase 1 + Phase 2 together:

- Phase 1 gives us assembly authority and diagnostics.
- Phase 2 introduces EnvironmentPromptController: general environment as base, user-selected task environments as overlays, and lifecycle prompts selected by current runtime state.

Doing Phase 2 without Phase 1 would make the system harder to inspect. Doing Phase 1 alone would improve reporting but leave the main lifecycle flaw alive.
