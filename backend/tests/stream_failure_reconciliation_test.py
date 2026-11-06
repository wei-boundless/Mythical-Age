from __future__ import annotations

from pathlib import Path

from harness.runtime import SingleAgentRuntimeHost
from runtime.shared.models import TurnRun
from sessions import SessionManager


def test_runtime_interruption_closes_turn_with_memory_package(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    runtime_root = tmp_path / "runtime"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="Recover stream")["id"]
    turn_id = f"turn:{session_id}:1"
    turn_run_id = f"turnrun:{session_id}:1"
    manager.append_messages(session_id, [{"role": "user", "content": "继续修复", "turn_id": turn_id}])
    host = SingleAgentRuntimeHost(runtime_root, backend_dir=backend_dir, session_manager=manager)
    run = host.run_registry.create_run(
        session_id=session_id,
        diagnostics={"turn_run_id": turn_run_id},
        owner_process_id=host.owner_process_id,
        owner_instance_id=host.instance_id,
    )
    host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=turn_id,
            status="running",
            created_at=1,
            updated_at=2,
        )
    )

    result = host.record_chat_turn_run_runtime_interruption(
        run,
        code="runtime_process_restarted",
        reason="runtime_cell_missing_after_restart",
        orphaned_by="test",
    )

    history = manager.get_history(session_id)["messages"]
    current = host.run_registry.get_run(run.stream_run_id)
    reconciled_turn = host.state_index.get_turn_run(turn_run_id)
    public_events = host.stream_replay.list_public_events_after(current or run, after_offset=-1)
    replay_response = host.stream_replay.public_replay_response(
        current or run,
        after_offset=int(getattr(current or run, "latest_event_offset", -1) or -1),
        limit=500,
    )
    terminal_events = [
        event
        for event in public_events
        if str((event.payload or {}).get("public_event_type") or "") == "turn_completed"
    ]

    turn_events = host.event_log.list_events(turn_run_id)
    interruption_event = turn_events[-1]
    interruption_payload = dict(interruption_event.payload or {})
    turn_memory = host.turn_memory_store.get_turn(session_id, turn_id)

    assert result["runtime_interruption_recorded"] is True
    assert result["public_terminal_event_appended"] is False
    assert result["turn_run_closed"] is True
    assert result["turn_run_interruption_recorded"] is True
    assert result["turn_runtime_interruption_event_recorded"] is True
    assert "visible_message_appended" not in result
    assert [item["role"] for item in history] == ["user"]
    assert [item["content"] for item in history] == ["继续修复"]
    assert current is not None
    assert current.status == "orphaned"
    assert current.terminal_event == ""
    assert replay_response["terminal"] is True
    assert dict(current.diagnostics or {})["recoverable"] is True
    assert dict(current.diagnostics or {})["agent_decision_terminal"] is False
    assert dict(current.diagnostics or {})["runtime_interruption_code"] == "runtime_process_restarted"
    assert reconciled_turn is not None
    assert reconciled_turn.status == "interrupted"
    assert reconciled_turn.terminal_reason == "runtime_interruption_closed"
    assert dict(reconciled_turn.diagnostics or {})["recoverable"] is True
    assert dict(reconciled_turn.diagnostics or {})["agent_decision_terminal"] is False
    assert dict(reconciled_turn.diagnostics or {})["runtime_interruption_code"] == "runtime_process_restarted"
    assert dict(reconciled_turn.diagnostics or {})["interrupted_turn_closed"] is True
    assert dict(reconciled_turn.diagnostics or {})["interrupted_turn_memory_package_ready"] is True
    assert dict(reconciled_turn.diagnostics or {})["terminal_status"] == "interrupted"
    assert dict(reconciled_turn.diagnostics or {})["turn_lifecycle_closed_by"] == "runtime_interruption"
    assert turn_memory is not None
    assert turn_memory.status == "terminal"
    assert turn_memory.phase == "terminal"
    assert turn_memory.handoff_state == "interrupted_turn_memory_package"
    assert turn_memory.recovery_state == "runtime_process_restarted"
    assert dict(turn_memory.pending_commit_summary or {})["turn_lifecycle_closed_by"] == "runtime_interruption"
    assert not terminal_events
    assert [event.event_type for event in turn_events] == ["turn_runtime_interruption_recorded"]
    assert interruption_payload["interruption_closure"]["state"] == "interrupted_turn_closed"
    assert interruption_payload["interruption_closure"]["memory_package_ready"] is True
    assert interruption_payload["interruption_closure"]["system_authored_terminal"] is False


def test_runtime_interruption_advances_turn_run_cursor_while_closing_lifecycle(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    runtime_root = tmp_path / "runtime"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="Recover stream cursor")["id"]
    turn_id = f"turn:{session_id}:1"
    turn_run_id = f"turnrun:{session_id}:1"
    host = SingleAgentRuntimeHost(runtime_root, backend_dir=backend_dir, session_manager=manager)
    run = host.run_registry.create_run(
        session_id=session_id,
        diagnostics={"turn_run_id": turn_run_id},
        owner_process_id=host.owner_process_id,
        owner_instance_id=host.instance_id,
    )
    host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=turn_id,
            status="running",
            created_at=1,
            updated_at=2,
            latest_event_offset=-1,
        )
    )
    observed = host.event_log.append(
        turn_run_id,
        "turn_tool_observation_recorded",
        payload={"turn_id": turn_id, "tool_observation": {"tool_name": "read_file", "status": "ok"}},
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run_id},
    )

    result = host.record_chat_turn_run_runtime_interruption(
        run,
        code="runtime_process_restarted",
        reason="runtime_cell_missing_after_restart",
        orphaned_by="test",
    )

    current = host.run_registry.get_run(run.stream_run_id)
    reconciled_turn = host.state_index.get_turn_run(turn_run_id)
    turn_events = host.event_log.list_events(turn_run_id)
    interruption_event = turn_events[-1]

    assert result["runtime_interruption_recorded"] is True
    assert result["public_terminal_event_appended"] is False
    assert result["turn_run_closed"] is True
    assert result["turn_runtime_interruption_event_recorded"] is True
    assert current is not None
    assert current.status == "orphaned"
    assert current.terminal_event == ""
    assert reconciled_turn is not None
    assert reconciled_turn.status == "interrupted"
    assert reconciled_turn.terminal_reason == "runtime_interruption_closed"
    assert reconciled_turn.latest_event_offset == interruption_event.offset
    assert interruption_event.offset > observed.offset
    assert [event.event_type for event in turn_events] == [
        "turn_tool_observation_recorded",
        "turn_runtime_interruption_recorded",
    ]
