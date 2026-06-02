# Codex-Style Chat Runtime UI Contract Design - 2026-06-02

## 1. Purpose

This document defines the target contract for a Codex-style chat runtime UI.

The goal is not to make the current runtime panel prettier. The goal is to stop exposing runtime events as the conversation surface. A mature coding agent experience is conversation-first:

- The assistant message is the primary user-facing output.
- Tool use and task progress appear as quiet inline execution trace only when they carry useful evidence.
- Completion is expressed as a natural final assistant summary.
- Ordinary runtime receipts, internal event names, raw status codes, and duplicate "done" labels do not appear in chat.
- Debug and monitor views remain available for raw trace, but they are not the chat UI.

This document is the contract to guide the next implementation pass and to prevent another CSS-heavy patch that leaves the authority structure unchanged.

## 2. Source Basis

The design below is grounded in the current project chain:

- `backend/harness/runtime/session_timeline.py`
  - Builds `runtime_attachments` for formal chat task runs.
  - Attaches `progress_presentation`, `progress_entries`, final answer, artifacts, and terminal state.
- `backend/harness/runtime/progress_presenter.py`
  - Already starts to convert runtime events into `mission`, `work_units`, and `technical_trace`.
  - This is the correct backend direction, but its output still flows into a frontend event-panel component.
- `backend/harness/runtime/public_progress.py`
  - Sanitizes public runtime text.
  - This is useful as a normalizer, but it must not become the main semantic owner of chat presentation.
- `frontend/src/lib/api.ts`
  - Defines `RuntimeProgressPresentation` and `SessionRuntimeAttachment`.
- `frontend/src/lib/store/utils.ts`
  - Anchors runtime attachments onto assistant messages.
- `frontend/src/lib/runtimeVisibilityProjection.ts`
  - Still projects streaming events such as `done` and `agent_turn_terminal` into visible progress entries.
  - This is one source of duplicate completion text.
- `frontend/src/components/chat/ChatMessage.tsx`
  - Renders `RuntimeRunSummary` before assistant content when runtime details exist.
  - This gives runtime UI visual authority over the assistant message.
- `frontend/src/components/chat/RuntimeRunSummary.tsx`
  - Currently renders mission strip plus expandable "execution details" and "technical details".
  - This is still closer to a runtime event receipt than to a Codex-style conversation turn.
- `backend/maintenance/agent_progress_ui_intelligence_optimization_plan_20260602.md`
  - Useful prior plan for progress semantics.
  - This document narrows and corrects the contract around chat ownership and backend/frontend authority.

## 3. Current Failure Mode

The current UI is not Codex-style because it treats runtime progress as a visible object beside or above the assistant answer.

Observed failures:

- The assistant turn can show "我已经处理完", "已完成", and "回答已生成并写回会话" around the same moment.
- Generic terminal receipts become visible chat material.
- "查看执行细节" and "查看技术细节" appear in ordinary completion states, even when the user only needs the answer.
- Raw runtime categories leak into the chat experience.
- Frontend filters try to repair backend semantics after the fact.
- Runtime feedback does not feel like a thinking assistant reporting work; it feels like a system log panel inserted into conversation.

The broken system property is presentation authority. The backend has partial semantic projection, the frontend still performs fallback interpretation, and raw runtime events can still become user-facing chat content.

## 4. Target Principle

The chat timeline must contain public conversation objects, not runtime events.

The target chain is:

```text
runtime events
  -> backend semantic projection
  -> public chat timeline items
  -> frontend rendering
```

The wrong chain is:

```text
runtime events
  -> frontend event filtering
  -> visible progress panel
  -> assistant content placed after the panel
```

The backend owns meaning. The frontend owns layout.

## 5. Codex-Style Frontend Design

### 5.1 Chat Layout

The chat surface should use this order:

```text
User message

Assistant turn
  - assistant text stream or final answer
  - inline tool activity rows, only when meaningful
  - artifacts and verification hints
```

