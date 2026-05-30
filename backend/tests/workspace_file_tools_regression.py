from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.units.tools.read_file_tool import ReadFileTool
from capability_system.units.tools.file_system_tools import GlobPathsTool
from capability_system.units.tools.search_files_tool import SearchFilesTool
from capability_system.units.tools.write_file_tool import EditFileTool, WriteFileTool


def test_workspace_file_tools_use_external_knowledge_root_when_initialized_from_backend(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    root_knowledge = tmp_path / "external-rag" / "knowledge"
    backend_knowledge = backend_dir / "knowledge"
    root_knowledge.mkdir(parents=True)
    backend_knowledge.mkdir(parents=True)
    monkeypatch.setenv("APP_KNOWLEDGE_ROOT", str(root_knowledge))
    (root_knowledge / "note.md").write_text("root knowledge", encoding="utf-8")
    (backend_knowledge / "note.md").write_text("backend knowledge", encoding="utf-8")

    reader = ReadFileTool(root_dir=backend_dir)
    writer = WriteFileTool(root_dir=backend_dir)
    editor = EditFileTool(root_dir=backend_dir)

    assert reader.invoke({"path": "knowledge/note.md"}) == "root knowledge"

    write_result = writer.invoke({"path": "knowledge/note.md", "content": "updated from workspace"})
    assert write_result == "Write succeeded: knowledge/note.md"
    assert (root_knowledge / "note.md").read_text(encoding="utf-8") == "updated from workspace"
    assert (backend_knowledge / "note.md").read_text(encoding="utf-8") == "backend knowledge"
    assert reader.invoke({"path": "knowledge/note.md"}) == "updated from workspace"

    edit_result = editor.invoke(
        {
            "path": "knowledge/note.md",
            "old_text": "updated",
            "new_text": "edited",
        }
    )
    assert edit_result == "Edit succeeded: knowledge/note.md"
    assert reader.invoke({"path": "knowledge/note.md"}) == "edited from workspace"


def test_workspace_file_tools_reject_path_traversal_from_project_root(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    backend_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    reader = ReadFileTool(root_dir=backend_dir)
    writer = WriteFileTool(root_dir=backend_dir)

    assert "Path traversal detected" in reader.invoke({"path": "../outside.md"})
    assert "Path traversal detected" in writer.invoke({"path": "../outside.md", "content": "bad"})
    assert outside.read_text(encoding="utf-8") == "outside"


def test_workspace_search_defaults_do_not_duplicate_backend_knowledge_root(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    root_knowledge = tmp_path / "external-rag" / "knowledge"
    backend_knowledge = backend_dir / "knowledge"
    root_knowledge.mkdir(parents=True)
    backend_knowledge.mkdir(parents=True)
    monkeypatch.setenv("APP_KNOWLEDGE_ROOT", str(root_knowledge))
    (root_knowledge / "shared-note.md").write_text("root", encoding="utf-8")
    (backend_knowledge / "shared-note.md").write_text("backend", encoding="utf-8")

    search = SearchFilesTool(root_dir=backend_dir)
    result = search.invoke({"query": "shared-note", "max_results": 10})

    assert "knowledge/shared-note.md" in result
    assert "backend/knowledge/shared-note.md" not in result


def test_workspace_glob_uses_single_project_root(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    docs_dir = workspace / "docs"
    docs_dir.mkdir(parents=True)
    backend_dir.mkdir(parents=True)
    (docs_dir / "plan.md").write_text("ok", encoding="utf-8")

    globber = GlobPathsTool(root_dir=backend_dir)
    result = globber.invoke({"pattern": "docs/**/*.md", "max_results": 10})

    assert result.splitlines() == ["docs/plan.md"]


