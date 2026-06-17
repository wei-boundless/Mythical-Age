# Mature Agent Protocol Rebuild Plan

Date: 2026-06-18
Status: implementation plan, pending approval before runtime refactor
Scope: model response protocol, single-agent execution loop, runtime feedback, output boundary, public projection, focused regression tests

## 1. Purpose

This plan rebuilds the agent response contract around a mature item/block protocol: assistant-authored text is a message output, tool calls are executable action items, and control actions are structured control payloads. The immediate user-visible failure is "OCR scanned the image but the agent did not reply." The deeper architecture failure is that the runtime currently treats "control actions are available" as "every model response must be a JSON action", so a valid assistant answer after OCR can be rejected as a protocol violation.

The goal is not to make the parser more tolerant. The goal is to restore correct authority:

- `ModelActionRequest` is only an action/control request.
- Provider-native tool calls are executable tool requests.
- Assistant natural language is a first-class assistant message, finalized through `assistant_text_final`.
- Runtime feedback explains only real contract failures and never causes valid final text to be discarded.
- Public projection shows body/control/commit/terminal events from their canonical sources without leaking protocol repair internals.

## 2. Current Breakage

### 2.1 Concrete Failure

The failing image/OCR turn used:

- Session: `session-1a9830819d2945b8`
- Stream run: `strun:4ed46dc5e1a5491487b356f56b18297a`
- Tool: `attachment_extract_text`
- Attachment: `storage/chat_attachments/session-1a9830819d2945b8/0b775aa31565425eb2cac07499f45f80.png`
- OCR provider: local `RapidOCR`
- OCR route: `image_ocr`
- OCR language: `chi_sim+eng`

OCR succeeded. The event file `storage/runtime_state/events/turnrun_strun_4ed46dc5e1a5491487b356f56b18297a.jsonl` records an `ok` `turn_tool_observation_recorded` event with `diagnostics.provider=rapidocr` and `result_kind=image_ocr_text`.

The model then produced a complete Chinese Markdown solution. The runtime rejected that answer because `require_json_action=True` produced `json_action_required`. The raw preview in the same event file begins with normal assistant answer text such as "现在我看到了题目，这是一道无线通信中平衰落信道容量计算的经典题。以下是完整求解。"

### 2.2 Actual Broken Property

The broken property is contract conflation:

```text
allowed control actions
=> requires_json_action_protocol
=> model_response_protocol_from_response rejects non-JSON assistant text
=> single_agent_turn records model_protocol_violation
=> runtime_control_signal tells the model to output JSON
=> public projection hides protocol repair noise
=> user loses the real answer
```

The runtime currently has no clean "assistant final text, no tool/action, complete the turn" exit inside the tool-followup/final parse path when JSON action is required by the packet.

## 3. Source Basis

### 3.1 Mature Agent References

Codex local source separates assistant text from tool/action items:

- `D:\AI应用\openai-codex\codex-rs\protocol\src\models.rs`
  - `ContentItem::OutputText` is separate from input items.
  - `MessagePhase::{Commentary, FinalAnswer}` distinguishes mid-turn commentary from terminal answer text.
  - `ResponseItem::Message` is separate from `ResponseItem::FunctionCall`, `CustomToolCall`, and tool output items.
- `D:\AI应用\openai-codex\codex-rs\protocol\src\items.rs`
  - `TurnItem::AgentMessage` is separate from `TurnItem::McpToolCall`.
  - `AgentMessageContent::Text` is the assistant text payload.
- `D:\AI应用\openai-codex\codex-rs\codex-api\src\common.rs`
  - streaming has distinct `OutputItemDone(ResponseItem)`, `OutputTextDelta`, `ToolCallInputDelta`, and `Completed`.

Claude Code local source uses block presence, not JSON action requirement, as the loop signal:

- `D:\AI应用\claude-code-nb-main\query.ts`
  - It collects `assistantMessages`, `toolResults`, and `toolUseBlocks`.
  - A comment states that `stop_reason === 'tool_use'` is unreliable, so the runtime uses the presence of `tool_use` blocks as the loop signal.
  - When no `tool_use` block is present, the turn completes.