Runtime progress must not appear as a separate large panel before the answer. It should appear as part of the assistant turn, similar to a quiet execution transcript.

### 5.2 Message Types

The frontend should render a small fixed set of public chat item types:

```ts
type PublicChatTimelineItem =
  | { kind: "assistant_text"; text: string; stream_state?: "streaming" | "done" }
  | { kind: "tool_activity"; title: string; detail?: string; state: "running" | "done" | "error" }
  | { kind: "artifact"; title: string; href?: string; path?: string; state: "ready" | "missing" }
  | { kind: "verification"; text: string; state: "passed" | "failed" | "partial" }
  | { kind: "blocked"; text: string; recovery_hint?: string }
  | { kind: "final_summary"; text: string; artifacts?: Array<Record<string, unknown>> };
```

This is intentionally smaller than the runtime event vocabulary. The user does not need to see every event. They need to see the agent's public work.

### 5.3 Visual Rules

- No nested cards inside chat.
- No large bordered runtime box for ordinary completion.
- No "查看执行细节" in normal successful turns.
- No "查看技术细节" in the main chat. Raw trace belongs in monitor/debug views, not in the transcript.
- User messages should be visually distinct and readable, but not bubble-heavy.
- Assistant output should read as a continuous work log and answer, not as disconnected status widgets.
- Tool activity rows should be compact: icon, action title, optional evidence/result, state.
- Completed tool activity should collapse in visual weight automatically.
- The final answer should be the strongest element at completion.

Recommended assistant turn shape:

```text
Assistant
  正在检查项目结构...

  ✓ 读取 package 配置
    确认前端测试入口。

  ✓ 修改 ChatMessage 渲染顺序
    运行反馈不再压过正文。

  我已完成这轮修改：...
```

This is conversation-native. It does not look like a monitoring card embedded into chat.

## 6. Backend Contract

The backend should expose a public chat projection separate from raw runtime trace.

Recommended field:

```json
{
  "public_timeline": [
    {
      "kind": "tool_activity",
      "title": "读取项目结构",
      "detail": "确认聊天消息和运行摘要的渲染入口。",
      "state": "done",
      "trace_refs": ["rtevt:..."]
    },
    {
      "kind": "assistant_text",
      "text": "我正在收口运行反馈的显示边界。"
    },
    {
      "kind": "final_summary",
      "text": "我已完成：运行收口不再显示普通终端回执，调试 trace 保留在监控侧。"
    }
  ],
  "debug_trace_ref": "taskrun:turn:..."
}
```

The existing `progress_presentation` can be the internal source for this, but chat should not consume it as a panel contract forever. `progress_presentation` is runtime presentation. `public_timeline` is chat presentation.

`final_summary` must not duplicate the assistant message. If the backend already wrote the final answer into the assistant message content, the public timeline should either omit `final_summary` or mark it as the canonical assistant text for that turn. The frontend must not render the same closeout twice.

`assistant_text` also has a single authority rule. During streaming, it may represent the live assistant text before the message is persisted. After the assistant message exists in session history, that history message is the canonical text source. The frontend must not render persisted assistant text from both `history.messages` and `public_timeline`.

### 6.1 Backend Responsibilities

Backend must:

- Decide which runtime facts are public.
- Merge model judgment, tool call, observation, and verification into user-readable activity.
- Suppress ordinary lifecycle receipts.
- Produce one final public closeout for successful completion.
- Deduplicate final closeout against assistant message content.
- Produce one clear blocked item for failures or waiting states.
- Keep raw event ids and payload previews behind debug references.
- Attach runtime output to the correct assistant turn.
- Preserve task isolation; a stopped task does not silently become the next task's continuation.

Backend must not:

- Send raw internal event names as chat-facing titles.
- Send `done`, `agent_turn_terminal`, or terminal receipt text as normal assistant content.
- Depend on frontend regex filters as the main safety layer.
- Treat debug trace as public progress.
- Make the frontend infer whether a terminal event is meaningful.

