from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from bootstrap.app_runtime import app_runtime
from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.models import TurnRun
from runtime.shared.runtime_run_registry import RuntimeRunRegistry
from sessions import SessionManager


async def _fake_resumable_astream(_request):
    yield {"type": "token", "content": "alpha"}
    yield {"type": "token", "content": "beta"}
    yield {"type": "done", "content": "alpha beta"}


async def _fake_scheduled_task_handoff_astream(_request):
    yield {
        "type": "done",
        "content": "任务已进入后台执行。",
        "terminal_reason": "task_executor_scheduled",
    }


def _create_session(client: TestClient, title: str) -> str:
    created = client.post("/api/sessions", json={"title": title})
    assert created.status_code == 200
    return created.json()["id"]


def _create_chat_run(client: TestClient, *, session_id: str, message: str) -> dict:
    response = client.post(
        "/api/chat/runs",
        json={"message": message, "session_id": session_id, "stream": True},
    )
    assert response.status_code == 200
    return response.json()


def _wait_for_run(runtime, stream_run_id: str, predicate, *, timeout_seconds: float = 2):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        current = runtime.harness_runtime.single_agent_runtime_host.run_registry.get_run(stream_run_id)
        if current is not None and predicate(current):
            return current
        time.sleep(0.01)
    return runtime.harness_runtime.single_agent_runtime_host.run_registry.get_run(stream_run_id)


def test_chat_run_event_stream_replays_after_offset_with_sse_ids() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.harness_runtime.astream
        runtime.harness_runtime.astream = _fake_resumable_astream  # type: ignore[method-assign]
        try:
            session_id = _create_session(client, "Resumable stream")
            run = _create_chat_run(client, session_id=session_id, message="hello resumable")
            assert run["stream_run_id"].startswith("strun:")
            assert run["event_log_id"].startswith("chatrun:")

            first_stream = client.get(run["stream_url"])
            assert first_stream.status_code == 200
            assert "id: " in first_stream.text
            assert "retry: 1500" in first_stream.text
            assert "event: token" in first_stream.text
            assert "event: done" in first_stream.text
            assert '"event_offset": 1' in first_stream.text

            replay = client.get(f"{run['stream_url']}?after_offset=1")
            assert replay.status_code == 200
            assert '"event_offset": 1' not in replay.text
            assert "beta" in replay.text
            assert "event: done" in replay.text

            latest = client.get(f"/api/chat/sessions/{session_id}/latest-run?active_only=false")
            assert latest.status_code == 200
            latest_run = latest.json()
            assert latest_run["stream_run_id"] == run["stream_run_id"]
            assert latest_run["status"] == "completed"
            assert latest_run["is_reconnectable"] is False
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_latest_active_chat_run_returns_no_content_when_absent() -> None:
    with TestClient(app) as client:
        session_id = _create_session(client, "No active run")

        latest = client.get(f"/api/chat/sessions/{session_id}/latest-run?active_only=true")

        assert latest.status_code == 204
        assert latest.content == b""


def test_task_handoff_done_is_not_returned_as_active_chat_run() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.harness_runtime.astream
        runtime.harness_runtime.astream = _fake_scheduled_task_handoff_astream  # type: ignore[method-assign]
        try:
            session_id = _create_session(client, "Scheduled task stream closes")
            run = _create_chat_run(client, session_id=session_id, message="启动后台任务")

            stream = client.get(run["stream_url"])
            assert stream.status_code == 200
            assert "event: done" in stream.text
            assert "task_executor_scheduled" in stream.text

            latest_active = client.get(f"/api/chat/sessions/{session_id}/latest-run?active_only=true")
            assert latest_active.status_code == 204

            latest = client.get(f"/api/chat/sessions/{session_id}/latest-run?active_only=false")
            assert latest.status_code == 200
            latest_run = latest.json()
            assert latest_run["stream_run_id"] == run["stream_run_id"]
            assert latest_run["status"] == "completed"
            assert latest_run["terminal_event"] == "done"
            assert latest_run["is_reconnectable"] is False
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_latest_active_chat_run_prefers_primary_stream_over_active_turn_steer() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        host = runtime.harness_runtime.single_agent_runtime_host
        session_id = _create_session(client, "Primary run over steer")
        primary = host.run_registry.create_run(
            session_id=session_id,
            diagnostics={
                "source": "api.chat",
                "expected_active_turn_id": "",
                "active_turn_input_policy": "auto",
            },
        )
        primary = host.run_registry.mark_running(primary)
        host.run_registry.mark_event(primary, latest_event_offset=0, status="running")
        steer = host.run_registry.create_run(
            session_id=session_id,
            diagnostics={
                "source": "api.chat",
                "expected_active_turn_id": "turn:session:latest:1",
                "active_turn_input_policy": "steer",
            },
        )
        steer = host.run_registry.mark_running(steer)
        host.run_registry.mark_event(steer, latest_event_offset=0, status="running")

        latest = client.get(f"/api/chat/sessions/{session_id}/latest-run?active_only=true")

        assert latest.status_code == 200
        assert latest.json()["stream_run_id"] == primary.stream_run_id