- `D:\AI应用\Claude-Code-Source-Study-main\docs\05-对话循环.md`
  - Describes the same user input -> assistant message -> tool_use if needed -> tool_result -> follow-up loop.

The mature pattern is not "force all answers into JSON". It is an item/block protocol:

```text
assistant message text -> present/commit/finalize
provider tool call -> authorize/execute/observe/follow up
structured control action -> validate/authorize/apply control
```

### 3.2 Local Project Sources

Current relevant files:

- `backend/runtime/model_gateway/model_response_protocol.py`
  - `model_response_protocol_from_response(...)` parses content and native tool calls.
  - Current behavior appends `json_action_required` when `require_json_action` is true and there is no JSON payload or native tool call.
- `backend/harness/runtime/compiler.py`
  - `_single_agent_turn_effective_control_capabilities(...)` sets `requires_json_action_protocol=True` when control actions are allowed.
  - `_single_agent_turn_output_contract(...)` exposes `json_action.required`.
  - `_model_decision_contract_payload(...)` currently reports `required_transport=json_action` when control actions exist.
- `backend/harness/loop/single_agent_turn.py`
  - `_single_agent_action_request_from_response(...)` currently turns `json_action_required` into `SingleAgentActionParse.error`.
  - The main loop recovers from that error instead of committing assistant text.
  - The final fallback near the end can commit raw assistant text, but it is reached only after the action parser path stops rejecting it.
- `backend/harness/loop/model_action_protocol.py`
  - `ModelActionRequest` is the strict action/control validator and should remain strict.
- `backend/harness/loop/presentation.py`
  - `assistant_body_final_event(...)` already routes final text to `assistant_text_final`.
- `backend/runtime/model_gateway/assistant_stream_frame.py`
  - `assistant_text_delta`, `assistant_text_final`, and `assistant_stream_repair` already exist as canonical body events.
- `backend/runtime/output_boundary/boundary.py`
  - Sanitizes internal protocol leakage and marks protocol repair text as non-public.
- `backend/runtime/output_stream/public_contract.py`
  - Defines public event families: `assistant_body`, `tool_control`, `runtime_commit`, `turn_anchor_terminal`, `status_trace`.
- `backend/harness/runtime/projection/projector.py`
  - Maps `assistant_text_final` to `body_finalize`.
  - Maps tool lifecycle events to control frames.
  - Keeps protocol/status internals as trace/hidden.
- `backend/api/chat.py`
  - Bridges runtime events into public stream events and attaches public projection frames.
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
  - Projects tool observations into model-visible context; this is evidence projection, not user-facing assistant body.

## 4. Design Standard

### 4.1 Contract Split

The refactor must split three contracts:

| Contract | Owner | Transport | Meaning | User-visible path |
| --- | --- | --- | --- | --- |
| Assistant message | Model turn output parser + output boundary | provider assistant text/message | The agent is speaking to the user | `assistant_text_delta` / `assistant_text_final` |
| Ordinary tool call | Provider tool call or JSON `tool_call` action | native tool call preferred, JSON allowed where explicitly enabled | Execute a runtime-visible tool | tool lifecycle events, then model follow-up |
| Control action | `ModelActionRequest` JSON | strict JSON object only | Change orchestration/task/control state | admission/control event, then projected public result if needed |

`respond` should be treated as a control/action only when the model explicitly emits a JSON `ModelActionRequest(action_type="respond")` or a native `respond` tool on a stage that intentionally exposes it. Plain assistant text must not be silently converted into `respond`.

### 4.2 Loop Continuation Rule

The execution loop continues only when the parsed output contains executable actions:

```text
if provider-native tool calls or JSON tool_call:
    authorize -> execute -> observe -> ask model again
elif valid JSON control action:
    authorize/apply -> terminal/control outcome
elif assistant text exists:
    commit assistant text -> emit assistant_text_final -> turn_completed
else:
    empty-output recovery or failure
```

This mirrors Codex and Claude Code: tool/action items drive continuation; assistant message text drives final/user output.

### 4.3 Strictness Preserved

