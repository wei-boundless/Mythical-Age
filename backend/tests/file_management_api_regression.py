from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import file_management as file_management_api
from api import files as files_api
from file_management.api_models import ManagedFileReadRequest, ManagedFileTarget, ManagedFileWriteRequest
from file_management.service import (
    GRAPH_INSTANCE_PROFILE_ID,
    GRAPH_INSTANCE_REPOSITORY_ID,
    MANAGED_PROJECT_PROFILE_ID,
    ManagedFileService,
    ManagedFileServiceContext,
)
from sessions import SessionManager
from tests.support.runtime_stubs import RuntimeBaseDirStub


class ManagedFileRuntimeStub(RuntimeBaseDirStub):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self.session_manager = SessionManager(base_dir)
        self.refreshed_paths: list[str] = []

    def refresh_indexes_for_path(self, path: str) -> None:
        self.refreshed_paths.append(path)


def test_managed_project_file_api_reads_writes_and_records_change(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, project_root = _runtime_with_project(tmp_path)
    target_file = project_root / "src" / "app.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("VALUE = 'before'\n", encoding="utf-8")
    target = _project_target(session_id=session_id, project_root=project_root, logical_path="src/app.py")
    monkeypatch.setattr(file_management_api, "require_runtime", lambda: runtime)

    read_payload = asyncio.run(file_management_api.read_managed_file(ManagedFileReadRequest(target=target, session_id=session_id)))
    write_payload = asyncio.run(
        file_management_api.write_managed_file(
            ManagedFileWriteRequest(
                target=target,
                content="VALUE = 'after'\n",
                expected_sha256=read_payload["content_sha256"],
                session_id=session_id,
            )
        )
    )

    assert target_file.read_text(encoding="utf-8") == "VALUE = 'after'\n"
    assert write_payload["authority"] == "file_management.service.write"
    assert write_payload["file_change_record"]["session_id"] == session_id
    assert write_payload["file_change_record"]["logical_path"] == "src/app.py"
    assert runtime.refreshed_paths == ["src/app.py"]


def test_managed_project_file_api_rejects_stale_expected_hash(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, project_root = _runtime_with_project(tmp_path)
    target_file = project_root / "src" / "stale.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("before\n", encoding="utf-8")
    target = _project_target(session_id=session_id, project_root=project_root, logical_path="src/stale.py")
    monkeypatch.setattr(file_management_api, "require_runtime", lambda: runtime)
    read_payload = asyncio.run(file_management_api.read_managed_file(ManagedFileReadRequest(target=target, session_id=session_id)))
    target_file.write_text("changed elsewhere\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            file_management_api.write_managed_file(
                ManagedFileWriteRequest(
                    target=target,
                    content="after\n",
                    expected_sha256=read_payload["content_sha256"],
                    session_id=session_id,
                )
            )
        )

    assert exc_info.value.status_code == 409
    assert dict(exc_info.value.detail)["code"] == "managed_file_conflict"
    assert target_file.read_text(encoding="utf-8") == "changed elsewhere\n"


def test_managed_project_file_api_rejects_sensitive_files(tmp_path: Path) -> None:
    runtime, session_id, project_root = _runtime_with_project(tmp_path)
    secret_file = project_root / ".env"
    secret_file.write_text("TOKEN=secret\n", encoding="utf-8")
    target = _project_target(session_id=session_id, project_root=project_root, logical_path=".env")

    with pytest.raises(HTTPException) as exc_info:
        ManagedFileService(runtime).read(target, context=ManagedFileServiceContext(session_id=session_id))

    assert exc_info.value.status_code == 400
    assert "Sensitive file" in str(exc_info.value.detail)


def test_legacy_files_api_still_cannot_write_project_code(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    backend_root = project_root / "backend"
    target_file = project_root / "frontend" / "src" / "app.tsx"
    target_file.parent.mkdir(parents=True)
    backend_root.mkdir(parents=True)
    target_file.write_text("export const value = 1;\n", encoding="utf-8")
    monkeypatch.setattr(files_api, "require_runtime", lambda: RuntimeBaseDirStub(backend_root))

    with pytest.raises(HTTPException) as exc_info:
        files_api._resolve_path("frontend/src/app.tsx", for_write=True)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Path is not in the editable whitelist"


def test_graph_task_instance_managed_write_uses_dynamic_repository_and_records_change(tmp_path: Path) -> None:
    host_backend = tmp_path / "host" / "backend"
    host_backend.mkdir(parents=True)
    runtime = ManagedFileRuntimeStub(host_backend)
    session_id = str(runtime.session_manager.create_session(title="Graph session")["id"])
    target = ManagedFileTarget(
        repository_id=GRAPH_INSTANCE_REPOSITORY_ID,
        repository_kind="artifact_repository",
        scope_kind="graph_task_instance",
        scope_id="instance-test",
        logical_path="artifacts/result.md",
        profile_id=GRAPH_INSTANCE_PROFILE_ID,
    )

    payload = ManagedFileService(runtime).write(
        target,
        content="# Result\n",
        context=ManagedFileServiceContext(session_id=session_id, actor_id="agent_ui"),
    )

    output_path = tmp_path / "host" / "storage" / "graph_task_instances" / "instance-test" / "artifacts" / "result.md"
    assert output_path.read_text(encoding="utf-8") == "# Result\n"
    assert payload["file_change_record"]["session_id"] == session_id
    assert payload["file_change_record"]["logical_path"] == "artifacts/result.md"


def _runtime_with_project(tmp_path: Path) -> tuple[ManagedFileRuntimeStub, str, Path]:
    host_backend = tmp_path / "host" / "backend"
    project_root = tmp_path / "project"
    host_backend.mkdir(parents=True)
    project_root.mkdir(parents=True)
    runtime = ManagedFileRuntimeStub(host_backend)
    session = runtime.session_manager.create_session(title="Managed project")
    session_id = str(session["id"])
    runtime.session_manager.bind_project(session_id, workspace_root=str(project_root), source="test")
    return runtime, session_id, project_root


def _project_target(*, session_id: str, project_root: Path, logical_path: str) -> ManagedFileTarget:
    return ManagedFileTarget(
        repository_id="repo.managed_project.project_workspace",
        repository_kind="project_workspace",
        scope_kind="project_scoped",
        scope_id=session_id,
        logical_path=logical_path,
        workspace_root=str(project_root),
        profile_id=MANAGED_PROJECT_PROFILE_ID,
    )
