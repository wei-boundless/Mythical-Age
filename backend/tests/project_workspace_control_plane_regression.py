from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import project_workspaces as project_workspaces_api
from project_workspaces.service import ProjectWorkspaceService
from sessions import SessionManager


def test_project_workspaces_derive_main_chat_sessions_from_project_binding(tmp_path: Path) -> None:
    backend_root = tmp_path / "host" / "backend"
    project_root = tmp_path / "repo"
    backend_root.mkdir(parents=True)
    project_root.mkdir()
    manager = SessionManager(backend_root)
    manager.create_session(
        title="Main project chat",
        project_binding={"workspace_root": str(project_root), "source": "test"},
    )
    manager.create_session(
        title="Scoped task chat",
        scope={"workspace_view": "task_environment", "task_environment_id": "env.test", "project_id": "logical"},
        project_binding={"workspace_root": str(project_root), "source": "test"},
    )

    projects = ProjectWorkspaceService(backend_root, manager).list_workspaces()

    assert len(projects) == 1
    assert projects[0]["workspace_root"] == str(project_root.resolve())
    assert projects[0]["session_count"] == 1


def test_project_workspace_session_create_binds_selected_project(tmp_path: Path, monkeypatch) -> None:
    backend_root = tmp_path / "host" / "backend"
    project_root = tmp_path / "repo"
    backend_root.mkdir(parents=True)
    project_root.mkdir()
    manager = SessionManager(backend_root)
    service = ProjectWorkspaceService(backend_root, manager)
    project = service.register_workspace(str(project_root), source="test")
    runtime = SimpleNamespace(base_dir=backend_root, session_manager=manager)
    monkeypatch.setattr(project_workspaces_api, "require_runtime", lambda: runtime)

    response = asyncio.run(
        project_workspaces_api.create_project_workspace_session(
            project["key"],
            project_workspaces_api.CreateProjectWorkspaceSessionRequest(title="Project chat"),
        )
    )

    session = response["session"]
    assert response["created"] is True
    assert session["title"] == "Project chat"
    assert session["conversation_state"]["project_binding"]["workspace_root"] == str(project_root.resolve())


def test_project_workspace_tree_uses_registered_project_without_session(tmp_path: Path, monkeypatch) -> None:
    backend_root = tmp_path / "host" / "backend"
    project_root = tmp_path / "repo"
    source_file = project_root / "src" / "main.py"
    backend_root.mkdir(parents=True)
    source_file.parent.mkdir(parents=True)
    source_file.write_text("print('ok')\n", encoding="utf-8")
    manager = SessionManager(backend_root)
    project = ProjectWorkspaceService(backend_root, manager).register_workspace(str(project_root), source="test")
    runtime = SimpleNamespace(base_dir=backend_root, session_manager=manager)
    monkeypatch.setattr(project_workspaces_api, "require_runtime", lambda: runtime)

    tree = asyncio.run(
        project_workspaces_api.project_workspace_tree(
            project["key"],
            max_depth=4,
            max_entries=100,
        )
    )

    assert Path(tree.root_path) == project_root.resolve()
    assert [node.name for node in tree.tree.children] == ["src"]

