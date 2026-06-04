from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.workspace_file_service import WorkspaceFileService


def test_glob_paths_excludes_runtime_sandbox_artifacts_by_default(tmp_path: Path) -> None:
    backend_dir = tmp_path / "project" / "backend"
    backend_dir.mkdir(parents=True)
    public_file = tmp_path / "project" / "docs" / "game" / "index.html"
    sandbox_file = (
        tmp_path
        / "project"
        / "storage"
        / "runtime_state"
        / "sandboxes"
        / "taskrun_old"
        / "storage"
        / "task_environments"
        / "general"
        / "workspace"
        / "artifacts"
        / "old.html"
    )
    public_file.parent.mkdir(parents=True)
    sandbox_file.parent.mkdir(parents=True)
    public_file.write_text("<html>public</html>", encoding="utf-8")
    sandbox_file.write_text("<html>old sandbox</html>", encoding="utf-8")

    matches = WorkspaceFileService(backend_dir).glob_paths("**/*.html", max_results=20)

    assert "docs/game/index.html" in matches
    assert not any("storage/runtime_state/sandboxes" in item for item in matches)


def test_glob_paths_excludes_output_by_default_but_allows_explicit_output(tmp_path: Path) -> None:
    backend_dir = tmp_path / "project" / "backend"
    backend_dir.mkdir(parents=True)
    public_file = tmp_path / "project" / "docs" / "visible.json"
    output_file = tmp_path / "project" / "output" / "benchmark" / "result.json"
    public_file.parent.mkdir(parents=True)
    output_file.parent.mkdir(parents=True)
    public_file.write_text("{}", encoding="utf-8")
    output_file.write_text('{"metric": 1}', encoding="utf-8")

    service = WorkspaceFileService(backend_dir)

    default_matches = service.glob_paths("**/*.json", max_results=20)
    explicit_output_matches = service.glob_paths("output/**/*.json", max_results=20)

    assert "docs/visible.json" in default_matches
    assert "output/benchmark/result.json" not in default_matches
    assert "output/benchmark/result.json" in explicit_output_matches
