from pathlib import Path

from code_environment.workspace_tree import build_workspace_tree


def _flatten_paths(node: dict) -> list[str]:
    paths = [node["path"]]
    for child in node.get("children", []):
        paths.extend(_flatten_paths(child))
    return paths


def test_workspace_tree_lists_project_files_and_skips_heavy_directories(tmp_path: Path) -> None:
    (tmp_path / "backend" / "api").mkdir(parents=True)
    (tmp_path / "backend" / "api" / "code_environment.py").write_text("", encoding="utf-8")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app.tsx").write_text("", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("", encoding="utf-8")
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / "events").mkdir()
    (tmp_path / "events" / "runtime.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "storage" / "embedding_cache").mkdir(parents=True)
    (tmp_path / "storage" / "embedding_cache" / "cache.bin").write_text("", encoding="utf-8")
    (tmp_path / "storage" / "runtime_state").mkdir(parents=True)
    (tmp_path / "storage" / "runtime_state" / "trace.json").write_text("", encoding="utf-8")

    response = build_workspace_tree(tmp_path, max_depth=4, max_entries=50)
    payload = response.model_dump()
    paths = set(_flatten_paths(payload["tree"]))

    assert payload["root_name"] == tmp_path.name
    assert payload["root_path"] == str(tmp_path.resolve())
    assert "backend" in paths
    assert "backend/api/code_environment.py" in paths
    assert "frontend/src/app.tsx" in paths
    assert "node_modules" not in paths
    assert ".git" not in paths
    assert "events" not in paths
    assert "storage/embedding_cache" not in paths
    assert "storage/runtime_state" not in paths


def test_workspace_tree_marks_budget_truncation(tmp_path: Path) -> None:
    for index in range(30):
        (tmp_path / f"file_{index:02d}.txt").write_text("", encoding="utf-8")

    response = build_workspace_tree(tmp_path, max_depth=2, max_entries=20)

    assert response.total_entries == 20
    assert response.truncated is True


