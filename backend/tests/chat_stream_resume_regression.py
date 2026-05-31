from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from bootstrap.app_runtime import app_runtime


async def _fake_resumable_astream(_request):
    yield {"type": "token", "content": "alpha"}
    yield {"type": "token", "content": "beta"}
    yield {"type": "done", "content": "alpha beta"}


def test_chat_run_event_stream_replays_after_offset_with_sse_ids() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.query_runtime.astream
        runtime.query_runtime.astream = _fake_resumable_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Resumable stream"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            run_response = client.post(
                "/api/chat/runs",
                json={"message": "hello resumable", "session_id": session_id, "stream": True},
            )
            assert run_response.status_code == 200
            run = run_response.json()
            assert run["stream_run_id"].startswith("strun:")
            assert run["task_run_id"].startswith("chatrun:")

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
            assert latest_run["is_reconnectable"] is True
        finally:
            runtime.query_runtime.astream = original_astream  # type: ignore[method-assign]


def test_chat_run_event_stream_resumes_from_last_event_id_header() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.query_runtime.astream
        runtime.query_runtime.astream = _fake_resumable_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Last event id resume"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            run_response = client.post(
                "/api/chat/runs",
                json={"message": "hello last event id", "session_id": session_id, "stream": True},
            )
            assert run_response.status_code == 200
            run = run_response.json()

            first_stream = client.get(run["stream_url"])
            assert first_stream.status_code == 200
            last_event_id = f"{run['stream_run_id']}:{run['task_run_id']}:1"

            replay = client.get(run["stream_url"], headers={"Last-Event-ID": last_event_id})
            assert replay.status_code == 200
            assert '"event_offset": 1' not in replay.text
            assert "beta" in replay.text
            assert "event: done" in replay.text
        finally:
            runtime.query_runtime.astream = original_astream  # type: ignore[method-assign]


def test_legacy_chat_stream_is_wrapped_by_resumable_run_stream() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.query_runtime.astream
        runtime.query_runtime.astream = _fake_resumable_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Legacy wrapper"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat",
                json={"message": "hello wrapper", "session_id": session_id, "stream": True},
            )

            assert response.status_code == 200
            assert "id: " in response.text
            assert "event: token" in response.text
            assert "event: done" in response.text
            assert '"stream_run_id": "strun:' in response.text
        finally:
            runtime.query_runtime.astream = original_astream  # type: ignore[method-assign]


def test_non_stream_chat_collects_terminal_event_from_run_stream() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.query_runtime.astream
        runtime.query_runtime.astream = _fake_resumable_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Non stream wrapper"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat",
                json={"message": "hello non stream", "session_id": session_id, "stream": False},
            )

            assert response.status_code == 200
            assert response.json() == {"content": "alpha beta"}
        finally:
            runtime.query_runtime.astream = original_astream  # type: ignore[method-assign]
