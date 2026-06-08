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
from runtime.shared.runtime_run_registry import RuntimeRunRegistry


async def _fake_resumable_astream(_request):
    yield {"type": "token", "content": "alpha"}
    yield {"type": "token", "content": "beta"}
    yield {"type": "done", "content": "alpha beta"}


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

