from __future__ import annotations

import base64
import json
import sys
import threading
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from bootstrap.app_runtime import app_runtime
from tests.support.app_client import isolated_app_client


async def _fake_astream(_request):
    yield {
        "type": "single_agent_turn_started",
        "turn_run_id": "turnrun:turn:smoke",
        "active_turn_id": "turn:smoke",
        "turn_id": "turn:smoke",
    }
    yield {
        "type": "assistant_text_delta",
        "turn_run_id": "turnrun:turn:smoke",
        "active_turn_id": "turn:smoke",
        "stream_ref": "stream:smoke",
        "message_ref": "message:smoke",
        "sequence": 1,
        "content": "smoke",
    }
    yield {
        "type": "assistant_text_final",
        "turn_run_id": "turnrun:turn:smoke",
        "active_turn_id": "turn:smoke",
        "stream_ref": "stream:smoke",
        "message_ref": "message:smoke",
        "sequence": 2,
        "content": "smoke result",
    }
    yield {"type": "done", "content": "smoke result"}


async def _fake_missing_terminal_astream(_request):
    yield {"type": "input_commit_gate", "commit_gate": {"allowed": True}}
    yield {"type": "task_intent_decision", "decision": {"status": "ok"}}


async def _fake_image_generate(self, **kwargs):
    target_id = str(kwargs.get("target_id") or "chat-turn").replace(":", "-")
    filename = f"chat-{target_id}.png"
    output_path = self.asset_dir / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(_ONE_PIXEL_PNG_BASE64))
    response = self._asset_response(output_path, filename, reused=False)
    response["revised_prompt"] = "revised prompt"
    return response


_ONE_PIXEL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/"
    "l6S9WQAAAABJRU5ErkJggg=="
)


def _replay_payload(client, replay_url: str, *, wait_for_terminal: bool = True) -> dict:
    payload: dict = {}
    for _attempt in range(100):
        replay = client.get(replay_url)
        assert replay.status_code == 200
        payload = replay.json()
        if not wait_for_terminal or payload.get("terminal") is True:
            return payload
        time.sleep(0.02)
    return payload


def _replay_event_types(payload: dict) -> list[str]:
    return [str(event.get("public_event_type") or "") for event in list(payload.get("events") or []) if isinstance(event, dict)]


