from __future__ import annotations

from types import SimpleNamespace

from harness.runtime.session_timeline import build_session_runtime_timeline


class _Event:
    def __init__(self, payload: dict) -> None:
        self._payload = dict(payload)

    def to_dict(self) -> dict:
        return dict(self._payload)


class _EventLog:
    def __init__(self, events_by_run: dict[str, list[dict]]) -> None:
        self.events_by_run = {
            run_id: [_Event(event) for event in events]
            for run_id, events in events_by_run.items()
        }

    def list_event_window(self, run_id: str, *, limit: int, include_payloads: bool = True) -> list[_Event]:
        return list(self.events_by_run.get(run_id, []))[-limit:]

    def estimated_event_count(self, run_id: str) -> int:
        return len(self.events_by_run.get(run_id, []))


class _StateIndex:
    def __init__(self, *, task_runs: list[SimpleNamespace], turn_runs: list[SimpleNamespace] | None = None) -> None:
        self._task_runs = list(task_runs)
        self._turn_runs = list(turn_runs or [])

    def list_session_task_runs(self, session_id: str) -> list[SimpleNamespace]:
        return [run for run in self._task_runs if run.session_id == session_id]

    def list_session_turn_runs(self, session_id: str) -> list[SimpleNamespace]:
        return [run for run in self._turn_runs if run.session_id == session_id]


def _runtime_host(*, task_runs: list[SimpleNamespace], events_by_run: dict[str, list[dict]], turn_runs: list[SimpleNamespace] | None = None):
    return SimpleNamespace(
        state_index=_StateIndex(task_runs=task_runs, turn_runs=turn_runs),
        event_log=_EventLog(events_by_run),
    )


def test_session_runtime_timeline_attachment_replays_public_projection_frames() -> None:
    task_run_id = "taskrun:turn:session-a:1:abc"
    task_run = SimpleNamespace(
        task_run_id=task_run_id,
        session_id="session-a",
        task_id="task:turn:session-a:1",
        status="completed",
        terminal_reason="completed",
        diagnostics={"turn_id": "turn:session-a:1"},
        created_at=1.0,
        updated_at=3.0,
    )
    runtime_host = _runtime_host(
        task_runs=[task_run],
        events_by_run={
            task_run_id: [
                {
                    "event_id": "event:commit",
                    "event_type": "session_output_commit_ack",
                    "run_id": task_run_id,
                    "offset": 7,
                    "created_at": 3.0,
                    "payload": {
                        "session_id": "session-a",
                        "turn_id": "turn:session-a:1",
                        "task_run_id": task_run_id,
                        "task_id": "task:turn:session-a:1",
                        "state": "committed",
                        "anchor_message_id": "history-message:turn:session-a:1:assistant",
                        "content_sha256": "sha256:final",
                    },
                    "refs": {"turn_ref": "turn:session-a:1", "task_run_ref": task_run_id},
                }
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={
            "messages": [
                {"role": "user", "content": "run", "turn_id": "turn:session-a:1"},
                {"role": "assistant", "content": "done", "turn_id": "turn:session-a:1"},
            ]
        },
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["task_run_id"] == task_run_id
    assert attachment["session_output_commit"]["state"] == "committed"
    assert attachment["session_output_commit"]["commit_event_offset"] == 7
    assert attachment["projection_anchor"]["anchor_turn_id"] == "turn:session-a:1"
    assert attachment["projection_anchor"]["anchor_message_id"] == "history-message:turn:session-a:1:assistant"
    assert attachment["public_projection_frames"]
    assert attachment["public_projection_frames"][0]["event_family"] == "runtime_commit"
    assert "public_timeline" not in attachment
    assert "task_projection" not in attachment
    assert "public_projection_status" not in attachment


def test_turn_runtime_attachment_keeps_projection_anchor_without_legacy_projection_fields() -> None:
    turn_run_id = "turnrun:turn:session-a:2"
    turn_run = SimpleNamespace(
        turn_run_id=turn_run_id,
        session_id="session-a",
        turn_id="turn:session-a:2",
        status="completed",
        terminal_reason="assistant_message",
        created_at=4.0,
        updated_at=5.0,
    )
    runtime_host = _runtime_host(
        task_runs=[],
        turn_runs=[turn_run],
        events_by_run={
            turn_run_id: [
                {
                    "event_id": "event:turn",
                    "event_type": "turn_completed",
                    "run_id": turn_run_id,
                    "offset": 1,
                    "created_at": 5.0,
                    "payload": {"status": "completed"},
                    "refs": {"turn_ref": "turn:session-a:2"},
                }
            ]
        },
    )

    timeline = build_session_runtime_timeline(
        session_id="session-a",
        history={"messages": [{"role": "user", "content": "hi", "turn_id": "turn:session-a:2"}]},
        runtime_host=runtime_host,
    )

    attachment = timeline["runtime_attachments"][0]
    assert attachment["run_id"] == turn_run_id
    assert attachment["trace_available"] is True
    assert attachment["projection_anchor"]["anchor_turn_id"] == "turn:session-a:2"
    assert "public_projection_frames" in attachment
    assert "public_timeline" not in attachment
    assert "task_projection" not in attachment