### 6.2 Suppressed Public Strings And Events

These must not appear in the main chat DOM:

- `回答已生成并写回会话`
- `会话输出完成`
- `agent_turn_terminal`
- `done`
- `runtime_invocation_packet_compiled`
- `task_execution_packet_compiled`
- `task_model_action_wait_heartbeat`
- `task_run_executor_scheduled`
- `task_run_executor_claimed`
- `step_summary_recorded`
- bare booleans: `true`, `false`
- raw statuses: `working`, `ready_to_finish`, `completed`, `running`
- provider internals such as `target_id`
- raw provider configuration errors unless translated into a user-facing blocked reason

Raw values may remain in monitor/debug trace.

### 6.3 Stream And History Parity

Live SSE events and refreshed session history must converge to the same visible chat state.

Required behavior:

- While a task is running, live events may update transient `tool_activity` rows.
- When session history is refreshed, the persisted `public_timeline` must replace the transient projection without changing the public meaning.
- `done` closes the live stream and marks pending public items as finished; it must not create a new visible receipt.
- `agent_turn_terminal` updates lifecycle/debug state only; it must not create visible chat content.
- If the same trace item arrives through both SSE and `runtime_attachments`, the frontend must deduplicate it by stable `item_id` or `trace_refs`.

This closes the current gap where streaming projection and session attachment projection can both render completion state.

### 6.4 Anchor Contract

Runtime attachments must be anchored by stable turn identity, not by frontend nearest-index guessing.

Current `frontend/src/lib/store/utils.ts` maps `anchor_turn_id` to the nearest assistant index. That is fragile when:

- the assistant message is empty or delayed;
- multiple assistant messages merge;
- a task is stopped and the user sends a new turn;
- history is refreshed while a runtime attachment is still being updated.

Target contract:

```ts
type SessionRuntimeAttachment = {
  attachment_id: string;
  run_id: string;
  anchor_turn_id: string;
  anchor_message_id?: string;
  anchor_role: "assistant";
  public_timeline?: PublicChatTimelineItem[];
  debug_trace_ref?: string;
};
```

Backend must emit the stable assistant message anchor when it exists. Frontend may use `anchor_turn_id` only as a temporary streaming key before the assistant message is persisted. After history refresh, attachment placement must use `anchor_message_id` or an equivalent stable turn id.

## 7. Authority Boundaries

| Layer | Owns | Must Not Own |
| --- | --- | --- |
| Runtime event log | Durable facts and raw execution trace | User-facing wording |
| `progress_presenter.py` | Runtime semantic grouping | Final chat layout |
| New public chat projector | Public chat item selection and final closeout | CSS/layout |
| `session_timeline.py` | Anchoring public timeline to the correct assistant turn | Rewriting user intent |
| Frontend store | Message normalization and attachment placement | Business meaning inference |
| Chat components | Rendering public timeline items | Runtime event filtering as primary logic |
| Monitor/debug views | Raw trace inspection | Main chat experience |

The key rule: frontend rendering is not allowed to decide that an internal event is important. It can only render public items already approved by the backend.

## 8. Interruption And Blocked-State Contract

When a task is interrupted, stopped, blocked, or resumed, the model must receive the relevant state as model-visible context if the next turn asks about that task. The chat UI should show one natural public message.

Correct behavior:

```text
用户：继续

Assistant:
  上一个任务已经停止，我不会把它当成同一个运行继续执行。
  如果你要重新开始，我会按新的任务重新装配上下文。
```

Incorrect behavior:

```text
系统状态：当前处理已停止
工具已直接调用
查看执行细节
agent_turn_terminal
```

Interruption is a task boundary fact, not a frontend status badge and not a hidden gate that bypasses model judgment.

## 9. Migration Plan

