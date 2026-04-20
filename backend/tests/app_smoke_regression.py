from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from runtime.app_runtime import app_runtime


async def _fake_astream(_request):
    yield {"type": "token", "content": "smoke"}
    yield {"type": "done", "content": "smoke result"}


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
