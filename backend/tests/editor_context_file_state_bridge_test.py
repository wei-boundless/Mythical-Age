from __future__ import annotations

from pathlib import Path

from harness.runtime.dynamic_context.manager import DynamicContextManager
from harness.runtime.dynamic_context.models import DynamicContextInput
from runtime.memory.file_evidence_scope import task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore


def test_editor_context_bridges_active_file_into_task_file_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    storage_root = tmp_path / "runtime-state"
    active_path = workspace / "src" / "app.py"
    active_path.parent.mkdir(parents=True)
    active_path.write_text("print('saved')\n", encoding="utf-8")

    projection = DynamicContextManager(base_dir=workspace).project(
        DynamicContextInput(
            invocation_kind="task_execution",
            session_id="session:editor-bridge",
            task_run_id="taskrun:editor-bridge",
            task_run={"task_run_id": "taskrun:editor-bridge"},
            execution_state={"system_projection": {"runtime_status": "running"}},
            runtime_assembly={
                "task_environment": {
                    "storage_space": {"runtime_state_root": str(storage_root)},
                },
            },
            editor_context={
                "source": "vscode",
                "workspace_roots": [str(workspace)],
                "active_file": {
                    "path": str(active_path),
                    "language_id": "python",
                    "dirty": True,
                    "selection": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 12},
                        "text": "print('dirty')",
                        "truncated": False,
                    },
                    "content_preview": {
                        "text": "print('saved')\nprint('dirty')\n",
                        "truncated": False,
                        "source": "dirty_buffer",
                    },
                    "visible_ranges": [
                        {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 2, "character": 0},
                        }
                    ],
                },
                "visible_files": [
                    {"path": str(active_path), "language_id": "python", "dirty": True},
                ],
                "diagnostics": [],
            },
        )
    )

    file_state = projection.volatile_state_projection["task_state"]["file_state"]

    assert projection.volatile_state_projection["task_state"]["file_state_source"] == "editor_context"
    assert file_state[0]["path"] == "src/app.py"
    assert file_state[0]["status"] == "editor_dirty"
    assert file_state[0]["editor_state"]["source"] == "vscode.editor_context"
    assert file_state[0]["editor_state"]["dirty"] is True
    assert file_state[0]["editor_state"]["content_preview"]["source"] == "dirty_buffer"
    assert file_state[0]["stale_reason"] == "editor buffer is dirty; disk reads may be stale"
    assert any(item["source"] == "editor_selection" for item in file_state[0]["read_ranges"])


def test_editor_context_file_state_does_not_replace_stored_read_file_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    storage_root = tmp_path / "runtime-state"
    workspace.mkdir()
    scope = task_run_file_evidence_scope("taskrun:editor-merge")
    FileStateAuthorityStore(storage_root).apply_events_scope(
        scope,
        [
            {
                "event_type": "read",
                "path": "src/app.py",
                "start_line": 1,
                "end_line": 20,
                "total_lines": 100,
                "has_more": True,
                "content_sha256": "sha256:persisted",
            }
        ],
        observation_ref="obs:read",
        tool_call_id="call:read",
    )
    persisted_file_state = FileStateAuthorityStore(storage_root).snapshot_scope(scope)

    projection = DynamicContextManager(base_dir=workspace).project(
        DynamicContextInput(
            invocation_kind="task_execution",
            session_id="session:editor-merge",
            task_run_id="taskrun:editor-merge",
            task_run={"task_run_id": "taskrun:editor-merge"},
            execution_state={
                "system_projection": {
                    "runtime_status": "running",
                    "file_state": persisted_file_state,
                    "file_state_source": "runtime.memory.file_state_store",
                }
            },
            runtime_assembly={
                "task_environment": {
                },
            },
            editor_context={
                "source": "vscode",
                "workspace_roots": [str(workspace)],
                "active_file": {
                    "path": str(workspace / "src" / "app.py"),
                    "language_id": "python",
                    "dirty": False,
                    "content_preview": {"text": "line1\nline2\n", "truncated": False, "source": "saved_document"},
                    "visible_ranges": [],
                },
                "visible_files": [],
                "diagnostics": [],
            },
        )
    )

    file_state = projection.volatile_state_projection["task_state"]["file_state"]

    assert projection.volatile_state_projection["task_state"]["file_state_source"] == "runtime.memory.file_state_store+editor_context"
    assert file_state[0]["path"] == "src/app.py"
    assert file_state[0]["status"] == "partial"
    assert file_state[0]["read_ranges"][0]["observation_ref"] == "obs:read"
    assert file_state[0]["editor_state"]["active"] is True


def test_file_state_still_absent_without_vscode_or_read_file_state(tmp_path: Path) -> None:
    storage_root = tmp_path / "runtime-state"
    FileStateAuthorityStore(storage_root).apply_events_scope(
        task_run_file_evidence_scope("taskrun:no-editor"),
        [
            {
                "event_type": "read",
                "path": "src/app.py",
                "start_line": 1,
                "end_line": 10,
                "total_lines": 20,
                "has_more": True,
                "content_sha256": "sha256:must-not-be-read-from-environment",
            }
        ],
        observation_ref="obs:read",
        tool_call_id="call:read",
    )

    projection = DynamicContextManager(base_dir=tmp_path).project(
        DynamicContextInput(
            invocation_kind="task_execution",
            session_id="session:no-editor",
            task_run_id="taskrun:no-editor",
            task_run={"task_run_id": "taskrun:no-editor"},
            execution_state={"system_projection": {"runtime_status": "running"}},
            runtime_assembly={
                "task_environment": {
                    "storage_space": {"runtime_state_root": str(storage_root)},
                },
            },
        )
    )

    assert "file_state" not in projection.volatile_state_projection["task_state"]
