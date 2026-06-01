from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from api import files as files_api
from tests.support.runtime_stubs import RuntimeBaseDirStub


def test_project_workspace_files_are_readable_but_not_editable(tmp_path: Path) -> None:
    project_root = tmp_path
    backend_root = project_root / "backend"
    frontend_file = project_root / "frontend" / "src" / "app.tsx"
    backend_file = backend_root / "api" / "files.py"
    frontend_file.parent.mkdir(parents=True)
    backend_file.parent.mkdir(parents=True)
    frontend_file.write_text("export const ok = true;\n", encoding="utf-8")
    backend_file.write_text("from __future__ import annotations\n", encoding="utf-8")

    original = files_api.require_runtime
    files_api.require_runtime = lambda: RuntimeBaseDirStub(backend_root)  # type: ignore[assignment]
    try:
        assert files_api._resolve_path("frontend/src/app.tsx") == frontend_file.resolve()
        assert files_api._resolve_path("backend/api/files.py") == backend_file.resolve()

        with pytest.raises(HTTPException) as exc:
            files_api._resolve_path("frontend/src/app.tsx", for_write=True)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Path is not in the editable whitelist"
    finally:
        files_api.require_runtime = original  # type: ignore[assignment]


def test_project_workspace_read_allows_tree_visible_root_files_without_enabling_secret_files(tmp_path: Path) -> None:
    project_root = tmp_path
    backend_root = project_root / "backend"
    source_file = project_root / "source" / "brief.md"
    root_file = project_root / "conftest.py"
    secret_file = project_root / ".env"
    source_file.parent.mkdir(parents=True)
    backend_root.mkdir(parents=True)
    source_file.write_text("brief", encoding="utf-8")
    root_file.write_text("pytest_plugins = []\n", encoding="utf-8")
    secret_file.write_text("TOKEN=secret\n", encoding="utf-8")

    original = files_api.require_runtime
    files_api.require_runtime = lambda: RuntimeBaseDirStub(backend_root)  # type: ignore[assignment]
    try:
        assert files_api._resolve_path("source/brief.md") == source_file.resolve()
        assert files_api._resolve_path("conftest.py") == root_file.resolve()

        with pytest.raises(HTTPException) as exc:
            files_api._resolve_path(".env")
        assert exc.value.status_code == 400
        assert exc.value.detail == "Path is not visible in the project file tree"
    finally:
        files_api.require_runtime = original  # type: ignore[assignment]


def test_project_workspace_read_rejects_binary_files_as_text(tmp_path: Path) -> None:
    image_file = tmp_path / "source" / "asset.png"
    backend_root = tmp_path / "backend"
    image_file.parent.mkdir(parents=True)
    backend_root.mkdir(parents=True)
    image_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00")

    original = files_api.require_runtime
    files_api.require_runtime = lambda: RuntimeBaseDirStub(backend_root)  # type: ignore[assignment]
    try:
        resolved = files_api._resolve_path("source/asset.png")
        assert resolved == image_file.resolve()
        with pytest.raises(HTTPException) as exc:
            files_api._read_text_with_fallback(resolved)
        assert exc.value.status_code == 415
        assert exc.value.detail == "File is not a supported text file"
    finally:
        files_api.require_runtime = original  # type: ignore[assignment]


def test_project_workspace_read_rejects_traversal(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    backend_root.mkdir(parents=True)

    original = files_api.require_runtime
    files_api.require_runtime = lambda: RuntimeBaseDirStub(backend_root)  # type: ignore[assignment]
    try:
        with pytest.raises(HTTPException) as exc:
            files_api._resolve_path("frontend/../../secret.txt")
        assert exc.value.status_code == 400
        assert exc.value.detail == "Path traversal detected"
    finally:
        files_api.require_runtime = original  # type: ignore[assignment]
