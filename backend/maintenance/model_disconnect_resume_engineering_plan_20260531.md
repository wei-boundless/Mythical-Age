# Model Disconnect Protection and Resume Engineering Plan - 2026-05-31

## 1. Problem Definition

Current chat streaming is request-bound: `POST /chat` opens one streaming response, iterates `runtime.query_runtime.astream(request)`, and stops when a terminal event is emitted. If the client connection drops, the visible stream drops with it. The backend has durable pieces such as `RuntimeEventLog`, `RuntimeExecutionStore`, `TaskRun.latest_event_offset`, and `latest_checkpoint_ref`, but the chat stream itself is not a resumable event stream with replay and continuation semantics.

Correct end state:

- Client disconnect must not automatically kill a running task.
- Client reconnect must replay missed public events from the last acknowledged offset.
- Runtime resume must start from explicit checkpoints and execution records, not from guessed conversation text.
- Tool side effects must be idempotent or explicitly blocked from replay.
- Partial model output must be recorded and surfaced honestly; it must not be duplicated by blind retry.

This is primarily a runtime durability and ownership problem, not a prompt problem.

## 2. Mature Reference Architecture

References to borrow:

- SSE reconnection model: Server-Sent Events support event IDs and browser reconnection behavior; `id` sets the last event ID and `retry` controls reconnection delay. MDN also notes that comments can be used as keep-alives. Source: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
- Durable execution model: Temporal uses an event history to restore progress after crashes and treats workflows as resumable/recoverable/reactive processes. Source: https://docs.temporal.io/temporal and https://docs.temporal.io/encyclopedia/event-history
- Activity/idempotency model: Temporal recommends activities be idempotent and split into smaller recoverable units; activity results are persisted into workflow event history. Source: https://docs.temporal.io/activities
- Agent checkpoint model: LangGraph persists state as checkpoints by thread, supports fault-tolerant resume, and persists pending writes so successful node work is not re-run. Source: https://docs.langchain.com/oss/python/langgraph/persistence

What to borrow:

- Event history as the durable source of replay.
- Checkpoints at execution boundaries, not arbitrary token positions.
- Idempotency for side-effect tools.
- Replay of public events by offset.

What not to borrow directly:

- Do not add a full external Temporal service now. The repo already has `RuntimeEventLog`, `RuntimeExecutionStore`, `RuntimeObjectStore`, and LangGraph checkpoint storage. The right move is to mature the local runtime first.
- Do not make model token streaming itself the durable source of truth. Token deltas are presentation events; checkpoints and execution records are the authoritative recovery state.

## 3. Current Codebase Source Report

Existing useful foundations:

- `backend/api/chat.py`
  - `POST /chat` streams `text/event-stream`.
  - It currently emits `event:` and `data:` only; it does not emit SSE `id:` or accept `Last-Event-ID`.
  - The generator is tied to the HTTP response lifecycle.
- `backend/runtime/shared/event_log.py`
  - `RuntimeEventLog.append()` already assigns monotonic `offset` and persists events to JSONL.
  - It has subscription support and `list_events` / `list_event_window`.
- `backend/runtime/shared/execution_record.py`
  - `OperationExecutionRecord` already has `request_fingerprint`, `idempotency_token`, `replay_policy`, `side_effect_state`, result refs, and statuses.
  - This is the right base for safe replay and duplicate suppression.
- `backend/harness/runtime/single_agent_host.py`
  - The runtime host already owns `event_log`, `execution_store`, `state_index`, `runtime_objects`, and `graph_checkpoint_store`.
- `frontend/src/lib/api.ts`
  - `streamChat()` manually parses fetch streaming SSE.
  - It currently throws when the stream closes without a terminal event.
  - It does not persist last event ID or reconnect to a replay endpoint.
- `frontend/src/lib/store/runtime.ts`
  - Store tracks active stream sessions and keeps in-memory stream cache.
  - A browser refresh or hard disconnect loses this cache.

