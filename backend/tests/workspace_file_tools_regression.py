from __future__ import annotations

import sys
import asyncio
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.native_tool_catalog import get_tool_definition_map
from capability_system.tools.tool_units.file_system_tools import GlobPathsTool
from capability_system.tools.tool_units.search_files_tool import SearchFilesTool, SearchTextInput, SearchTextTool
from capability_system.tools.tool_units.write_file_tool import EditFileTool, WriteFileTool
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_use_context import ToolUseContext


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

    writer = WriteFileTool(root_dir=backend_dir)
    editor = EditFileTool(root_dir=backend_dir)

    assert _read_file_text(backend_dir, "knowledge/note.md") == "1 | root knowledge"

    write_result = writer.invoke({"path": "knowledge/note.md", "content": "updated from workspace", "allow_overwrite": True})
    assert write_result == "Write succeeded: knowledge/note.md"
    assert (root_knowledge / "note.md").read_text(encoding="utf-8") == "updated from workspace"
    assert (backend_knowledge / "note.md").read_text(encoding="utf-8") == "backend knowledge"
    assert _read_file_text(backend_dir, "knowledge/note.md") == "1 | updated from workspace"

    edit_result = editor.invoke(
        {
            "path": "knowledge/note.md",
            "old_text": "updated",
            "new_text": "edited",
        }
    )
    assert edit_result == "Edit succeeded: knowledge/note.md"
    assert _read_file_text(backend_dir, "knowledge/note.md") == "1 | edited from workspace"


def test_workspace_file_tools_reject_path_traversal_from_project_root(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    backend_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    writer = WriteFileTool(root_dir=backend_dir)

    assert "Path traversal detected" in _read_file_text(backend_dir, "../outside.md")
    assert "Path traversal detected" in writer.invoke({"path": "../outside.md", "content": "bad"})
    assert outside.read_text(encoding="utf-8") == "outside"


def test_workspace_write_file_requires_explicit_overwrite(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    docs_dir = workspace / "docs"
    docs_dir.mkdir(parents=True)
    backend_dir.mkdir(parents=True)
    target = docs_dir / "note.md"
    target.write_text("old", encoding="utf-8")

    writer = WriteFileTool(root_dir=backend_dir)

    denied = writer.invoke({"path": "docs/note.md", "content": "new"})
    allowed = writer.invoke({"path": "docs/note.md", "content": "new", "allow_overwrite": True})

    assert "allow_overwrite=true" in denied
    assert allowed == "Write succeeded: docs/note.md"
    assert target.read_text(encoding="utf-8") == "new"


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


def test_workspace_search_text_accepts_concrete_paths_and_rejects_files_in_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    docs_dir = workspace / "docs"
    docs_dir.mkdir(parents=True)
    backend_dir.mkdir(parents=True)
    (docs_dir / "plan.md").write_text("alpha\nneedle here\nneedle later\nomega", encoding="utf-8")
    (docs_dir / "other.md").write_text("needle elsewhere", encoding="utf-8")

    search = SearchTextTool(root_dir=backend_dir)

    result = search.invoke({"query": "needle", "paths": ["docs/plan.md"], "max_results": 10})
    misuse = search.invoke({"query": "needle", "roots": ["docs/plan.md"], "max_results": 10})

    assert result.splitlines() == [
        "docs/plan.md:2:1:needle here",
        "docs/plan.md:3:1:needle later",
    ]
    assert "docs/other.md" not in result
    assert "roots accepts directories only" in misuse
    assert "paths" in misuse


def test_search_text_schema_exposes_pagination_and_output_mode_fields() -> None:
    schema = SearchTextInput.model_json_schema()
    properties = dict(schema.get("properties") or {})

    for field_name in ("output_mode", "context", "case_sensitive", "head_limit", "offset"):
        assert field_name in properties
    assert "query" in set(schema.get("required") or [])


def test_native_search_text_returns_recommended_read_windows(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    docs_dir = workspace / "docs"
    docs_dir.mkdir(parents=True)
    backend_dir.mkdir(parents=True)
    (docs_dir / "plan.md").write_text("alpha\nneedle here\nneedle later\nomega", encoding="utf-8")

    definition = get_tool_definition_map()["search_text"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None

    envelope = asyncio.run(
        tool.call(
            {"query": "needle", "paths": ["docs/plan.md"], "head_limit": 1, "context": 1},
            ToolUseContext(workspace_root=backend_dir),
        )
    )
    tool_result = dict(dict(envelope.structured_payload).get("tool_result") or {})

    assert envelope.text == "docs/plan.md:2:1:needle here"
    assert tool_result["applied_limit"] == 1
    assert tool_result["recommended_read_windows"] == [
        {"path": "docs/plan.md", "start_line": 1, "line_count": 3, "reason": "match near line 2"}
    ]


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


def _read_file_text(root_dir: Path, path: str, *, start_line: int = 1, line_count: int = 240) -> str:
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    envelope = asyncio.run(
        tool.call(
            {"path": path, "start_line": start_line, "line_count": line_count},
            ToolUseContext(workspace_root=root_dir),
        )
    )
    return envelope.text