The target design is strict, but strict at the correct boundary:

- Malformed JSON action remains invalid.
- JSON action with unsupported `action_type` remains invalid.
- JSON action mixed with native tool calls remains invalid.
- Control actions cannot be provider-native tool calls.
- Native tool calls are rejected if that service surface is not mounted.
- Empty text is not a final answer.
- Raw tool output and protocol repair text do not become assistant body.

The parser must not "helpfully" infer a task action from natural language.

## 5. Tradeoff Analysis

### Option A: Normalize Natural Text Into `respond`

Rejected.

This hides the design failure by making a parser perform semantic action construction. It makes `ModelActionRequest` a second assistant message channel and blurs action vs output. It also risks converting text into control paths.

### Option B: Keep JSON Requirement But Improve Prompts

Rejected as primary fix.

Prompt improvements may reduce failures, but the runtime would still reject valid assistant text whenever a model naturally answers after a tool observation. Mature runtimes do not rely on prompt obedience to preserve the core output channel.

### Option C: Split Assistant Output From Action Requests

Accepted.

This matches Codex and Claude Code source behavior, uses existing local `assistant_text_final` infrastructure, keeps `ModelActionRequest` strict, and removes the hidden coupling between "allowed control actions" and "all outputs must be JSON".

## 6. Target Authority Chain

```text
RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
-> OutputBoundary
-> PublicProjection
```

| Layer | Owner | Allowed | Forbidden |
| --- | --- | --- | --- |
| RequestFacts | API/session/attachment intake | Record user text, attachments, OCR availability | Choose action or response mode |
| BoundaryPolicy | runtime compiler + permission policy | Decide which action classes and tools are mounted | Convert final answer into JSON requirement |
| ContextCandidates | dynamic context projectors | Provide OCR/tool observations as evidence | Decide final user answer |
| ModelTurnDecision | model | Choose tool/action/control/text response | Grant permissions |
| ActionPermit | admission/action permit | Allow or deny tool/control actions | Rewrite the user's goal |
| RuntimeStartPacket | compiler/assembly | Assemble exact model-visible contract | Recompute intent or force text into actions |
| ExecutionLoop | single_agent_turn/task_executor | Execute actions, observe, finalize text | Reject valid text only because control actions are available |
| OutputBoundary | presentation/output boundary | Sanitize and canonicalize final body | Synthesize semantic answer text |
| PublicProjection | projection/projector + api/chat | Map canonical events to public UI channels | Publish protocol repair internals as body |

## 7. Target Data Model

### 7.1 Response Protocol Result

Replace the current `require_json_action` boolean behavior with an explicit contract object or enum. Proposed shape:

```python
@dataclass(frozen=True, slots=True)
class ModelResponseParseContract:
    assistant_text_allowed: bool
    native_tool_calls_allowed: bool
    json_action_allowed: bool
    json_action_required_for_control: bool
    strict_json_if_action_like: bool = True
```

`model_response_protocol_from_response(...)` should output transport facts only:

```python
@dataclass(frozen=True, slots=True)
class ModelResponseProtocolResult:
    content: str
    native_tool_calls: tuple[dict[str, Any], ...]
    json_payload: dict[str, Any]
    parse_diagnostics: dict[str, Any]
    response_diagnostics: dict[str, Any]
    transport_errors: tuple[str, ...]
```

It should not emit `json_action_required` merely because text is not JSON. It may still emit:

- `json_action_must_not_use_markdown_fence` when a JSON action is actually required for a control/action repair stage.
- `json_action_must_not_use_trailing_text` when a parsed action object has extra text.
- `native_tool_call_transport_not_available` when native tool calls are not mounted.

### 7.2 Single Agent Parse Result

Extend `SingleAgentActionParse` into an output parse result:

```python
@dataclass(frozen=True, slots=True)
class SingleAgentOutputParse:
    action_request: ModelActionRequest | None
    tool_actions: tuple[ModelActionRequest, ...]
    control_action: ModelActionRequest | None
    assistant_final_text: str = ""
    native_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    packet_public_progress_note: str = ""
```