def test_latest_active_chat_run_keeps_auto_active_turn_runs_reconnectable() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        host = runtime.harness_runtime.single_agent_runtime_host
        session_id = _create_session(client, "Auto active run remains latest")
        primary = host.run_registry.create_run(
            session_id=session_id,
            diagnostics={
                "source": "api.chat",
                "expected_active_turn_id": "",
                "active_turn_input_policy": "auto",
            },
        )
        primary = host.run_registry.mark_running(primary)
        host.run_registry.mark_event(primary, latest_event_offset=0, status="running")
        auto_followup = host.run_registry.create_run(
            session_id=session_id,
            diagnostics={
                "source": "api.chat",
                "expected_active_turn_id": "turn:session:latest:auto",
                "active_turn_input_policy": "auto",
            },
        )
        auto_followup = host.run_registry.mark_running(auto_followup)
        host.run_registry.mark_event(auto_followup, latest_event_offset=0, status="running")

        latest = client.get(f"/api/chat/sessions/{session_id}/latest-run?active_only=true")

        assert latest.status_code == 200
        assert latest.json()["stream_run_id"] == auto_followup.stream_run_id


def test_chat_run_event_stream_resumes_from_last_event_id_header() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.harness_runtime.astream
        runtime.harness_runtime.astream = _fake_resumable_astream  # type: ignore[method-assign]
        try:
            session_id = _create_session(client, "Last event id resume")
            run = _create_chat_run(client, session_id=session_id, message="hello last event id")

            first_stream = client.get(run["stream_url"])
            assert first_stream.status_code == 200
            last_event_id = f"{run['stream_run_id']}:{run['event_log_id']}:1"

            replay = client.get(run["stream_url"], headers={"Last-Event-ID": last_event_id})
            assert replay.status_code == 200
            assert '"event_offset": 1' not in replay.text
            assert "beta" in replay.text
            assert "event: done" in replay.text
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_chat_run_resume_is_attach_only_and_does_not_reexecute_turn() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.harness_runtime.astream
        calls = {"count": 0}

        async def fake_counting_astream(_request):
            calls["count"] += 1
            yield {"type": "done", "content": "finished once"}

        runtime.harness_runtime.astream = fake_counting_astream  # type: ignore[method-assign]
        try:
            session_id = _create_session(client, "Attach only resume")
            run = _create_chat_run(client, session_id=session_id, message="run once")

            stream = client.get(run["stream_url"])
            assert stream.status_code == 200
            assert "finished once" in stream.text
            assert calls["count"] == 1

            resume = client.post(f"/api/chat/runs/{run['stream_run_id']}/resume")
            assert resume.status_code == 200
            assert resume.json()["resume_mode"] == "attach_existing_run"
            assert calls["count"] == 1
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_disconnected_event_stream_does_not_cancel_background_chat_run() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.harness_runtime.astream
        calls = {"count": 0}
        release = threading.Event()

        async def fake_long_astream(_request):
            calls["count"] += 1
            yield {"type": "token", "content": "started"}
            await asyncio.to_thread(release.wait)
            yield {"type": "done", "content": "finished after disconnect"}

        import asyncio

        runtime.harness_runtime.astream = fake_long_astream  # type: ignore[method-assign]
        try:
            session_id = _create_session(client, "Disconnect keeps running")
            run = _create_chat_run(client, session_id=session_id, message="keep running")
            stream_run_id = run["stream_run_id"]

            current = _wait_for_run(runtime, stream_run_id, lambda item: item.latest_event_offset >= 1)
            assert calls["count"] == 1
            assert current is not None
            assert current.status == "running"
            assert current.latest_event_offset >= 1

            release.set()

            current = _wait_for_run(runtime, stream_run_id, lambda item: item.status == "completed")
            assert current is not None
            assert current.status == "completed"
            assert calls["count"] == 1

            replay = client.get(f"{run['stream_url']}?after_offset=1")
            assert replay.status_code == 200
            assert "finished after disconnect" in replay.text
            assert "event: done" in replay.text
            assert calls["count"] == 1
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_runtime_startup_marks_previous_process_active_chat_runs_orphaned(tmp_path) -> None:
    registry = RuntimeRunRegistry(tmp_path)
    stale = registry.create_run(
        session_id="session:stale",
        owner_process_id=999999,
        owner_instance_id="runtime-instance:previous",
    )
    stale = registry.mark_running(stale)
    registry.mark_event(stale, latest_event_offset=0, status="running")

    host = SingleAgentRuntimeHost(tmp_path)

    recovered = host.run_registry.get_run(stale.stream_run_id)
    assert recovered is not None
    assert recovered.status == "orphaned"
    assert recovered.terminal_event == "error"
    assert recovered.latest_event_offset >= 0
    assert recovered.diagnostics is not None
    assert recovered.diagnostics["reason"] == "runtime_process_restarted"

    events = host.stream_replay.list_public_events_after(recovered, after_offset=-1)
    assert len(events) == 1
    payload = dict(events[0].payload or {})
    assert payload["public_event_type"] == "error"
    data = dict(payload["data"])
    assert data["code"] == "runtime_process_restarted"
    assert "agent 没有收到新的模型轮次" in data["error"]
    assert "系统会根据当前任务状态重新判断下一步" not in data["error"]


