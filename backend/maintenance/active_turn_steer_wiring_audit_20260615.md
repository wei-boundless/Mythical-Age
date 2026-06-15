# Active Turn Steer Wiring Audit - 2026-06-15

## Scope

本记录审查 `session-9458b9376ed8437e` 中 active task 期间用户补充输入的 steer 链路，重点确认：

- 用户在任务运行期间输入补充、质疑、继续等内容时，是否被作为当前 active turn 的 steer 信号发送。
- `expected_active_turn_id` 与 `active_turn_input_policy` 是否从前端请求层到后端 boundary 保持一致。
- stop/pause/resume 控制信号是否与普通 steer 输入共用或串线。

本轮只记录审查结论，不修改运行代码。

## Expected Mature Line

```text
user follow-up while active task is running
-> frontend detects active single_agent_task turn
-> chat request carries expected_active_turn_id + active_turn_input_policy=steer
-> backend validates active turn/task binding
-> current_work_boundary exposes active_work_control only for the bound current work
-> model emits active_work_control with visible response obligation
-> runtime appends/continues/stops according to model-owned action
-> task executor consumes pending_user_steers or runtime_control signal
-> projection shows feedback/status under the correct turn and task ids
```

## Findings

### P1 - Background active-task follow-up is rendered as queued steer in UI but sent as `auto`

Evidence:

- `frontend/src/lib/store/runtime.ts` uses `startQueuedActiveTurn(...)` when `queueActiveTurnInput` is true.
- The same branch then sends the request with `active_turn_input_policy: "auto"` instead of `steer`.
- The real run `strun:49fa6399d6f34e08a7a1f9c337f1aba1` has:
  - `expected_active_turn_id: "turn:session-9458b9376ed8437e:40"`
  - `active_turn_input_policy: "auto"`
  - `runtime_task_run_id: "taskrun:turn:session-9458b9376ed8437e:40:199feb77"`

Broken edge:

```text
frontend active-task follow-up detection
-> chat request policy identity
```

Why it matters:

The UI creates a runtime-control/progress-only assistant placeholder, but the transport tells the backend this is an ordinary `auto` input. The backend may still find active work and route to `active_work_control`, but that is an implicit fallback, not the authoritative steer contract. This makes supplement, continue, independent turn, and stop behavior unstable.

Required fix:

When `queueActiveTurnInput === true`, the normal `sendMessage` request must use:

```json
{
  "expected_active_turn_id": "<active turn id>",
  "active_turn_input_policy": "steer"
}
```

The dedicated `submitActiveTurnSteerDuringActiveStream(...)` and the background active-task branch must share one request builder so the policy cannot diverge.

### P1 - `followUpQueueMode = "steer"` is not wired into project frontend decision logic

Evidence:

- User config contains `[desktop] followUpQueueMode = "steer"`.
- Project search found no source reference to `followUpQueueMode` in `frontend` or `backend`.
- Therefore the current project code does not read this setting to decide whether a follow-up is steer.

Broken edge:

```text
desktop config
-> frontend follow-up routing policy
```

Why it matters:

The configured intention is not part of the project signal graph. The only effective decision today is `shouldQueueActiveTurnInput(...)`, and even when that decision is true, one branch still sends `auto`.

Required fix:

Either remove project reliance on this external desktop config and make active-task follow-up routing deterministic from runtime state, or explicitly inject the config into the frontend runtime state. For this project, the mature route should be runtime-state driven: if a steerable active single-agent task is bound, the input is a steer unless the user explicitly starts a new independent task.

### P1 - Backend accepts `auto` input into active work when active_work_context exists

Evidence:

- `runtime_facade.py` passes `require_bound_task=bool(active_work_context) or policy == "steer"`.
- `current_work_boundary.py` returns `current_work_control_required` for active work even when policy is `auto`.
- Real event `current_work_boundary_decided` for turn 41 shows:
  - decision `current_work_control_required`
  - active task `taskrun:turn:session-9458b9376ed8437e:40:199feb77`
  - diagnostics `active_turn_input_policy: "auto"`

Broken edge:

```text
request policy authority
-> backend current-work boundary authority
```

Why it matters:

`auto` is doing two jobs: ordinary new turn and implicit current-work control. That makes the backend permissive enough to mask the frontend policy bug. A mature agent should not let a weak/ordinary policy silently become current-work control just because an active context happens to exist.

Required fix:

Separate policies:

- `steer`: requires `expected_active_turn_id`, validates active turn/task binding, may expose `active_work_control`.
- `auto`: ordinary turn unless the backend has an explicit, typed reason to treat it as current-work control.

