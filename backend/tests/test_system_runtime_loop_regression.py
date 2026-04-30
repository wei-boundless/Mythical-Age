from __future__ import annotations

from test_system.assertions import evaluate_turn_assertions
from test_system.runtime_loop_probe import runtime_events_from_turn_payload, runtime_loop_summary_from_turn_payload


def _runtime_event(event_type: str, *, payload=None, payload_summary=None, offset=1):
    return {
        "event": "runtime_loop_event",
        "data": {
            "event": {
                "event_id": f"evt:{event_type}:{offset}",
                "task_run_id": "taskrun:test",
                "event_type": event_type,
                "offset": offset,
                "created_at": 1.0,
                "payload": dict(payload or {}),
                "payload_summary": dict(payload_summary or {}),
                "refs": {},
            }
        },
        "ts_ms": float(offset),
    }


def test_runtime_loop_probe_extracts_orchestration_monitor_summary() -> None:
    payload = {
        "events": [
            _runtime_event("task_run_started", offset=1),
            _runtime_event(
                "operation_gate_checked",
                payload_summary={"operation_id": "op.shell", "allowed": True, "reason": "ok"},
                offset=2,
            ),
            _runtime_event(
                "tool_call_requested",
                payload_summary={"tool_name": "terminal", "request_id": "req1"},
                offset=3,
            ),
            _runtime_event("tool_result_received", offset=4),
            _runtime_event(
                "loop_terminal",
                payload_summary={"status": "completed", "terminal_reason": "completed"},
                offset=5,
            ),
        ]
    }

    events = runtime_events_from_turn_payload(payload)
    summary = runtime_loop_summary_from_turn_payload(payload)

    assert [event["event_type"] for event in events] == [
        "task_run_started",
        "operation_gate_checked",
        "tool_call_requested",
        "tool_result_received",
        "loop_terminal",
    ]
    assert summary["status"] == "completed"
    assert summary["operation_gate"]["allowed_count"] == 1
    assert summary["tools"]["requested"] == ["terminal"]
    assert summary["tools"]["pairing_ok"] is True


def test_runtime_loop_assertions_cover_new_loop_contract() -> None:
    payload = {
        "turn": {"checks": ["response.nonempty"]},
        "result": {"response_text": "done"},
        "events": [
            _runtime_event(
                "tool_call_requested",
                payload_summary={"tool_name": "python_repl"},
                offset=1,
            ),
            _runtime_event("tool_result_received", offset=2),
            _runtime_event(
                "loop_terminal",
                payload_summary={"status": "completed", "terminal_reason": "completed"},
                offset=3,
            ),
        ],
    }

    results = evaluate_turn_assertions(
        payload,
        [
            "response.nonempty",
            "loop.event=tool_result_received",
            "loop.tool=python_repl",
            "tool.pairing_ok",
            "loop.completed",
        ],
    )

    assert all(result.passed for result in results)


def test_runtime_loop_monitor_covers_denied_gate_commit_and_memory_state() -> None:
    payload = {
        "runtime_loop_events": [
            {
                "event_type": "operation_gate_checked",
                "task_run_id": "taskrun:deny",
                "offset": 1,
                "payload_summary": {"operation_id": "op.shell", "allowed": False, "reason": "policy-deny"},
            },
            {
                "event_type": "commit_gate_checked",
                "task_run_id": "taskrun:deny",
                "offset": 2,
                "payload_summary": {"allowed": True},
            },
            {
                "event_type": "loop_terminal",
                "task_run_id": "taskrun:deny",
                "offset": 3,
                "payload_summary": {"status": "blocked", "terminal_reason": "operation_denied"},
            },
        ],
        "latest_checkpoint": {},
    }

    summary = runtime_loop_summary_from_turn_payload(payload)

    assert summary["status"] == "blocked"
    assert summary["terminal_reason"] == "operation_denied"
    assert summary["operation_gate"]["denied_count"] == 1
    assert summary["tools"]["pairing_ok"] is True


def test_runtime_loop_assertions_cover_commit_and_memory_writeback() -> None:
    payload = {
        "runtime_loop_events": [
            {
                "event_type": "checkpoint_written",
                "task_run_id": "taskrun:commit",
                "offset": 1,
                "payload": {
                    "checkpoint_id": "checkpoint-1",
                    "event_offset": 1,
                    "loop_state": {
                        "commit_state": {
                            "assistant_session_write_allowed": True,
                            "assistant_session_write_applied": True,
                            "memory_write_allowed": True,
                            "session_memory_refresh_applied": True,
                            "durable_memory_commit_applied": True,
                            "task_result_final": True,
                            "session_memory_chars": 42,
                            "durable_saved_count": 1,
                        }
                    },
                },
            },
            {
                "event_type": "loop_terminal",
                "task_run_id": "taskrun:commit",
                "offset": 2,
                "payload_summary": {"status": "completed", "terminal_reason": "completed"},
            },
        ],
        "result": {"response_text": "committed"},
    }

    results = evaluate_turn_assertions(
        payload,
        [
            "loop.completed",
            "commit.assistant_session=true",
            "memory.session_refresh=true",
            "memory.durable_commit=true",
        ],
    )

    assert all(result.passed for result in results)