def test_runtime_startup_reconciles_orphaned_chat_turn_run_and_visible_boundary(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    runtime_root = tmp_path / "storage" / "runtime_state"
    session_manager = SessionManager(backend_dir)
    session_id = session_manager.create_session(title="Interrupted turn")["id"]
    turn_id = f"turn:{session_id}:1"
    session_manager.append_messages(
        session_id,
        [{"role": "user", "content": "查一下今天 NBA 有没有比赛", "turn_id": turn_id}],
    )
    previous_host = SingleAgentRuntimeHost(
        runtime_root,
        backend_dir=backend_dir,
        session_manager=session_manager,
    )
    stale = previous_host.run_registry.create_run(
        session_id=session_id,
        owner_process_id=previous_host.owner_process_id,
        owner_instance_id=previous_host.instance_id,
    )
    turn_run_id = f"turnrun:{stale.stream_run_id}"
    previous_host.run_registry.update_run(
        stale.stream_run_id,
        diagnostics={"runtime_turn_run_id": turn_run_id},
    )
    stale = previous_host.run_registry.mark_running(stale)
    previous_host.run_registry.mark_event(stale, latest_event_offset=0, status="running")
    previous_host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=turn_id,
            status="running",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={"stream_run_id": stale.stream_run_id},
        )
    )
    previous_host.active_turn_registry.start(
        session_id=session_id,
        turn_id=turn_id,
        turn_run_id=turn_run_id,
        stream_run_id=stale.stream_run_id,
        state="model_turn",
    )

    host = SingleAgentRuntimeHost(
        runtime_root,
        backend_dir=backend_dir,
        session_manager=session_manager,
    )

    recovered = host.run_registry.get_run(stale.stream_run_id)
    assert recovered is not None
    assert recovered.status == "orphaned"
    turn_run = host.state_index.get_turn_run(turn_run_id)
    assert turn_run is not None
    assert turn_run.status == "failed"
    assert turn_run.terminal_reason == "context_unrecoverable"
    assert turn_run.diagnostics["reason"] == "runtime_process_restarted"
    assert turn_run.diagnostics["interrupted_stream_run_id"] == stale.stream_run_id
    terminal_events = [
        event
        for event in host.event_log.list_events(turn_run_id)
        if event.event_type == "agent_turn_terminal"
    ]
    assert len(terminal_events) == 1
    terminal_payload = dict(terminal_events[0].payload or {})
    assert terminal_payload["failure_code"] == "runtime_process_restarted"
    assert terminal_payload["terminal_reason"] == "context_unrecoverable"
    assert host.active_turn_registry.snapshot(session_id) is None
    history = session_manager.load_session_record(session_id)
    assistant_messages = [
        item
        for item in history["messages"]
        if item.get("role") == "assistant" and item.get("turn_id") == turn_id
    ]
    assert len(assistant_messages) == 1
    assert "工具结果没有交回模型完成收口" in assistant_messages[0]["content"]
    assert assistant_messages[0]["answer_source"] == "harness.runtime.stream_failure_reconciliation"
    api_history = session_manager.load_session_for_api(session_id)
    assert [item["role"] for item in api_history] == ["user", "assistant"]


