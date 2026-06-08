from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.file_changes import FileChangeConflict, FileChangeTracker
from runtime.tool_runtime.native_tools import NativeEditFileTool, NativePythonReplTool, NativeTerminalTool, NativeWriteFileTool
from runtime.tool_runtime.tool_use_context import ToolUseContext


def test_write_file_records_diff_snapshot_and_rollback_restores_previous_content(tmp_path: Path) -> None:
    context = _tool_context(tmp_path)
    write_tool = _tool("write_file", "op.write_file")
    tracker = FileChangeTracker(tmp_path)

    first = write_tool._call_sync({"path": "src/app.txt", "content": "before"}, context)
    second = write_tool._call_sync({"path": "src/app.txt", "content": "after"}, context)

    assert first.status == "ok"
    assert second.status == "ok"
    file_change = second.structured_payload["file_change"]
    record = file_change["record"]
    assert file_change["status"] == "recorded"
    assert record["before_exists"] is True
    assert record["logical_path"] == "src/app.txt"
    assert Path(record["before_snapshot_path"]).read_text(encoding="utf-8") == "before"
    assert Path(record["after_snapshot_path"]).read_text(encoding="utf-8") == "after"
    assert file_change["frontend_diff"]["api_path"] == f"/file-changes/{record['record_id']}/diff"
    assert "vscode_diff_command" not in file_change

    rolled_back = tracker.rollback(record["record_id"])

    assert rolled_back["status"] == "rolled_back"
    assert (tmp_path / "src" / "app.txt").read_text(encoding="utf-8") == "before"


def test_rollback_rejects_when_target_changed_after_record(tmp_path: Path) -> None:
    context = _tool_context(tmp_path)
    write_tool = _tool("write_file", "op.write_file")
    tracker = FileChangeTracker(tmp_path)

    write_tool._call_sync({"path": "src/app.txt", "content": "before"}, context)
    result = write_tool._call_sync({"path": "src/app.txt", "content": "after"}, context)
    record_id = result.structured_payload["file_change"]["record"]["record_id"]
    (tmp_path / "src" / "app.txt").write_text("user changed later", encoding="utf-8")

    with pytest.raises(FileChangeConflict):
        tracker.rollback(record_id)


def test_edit_file_records_diff_snapshot(tmp_path: Path) -> None:
    context = _tool_context(tmp_path)
    write_tool = _tool("write_file", "op.write_file")
    edit_tool = _tool("edit_file", "op.edit_file")
    write_tool._call_sync({"path": "src/app.txt", "content": "hello world"}, context)

    result = edit_tool._call_sync(
        {"path": "src/app.txt", "old_text": "world", "new_text": "agent"},
        context,
    )

    record = result.structured_payload["file_change"]["record"]
    assert result.status == "ok"
    assert Path(record["before_snapshot_path"]).read_text(encoding="utf-8") == "hello world"
    assert Path(record["after_snapshot_path"]).read_text(encoding="utf-8") == "hello agent"


def test_tool_change_records_use_runtime_base_dir_when_workspace_is_separate(tmp_path: Path) -> None:
    runtime_base_dir = tmp_path / "backend"
    workspace_root = tmp_path / "project"
    runtime_base_dir.mkdir()
    workspace_root.mkdir()
    context = _tool_context(workspace_root, runtime_base_dir=runtime_base_dir)
    write_tool = _tool("write_file", "op.write_file")

    result = write_tool._call_sync({"path": "src/app.txt", "content": "after"}, context)

    assert result.status == "ok"
    record_id = result.structured_payload["file_change"]["record"]["record_id"]
    runtime_tracker = FileChangeTracker(runtime_base_dir)
    workspace_tracker = FileChangeTracker(workspace_root)
    assert runtime_tracker.require_record(record_id)["logical_path"] == "src/app.txt"
    with pytest.raises(FileNotFoundError):
        workspace_tracker.require_record(record_id)


def test_terminal_records_command_text_file_changes(tmp_path: Path) -> None:
    context = _tool_context(tmp_path)
    terminal_tool = _tool("terminal", "op.terminal")

    result = terminal_tool._call_sync({"command": "Set-Content -Path 'generated.txt' -Value 'from terminal'"}, context)

    assert result.status == "ok"
    payload = result.structured_payload["file_changes"]
    assert payload["record_count"] == 1
    record = payload["records"][0]
    assert record["logical_path"] == "generated.txt"
    assert record["before_exists"] is False
    assert record["after_exists"] is True
    assert payload["frontend_diffs"][0]["api_path"] == f"/file-changes/{record['record_id']}/diff"
    assert "vscode_diff_command" not in payload


def test_python_repl_records_text_file_changes(tmp_path: Path) -> None:
    context = _tool_context(tmp_path)
    python_tool = _tool("python_repl", "op.python_repl")

    result = python_tool._call_sync(
        {
            "code": "from pathlib import Path\nPath('generated.py').write_text('from python', encoding='utf-8')",
        },
        context,
    )

    assert result.status == "ok"
    payload = result.structured_payload["file_changes"]
    assert payload["record_count"] == 1
    record = payload["records"][0]
    assert record["logical_path"] == "generated.py"
    assert record["before_exists"] is False
    assert record["after_exists"] is True
    assert payload["frontend_diffs"][0]["api_path"] == f"/file-changes/{record['record_id']}/diff"
    assert "vscode_diff_command" not in payload


def _tool(name: str, operation_id: str):
    definition = SimpleNamespace(
        name=name,
        operation_id=operation_id,
        contract=SimpleNamespace(required_inputs=[]),
    )
    if name == "write_file":
        return NativeWriteFileTool(definition)
    if name == "terminal":
        return NativeTerminalTool(definition)
    if name == "python_repl":
        return NativePythonReplTool(definition)
    return NativeEditFileTool(definition)


def _tool_context(workspace_root: Path, *, runtime_base_dir: Path | None = None) -> ToolUseContext:
    return ToolUseContext(
        workspace_root=workspace_root,
        runtime_base_dir=str(runtime_base_dir or ""),
        session_id="session-change",
        task_run_id="taskrun-change",
        agent_run_id="agentrun-change",
        tool_call_id="toolcall-change",
        sandbox_policy={"workspace_root": str(workspace_root), "session_id": "session-change"},
        environment_snapshot={"workspace_root": str(workspace_root)},
        execution_receipt={
            "tool_call_id": "toolcall-change",
            "request_ref": "request-change",
            "caller_kind": "agent_turn",
            "caller_ref": "turn-change",
        },
    )
