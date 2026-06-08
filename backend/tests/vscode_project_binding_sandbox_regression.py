from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api import sessions as sessions_api
from api.chat import _bind_or_validate_editor_project
from harness.runtime.assembly import assemble_runtime
from runtime.shared.safety import build_task_safety_validators
from runtime.tool_runtime.tool_control_plane import _workspace_root
from runtime.tool_runtime.tool_executor import _workspace_root_from_sandbox_policy
from runtime.tool_runtime.tool_invocation_request import ToolInvocationRequest
from sessions import SessionManager, SessionProjectBindingConflict


def test_session_project_binding_is_immutable_after_first_root(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    session = manager.create_session(title="Project A")

    binding = manager.bind_project(session["id"], workspace_root=str(project_a), source="vscode")
    refreshed = manager.bind_project(session["id"], workspace_root=str(project_a), source="vscode")

    assert binding["workspace_root"] == str(project_a.resolve())
    assert refreshed["workspace_root"] == str(project_a.resolve())
    assert refreshed["immutable"] is True

    with pytest.raises(SessionProjectBindingConflict):
        manager.bind_project(session["id"], workspace_root=str(project_b), source="vscode")


def test_chat_editor_context_auto_binds_once_and_rejects_conflict(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    session = manager.create_session(title="VS Code")
    runtime = SimpleNamespace(session_manager=manager)

    _bind_or_validate_editor_project(runtime, session["id"], {"workspace_roots": [str(project_a)]})
    assert manager.get_project_binding(session["id"])["workspace_root"] == str(project_a.resolve())

    _bind_or_validate_editor_project(runtime, session["id"], {"workspace_roots": [str(project_a)]})

    with pytest.raises(HTTPException) as error:
        _bind_or_validate_editor_project(runtime, session["id"], {"workspace_roots": [str(project_b)]})
    assert error.value.status_code == 409


def test_chat_editor_context_requires_explicit_binding_for_multiple_initial_roots(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    session = manager.create_session(title="VS Code")
    runtime = SimpleNamespace(session_manager=manager)

    with pytest.raises(HTTPException) as error:
        _bind_or_validate_editor_project(
            runtime,
            session["id"],
            {"workspace_roots": [str(project_a), str(project_b)]},
        )

    assert error.value.status_code == 409
    assert manager.get_project_binding(session["id"]) == {}


def test_project_directory_picker_endpoint_binds_selected_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = SessionManager(tmp_path / "sessions")
    selected_project = tmp_path / "selected-project"
    selected_project.mkdir()
    session = manager.create_session(title="Directory picker")
    runtime = SimpleNamespace(session_manager=manager)

    monkeypatch.setattr(sessions_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_api, "_select_project_directory_with_windows_dialog", lambda: str(selected_project))

    result = asyncio.run(
        sessions_api.select_session_project_directory(
            session["id"],
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    assert result["project_binding"]["workspace_root"] == str(selected_project.resolve())
    assert result["project_binding"]["source"] == "frontend.directory_picker"


def test_project_directory_picker_cancel_does_not_bind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = SessionManager(tmp_path / "sessions")
    session = manager.create_session(title="Directory picker")
    runtime = SimpleNamespace(session_manager=manager)

    monkeypatch.setattr(sessions_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_api, "_select_project_directory_with_windows_dialog", lambda: "")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            sessions_api.select_session_project_directory(
                session["id"],
                workspace_view=None,
                task_environment_id=None,
                project_id=None,
            )
        )

    assert exc.value.status_code == 409
    assert manager.get_project_binding(session["id"]) == {}


def test_open_vscode_uses_new_window_for_bound_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = SessionManager(tmp_path / "sessions")
    selected_project = tmp_path / "selected-project"
    selected_project.mkdir()
    session = manager.create_session(title="VS Code window")
    manager.bind_project(session["id"], workspace_root=str(selected_project), source="test")
    runtime = SimpleNamespace(session_manager=manager)
    launched: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> object:
        launched["command"] = command
        launched["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(sessions_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_api.shutil, "which", lambda name: "C:/bin/code.cmd" if name == "code" else None)
    monkeypatch.setattr(
        sessions_api,
        "_ensure_vscode_connection_extension_installed",
        lambda: {"extension_id": "local.langchain-agent-vscode", "install_dir": "C:/Users/test/.vscode/extensions/local.langchain-agent-vscode-0.1.0"},
    )
    monkeypatch.setattr(sessions_api.subprocess, "Popen", fake_popen)

    result = asyncio.run(
        sessions_api.open_session_project_in_vscode(
            session["id"],
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    command = launched["command"]
    assert command == ["C:/bin/code.cmd", "--new-window", str(selected_project.resolve())]
    assert "-r" not in command
    assert "--extensionDevelopmentPath=D:/agent/extensions/vscode" not in command
    assert result["window_mode"] == "new_window"
    assert result["extension_installation"]["extension_id"] == "local.langchain-agent-vscode"
    assert result["session_id"] == session["id"]


def test_open_vscode_reuses_existing_project_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = SessionManager(tmp_path / "sessions")
    selected_project = tmp_path / "selected-project"
    selected_project.mkdir()
    source_session = manager.create_session(title="VS Code source")
    target_session = manager.create_session(title="VS Code target")
    manager.bind_project(source_session["id"], workspace_root=str(selected_project), source="test")
    manager.bind_project(target_session["id"], workspace_root=str(selected_project), source="test")
    runtime = SimpleNamespace(session_manager=manager)
    store = sessions_api.get_vscode_connection_store()
    store.clear()
    store.record_context(
        session_manager=manager,
        session_id=source_session["id"],
        editor_context={
            "source": "vscode",
            "workspace_roots": [str(selected_project)],
            "active_file": {"path": str(selected_project / "README.md"), "language_id": "markdown", "dirty": False},
            "visible_files": [],
            "diagnostics": [],
        },
    )

    def fail_popen(*args: object, **kwargs: object) -> object:
        raise AssertionError("VS Code should not be launched when project connection is already active")

    monkeypatch.setattr(sessions_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_api.shutil, "which", lambda name: None)
    monkeypatch.setattr(sessions_api.subprocess, "Popen", fail_popen)
    try:
        result = asyncio.run(
            sessions_api.open_session_project_in_vscode(
                target_session["id"],
                workspace_view=None,
                task_environment_id=None,
                project_id=None,
            )
        )
    finally:
        store.clear()

    assert result["window_mode"] == "existing_project_connection"
    assert result["connection_reused"] is True
    assert result["command"] == []
    assert result["connection_status"]["connection_session_id"] == source_session["id"]
    assert result["connection_status"]["reused_project_connection"] is True


def test_open_vscode_requires_connection_extension_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = SessionManager(tmp_path / "sessions")
    selected_project = tmp_path / "selected-project"
    selected_project.mkdir()
    session = manager.create_session(title="VS Code window")
    manager.bind_project(session["id"], workspace_root=str(selected_project), source="test")
    runtime = SimpleNamespace(session_manager=manager)

    monkeypatch.setattr(sessions_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_api.shutil, "which", lambda name: "C:/bin/code.cmd" if name == "code" else None)
    monkeypatch.setattr(sessions_api, "_ensure_vscode_connection_extension_installed", lambda: {})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            sessions_api.open_session_project_in_vscode(
                session["id"],
                workspace_view=None,
                task_environment_id=None,
                project_id=None,
            )
        )

    assert exc.value.status_code == 503
    assert "VS Code connection extension is not built" in str(exc.value.detail)


def test_runtime_assembly_carries_bound_workspace_root(tmp_path: Path) -> None:
    project_root = tmp_path / "bound-project"
    project_root.mkdir()

    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-bound",
        turn_id="turn-bound",
        agent_invocation_id="aginvoke-bound",
        request_task_selection={},
        model_selection={},
        agent_runtime_profile=None,
        tool_instances=(),
        definitions_by_name={},
        workspace_root=str(project_root),
    ).to_dict()

    environment = dict(assembly["task_environment"])
    assert environment["storage_space"]["workspace_root"] == str(project_root.resolve())
    assert environment["sandbox_policy"]["workspace_root"] == str(project_root.resolve())
    assert environment["project_binding"]["workspace_root"] == str(project_root.resolve())


def test_tool_control_plane_and_executor_prefer_bound_workspace_root(tmp_path: Path) -> None:
    project_root = tmp_path / "bound-project"
    backend_root = tmp_path / "backend-project"
    project_root.mkdir()
    backend_root.mkdir()
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:bound",
        caller_kind="agent_turn",
        caller_ref="turn:bound",
        session_id="session-bound",
        turn_id="turn:bound",
        tool_name="read_file",
        tool_call_id="toolcall:bound",
        sandbox_scope={"workspace_root": str(project_root)},
    )

    assert _workspace_root(request) == project_root.resolve()
    assert _workspace_root_from_sandbox_policy(
        {"workspace_root": str(project_root)},
        fallback=backend_root,
    ) == project_root.resolve()


def test_task_safety_validator_uses_bound_workspace_root_for_absolute_paths(tmp_path: Path) -> None:
    bound_project = tmp_path / "bound-project"
    backend_project = tmp_path / "backend-project"
    outside = tmp_path / "outside.txt"
    bound_project.mkdir()
    backend_project.mkdir()
    (bound_project / "backend").mkdir()
    inside = bound_project / "backend" / "TOOLS_REGISTRY.json"
    inside.write_text("{}", encoding="utf-8")
    outside.write_text("secret", encoding="utf-8")
    validators = build_task_safety_validators(
        root_dir=backend_project,
        safety_envelope={},
        sandbox_policy={"workspace_root": str(bound_project)},
    )

    assert validators["filesystem_path"]({"operation_id": "op.read_file", "path": str(inside)}) is True
    assert validators["filesystem_path"]({"operation_id": "op.read_file", "path": str(outside)}) == (
        False,
        "path traversal detected",
    )