Important rule: `assistant_final_text` is not a `ModelActionRequest`. It is a body output candidate.

### 7.3 Decision Contract Payload

Change the compiler-facing contract from one global `required_transport` into separate lanes:

```json
{
  "assistant_response_transport": "assistant_message",
  "ordinary_tool_transport": "provider_native_tool_call_or_json_tool_call",
  "control_action_transport": "json_action",
  "json_action_required_for": "control_or_task_action_only",
  "assistant_text_allowed_when_no_action": true
}
```

The prompt should tell the model:

- Use ordinary assistant text when ready to answer the user.
- Use provider-native tool calls for mounted tools.
- Use JSON `ModelActionRequest` only for control/task actions or when the current packet explicitly requires a control action.
- Do not put user-facing final answer inside `payload.content`, `action.content`, or other legacy envelopes.

## 8. Fixed Execution Flow

### 8.1 Initial Turn

Inputs:

- User message, attachments, session context.
- Runtime packet with allowed actions and visible tools.
- Model response items.

Outputs:

- Tool actions, control action, or assistant body.

Rules:

- If the model emits tool calls, execute them.
- If the model emits a control JSON action, validate and admit it.
- If the model emits assistant text and no action, commit it.
- If the model emits no meaningful output, enter empty-output recovery.

### 8.2 Tool Observation Follow-Up

Inputs:

- Prior tool observations, including OCR text.
- Current allowed action types and mounted tools.
- Model follow-up response.

Outputs:

- More tool actions, a control action, or final assistant answer.

Rules:

- Plain assistant text after OCR is a valid final answer.
- The loop must not demand JSON merely because `request_task_run`, `ask_user`, or `block` were allowed.
- Runtime feedback is generated only for actual protocol violations, not for normal assistant text.

### 8.3 Control Action Phase

Inputs:

- A JSON action payload or an explicitly control-required repair stage.

Outputs:

- Accepted `ModelActionRequest`, admission denial, or model-visible contract feedback.

Rules:

- Control actions remain strict JSON.
- Native `ask_user`, `block`, `request_task_run`, or `active_work_control` remain invalid.
- Malformed action payloads produce internal/model-visible feedback, not public body text.

### 8.4 Finalization

Inputs:

- Assistant final text or validated `respond`/`ask_user`/`block` content.

Outputs:

- `assistant_text_final`
- session output commit event
- hidden `turn_completed`

Rules:

- The canonical final answer body comes from assistant text or model-authored final fields.
- `turn_completed` is a terminal anchor, not the final answer body.
- Commit failures surface as commit/status events, not invented answer text.

## 9. Module Plan

### 9.1 `backend/runtime/model_gateway/model_response_protocol.py`

Current role: transport parser plus premature JSON requirement gate.

Target role: provider response normalizer only.

Actions:

- Remove blanket `json_action_required` from this transport-level function.
- Keep JSON parsing diagnostics.
- Keep strict markdown/trailing checks only under an explicit action-required contract.
- Add tests proving plain text with `assistant_text_allowed=True` is not a protocol error.

Done condition:

- Plain text response with no tool calls and no JSON action returns content and no `json_action_required`.
- Action-like malformed JSON still reports parse/validation failures in the action parser layer.

### 9.2 `backend/harness/runtime/compiler.py`

Current role: runtime packet assembly plus contract text.

Target role: separate response lanes in the model decision contract.

Actions:

- Replace global `required_transport=json_action` with lane-specific transport fields.
- Keep `control_actions.transport=json_action`.
- Add `assistant_response_transport=assistant_message`.
- Add `json_action_required_for=control_or_task_action_only`.
- Stop setting `requires_json_action_protocol=True` merely because control actions are allowed.
- Keep a separate flag only for phases where assistant text is not a valid output.

Done condition:

- Compiled packet exposes that final assistant text is allowed when no action is needed.
- Control action instructions remain strict.

### 9.3 `backend/harness/loop/single_agent_turn.py`

Current role: execution loop, action parse, recovery, final commit.

Target role: item/block execution loop with explicit assistant text finalization.

Actions:

- Rename or replace `_single_agent_action_request_from_response(...)` with an output parser that can return `assistant_final_text`.
- If parsed output has no actions and has assistant text, break the tool loop and commit through the existing final message path.
- Do not convert assistant text into `ModelActionRequest(action_type="respond")`.
- Remove the previous nested envelope normalization patch for `payload.final_answer` / `action.content` unless it is still needed for a strictly defined current public contract. The preferred path is strict top-level JSON action validation.
- Update runtime recovery:
  - malformed action object -> contract feedback
  - mixed JSON + native tool call -> contract feedback
  - plain assistant text -> final answer
- Ensure streaming delta is allowed whenever assistant text can be a valid output.

Done condition:

- OCR/tool follow-up Markdown answer commits as `assistant_text_final`.
- Tool calls still execute.
- Invalid control JSON still triggers model-visible feedback.

### 9.4 `backend/harness/loop/model_action_protocol.py`

Current role: strict action validator.

Target role: unchanged strict action authority.

Actions:

- Do not weaken validation.
- Do not accept nested legacy action envelopes as primary contract.
- Keep `respond.final_answer`, `ask_user.user_question`, `block.blocking_reason`, `tool_call.tool_call`, and task fields strict.

Done condition:

- Tests prove malformed/nested legacy action shapes are rejected unless deliberately supported by a named migration rule. Default target is no legacy envelope support.

### 9.5 `backend/harness/loop/presentation.py`

Current role: final assistant event helper.

Target role: canonical final body event helper.

Actions:

- Reuse `assistant_body_final_event(...)` for assistant text finalization where suitable.
- Ensure final answer body uses `answer_channel=conversation` and source like `harness.single_agent_turn.assistant_message`.

Done condition:

- Final assistant body event carries stable content, source, channel, and terminal reason.

### 9.6 `backend/runtime/output_boundary/boundary.py`

Current role: sanitizes internal protocol and output leakage.

Target role: final/public content guard, not a semantic action parser.

Actions:

- Keep protocol repair text from becoming body.
- Add/adjust tests that `json_action_required`, `single_agent_turn_model_protocol_error`, and runtime control signal text are never projected as assistant body.
- Ensure a real assistant answer containing Markdown tables/math is not falsely classified as internal protocol.

Done condition:

- Math/Markdown answer passes canonical output boundary.
- Protocol repair text fails closed to trace/hidden or recovery status only.

### 9.7 `backend/harness/runtime/projection/projector.py`

Current role: maps runtime/public events to projection frames.

Target role: body/control/commit/terminal separation.

Actions:

- Keep `assistant_text_final` -> `body_finalize`, visible final.
- Keep tool lifecycle -> control channel.
- Keep `turn_completed` hidden trace.
- Keep `agent_contract_feedback_required` and runtime protocol repair hidden trace unless a future explicit user-facing status contract is defined.
- Add regression that an OCR-follow-up assistant final produces exactly one visible body final frame and no protocol repair body.

Done condition:

- Projection lifecycle cannot display protocol feedback as body.
- Body frames only originate from model-authored assistant text or sanctioned model public feedback.

### 9.8 `backend/api/chat.py`

Current role: runtime event to SSE/public event bridge.

Target role: pass canonical events and attach projection frames.

Actions:

- Ensure `_project_public_stream_event(...)` preserves `assistant_text_final` content and anchors after tool follow-up.
- Ensure `turn_runtime_control_signal_observed` remains non-body trace/status if surfaced.
- Ensure allowlist includes only required body fields for assistant final text.

Done condition:

- SSE contains `assistant_text_final` for final answer and hidden `turn_completed`.
- No duplicate body final from `done.content`.

### 9.9 `backend/harness/runtime/dynamic_context/tool_result_projector.py`

Current role: model-visible evidence projection from tool results.

Target role: evidence projection only.

Actions:

- Keep OCR/text tool result projection model-visible as evidence.
- Do not route tool result projection directly into public assistant body.
- Validate OCR result retains provider/language diagnostics for model context and trace.

Done condition:

- OCR tool output is available to the follow-up model turn but not mistaken for user-visible final answer.

