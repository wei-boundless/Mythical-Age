# Backend CLI Session Port Plan

## 1. Problem Definition

The backend CLI must become a terminal-facing session port for the existing agent runtime. It is not a new validation system, not a test runner, and not a hidden execution lane.

The current user-facing session path already exists:

```text
Frontend main chat
-> /api/chat
-> QueryRuntime.astream
-> TaskRunLoop
-> session history, runtime monitor, token usage, health governance
```

The CLI design is proven only if it reuses this same path and produces the same observable records as the frontend.

## 2. Target Property

The CLI is correct when a turn started from the terminal is indistinguishable from a turn started from the frontend main chat at the backend authority layers:

- Session history is owned by `/api/sessions`.
- Message execution is owned by `/api/chat`.
- Streaming output is the same SSE contract consumed by the frontend.
- Runtime progress is visible through `/api/orchestration/runtime-loop`.
- Token usage and runtime efficiency are visible through health governance.

This means the CLI is a client of the backend session API, not an internal caller of runtime classes.

## 3. Authority Map

| Layer | Current Owner | CLI Role | Rule |
| --- | --- | --- | --- |
| Session list/create/read/delete | `backend/api/sessions.py` | Client | CLI must call HTTP API, not read session JSON directly. |
| User message execution | `backend/api/chat.py` | Client | CLI must post to `/api/chat` with `stream: true`. |
| Stream parsing | Frontend `streamChat` contract | Equivalent client | CLI must parse SSE events and terminal events. |
| Runtime execution | `QueryRuntime.astream` and `TaskRunLoop` | No authority | CLI must not instantiate or call runtime internals directly. |
| Runtime monitor | `backend/api/orchestration_runtime_loop.py` | Client | CLI can display monitor snapshots, not rewrite them. |
| Health governance | `backend/api/health_system.py` | Observer | CLI output can link to health records, not own health logic. |

## 4. CLI Command Surface

The first version should stay deliberately small, but interactive mode is the primary user experience:

```text
agent-cli
> 帮我分析当前任务
> /history
> /monitor
> /exit
```

Plain text inside the interactive window is sent as a backend chat message. Slash commands manage the session.

The command-style surface remains available for scripts and smoke checks:

```text
agent-cli session list
agent-cli session create [--title "..."]
agent-cli session use <session_id>
agent-cli session history [--session <session_id>]
agent-cli send "message" [--session <session_id>]
agent-cli monitor [--session <session_id>]
agent-cli config show
```

Interactive slash commands:

```text
> /sessions
> /new
> /use session-xxx
> 帮我分析当前任务
> /monitor
> /exit
```

The CLI should persist only local client preferences, such as the last selected session and API base. It must not persist its own conversation store.

## 5. Protocol Contract

### API Base

Default API base:

```text
http://127.0.0.1:8003/api
```

The CLI may allow explicit override for development, but the project default must remain the fixed backend node.

### Send Message

Request:

```http
POST /api/chat
Content-Type: application/json
```

Body:

```json
{
  "session_id": "session-xxx",
  "message": "user message",
  "stream": true,
  "ephemeral_system_messages": [],
  "search_policy": null,
  "task_selection": {},
  "task_order_intent": {},
  "model_selection": {},
  "image_generation": {}
}
```

The CLI must support the same terminal events used by the frontend:

```text
done
error
stopped
```

It must render these streaming content events as assistant text:

```text
token
content_delta
answer_candidate
```

Other runtime events should be rendered as compact progress lines or hidden behind a verbose flag. Raw internal payloads should not dominate the normal terminal output.

## 6. Proof Plan

The design is proven by one real end-to-end run:

1. Start backend on `127.0.0.1:8003`.
2. Run `agent-cli session create --title "CLI proof"`.
3. Run `agent-cli send "用一句话说明你正在通过后端 CLI 会话口工作"`.
4. Confirm the CLI prints streaming assistant text and ends on `done`.
5. Read `/api/sessions/{session_id}/history` and confirm the user and assistant messages exist.
6. Read `/api/orchestration/runtime-loop/sessions/{session_id}/live-monitor` and confirm the run is visible.
7. Read `/api/health-system/token-usage` and `/api/health-system/efficiency` and confirm the run contributes to cost and efficiency views when task telemetry exists.

If these checks pass, the CLI is using the same runtime path as the frontend.

## 7. Implementation Plan

### Phase 1: HTTP Client Core

Files to add:

- `backend/cli/__init__.py`
- `backend/cli/client.py`
- `backend/cli/sse.py`
- `backend/cli/state.py`
- `backend/cli/main.py`

Responsibilities:

- `client.py`: typed HTTP calls to session, chat, monitor, and config endpoints.
- `sse.py`: SSE parser matching frontend `streamChat` behavior.
- `state.py`: local CLI state for API base and selected session only.
- `main.py`: argparse command surface.
- no-argument `main.py`: interactive session window.

Completion criteria:

- Can list sessions.
- Can create a session.
- Can send a streamed message.
- Can enter interactive mode, send plain text, and exit with `/exit`, `/quit`, or `/q`.
- Does not import `QueryRuntime`, `TaskRunLoop`, or session storage internals.

### Phase 2: Terminal Presentation

Responsibilities:

- Render assistant text progressively.
- Render progress events as short status lines.
- Render errors with backend error code and message.
- Keep raw payload display behind `--verbose`.

Completion criteria:

- Normal output is readable as a conversation.
- Debug output can still expose event names and compact JSON when needed.

### Phase 3: Monitor and Health Observation

Responsibilities:

- Add `monitor` command for session live monitor.
- Add optional post-run summary with task run id, completion state, token hints, and health links when available.

Completion criteria:

- CLI can show that the just-run session has backend runtime records.
- CLI does not duplicate health scoring or token aggregation.

### Phase 4: Proof Script

Files to add:

- `backend/tests/cli_session_port_regression.py`

Responsibilities:

- Test the CLI client against FastAPI `TestClient` or a local ASGI adapter where practical.
- Verify SSE parsing with real event blocks.
- Verify command layer calls HTTP client methods instead of runtime internals.

Completion criteria:

- Regression covers session creation, stream terminal event handling, and history visibility.
- No fake success output is used to bypass backend behavior.

## 8. Non-Goals

The first CLI version must not:

- Replace the frontend.
- Become the experiment system.
- Become the test system.
- Read or write session JSON directly.
- Call `QueryRuntime.astream` directly.
- Implement its own task orchestration.
- Implement its own health scoring.
- Preserve obsolete validation scripts as compatibility paths.

## 9. Validation Commands

After implementation:

```powershell
python -m py_compile backend/cli/__init__.py backend/cli/client.py backend/cli/sse.py backend/cli/state.py backend/cli/main.py
pytest backend/tests/cli_session_port_regression.py
python -m backend.cli.main session list
```

If backend is running on the fixed local node:

```powershell
python -m backend.cli.main session create --title "CLI proof"
python -m backend.cli.main send "用一句话说明你正在通过后端 CLI 会话口工作"
python -m backend.cli.main monitor
```

## 10. Cutover Rule

There is no old CLI surface to preserve for this backend session port. If an old script is discovered during implementation and it owns a conflicting session, validation, or runtime decision, it should be deleted or explicitly left outside this CLI plan.

The CLI becomes accepted only after the proof run shows the same backend records that the frontend path produces.
