from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from bootstrap.app_runtime import app_runtime


async def _fake_astream(_request):
    yield {"type": "token", "content": "smoke"}
    yield {"type": "done", "content": "smoke result"}


async def _fake_error_astream(_request):
    yield {
        "type": "error",
        "error": "model unavailable",
        "code": "provider_unavailable",
    }


def test_api_smoke_flow() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()

        original_astream = runtime.query_runtime.astream
        original_prompt = runtime.query_runtime.build_system_prompt_for_session
        runtime.query_runtime.astream = _fake_astream  # type: ignore[method-assign]
        runtime.query_runtime.build_system_prompt_for_session = lambda *_args, **_kwargs: "system prompt"  # type: ignore[method-assign]
        try:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            rag_mode = client.get("/api/config/rag-mode")
            assert rag_mode.status_code == 200
            assert "enabled" in rag_mode.json()

            created = client.post("/api/sessions", json={"title": "Smoke"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            tokens = client.get(f"/api/tokens/session/{session_id}")
            assert tokens.status_code == 200
            assert "total_tokens" in tokens.json()

            response = client.post(
                "/api/chat",
                json={"message": "hello smoke", "session_id": session_id, "stream": True},
            )
            assert response.status_code == 200
            assert "event: token" in response.text
            assert "event: done" in response.text
        finally:
            runtime.query_runtime.astream = original_astream  # type: ignore[method-assign]
            runtime.query_runtime.build_system_prompt_for_session = original_prompt  # type: ignore[method-assign]


def test_non_stream_chat_returns_error_status() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()

        original_astream = runtime.query_runtime.astream
        runtime.query_runtime.astream = _fake_error_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Error smoke"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat",
                json={"message": "hello error", "session_id": session_id, "stream": False},
            )
            assert response.status_code == 503
            assert response.json() == {
                "error": "model unavailable",
                "code": "provider_unavailable",
            }
        finally:
            runtime.query_runtime.astream = original_astream  # type: ignore[method-assign]


def test_chat_rejects_invalid_session_id_before_streaming() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "hello", "session_id": "../outside", "stream": True},
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid session_id"}


def test_legacy_agent_control_plane_routes_are_removed() -> None:
    with TestClient(app) as client:
        response = client.get("/api/agents/catalog")
        assert response.status_code == 404