### 9.10 Tests

Current role: several tests now protect old or patchy behavior.

Target role: behavior tests for mature protocol.

Actions:

- Remove tests that require nested action envelope normalization if they only preserve the rejected patch direction.
- Add tests for assistant text finalization after tool observation.
- Add tests for strict control/action validation.
- Add tests for projection chain from final text to body frame.

Done condition:

- Tests protect behavior and chain authority, not obsolete internal shapes.

## 10. Phase Plan

### Phase 0: Baseline and Dirty Worktree Audit

Goal: separate existing user changes from protocol refactor work.

Inputs:

- `git status --short`
- Current diffs in `backend/api/chat.py`, `backend/harness/loop/single_agent_turn.py`, `backend/harness/runtime/compiler.py`, `backend/harness/runtime/dynamic_context/tool_result_projector.py`, and tests.

Outputs:

- Confirmed list of changes to keep, rewrite, or remove.

Prohibited:

- Do not revert `.gitignore` or `AGENTS.md`.
- Do not keep nested action envelope normalization as an unowned compatibility shim.

Completion criteria:

- Every dirty change touched by the refactor has an explicit keep/rewrite/delete decision.

### Phase 1: Contract Schema Split

Goal: establish lane-specific response/action contract.

Affected files:

- `backend/runtime/model_gateway/model_response_protocol.py`
- `backend/harness/runtime/compiler.py`
- `backend/tests/model_response_protocol_regression.py`
- `backend/tests/harness_model_action_protocol_regression.py`

Main changes:

- Replace global JSON requirement with assistant/action/control lanes.
- Update compiled model decision contract.
- Preserve strict action validation.

Inputs:

- Provider response content and native tool calls.
- Runtime packet allowed actions.

Outputs:

- Transport facts.
- Action candidate only when action-like JSON is present.
- Assistant text candidate when plain text is present.

Rollback condition:

- If this phase makes invalid actions silently accepted, stop and restore strict action validation before continuing.

### Phase 2: Single-Agent Loop Output Parser

Goal: make loop continuation item/block based.

Affected files:

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/presentation.py` if helper changes are needed
- `backend/tests/harness_model_action_protocol_regression.py`

Main changes:

- Parser returns `assistant_final_text`.
- Tool loop exits to final commit when assistant text is present and no action exists.
- Invalid actual actions still enter protocol feedback.

Inputs:

- `ModelResponseProtocolResult`
- Allowed action types
- Tool observation context

Outputs:

- Tool action batch, control action, assistant final text, or protocol issue.

Prohibited:

- Do not wrap natural-language Markdown into `ModelActionRequest`.
- Do not retry protocol recovery for a valid assistant answer.

Completion criteria:

- Unit test reproducing OCR follow-up plain Markdown answer passes.

### Phase 3: Runtime Feedback Reclassification

Goal: make system feedback accurate and non-invasive.

Affected files:

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/runtime/public_progress.py`
- `backend/runtime/output_boundary/boundary.py`
- `backend/tests/public_projection_contract_test.py`

Main changes:

- Generate runtime control signal only for actual protocol/action failures.
- Keep contract feedback model-visible but hidden from public body.
- Update repair instructions to reflect lane-specific contracts.

Inputs:

- Parser issue kind: malformed action, mixed action sources, unavailable tool transport, empty output.

Outputs:

- `turn_runtime_control_signal_observed` or `agent_contract_feedback_required` only for real failures.

Completion criteria:

- Valid assistant text produces no protocol repair event.
- Malformed action still produces model-visible feedback.

### Phase 4: Output Boundary and Commit Flow

Goal: ensure final assistant text becomes the canonical public body.

