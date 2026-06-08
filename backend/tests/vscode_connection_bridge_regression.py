from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
import sys

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api.chat import _effective_editor_context
from integrations.vscode_connection import VSCodeConnectionStore, get_vscode_connection_store
from integrations.vscode_connection.models import VSCodeConnectionConflict
from sessions import SessionManager


def test_vscode_context_store_auto_binds_single_workspace_root(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "backend")
    project = tmp_path / "project"
    project.mkdir()
    session = manager.create_session(title="VS Code")
    store = VSCodeConnectionStore()

    snapshot = store.record_context(
        session_manager=manager,
        session_id=session["id"],
        editor_context={
            "source": "vscode",
            "workspace_roots": [str(project)],
            "active_file": {
                "path": str(project / "src" / "main.py"),
                "language_id": "python",
                "dirty": True,
                "content_preview": {
                    "text": "print('dirty buffer')",
                    "truncated": False,
                    "source": "dirty_buffer",
                },
            },
            "visible_files": [],
            "diagnostics": [],
        },
    )

    assert manager.get_project_binding(session["id"])["workspace_root"] == str(project.resolve())
    assert snapshot.workspace_root == str(project.resolve())
    assert store.latest_editor_context(session["id"])["active_file"]["content_preview"]["source"] == "dirty_buffer"
    assert store.status(session["id"]).to_dict()["status"] == "connected"


def test_vscode_context_store_rejects_multiple_initial_roots(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "backend")
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    session = manager.create_session(title="VS Code")
    store = VSCodeConnectionStore()

    with pytest.raises(VSCodeConnectionConflict):
        store.record_context(
            session_manager=manager,
            session_id=session["id"],
            editor_context={"workspace_roots": [str(project_a), str(project_b)]},
        )

    assert manager.get_project_binding(session["id"]) == {}


def test_vscode_launch_intent_resolves_session_for_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = VSCodeConnectionStore()

    store.register_launch_intent(session_id="session-launch", workspace_root=str(project))
    resolved = store.resolve_launch_intent(workspace_roots=[str(project)])

    assert resolved["session_id"] == "session-launch"
    assert resolved["matched"] is True


def test_vscode_resolve_falls_back_to_latest_project_session(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "backend")
    project = tmp_path / "project"
    project.mkdir()
    first = manager.create_session(title="older", project_binding={"workspace_root": str(project), "source": "test"})
    second = manager.create_session(title="newer", project_binding={"workspace_root": str(project), "source": "test"})
    store = VSCodeConnectionStore()

    resolved = store.resolve_launch_intent(workspace_roots=[str(project)], session_manager=manager)

    assert first["id"] != second["id"]
    assert resolved["session_id"] == second["id"]
    assert resolved["match_source"] == "project_session_binding"


def test_chat_run_uses_latest_vscode_context_when_payload_context_is_empty(tmp_path: Path) -> None:
    store = get_vscode_connection_store()
    store.clear()
    manager = SessionManager(tmp_path / "backend")
    project = tmp_path / "project"
    project.mkdir()
    session = manager.create_session(title="VS Code")
    active_file = project / "frontend" / "App.tsx"

    store.record_context(
        session_manager=manager,
        session_id=session["id"],
        editor_context={
            "source": "vscode",
            "workspace_roots": [str(project)],
            "active_file": {
                "path": str(active_file),
                "language_id": "typescriptreact",
                "dirty": False,
                "content_preview": {
                    "text": "export function App() { return null; }",
                    "truncated": False,
                    "source": "saved_document",
                },
            },
            "visible_files": [],
            "diagnostics": [],
        },
    )

    effective = _effective_editor_context(session["id"], {})

    assert effective["source"] == "vscode"
    assert effective["active_file"]["path"] == str(active_file)
    store.clear()


def test_project_managed_session_reuses_vscode_context_from_same_project(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "backend")
    project = tmp_path / "project"
    project.mkdir()
    source_session = manager.create_session(title="VS Code source", project_binding={"workspace_root": str(project), "source": "test"})
    target_session = manager.create_session(title="Project chat", project_binding={"workspace_root": str(project), "source": "test"})
    store = VSCodeConnectionStore()
    active_file = project / "backend" / "app.py"

    store.record_context(
        session_manager=manager,
        session_id=source_session["id"],
        editor_context={
            "source": "vscode",
            "workspace_roots": [str(project)],
            "active_file": {
                "path": str(active_file),
                "language_id": "python",
                "dirty": False,
            },
            "visible_files": [],
            "diagnostics": [],
        },
    )

    status = store.status(target_session["id"], session_manager=manager).to_dict()
    effective = store.latest_editor_context(target_session["id"], session_manager=manager)

    assert status["status"] == "connected"
    assert status["session_id"] == target_session["id"]
    assert status["connection_session_id"] == source_session["id"]
    assert status["reused_project_connection"] is True
    assert status["workspace_root"] == str(project.resolve())
    assert effective["active_file"]["path"] == str(active_file)
