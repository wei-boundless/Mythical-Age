from __future__ import annotations

from pathlib import Path

from harness.runtime import SingleAgentRuntimeHost
from runtime.shared.models import TurnRun
from sessions import SessionManager


def test_stream_failure_reconciliation_projects_terminal_without_assistant_boundary(tmp_path: Path) -> None:
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

    result = host.close_chat_turn_run_for_stream_failure(
        run,
        code="runtime_process_restarted",
        reason="background_executor_missing_after_restart",
        orphaned_by="test",
    )

    history = manager.get_history(session_id)["messages"]
    current = host.run_registry.get_run(run.stream_run_id)
    reconciled_turn = host.state_index.get_turn_run(turn_run_id)
    public_events = host.stream_replay.list_public_events_after(current or run, after_offset=-1)
    terminal_events = [
        event
        for event in public_events
        if str((event.payload or {}).get("public_event_type") or "") == "turn_completed"
    ]

    assert result["public_terminal_event_appended"] is True
    assert "visible_message_appended" not in result
    assert [item["role"] for item in history] == ["user"]
    assert [item["content"] for item in history] == ["继续修复"]
    assert current is not None
    assert current.status == "stopped"
    assert current.terminal_event == "turn_completed"
    assert reconciled_turn is not None
    assert reconciled_turn.status == "aborted"
    assert reconciled_turn.terminal_reason == "internal_error"
    assert len(terminal_events) == 1
    data = dict(terminal_events[0].payload["data"])
    frame = dict(data.get("public_projection_frame") or {})
    assert data["status"] == "stopped"
    assert data["terminal_reason"] == "runtime_process_restarted"
    assert frame["op"] == "turn_terminal"
    assert frame["source_event_type"] == "turn_completed"
    assert frame["anchor"]["session_id"] == session_id
    assert frame["anchor"]["turn_id"] == turn_id
    assert frame["anchor"]["turn_run_id"] == turn_run_id
