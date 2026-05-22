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


async def _fake_image_generate(self, **kwargs):
    return {
        "asset_path": "/souls/generated/chat-turn.png",
        "file_path": "D:/tmp/chat-turn.png",
        "reused": False,
        "bytes": 1234,
        "revised_prompt": "revised prompt",
    }


def test_chat_accepts_per_turn_model_selection() -> None:
    captured: dict[str, object] = {}

    async def fake_astream(request):
        captured["model_selection"] = dict(request.model_selection)
        yield {"type": "done", "content": "ok"}

    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.query_runtime.astream
        runtime.query_runtime.astream = fake_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Model selection"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat",
                json={
                    "message": "hello selected model",
                    "session_id": session_id,
                    "stream": False,
                    "model_selection": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-flash",
                        "credential_ref": "provider:deepseek:primary",
                    },
                },
            )

            assert response.status_code == 200
            assert captured["model_selection"] == {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "credential_ref": "provider:deepseek:primary",
            }
        finally:
            runtime.query_runtime.astream = original_astream  # type: ignore[method-assign]


def test_chat_routes_gpt_image_2_to_image_generation() -> None:
    with TestClient(app) as client:
        original_generate = None
        from soul.image_asset_service import SoulImageAssetService

        original_generate = SoulImageAssetService.generate
        SoulImageAssetService.generate = _fake_image_generate  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Image generation"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat",
                json={
                    "message": "a blue glass mountain at sunset",
                    "session_id": session_id,
                    "stream": False,
                    "model_selection": {
                        "provider": "openai",
                        "model": "gpt-image-2",
                    },
                    "image_generation": {
                        "mode": "generate",
                        "selection_id": "openai::gpt-image-2",
                        "provider": "openai",
                        "model": "gpt-image-2",
                        "asset_kind": "chat",
                    },
                },
            )

            assert response.status_code == 200
            assert response.json()["content"] == "已生成图像。"
            assert response.json()["image"] == {
                "src": "/souls/generated/chat-turn.png",
                "alt": "a blue glass mountain at sunset",
                "caption": "revised prompt",
            }
        finally:
            SoulImageAssetService.generate = original_generate  # type: ignore[method-assign]


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


def test_session_messages_can_be_truncated_for_edit_resend() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        created = client.post("/api/sessions", json={"title": "Edit resend"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        runtime.session_manager.append_messages(
            session_id,
            [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "follow up"},
            ],
        )

        response = client.post(
            f"/api/sessions/{session_id}/messages/truncate",
            json={"message_index": 0},
        )
        assert response.status_code == 200
        assert response.json()["messages"] == []


def test_removed_agent_control_plane_routes_stay_absent() -> None:
    with TestClient(app) as client:
        response = client.get("/api/agents/catalog")
        assert response.status_code == 404
