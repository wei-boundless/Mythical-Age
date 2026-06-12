from __future__ import annotations

import json

from app import app
from api.runtime_logs import (
    _resolve_runtime_log_after_offset,
    _runtime_log_events_after,
    _runtime_log_snapshot_sse,
)
from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from runtime.shared.models import TaskRun, TurnRun


def test_runtime_log_routes_are_registered() -> None:
    paths = {str(getattr(route, "path", "") or "") for route in app.routes}

    assert "/api/runtime/logs/task-runs/{task_run_id}/events" in paths
    assert "/api/runtime/logs/turn-runs/{turn_run_id}/events" in paths


def test_task_run_log_snapshot_is_scoped_and_redacted(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    task_run_id = "taskrun:log:a"
    other_task_run_id = "taskrun:log:b"
    host.state_index.upsert_task_run(
        TaskRun(task_run_id=task_run_id, session_id="session:log", task_id="task:a", created_at=1, updated_at=1)
    )
    host.state_index.upsert_task_run(
        TaskRun(task_run_id=other_task_run_id, session_id="session:log", task_id="task:b", created_at=1, updated_at=1)
    )
    host.event_log.append(
        task_run_id,
        "step_summary_recorded",  # type: ignore[arg-type]
        payload={
            "summary": "visible diagnostic summary",
            "messages": ["must not leak"],
            "packet": {"model_messages": ["must not leak either"]},
        },
    )
    host.event_log.append(
        other_task_run_id,
        "step_summary_recorded",  # type: ignore[arg-type]
        payload={"summary": "other run"},
    )

    events = _runtime_log_events_after(
        host,
        task_run_id,
        after_offset=-1,
        limit=20,
        include_payloads=True,
    )
    payload = _sse_json(
        _runtime_log_snapshot_sse(
            scope="task_run",
            run_id=task_run_id,
            events=events,
            latest_offset=max(event.offset for event in events),
            include_model_messages=False,
        )
    )

    assert payload["scope"] == "task_run"
    assert payload["run_id"] == task_run_id
    assert payload["returned"] == 1
    assert payload["events"][0]["run_id"] == task_run_id
    assert payload["events"][0]["payload"]["summary"] == "visible diagnostic summary"
    assert payload["events"][0]["payload"]["messages"] == "[redacted]"
    assert payload["events"][0]["payload"]["packet"]["model_messages"] == "[redacted]"
    assert other_task_run_id not in str(payload)


def test_turn_run_log_cursor_is_scoped(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    turn_run_id = "turnrun:turn:log:1"
    host.state_index.upsert_turn_run(
        TurnRun(turn_run_id=turn_run_id, session_id="session:log", turn_id="turn:log:1", created_at=1, updated_at=1)
    )
    host.event_log.append(
        turn_run_id,
        "agent_turn_received",  # type: ignore[arg-type]
        payload={"messages": ["hidden"]},
    )

    events = _runtime_log_events_after(
        host,
        turn_run_id,
        after_offset=-1,
        limit=20,
        include_payloads=False,
    )

    assert [event.run_id for event in events] == [turn_run_id]
    assert _resolve_runtime_log_after_offset(
        "turn_run",
        turn_run_id,
        after_offset=None,
        last_event_id=f"runtime-log:turn_run:{turn_run_id}:7",
    ) == 7
    assert _resolve_runtime_log_after_offset(
        "task_run",
        turn_run_id,
        after_offset=None,
        last_event_id=f"runtime-log:turn_run:{turn_run_id}:7",
    ) == -1


def _sse_json(block: str) -> dict:
    data_lines = [
        line.removeprefix("data: ")
        for line in block.splitlines()
        if line.startswith("data: ")
    ]
    return json.loads("\n".join(data_lines))