Main gap:

The durable backend event log and the frontend stream are not connected by a resumable stream protocol.

## 4. Target Design

### 4.1 Runtime Ownership

Authority map:

| Layer | Owner | Responsibility |
| --- | --- | --- |
| Run identity | new `RuntimeRunRegistry` or extension of `RuntimeStateIndex` | map `stream_run_id -> session_id/task_run_id/root_event_offset/status` |
| Durable event history | `RuntimeEventLog` | append canonical runtime events with offsets |
| Presentation stream | new `RuntimeStreamReplayService` | project event-log entries into SSE events and replay from offset |
| Execution idempotency | `RuntimeExecutionStore` | decide reuse/suppress/retry for operation records |
| Model call recovery | `ModelResponseRuntimeExecutor` + execution record | classify `not_started`, `partial_output`, `completed`, `failed_retryable` |
| User-facing state | frontend runtime store | reconnect, replay missed events, render status without restarting work |

### 4.2 New Runtime Concepts

`RuntimeRun`

```python
@dataclass(frozen=True, slots=True)
class RuntimeRun:
    stream_run_id: str
    session_id: str
    task_run_id: str
    root_request_ref: str
    status: Literal["starting", "running", "waiting", "completed", "failed", "stopped", "orphaned"]
    created_at: float
    updated_at: float
    latest_event_offset: int = -1
    latest_checkpoint_ref: str = ""
    reconnectable_until: float = 0.0
    authority: str = "runtime.run_registry"
```

`RuntimeStreamCursor`

```python
@dataclass(frozen=True, slots=True)
class RuntimeStreamCursor:
    stream_run_id: str
    task_run_id: str
    last_event_offset: int
    last_event_id: str = ""
    authority: str = "runtime.stream_cursor"
```

SSE event ID format:

```text
{stream_run_id}:{task_run_id}:{offset}
```

This lets the server validate reconnect requests without trusting client-side state.

### 4.3 Transport Protocol

Create a resumable stream API instead of overloading the current fire-and-forget `/chat` stream:

1. `POST /api/chat/runs`
   - Starts or attaches to a run.
   - Returns `stream_run_id`, `task_run_id`, `stream_url`, `latest_event_offset`.
   - Does not require the client to keep the request open.

2. `GET /api/chat/runs/{stream_run_id}/events`
   - SSE endpoint.
   - Accepts `Last-Event-ID` header or `?after_offset=N`.
   - First replays missed public events from `RuntimeEventLog`.
   - Then subscribes to live events.
   - Emits keep-alive comments while idle.

3. `POST /api/chat/runs/{stream_run_id}/resume`
   - Explicit resume command for interrupted runs.
   - Uses runtime resume decision and execution records.
   - Does not blindly resubmit the original user message.

4. Existing `POST /api/chat`
   - Keep only as a thin compatibility wrapper during migration.
   - It should internally create a run and stream the new run events.
   - Removal condition: frontend no longer calls legacy stream path.

### 4.4 Event Replay Rules

Backend stream rules:

- Every emitted public SSE event must have:
  - `id: {stream_run_id}:{task_run_id}:{offset}`
  - `event: {public_event_type}`
  - `data: {..., "task_run_id": "...", "event_offset": offset, "stream_run_id": "..."}`
- If the event came from existing runtime events, use the runtime event offset.
- Pure presentation events that are not in `RuntimeEventLog` should be eliminated or converted into durable runtime events.
- On reconnect:
  - replay events with `offset > last_event_offset`;
  - if no events are available and run is terminal, emit current terminal projection;
  - if run is still running, subscribe live.

Client rules:

- Store `stream_run_id`, `task_run_id`, and last received offset in persisted frontend state.
- On network error, reconnect with `Last-Event-ID` or `after_offset`.
- Do not append duplicate events with offset already seen.
- If reconnect fails because the run expired, fall back to monitor/timeline and show a resumable status.