def _run_payload_until_status(client, stream_run_id: str, status: str) -> dict:
    payload: dict = {}
    for _attempt in range(100):
        response = client.get(f"/api/chat/runs/{stream_run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload.get("status") == status:
            return payload
        time.sleep(0.02)
    return payload


def test_chat_accepts_per_turn_model_selection() -> None:
    captured: dict[str, object] = {}

    async def fake_astream(request):
        captured["model_selection"] = dict(request.model_selection)
        yield {"type": "done", "content": "ok"}

    with isolated_app_client(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.harness_runtime.astream
        runtime.harness_runtime.astream = fake_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Model selection"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat/runs",
                json={
                    "message": "hello selected model",
                    "session_id": session_id,
                    "model_selection": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-flash",
                        "credential_ref": "provider:deepseek:primary",
                    },
                },
            )

            assert response.status_code == 200
            replay = _replay_payload(client, response.json()["replay_url"])
            assert "turn_completed" in _replay_event_types(replay)
            assert captured["model_selection"] == {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "credential_ref": "provider:deepseek:primary",
            }
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_chat_run_creation_defers_auto_compaction_past_api_boundary(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_astream(request):
        captured["runtime_profile"] = dict(request.runtime_profile)
        yield {"type": "done", "content": "ok"}

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("POST /chat/runs must not run auto compaction on the API event loop")

    monkeypatch.setattr(
        "harness.entrypoint.runtime_facade.auto_compact_session_if_needed",
        fail_if_called,
    )

    with isolated_app_client(app) as client:
        runtime = app_runtime.require_ready()
        original_astream = runtime.harness_runtime.astream
        runtime.harness_runtime.astream = fake_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Deferred compaction"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat/runs",
                json={
                    "message": "continue after reconnect",
                    "session_id": session_id,
                    "client_message_id": "user:deferred-compaction-api",
                },
            )

            assert response.status_code == 200
            run_payload = response.json()
            stream_run_id = run_payload["stream_run_id"]
            assert stream_run_id
            replay = _replay_payload(client, run_payload["replay_url"])
            assert "turn_completed" in _replay_event_types(replay)
            assert captured["runtime_profile"]["precommitted_user_message_defer_auto_compaction"] is True
            supervisor = runtime.harness_runtime.single_agent_runtime_host.agent_run_supervisor
            for _attempt in range(100):
                if supervisor.active_cell_for_stream_run(stream_run_id, session_id=session_id) is None:
                    break
                time.sleep(0.02)
            assert supervisor.active_cell_for_stream_run(stream_run_id, session_id=session_id) is None
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_chat_routes_gpt_image_2_to_image_generation() -> None:
    with isolated_app_client(app) as client:
        original_generate = None
        from capability_system.capabilities.image_generation.image_asset_service import ImageAssetService

        original_generate = ImageAssetService.generate
        ImageAssetService.generate = _fake_image_generate  # type: ignore[method-assign]
        session_id = ""
        generated_path: Path | None = None
        try:
            created = client.post("/api/sessions", json={"title": "Image generation"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat/runs",
                json={
                    "message": "a blue glass mountain at sunset",
                    "session_id": session_id,
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
            replay = _replay_payload(client, response.json()["replay_url"])
            assert "turn_completed" in _replay_event_types(replay)
            history = client.get(f"/api/sessions/{session_id}/history")
            assert history.status_code == 200
            image = history.json()["messages"][-1]["image"]
            generated_path = Path(client.isolated_storage_root) / "generated" / "images" / Path(image["src"]).name
            assert image["src"].startswith(f"/api/image-assets/files/chat-turn-{session_id}-")
            assert image["src"].endswith(".png")
            assert generated_path.exists()
            image_file = client.get(image["src"])
            assert image_file.status_code == 200
            assert image_file.headers["content-type"].startswith("image/png")
            assert image == {
                "src": image["src"],
                "alt": "a blue glass mountain at sunset",
                "caption": "revised prompt",
            }
        finally:
            ImageAssetService.generate = original_generate  # type: ignore[method-assign]
            if generated_path is not None and generated_path.exists():
                generated_path.unlink()
            if session_id:
                client.delete(f"/api/sessions/{session_id}")


def test_delete_session_queues_runtime_cleanup_and_removes_session_immediately() -> None:
    with isolated_app_client(app) as client:
        created = client.post("/api/sessions", json={"title": "Delete quickly"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        response = client.delete(f"/api/sessions/{session_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["cleanup"]["mode"] == "queued_runtime_cleanup"
        assert payload["cleanup"]["queued"] is True
        assert payload["cleanup"]["session_deletion_tombstone"]["recorded"] is True
        sessions = client.get("/api/sessions")
        assert sessions.status_code == 200
        assert session_id not in {item["id"] for item in sessions.json()}


def test_api_smoke_flow() -> None:
    with isolated_app_client(app) as client:
        runtime = app_runtime.require_ready()

        original_astream = runtime.harness_runtime.astream
        runtime.harness_runtime.astream = _fake_astream  # type: ignore[method-assign]
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
                "/api/chat/runs",
                json={"message": "hello smoke", "session_id": session_id, "stream": True},
            )
            assert response.status_code == 200
            replay = _replay_payload(client, response.json()["replay_url"])
            assert "assistant_text_delta" in _replay_event_types(replay)
            assert "turn_completed" in _replay_event_types(replay)
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_session_summary_endpoint_reads_single_session() -> None:
    with isolated_app_client(app) as client:
        created = client.post("/api/sessions", json={"title": "Single summary"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        summary = client.get(f"/api/sessions/{session_id}")

        assert summary.status_code == 200
        assert summary.json()["id"] == session_id
        assert summary.json()["title"] == "Single summary"
        assert "messages" not in summary.json()


def test_app_test_client_uses_isolated_runtime_storage() -> None:
    real_sessions_dir = BACKEND_DIR.parent / "storage" / "sessions"
    with isolated_app_client(app) as client:
        created = client.post("/api/sessions", json={"title": "Isolated test storage"})
        assert created.status_code == 200
        session_id = created.json()["id"]
        isolated_path = Path(client.isolated_storage_root) / "sessions" / f"{session_id}.json"
        real_path = real_sessions_dir / f"{session_id}.json"

        runtime = app_runtime.require_ready()
        assert Path(runtime.session_manager.sessions_dir).resolve() == (Path(client.isolated_storage_root) / "sessions").resolve()
        assert isolated_path.exists()
        assert not real_path.exists()


def test_workbench_current_session_ref_is_persisted() -> None:
    with isolated_app_client(app) as client:
        created = client.post("/api/sessions", json={"title": "Workbench current"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        saved = client.put(
            "/api/workbench/current-session",
            json={"session_id": session_id, "scope": {}, "pool_key": "main-chat"},
        )
        assert saved.status_code == 200

        current = client.get("/api/workbench/current-session")
        assert current.status_code == 200
        assert current.json()["current_session"]["session_id"] == session_id
        assert current.json()["current_session"]["pool_key"] == "main-chat"

        cleared = client.delete(f"/api/workbench/current-session?session_id={session_id}")
        assert cleared.status_code == 200
        assert cleared.json()["current_session"] is None


def test_workbench_current_session_ref_persists_authoritative_session_scope() -> None:
    with isolated_app_client(app) as client:
        created = client.post(
            "/api/sessions",
            json={
                "title": "Scoped current",
                "scope": {
                    "workspace_view": "task_environment",
                    "task_environment_id": "env.general.workspace",
                    "project_id": "project-a",
                },
            },
        )
        assert created.status_code == 200
        session_id = created.json()["id"]

        saved = client.put(
            "/api/workbench/current-session",
            json={"session_id": session_id, "scope": {}, "pool_key": "task_environment:env.general.workspace:project-a"},
        )

        assert saved.status_code == 200
        assert saved.json()["current_session"]["scope"] == {
            "workspace_view": "task_environment",
            "task_environment_id": "env.general.workspace",
            "project_id": "project-a",
        }


def test_stream_chat_records_orphaned_runtime_interruption_without_terminal_event() -> None:
    with isolated_app_client(app) as client:
        runtime = app_runtime.require_ready()

        original_astream = runtime.harness_runtime.astream
        runtime.harness_runtime.astream = _fake_missing_terminal_astream  # type: ignore[method-assign]
        try:
            created = client.post("/api/sessions", json={"title": "Missing terminal"})
            assert created.status_code == 200
            session_id = created.json()["id"]

            response = client.post(
                "/api/chat/runs",
                json={"message": "hello missing terminal", "session_id": session_id, "stream": True},
            )

            assert response.status_code == 200
            run_payload = _run_payload_until_status(client, response.json()["stream_run_id"], "orphaned")
            replay = _replay_payload(client, response.json()["replay_url"], wait_for_terminal=False)
            replay_text = json.dumps(replay, ensure_ascii=False)
            assert "input_commit_gate" in _replay_event_types(replay)
            assert "task_intent_decision" in _replay_event_types(replay)
            assert "turn_completed" not in _replay_event_types(replay)
            assert run_payload["status"] == "orphaned"
            assert run_payload["terminal_event"] == ""
            assert run_payload["diagnostics"]["runtime_interruption_code"] == "missing_terminal_event"
            assert run_payload["diagnostics"]["semantic_terminal"] is False
            assert "输出流没有正常收口" not in replay_text
        finally:
            runtime.harness_runtime.astream = original_astream  # type: ignore[method-assign]


def test_chat_rejects_invalid_session_id_before_streaming() -> None:
    with isolated_app_client(app) as client:
        response = client.post(
            "/api/chat/runs",
            json={"message": "hello", "session_id": "../outside", "stream": True},
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid session_id"}


def test_session_messages_can_be_truncated_for_edit_resend() -> None:
    with isolated_app_client(app) as client:
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


def test_session_truncate_does_not_block_health_while_reset_waits() -> None:
    with isolated_app_client(app) as client:
        runtime = app_runtime.require_ready()
        created = client.post("/api/sessions", json={"title": "Edit resend responsive"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        runtime.session_manager.append_messages(
            session_id,
            [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ],
        )
        ledger = runtime.harness_runtime.single_agent_runtime_host.prompt_accounting_ledger
        original_reset = ledger.reset_prompt_cache_baseline
        reset_started = threading.Event()
        release_reset = threading.Event()
        truncate_result: dict[str, object] = {}
        health_result: dict[str, object] = {}

        def waiting_reset(**kwargs):
            reset_started.set()
            assert release_reset.wait(2.0)
            return original_reset(**kwargs)

        def post_truncate() -> None:
            truncate_result["response"] = client.post(
                f"/api/sessions/{session_id}/messages/truncate",
                json={"message_index": 0},
            )

        def get_health() -> None:
            health_result["response"] = client.get("/health")

        ledger.reset_prompt_cache_baseline = waiting_reset
        truncate_thread = threading.Thread(target=post_truncate)
        health_thread = threading.Thread(target=get_health)
        try:
            truncate_thread.start()
            assert reset_started.wait(2.0)
            health_thread.start()
            health_thread.join(0.5)
            assert not health_thread.is_alive()
        finally:
            release_reset.set()
            truncate_thread.join(2.0)
            health_thread.join(2.0)
            ledger.reset_prompt_cache_baseline = original_reset

        health_response = health_result.get("response")
        truncate_response = truncate_result.get("response")
        assert getattr(health_response, "status_code", None) == 200
        assert getattr(truncate_response, "status_code", None) == 200


def test_session_truncate_does_not_wait_for_memory_maintenance_enqueue(monkeypatch) -> None:
    with isolated_app_client(app) as client:
        runtime = app_runtime.require_ready()
        created = client.post("/api/sessions", json={"title": "Edit resend fast maintenance"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        runtime.session_manager.append_messages(
            session_id,
            [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ],
        )

        maintenance_started = threading.Event()
        release_maintenance = threading.Event()
        captured: dict[str, object] = {}

        def waiting_enqueue(**kwargs):
            captured.update(kwargs)
            maintenance_started.set()
            if not release_maintenance.wait(2.0):
                raise AssertionError("truncate response waited for memory maintenance enqueue")
            return {"status": "queued"}

        monkeypatch.setattr(runtime.memory_facade, "enqueue_memory_maintenance_after_commit", waiting_enqueue)
        try:
            started_at = time.perf_counter()
            response = client.post(
                f"/api/sessions/{session_id}/messages/truncate",
                json={"message_index": 0},
            )
            elapsed = time.perf_counter() - started_at

            assert response.status_code == 200
            assert response.json()["messages"] == []
            assert elapsed < 1.0
            assert maintenance_started.wait(2.0)
            assert captured["session_id"] == session_id
            assert captured["messages"] == []
            assert captured["durable_lane_enabled"] is False
        finally:
            release_maintenance.set()


def test_removed_agent_control_plane_routes_stay_absent() -> None:
    with isolated_app_client(app) as client:
        response = client.get("/api/agents/catalog")
        assert response.status_code == 404