### Phase 1 - Backend Public Timeline

Files:

- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/session_timeline.py`
- New file: `backend/harness/runtime/public_chat_timeline.py`
- `backend/tests/runtime_progress_presenter_regression.py`

Tasks:

- Add a backend projection that converts runtime presentation into `public_timeline`.
- Suppress generic terminal receipts at the backend boundary.
- Add `final_summary` only when there is actual final answer, artifact, verification result, or useful closeout.
- Keep `debug_trace_ref` or `trace_available` for monitor access.
- Keep `progress_entries` out of the chat rendering contract; if retained, it is monitor/debug input only.
- Emit stable public item ids and trace refs so live SSE and refreshed history can deduplicate.

Completion criteria:

- Ordinary completion does not emit visible `done` text.
- Failed tool/provider state becomes one `blocked` item.
- Meaningful tool work becomes compact `tool_activity`.
- Public timeline contains no item derived only from ordinary lifecycle receipt.

### Phase 2 - Frontend Chat Consumption

Files:

- `frontend/src/lib/api.ts`
- `frontend/src/lib/store/types.ts`
- `frontend/src/lib/store/utils.ts`
- `frontend/src/components/chat/ChatMessage.tsx`
- New component: `frontend/src/components/chat/PublicRunActivity.tsx`

Tasks:

- Add typed `public_timeline` to `SessionRuntimeAttachment`.
- Add typed `anchor_message_id`, `anchor_role`, and `debug_trace_ref` when the backend provides them.
- Render `public_timeline` inside the assistant turn after or between assistant text, not as a large panel before the message.
- Hide runtime activity entirely when it contains only ordinary completion receipts.
- Keep artifact and verification rows compact.
- Remove frontend dependency on `progress_entries` for main chat rendering.

Completion criteria:

- Assistant message has visual authority.
- Runtime activity appears as conversation-native inline rows.
- No generic completion panel appears after a direct answer.
- Runtime attachments are placed by stable message/turn identity, not nearest assistant index.

### Phase 3 - Retire Chat-Facing `RuntimeRunSummary`

Files:

- `frontend/src/components/chat/RuntimeRunSummary.tsx`
- `frontend/src/components/chat/RuntimeRunSummary.test.ts`
- Replacement test: `frontend/src/components/chat/PublicRunActivity.test.tsx`
- `frontend/src/app/globals.css`

Tasks:

- Stop using `RuntimeRunSummary` as the primary chat progress component.
- Either remove it from chat or move it behind monitor/debug usage.
- Delete or replace `RuntimeRunSummary.test.ts` if the component is removed from the chat path.
- Delete CSS that exists only for the old event-panel presentation.
- Do not keep old panel rendering as a compatibility fallback in chat.

Completion criteria:

- Main chat no longer renders "查看执行细节" for normal task completion.
- Main chat no longer renders "查看技术细节" for ordinary runs.
- Old event-panel classes are not part of the chat path.

### Phase 4 - Streaming Event Cleanup

Files:

- `frontend/src/lib/runtimeVisibilityProjection.ts`
- `frontend/src/lib/store/events.ts`
- Relevant frontend tests

Tasks:

- Streaming events may update transient activity state, but they must not create permanent chat-visible terminal receipts.
- `done` should close the stream state, not render "回答已生成并写回会话".
- `agent_turn_terminal` should be used for lifecycle/debug state, not chat content.
- Live transient activity must deduplicate against persisted `public_timeline` after session refresh.

Completion criteria:

- No duplicate completion text.
- A direct assistant answer with no meaningful tools renders as a normal answer only.
- Live view and refreshed session history converge to the same visible transcript.

## 10. Acceptance Criteria

### Direct Answer

Given a normal assistant answer without meaningful tool work:

- Show assistant text.
- Do not show runtime summary.
- Do not show "已完成" badge as separate content.
- Do not show "回答已生成并写回会话".
- After history refresh, the same answer still renders once.

### Long Tool Task

Given a coding or asset task with tools:

- Show compact inline activity rows.
- Each row says what the agent did and what it learned.
- Rows are visually subordinate to the assistant message.
- Raw event names and payloads are absent.
- Live SSE activity and persisted timeline do not duplicate the same tool step.

### Successful Completion

Given a completed task:

- Show one natural final summary.
- Show artifacts/verification if available.
- Do not show ordinary terminal receipt.
- Do not show duplicate completion labels.

### Blocked State

Given a provider/tool/configuration failure:

- Show one natural blocked explanation.
- Include a recovery hint if there is one.
- Do not show raw provider field names or target ids.
- Keep raw trace in monitor/debug only.

### Interruption Or Resume

Given a stopped previous task and a new user message:

- The backend exposes the stopped-task fact to the model if relevant.
- The model decides whether the new user message starts a new task or asks about the stopped task.
- The UI does not silently continue the stopped run.
- The UI does not directly call tools before the model receives the interruption context.
- The stopped run's attachment remains anchored to its original assistant turn.

## 11. Tests

Backend tests:

```powershell
python -m pytest backend/tests/runtime_progress_presenter_regression.py -q
```

Required new backend assertions:

- `public_timeline` suppresses generic `done`.
- `public_timeline` suppresses `agent_turn_terminal`.
- Meaningful tool observation becomes `tool_activity`.
- Provider failure becomes `blocked`.
- The completed turn has exactly one visible closeout, either as assistant message content or as `final_summary`.
- Public timeline items have stable ids or trace refs for deduplication.
- Runtime attachment exposes stable assistant-turn anchoring when the assistant message exists.

Frontend tests:

```powershell
cd frontend
npm test -- --run src/components/chat/ChatMessage.test.ts src/components/chat/PublicRunActivity.test.tsx src/lib/runtimeVisibilityProjection.test.ts
```

Required new frontend assertions:

- A completion-only runtime attachment renders no runtime panel.
- `public_timeline` tool items render as inline assistant activity.
- Main chat does not contain internal event names.
- `done` closes stream state without visible receipt text.
- Refreshing session history after a live run does not duplicate assistant text, final summary, or tool activity.
- Runtime attachments do not move to a later assistant turn after a stopped-task follow-up.

Browser validation:

- Use fixed frontend `http://127.0.0.1:3000`.
- Use fixed backend `http://127.0.0.1:8003/api`.
- Validate with a direct answer, a long tool task, a blocked provider case, and a stopped-task follow-up.