### 4.5 Model Call Recovery Rules

Model invocation must be treated as an activity with explicit state:

| State | Safe action |
| --- | --- |
| `not_started` | retry or fallback allowed |
| `started_no_delta` | retry/fallback allowed if provider error is retryable |
| `partial_output_emitted` | do not retry blindly; persist partial output and mark `partial_timeout` or wait for explicit resume |
| `tool_call_emitted` | persist action request; tool execution is controlled by OperationGate and execution store |
| `completed` | reuse result |
| `unknown_after_disconnect` | recover from event/execution record; if side effect may have happened, require repair/approval |

The current `ModelResponseRuntimeExecutor` already has partial-output timeout and pre-delta recovery concepts. The upgrade is to persist these states into execution records and runtime events so reconnect can observe them.

### 4.6 Tool and Side-Effect Replay Rules

Execution store rules:

- Read-only operations with same fingerprint may replay/read again or reuse result depending on `replay_policy`.
- Write/edit/shell/python side effects must not auto-repeat if `side_effect_state in {"in_progress", "unknown", "committed"}`.
- If a write completed and has a result ref, reconnect/retry returns the stored tool result envelope.
- If a side effect is unknown, runtime emits `manual_recovery_required` or asks the model to inspect state using read-only tools.

This aligns with the existing `OperationExecutionRecord` fields and the planned approval fingerprint hardening.

## 5. Engineering Phases

### Phase 1 - Resumable Public Event Stream

Files:

- `backend/runtime/shared/event_log.py`
- new `backend/runtime/shared/stream_replay.py`
- `backend/api/chat.py`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/store/runtime.ts`
- tests under `backend/tests/` and `frontend/src/lib/`

Deliverables:

- SSE emits `id:` and `retry:`.
- Backend can replay events after a given offset.
- Frontend stores cursor and reconnects without duplicating messages.

Completion criteria:

- Simulated stream disconnect after `assistant_text_delta` reconnects and replays missed transcript events.
- Stream closure without terminal event no longer forces the user-visible session into false failure while the backend run is still active.

### Phase 2 - Runtime Run Registry

Files:

- new `backend/runtime/shared/runtime_run_registry.py`
- `backend/harness/runtime/single_agent_host.py`
- `backend/api/chat.py`
- `backend/runtime/memory/state_index.py` if using state index instead of a new store

Deliverables:

- Persist `stream_run_id -> task_run_id/session_id/status/latest_event_offset`.
- Expose run monitor endpoint.
- Frontend can reload page and attach to the latest active run for the session.

Completion criteria:

- Browser refresh during a running task restores run status and reconnects to the event stream.
- Multiple sessions do not cross-attach to each other's runs.

### Phase 3 - Execution Record Recovery Contract

Files:

- `backend/runtime/shared/execution_record.py`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/runtime/model_gateway/model_response.py`
- `backend/runtime/shared/resume_decision.py`
- tests for model/tool replay

Deliverables:

- Model call execution records include `model_call_state`.
- Tool execution replay uses `request_fingerprint + idempotency_token`.
- Side-effect unknown states fail closed.

Completion criteria:

- Repeating a completed write after reconnect reuses the stored result and does not write again.
- Repeating an unknown shell execution does not auto-rerun.
- Retryable model failure before first delta falls back safely.
- Failure after partial output persists partial state and offers resume/repair.

### Phase 4 - Resume Command and UI

Files:

- `backend/api/orchestration_harness.py`
- `backend/api/chat.py`
- `backend/harness/loop/resume_policy.py`
- `backend/harness/loop/active_work.py`
- `frontend/src/lib/store/runtime.ts`
- relevant chat/runtime components

Deliverables:

- User-visible run state: running, reconnecting, interrupted, resumable, waiting approval, completed.
- Explicit resume uses runtime checkpoint and execution records.
- No hidden rerun of the original user message.

Completion criteria:

- User can refresh, reconnect, pause, resume, and inspect status.
- Resume from waiting executor continues same task.
- Resume from interrupted terminal creates checkout/fork when required.

### Phase 5 - Cutover and Cleanup

Files:

- `backend/api/chat.py`
- `frontend/src/lib/api.ts`
- old tests that assert legacy stream failure behavior

Deliverables:

- Frontend uses `POST /chat/runs` + `GET /chat/runs/{id}/events`.
- Legacy `POST /chat` stream wrapper is either removed or kept behind a documented temporary compatibility boundary.
- Old behavior "stream ended without terminal event = terminal user failure" is removed from the main path.

Completion criteria:

- No production frontend path depends on the legacy non-resumable chat stream.
- Search confirms no duplicate stream authority remains.

## 6. Validation Matrix

Backend tests:

```powershell
python -m pytest backend/tests/model_response_runtime_regression.py backend/tests/sandbox_tool_runtime_regression.py backend/tests/professional_run_resume_regression.py -q
```

New backend tests:

- `chat_stream_replay_regression.py`
- `runtime_run_registry_regression.py`
- `execution_record_replay_regression.py`

Frontend tests:

```powershell
npm test -- frontend/src/lib/api.test.ts frontend/src/lib/store/runtime.test.ts
```

Required new frontend cases:

- reconnect after partial SSE event;
- reconnect after content delta but before done;
- replay does not duplicate assistant content;
- page reload attaches to active run;
- expired run falls back to monitor with resumable status.

Full runtime validation:

- Start backend on `127.0.0.1:8003` and frontend on `127.0.0.1:3000`.
- Use real browser/Edge or Playwright against the fixed ports.
- Interrupt network/abort fetch mid-run, then verify reconnect and no duplicate writes.

## 7. Anti-Patterns That Are Not Allowed

- No "retry the whole user message" as disconnect recovery.
- No duplicate model call after partial output.
- No duplicate write/edit/shell execution after unknown side-effect state.
- No frontend-only reconstruction of backend state.
- No hidden compatibility path that bypasses `RuntimeExecutionStore`.
- No prompt-only fix for runtime durability.

## 8. Recommended Decision

Adopt this as a second, larger runtime upgrade after the current permission/resume hardening plan.

Implementation order should be:

1. Finish approval fingerprint + resume obligation + stream fallback + preflight fail-closed.
2. Implement resumable SSE replay and frontend cursor.
3. Add run registry.
4. Tighten execution record recovery and side-effect replay.
5. Cut over frontend to run-based streaming and remove the old request-bound stream path.

## 9. Implementation Status - 2026-05-31

Implemented:

- Added `RuntimeRunRegistry` and `RuntimeStreamReplayService`.
- Added run-based chat APIs: `POST /api/chat/runs`, `GET /api/chat/runs/{stream_run_id}`, `GET /api/chat/runs/{stream_run_id}/events`, `POST /api/chat/runs/{stream_run_id}/resume`, and `GET /api/chat/sessions/{session_id}/latest-run`.
- Changed the legacy `POST /api/chat` stream path into a wrapper over the run-based event stream.
- Added SSE `id`, `retry`, keepalive, `Last-Event-ID`, and `after_offset` replay support.
- Added frontend stream cursor persistence, transport reconnect, duplicate-offset suppression, user-visible reconnect events, and page/session initialization attach to an existing run.
- Added regression coverage for replay by offset, replay by `Last-Event-ID`, latest run lookup, frontend reconnect, and reload attach.

Remaining:

- `POST /api/chat/runs/{stream_run_id}/resume` is attach-only. Actual task continuation must still use the runtime/harness resume path and execution records.
- Model invocation recovery still needs explicit persisted `model_call_state` beyond the current partial-output safeguards.
- Side-effect replay hardening still depends on completing the execution-record recovery contract for all write/shell/tool operations.
- The legacy `/api/chat` wrapper remains as a temporary compatibility boundary until all production callers use run-based streaming directly.