Affected files:

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/presentation.py`
- `backend/runtime/model_gateway/assistant_stream_frame.py` only if metadata needs extension
- `backend/runtime/output_boundary/boundary.py`

Main changes:

- Commit assistant text via `_commit_final_message(...)`.
- Emit `assistant_text_final` before or alongside commit events according to existing ordering.
- Keep `turn_completed` as hidden terminal anchor.

Inputs:

- Assistant final text, answer source, channel, tool receipt flag.

Outputs:

- `assistant_text_final`
- `session_output_commit_checked`
- `session_output_commit_ack` or failed/skipped commit event
- `turn_completed`

Completion criteria:

- Public stream has one final body event and one terminal anchor.
- Session history receives the full answer.

### Phase 5: Public Projection Chain

Goal: prove projection honors the contract split.

Affected files:

- `backend/harness/runtime/projection/projector.py`
- `backend/harness/runtime/projection/authority.py`
- `backend/api/chat.py`
- `backend/runtime/shared/stream_replay.py`
- `backend/tests/public_projection_contract_test.py`

Main changes:

- Add regression for assistant final after OCR/tool observation.
- Add regression that runtime protocol feedback is trace/hidden.
- Ensure replay sanitization does not hide real assistant final body.

Inputs:

- Runtime events from single-agent loop.

Outputs:

- Public SSE frames with correct family/channel/visibility.

Completion criteria:

- `assistant_text_final` maps to `body_finalize`, `visible_final`, `body`.
- Protocol feedback maps to `trace`, hidden/trace-only.

### Phase 6: End-to-End Verification

Goal: verify the real runtime path.

Commands:

```powershell
pytest backend/tests/model_response_protocol_regression.py backend/tests/harness_model_action_protocol_regression.py backend/tests/public_projection_contract_test.py
pytest backend/tests/chat_attachment_api_regression.py backend/tests/image_ocr_runtime_config_regression.py backend/tests/tool_result_projection_regression.py
```

Runtime verification:

- Start backend on `http://127.0.0.1:8003`.
- Start frontend on `http://127.0.0.1:3000`.
- Upload or reuse an image attachment.
- Confirm OCR tool observation succeeds.
- Confirm follow-up assistant Markdown answer appears in the UI.
- Confirm event log contains `assistant_text_final`.
- Confirm no `json_action_required` recovery is emitted for the plain final answer.

Completion criteria:

- The previously failing OCR-answer scenario completes with a full visible answer.
- No random port changes.
- No tests skipped, weakened, or mocked around the core behavior.

## 11. File-Level Checklist

| File | Current role | Action | Done condition |
| --- | --- | --- | --- |
| `backend/runtime/model_gateway/model_response_protocol.py` | Transport parser plus JSON gate | Demote to transport facts; remove blanket `json_action_required` | Plain text can be valid assistant output |
| `backend/harness/runtime/compiler.py` | Packet/contract assembler | Split assistant/action/control lanes | Prompt contract no longer says global JSON transport |
| `backend/harness/loop/single_agent_turn.py` | Main execution loop and parser | Add assistant text parse/finalization path | OCR follow-up text commits |
| `backend/harness/loop/model_action_protocol.py` | Strict action validator | Keep strict; do not add natural text conversion | Invalid actions remain invalid |
| `backend/harness/loop/presentation.py` | Final body event helper | Reuse for assistant final body | `assistant_text_final` metadata stable |
| `backend/runtime/output_boundary/boundary.py` | Public content guard | Keep protocol internals out of body | Markdown answer passes, repair text hidden |
| `backend/runtime/model_gateway/assistant_stream_frame.py` | Assistant frame events | Leave mostly unchanged unless metadata needed | Final body frames remain canonical |
| `backend/runtime/output_stream/public_contract.py` | Event family/channel contract | Leave existing body/control/commit/terminal split | No family regression |
| `backend/harness/runtime/projection/projector.py` | Public projection | Add/adjust tests for new chain | Body/control/trace separation enforced |
| `backend/api/chat.py` | Runtime-to-SSE bridge | Preserve assistant final text and anchor | SSE has final body and hidden terminal |
| `backend/harness/runtime/dynamic_context/tool_result_projector.py` | Model-visible tool evidence | Keep as evidence only | OCR evidence reaches model, not public body |
| `backend/tests/model_response_protocol_regression.py` | Protocol tests | Update for lane split | Plain text no longer fails transport |
| `backend/tests/harness_model_action_protocol_regression.py` | Loop/action parser tests | Replace nested-envelope patch tests with mature protocol tests | Strict action plus final text behavior covered |
| `backend/tests/public_projection_contract_test.py` | Projection contract tests | Add full final body/protocol feedback tests | Public projection is correct |

