from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import api.chat as chat_api
from runtime.shared.queued_user_input_store import QueuedUserInputStore
from runtime.shared.runtime_run_registry import RuntimeRun


class _SessionManagerStub:
    def __init__(self, workspace_root: Path, *, has_binding: bool = True) -> None:
        self.workspace_root = str(workspace_root)
        self.has_binding = has_binding
        self.bind_calls: list[dict[str, str]] = []

    def get_project_binding(self, _session_id: str) -> dict[str, Any]:
        if not self.has_binding:
            return {}
        return {"workspace_root": self.workspace_root, "source": "manual"}

    def get_history(self, session_id: str) -> dict[str, Any]:
        return {
            "id": session_id,
            "scope": {"workspace_view": "chat", "task_environment_id": "", "project_id": ""},
        }

    def bind_project(self, session_id: str, *, workspace_root: str, source: str) -> dict[str, Any]:
        self.bind_calls.append({"session_id": session_id, "workspace_root": workspace_root, "source": source})
        return {"workspace_root": self.workspace_root, "source": source}


class _ForbiddenVSCodeStore:
    def latest_editor_context(self, *_args, **_kwargs):
        raise AssertionError("chat API must not fetch implicit VS Code editor context")


def _runtime(tmp_path: Path, *, has_binding: bool = True, queued_user_inputs: QueuedUserInputStore | None = None):
    host = SimpleNamespace(
        queued_user_inputs=queued_user_inputs,
        active_turn_registry=SimpleNamespace(resolve_current=lambda _session_id: None),
        run_registry=SimpleNamespace(list_session_runs=lambda _session_id: []),
        agent_run_supervisor=SimpleNamespace(
            active_cell_for_stream_run=lambda _stream_run_id, *, session_id: SimpleNamespace(scope=SimpleNamespace(run_cell_id=""))
        ),
    )
    return SimpleNamespace(
        base_dir=tmp_path,
        session_manager=_SessionManagerStub(tmp_path, has_binding=has_binding),
        harness_runtime=SimpleNamespace(single_agent_runtime_host=host),
    )


def _runtime_run(session_id: str = "session-editor-context") -> RuntimeRun:
    now = time.time()
    return RuntimeRun(
        stream_run_id="strun:editor-context",
        session_id=session_id,
        event_log_id="chatrun:editor-context",
        root_request_ref="chatreq:editor-context",
        status="running",
        created_at=now,
        updated_at=now,
        reconnectable_until=now + 3600,
        diagnostics={},
    )


def test_chat_run_uses_only_explicit_editor_context_when_session_has_project_binding(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path, has_binding=True)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(chat_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(chat_api, "get_vscode_connection_store", lambda: _ForbiddenVSCodeStore(), raising=False)

    def fake_schedule(_runtime, request):
        captured["request"] = request
        return _runtime_run(request.session_id)

    monkeypatch.setattr(chat_api, "_create_and_schedule_run", fake_schedule)

    response = asyncio.run(
        chat_api.create_chat_run(
            chat_api.ChatRequest(
                message="继续当前任务",
                session_id="session-editor-context",
            )
        )
    )

    assert response["stream_run_id"] == "strun:editor-context"
    assert captured["request"].editor_context == {}
    assert runtime.session_manager.bind_calls == []
    assert not hasattr(chat_api, "_effective_editor_context")
    assert not hasattr(chat_api, "_merge_editor_contexts")


def test_explicit_editor_context_is_preserved_and_project_binding_uses_payload_source(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path, has_binding=False)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(chat_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(chat_api, "get_vscode_connection_store", lambda: _ForbiddenVSCodeStore(), raising=False)

    def fake_schedule(_runtime, request):
        captured["request"] = request
        return _runtime_run(request.session_id)

    monkeypatch.setattr(chat_api, "_create_and_schedule_run", fake_schedule)

    editor_context = {
        "source": "frontend.center_workspace",
        "workspace_roots": [str(tmp_path)],
        "active_file": {"path": str(tmp_path / "app.py"), "dirty": False},
    }

    asyncio.run(
        chat_api.create_chat_run(
            chat_api.ChatRequest(
                message="检查当前文件",
                session_id="session-explicit-context",
                editor_context=editor_context,
            )
        )
    )

    assert captured["request"].editor_context == editor_context
    assert runtime.session_manager.bind_calls == [
        {
            "session_id": "session-explicit-context",
            "workspace_root": str(tmp_path),
            "source": "frontend.center_workspace",
        }
    ]


def test_queued_input_persists_only_request_editor_context_without_vscode_fallback(tmp_path, monkeypatch) -> None:
    store = QueuedUserInputStore(tmp_path / "queued")
    runtime = _runtime(tmp_path, has_binding=True, queued_user_inputs=store)
    monkeypatch.setattr(chat_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(chat_api, "get_vscode_connection_store", lambda: _ForbiddenVSCodeStore(), raising=False)

    async def no_dispatch(*_args, **_kwargs):
        return None

    monkeypatch.setattr(chat_api, "_dispatch_next_queued_input", no_dispatch)

    response = asyncio.run(
        chat_api.enqueue_queued_chat_input(
            "session-queue-editor-context",
            chat_api.QueuedChatInputRequest(
                message="补充一句约束",
                client_message_id="user:editor-context",
            ),
        )
    )

    assert response["item"]["editor_context"] == {}
    assert store.list_session("session-queue-editor-context")[0].editor_context == {}
    assert runtime.session_manager.bind_calls == []