def test_stream_failure_reconciliation_closes_existing_api_transcript(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    runtime_root = tmp_path / "storage" / "runtime_state"
    session_manager = SessionManager(backend_dir)
    session_id = session_manager.create_session(title="Protocol close")["id"]
    turn_id = f"turn:{session_id}:1"
    session_manager.append_messages(
        session_id,
        [{"role": "user", "content": "查一下赛程", "turn_id": turn_id}],
    )
    session_manager.append_api_messages(
        session_id,
        [
            {"role": "user", "content": "查一下赛程", "turn_id": turn_id},
            {
                "role": "assistant",
                "content": "",
                "turn_id": turn_id,
                "tool_calls": [{"id": "call_1", "name": "fetch_url", "args": {}, "type": "tool_call"}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "HTTP 406", "turn_id": turn_id},
        ],
    )
    host = SingleAgentRuntimeHost(
        runtime_root,
        backend_dir=backend_dir,
        session_manager=session_manager,
    )
    run = host.run_registry.create_run(session_id=session_id)
    turn_run_id = f"turnrun:{run.stream_run_id}"
    run = host.run_registry.update_run(
        run.stream_run_id,
        diagnostics={"runtime_turn_run_id": turn_run_id},
    )
    host.state_index.upsert_turn_run(
        TurnRun(
            turn_run_id=turn_run_id,
            session_id=session_id,
            turn_id=turn_id,
            status="running",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={"stream_run_id": run.stream_run_id},
        )
    )

    result = host.close_chat_turn_run_for_stream_failure(
        run,
        code="stream_exception",
        reason="boom",
    )

    assert result["turn_run_closed"] is True
    api_history = session_manager.load_session_for_api(session_id)
    assert [item["role"] for item in api_history] == ["user", "assistant", "tool", "assistant"]
    assert api_history[-1]["turn_id"] == turn_id
    assert "异常中断" in api_history[-1]["content"]
    public_assistant = [
        item
        for item in session_manager.load_session_record(session_id)["messages"]
        if item.get("role") == "assistant"
    ]
    assert len(public_assistant) == 1
    assert public_assistant[0]["answer_source"] == "harness.runtime.stream_failure_reconciliation"


def test_runtime_startup_repairs_previously_orphaned_chat_turn_run(tmp_path) -> None:
    runtime_root = tmp_path / "runtime_state"
    registry = RuntimeRunRegistry(runtime_root)
    cases = [
        ("runtime_process_restarted", {"reason": "runtime_process_restarted"}),
        ("stream_cancelled", {"reason": "stream_cancelled", "cancelled": True}),
    ]
    turn_run_ids: list[tuple[str, str]] = []
    for index, (failure_code, diagnostics) in enumerate(cases, start=1):
        stale = registry.create_run(
            session_id=f"session:already-orphaned:{index}",
            owner_process_id=999999,
            owner_instance_id="runtime-instance:previous",
        )
        turn_run_id = f"turnrun:{stale.stream_run_id}"
        registry.update_run(
            stale.stream_run_id,
            diagnostics={
                "runtime_turn_run_id": turn_run_id,
                **diagnostics,
            },
        )
        stale = registry.mark_running(stale)
        registry.mark_event(stale, latest_event_offset=0, status="orphaned", terminal_event="error")
        RuntimeStateIndex(runtime_root).upsert_turn_run(
            TurnRun(
                turn_run_id=turn_run_id,
                session_id=f"session:already-orphaned:{index}",
                turn_id=f"turn:session:already-orphaned:{index}",
                status="running",
                created_at=time.time(),
                updated_at=time.time(),
                diagnostics={"stream_run_id": stale.stream_run_id},
            )
        )
        turn_run_ids.append((turn_run_id, failure_code))

    host = SingleAgentRuntimeHost(runtime_root)

    for turn_run_id, failure_code in turn_run_ids:
        turn_run = host.state_index.get_turn_run(turn_run_id)
        assert turn_run is not None
        assert turn_run.status == "failed"
        assert turn_run.diagnostics["reason"] == failure_code


def test_runtime_startup_uses_instance_owner_not_only_process_id_for_recovery(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    current = host.run_registry.create_run(
        session_id="session:current",
        owner_process_id=host.owner_process_id,
        owner_instance_id=host.instance_id,
    )
    current = host.run_registry.mark_running(current)
    host.run_registry.mark_event(current, latest_event_offset=0, status="running")

    same_process_new_instance_host = SingleAgentRuntimeHost(tmp_path)

    recovered = same_process_new_instance_host.run_registry.get_run(current.stream_run_id)
    assert recovered is not None
    assert recovered.status == "orphaned"