## 12. Scope Control

This must be a contract refactor, not a broad visual rewrite.

Allowed:

- Add backend public projection.
- Change chat rendering to consume public projection.
- Delete obsolete chat-facing runtime panel paths.
- Remove CSS tied only to deleted panel UI.
- Update tests that protected old event-panel behavior.

Not allowed in this pass:

- Rework graph UI.
- Rework image generation bypass.
- Rework model selection.
- Redesign the entire workbench layout.
- Add more frontend regex filters as the main fix.
- Preserve old chat panel rendering as a compatibility fallback.
- Expand `globals.css` with another broad style layer.

Any implementation touching more than these paths needs a new plan before editing.

## 13. Final Target

After this refactor, the same class of task should read like this:

```text
Assistant

我正在检查这次任务的运行入口。

✓ 读取聊天消息渲染链路
  确认运行附件现在挂在 assistant turn 上。

✓ 整理公开进展
  普通完成回执不会进入主聊天；调试 trace 保留在监控里。

我已完成这轮处理：聊天主界面现在只显示回答、必要的工具活动和最终收口。
```

It should not read like this:

```text
我已经处理完
已完成
回答已生成并写回会话
查看执行细节
查看技术细节
agent_turn_terminal
done
```

This is the core distinction: Codex-style chat shows the agent's work as a conversation. It does not ask the user to read the runtime system.
