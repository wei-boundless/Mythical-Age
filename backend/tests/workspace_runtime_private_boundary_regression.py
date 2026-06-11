from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.native_tool_catalog import get_tool_definition_map
from capability_system.tools.tool_units.file_system_tools import GlobPathsTool, ListDirTool, PathExistsTool, StatPathTool
from capability_system.tools.tool_units.search_files_tool import SearchFilesTool, SearchTextTool
from capability_system.tools.tool_units.write_file_tool import EditFileTool, WriteFileTool
from capability_system.tools.workspace_file_service import RUNTIME_PRIVATE_PATH_ERROR, WorkspaceFileService
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_use_context import ToolUseContext


def test_workspace_file_service_blocks_runtime_private_paths_even_when_explicit(tmp_path: Path) -> None:
    backend_dir, private_file = _seed_workspace(tmp_path)
    service = WorkspaceFileService(backend_dir)

    assert service.is_runtime_private_path(private_file)
    with pytest.raises(ValueError, match=RUNTIME_PRIVATE_PATH_ERROR):
        service.resolve("storage/runtime_state/dynamic_context/replacements/replacement_secret.json", require_path=True)
    with pytest.raises(ValueError, match=RUNTIME_PRIVATE_PATH_ERROR):
        service.read_text(private_file)
    with pytest.raises(ValueError, match=RUNTIME_PRIVATE_PATH_ERROR):
        service.write_text("storage/runtime_state/new.json", "bad", allow_overwrite=True)
    with pytest.raises(ValueError, match=RUNTIME_PRIVATE_PATH_ERROR):
        service.edit_text("storage/runtime_state/dynamic_context/replacements/replacement_secret.json", "secret", "bad")
    with pytest.raises(ValueError, match=RUNTIME_PRIVATE_PATH_ERROR):
        service.path_info("storage/runtime_state/dynamic_context/replacements/replacement_secret.json")
    with pytest.raises(ValueError, match=RUNTIME_PRIVATE_PATH_ERROR):
        service.exists("storage/runtime_state/dynamic_context/replacements/replacement_secret.json")

    assert "storage/runtime_state/dynamic_context/replacements/replacement_secret.json" not in service.glob_paths(
        "storage/runtime_state/**/*.json",
        max_results=20,
    )
    assert [item.name for item in service.list_dir("storage")] == ["public"]


def test_langchain_workspace_tools_do_not_expose_runtime_private_paths(tmp_path: Path) -> None:
    backend_dir, _private_file = _seed_workspace(tmp_path)

    langchain_search_result = SearchFilesTool(root_dir=backend_dir).invoke(
        {"query": "replacement_secret", "roots": ["storage"], "max_results": 20}
    )
    assert "storage/runtime_state" not in langchain_search_result
    assert "replacement_secret.json" not in langchain_search_result
    explicit_search = SearchTextTool(root_dir=backend_dir).invoke(
        {
            "query": "secret",
            "paths": ["storage/runtime_state/dynamic_context/replacements/replacement_secret.json"],
        }
    )
    assert RUNTIME_PRIVATE_PATH_ERROR in explicit_search
    assert GlobPathsTool(root_dir=backend_dir).invoke(
        {"pattern": "storage/runtime_state/**/*.json", "max_results": 20}
    ) == "No paths matched."
    assert ListDirTool(root_dir=backend_dir).invoke({"path": "storage", "max_entries": 20}).splitlines() == [
        "dir\tstorage/public"
    ]
    assert RUNTIME_PRIVATE_PATH_ERROR in StatPathTool(root_dir=backend_dir).invoke(
        {"path": "storage/runtime_state/dynamic_context/replacements/replacement_secret.json"}
    )
    assert RUNTIME_PRIVATE_PATH_ERROR in PathExistsTool(root_dir=backend_dir).invoke(
        {"path": "storage/runtime_state/dynamic_context/replacements/replacement_secret.json"}
    )
    assert RUNTIME_PRIVATE_PATH_ERROR in WriteFileTool(root_dir=backend_dir).invoke(
        {"path": "storage/runtime_state/new.json", "content": "bad", "allow_overwrite": True}
    )
    assert RUNTIME_PRIVATE_PATH_ERROR in EditFileTool(root_dir=backend_dir).invoke(
        {
            "path": "storage/runtime_state/dynamic_context/replacements/replacement_secret.json",
            "old_text": "secret",
            "new_text": "bad",
        }
    )


def test_native_workspace_tools_do_not_expose_runtime_private_paths(tmp_path: Path) -> None:
    backend_dir, _private_file = _seed_workspace(tmp_path)

    native_search_result = _call_native(backend_dir, "search_files", {"query": "replacement_secret", "roots": ["storage"]}).text
    assert "storage/runtime_state" not in native_search_result
    assert "replacement_secret.json" not in native_search_result
    explicit_search = _call_native(
        backend_dir,
        "search_text",
        {
            "query": "secret",
            "paths": ["storage/runtime_state/dynamic_context/replacements/replacement_secret.json"],
        },
    )
    assert explicit_search.status == "error"
    assert RUNTIME_PRIVATE_PATH_ERROR in explicit_search.text
    assert _call_native(
        backend_dir,
        "glob_paths",
        {"pattern": "storage/runtime_state/**/*.json", "max_results": 20},
    ).text == "No paths matched."
    assert _call_native(backend_dir, "list_dir", {"path": "storage", "max_entries": 20}).text == "dir\tstorage/public\t0 bytes"
    assert _call_native(
        backend_dir,
        "stat_path",
        {"path": "storage/runtime_state/dynamic_context/replacements/replacement_secret.json"},
    ).status == "error"
    assert _call_native(
        backend_dir,
        "path_exists",
        {"path": "storage/runtime_state/dynamic_context/replacements/replacement_secret.json"},
    ).status == "error"
    assert _call_native(
        backend_dir,
        "read_file",
        {"path": "storage/runtime_state/dynamic_context/replacements/replacement_secret.json"},
    ).status == "error"
    assert _call_native(
        backend_dir,
        "write_file",
        {"path": "storage/runtime_state/new.json", "content": "bad", "allow_overwrite": True},
    ).status == "error"
    assert _call_native(
        backend_dir,
        "edit_file",
        {
            "path": "storage/runtime_state/dynamic_context/replacements/replacement_secret.json",
            "old_text": "secret",
            "new_text": "bad",
        },
    ).status == "error"


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    private_file = workspace / "storage" / "runtime_state" / "dynamic_context" / "replacements" / "replacement_secret.json"
    tool_result_file = workspace / "runtime_state" / "tool_results" / "session" / "content-secret.txt"
    public_file = workspace / "storage" / "public" / "note.txt"
    backend_dir.mkdir(parents=True)
    private_file.parent.mkdir(parents=True)
    tool_result_file.parent.mkdir(parents=True)
    public_file.parent.mkdir(parents=True)
    private_file.write_text('{"secret": true}', encoding="utf-8")
    tool_result_file.write_text("secret tool result", encoding="utf-8")
    public_file.write_text("public", encoding="utf-8")
    return backend_dir, private_file


def _call_native(backend_dir: Path, tool_name: str, args: dict[str, object]):
    definition = get_tool_definition_map()[tool_name]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    return asyncio.run(tool.call(args, ToolUseContext(workspace_root=backend_dir)))