If this project wants every active-task follow-up to be steer, the frontend must send `steer`; the backend should not compensate for a missing steer identity.

### P1 - Existing frontend tests encode the wrong background follow-up contract

Evidence:

- `frontend/src/lib/store/runtime.test.ts` has cases expecting post-handoff active-task input to send `active_turn_input_policy: "auto"`.
- These tests match the current bug rather than the intended steer architecture.

Broken edge:

```text
intended active-task steer contract
-> regression coverage
```

Why it matters:

Fixing the runtime policy will break tests that currently protect the incorrect route. These are not useful semantic safeguards for the mature steer design.

Required fix:

Remove or rewrite those cases as structural tests that assert:

- active task follow-up carries `expected_active_turn_id`.
- active task follow-up carries `active_turn_input_policy=steer`.
- paused/stopped/terminal task follow-up does not get silently attached.
- explicit stop button uses the orchestration control API, not chat steer.

## Connected Lines Proven

| Line | Evidence | Status |
| --- | --- | --- |
| Active-stream follow-up sends steer | `submitActiveTurnSteerDuringActiveStream(...)` sends `active_turn_input_policy: "steer"` | Connected |
| Backend request preserves policy into run diagnostics | `backend/api/chat.py` stores `active_turn_input_policy` in run diagnostics | Connected |
| Backend boundary can validate steer against active turn | `current_work_boundary.py` rejects steer without expected active turn or active work | Connected |
| Stop button sends runtime control, not chat steer | `stopActiveTaskRun()` calls `stopOrchestrationHarnessTaskRun(..., "user_stop_from_chat", expectedTurnId)` | Connected |

## Miswired Lines

| Line | Producer | Actual payload | Expected payload |
| --- | --- | --- | --- |
| Background active-task follow-up | `sendMessage()` normal branch | `active_turn_input_policy: "auto"` | `active_turn_input_policy: "steer"` |
| Config-driven steer mode | `C:\Users\admin\.codex\config.toml` | no project consumer | deterministic frontend policy or explicit config injection |
| Backend active-work auto fallback | `runtime_facade.py` + `current_work_boundary.py` | `auto` may still expose `active_work_control` | `active_work_control` should require authoritative steer/control route |

## Real Run Timeline

Target task:

```text
taskrun:turn:session-9458b9376ed8437e:40:199feb77
```

Observed stream run:

```text
strun:49fa6399d6f34e08a7a1f9c337f1aba1
```

Sequence:

1. Frontend created a new chat run for the follow-up.
2. Run diagnostics recorded `expected_active_turn_id=turn:session-9458b9376ed8437e:40` but `active_turn_input_policy=auto`.
3. Backend still produced `current_work_control_required` because active work context existed.
4. Model produced visible feedback: `我会直接修改，不再读取。`
5. Runtime emitted `active_task_steer_accepted`.
6. The task later ended as `user_aborted` after an explicit runtime control stop, with `runtime_control.reason=user_stop_from_chat`.

Conclusion:

The final abort was caused by a stop control signal, but the earlier steer follow-up already had a policy identity mismatch. The bug is not "steer never works"; the bug is that steer has two inconsistent entry paths and one of them labels the request as `auto`.

## Repair Plan

1. Create one frontend helper for active-task follow-up request policy:
   - Input: `sessionId`, current state, active turn snapshot, active task monitor.
   - Output: `{ expected_active_turn_id, active_turn_input_policy }`.
   - If `shouldQueueActiveTurnInput(...)` is true, output must be `steer`.

2. Use the helper in both active-stream and background active-task branches:
   - Remove the hard-coded `active_turn_input_policy: "auto"` from the queued active-task branch.
   - Keep ordinary non-task turns as `auto`.

3. Remove the `autoActiveWorkTurnStreamSessionIds` behavior if it exists only to prevent nested active-task steer while the control run is in progress. Replace it with an explicit per-session "steer submission in flight" guard keyed by stream run/session, not a semantic policy downgrade.

4. Tighten backend boundary after frontend is fixed:
   - `steer` remains the only route that requires and validates active turn binding for user follow-up.
   - `auto` should not silently promote to `active_work_control` unless there is an explicit, documented control source.

5. Clean incorrect regression coverage:
   - Delete or rewrite tests expecting `active_turn_input_policy: "auto"` for active-task follow-up.
   - Keep structural tests around identity, terminal boundaries, and explicit stop control.

## Non-goals

- Do not treat ordinary terminal task follow-up as steer.
- Do not route the stop button through chat/steer.
- Do not hide this issue in projection UI. The request policy must be correct before projection.
- Do not add compatibility routes that keep both `auto` and `steer` as equivalent active-work control identities.