## 12. Migration and Cutover Rules

This refactor should be a direct cutover, not a long compatibility window.

Allowed temporary overlap:

- A short-lived internal parse result may carry both old `action_request` and new `assistant_final_text` fields while call sites are updated.

Not allowed:

- Keeping nested `payload.content` / `action.content` normalization as a permanent fallback.
- Accepting free-form text as `request_task_run`, `active_work_control`, `tool_call`, `ask_user`, or `block`.
- Publishing protocol repair status as assistant body.
- Using prompt-only fixes while leaving the parser to reject valid text.

Cutover criteria:

- All single-agent call sites use the lane-split parser.
- Tests no longer assert `json_action_required` for plain final text.
- Search confirms old blanket requirement paths are unreachable:

```powershell
rg -n "json_action_required|required_transport|requires_json_action_protocol|_normalize_single_agent_json_payload" backend
```

Rollback criteria:

- If strict action failures start being accepted as assistant text, revert the parser slice and reapply stricter action-like detection before continuing.
- If public projection duplicates final body, rollback the projection/chat bridge slice and fix event ordering before restarting runtime verification.

## 13. Validation Matrix

| Scenario | Expected behavior |
| --- | --- |
| OCR succeeds, model writes Markdown answer | Commit full answer as `assistant_text_final`; no protocol repair |
| Model emits provider-native `attachment_extract_text` | Tool lifecycle visible in control channel; observation feeds follow-up |
| Model emits malformed JSON action | Runtime feedback generated; no public body from malformed payload |
| Model emits JSON `request_task_run` | Validate through `ModelActionRequest`, admission, task scheduling |
| Model emits native control action | Reject with control-action-requires-JSON feedback |
| Model emits JSON action plus native tool call | Reject as multiple action sources |
| Model emits empty content and no tool | Empty-output recovery/closeout |
| Commit gate fails | Commit failure status event, no invented answer |
| Runtime protocol repair event reaches projection | Hidden trace only |
| Final turn completed event reaches projection | Hidden terminal anchor, not body |

## 14. Prohibited Shortcuts

- Do not normalize ordinary assistant text into `respond`.
- Do not solve this by adding more prompt warnings while leaving the global JSON gate intact.
- Do not weaken `ModelActionRequest` validation to accept legacy nested envelopes.
- Do not skip, delete, or weaken failing tests to manufacture green output.
- Do not keep old paths "just in case" without a named owner and removal condition.
- Do not expose `json_action_required`, runtime control signal text, or internal repair instructions in the visible assistant body.
- Do not change the fixed local ports during verification.

## 15. Expected Outcome

After implementation:

- OCR/image workflows can scan and then answer naturally.
- Tool calls and control actions remain strict and auditable.
- Assistant text has a first-class terminal path matching Codex/Claude Code style runtimes.
- System feedback becomes precise: it corrects actual protocol failures and no longer blocks valid final answers.
- Public projection becomes easier to reason about:
  - body = model-authored assistant output
  - control = tool lifecycle
  - commit = session persistence result
  - terminal = hidden turn anchor
  - status/trace = non-body runtime diagnostics

## 16. Per-Phase Deliverables

| Phase | Code deliverable | Observability deliverable | Validation deliverable |
| --- | --- | --- | --- |
| 0 | Dirty worktree decision list | Audit note in implementation summary | No user changes overwritten |
| 1 | Lane-split protocol/contract | Parser diagnostics distinguish text/action/tool | Protocol tests |
| 2 | Assistant final path in loop | Event log records final text instead of repair | Single-agent parser tests |
| 3 | Feedback reclassification | Contract feedback only on real failures | Feedback/projection tests |
| 4 | Canonical final commit | `assistant_text_final` + commit events | Output boundary tests |
| 5 | Public projection chain | Correct body/control/trace frames | Public projection tests |
| 6 | Runtime verification | Real run event log and UI output | CLI backend/frontend verification |

