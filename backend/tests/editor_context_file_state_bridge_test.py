from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.dynamic_context.manager import DynamicContextManager
from harness.runtime.dynamic_context.models import DynamicContextInput
from runtime.memory.file_evidence_scope import task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore


def test_editor_context_projects_as_index_and_current_evidence_delta(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    storage_root = tmp_path / "runtime-state"
    active_path = workspace / "src" / "app.py"
    open_path = workspace / "src" / "settings.py"
    active_path.parent.mkdir(parents=True)
    active_path.write_text("print('saved')\n", encoding="utf-8")
    open_path.write_text("SETTING = True\n", encoding="utf-8")

    projection = DynamicContextManager(base_dir=workspace).project(
        DynamicContextInput(
            invocation_kind="task_execution",
            session_id="session:editor-index",
            task_run_id="taskrun:editor-index",
            task_run={"task_run_id": "taskrun:editor-index"},
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
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 14},
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
                "open_tabs": [
                    {"path": str(active_path), "label": "app.py", "language_id": "python", "dirty": True, "active": True, "visible": True},
                    {"path": str(open_path), "label": "settings.py", "language_id": "python", "dirty": False, "active": False, "visible": False},
                ],
                "diagnostics": [],
            },
        )
    )

    volatile = projection.volatile_state_projection
    task_state = volatile["task_state"]
    editor_index = volatile["editor_context_index"]
    editor_delta = volatile["current_editor_evidence_delta"]

    assert "file_state" not in task_state
    assert editor_index[0]["path"] == "src/app.py"
    assert editor_index[0]["active_tab"] is True
    assert editor_index[0]["dirty"] is True
    assert editor_index[0]["freshness"] == "buffer_newer_than_disk"
    assert editor_index[0]["selection_ranges_ref"].startswith("edsel:src/app.py:")
    assert editor_index[0]["visible_ranges_ref"].startswith("edvis:src/app.py:")
    assert editor_index[1]["path"] == "src/settings.py"
    assert editor_index[1]["open"] is True
    assert "print('dirty')" not in json.dumps(editor_index, ensure_ascii=False)
    assert "content_preview" not in json.dumps(editor_index, ensure_ascii=False)

    event = editor_delta["events"][0]
    assert event["event"] == "editor_selection_visible"
    assert event["path"] == "src/app.py"
    assert event["range"] == {"start_line": 1, "end_line": 1}
    assert event["visible_text_status"] == "exact_visible_in_current_packet"
    assert event["text"] == "print('dirty')"
    assert event["evidence_ref"].startswith("ev:editor:src/app.py:")


def test_editor_context_does_not_replace_stored_read_file_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    storage_root = tmp_path / "runtime-state"
    workspace.mkdir()
    scope = task_run_file_evidence_scope("taskrun:editor-separate")
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
            session_id="session:editor-separate",
            task_run_id="taskrun:editor-separate",
            task_run={"task_run_id": "taskrun:editor-separate"},
            execution_state={
                "system_projection": {
                    "runtime_status": "running",
                    "file_state": persisted_file_state,
                    "file_state_source": "runtime.memory.file_state_store",
                }
            },
            runtime_assembly={
                "task_environment": {},
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

    volatile = projection.volatile_state_projection
    evidence_index = volatile["evidence_index_cursor"]
    file_state = evidence_index["files"]
    editor_index = volatile["editor_context_index"]

    assert "file_state" not in volatile["task_state"]
    assert evidence_index["file_state_source"] == "runtime.memory.file_state_store"
    assert file_state[0]["path"] == "src/app.py"
    assert file_state[0]["status"] == "partial"
    assert file_state[0]["read_window_refs"][0]["observation_ref"] == "obs:read"
    assert "editor_state" not in file_state[0]
    assert editor_index[0]["path"] == "src/app.py"
    assert editor_index[0]["freshness"] == "editor_snapshot_saved_document"


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
    assert "editor_context_index" not in projection.volatile_state_projection


def test_runtime_compiler_emits_editor_context_segments_outside_current_state() -> None:
    editor_context = {
        "source": "vscode",
        "workspace_roots": ["D:/repo"],
        "active_file": {
            "path": "D:/repo/src/app.py",
            "language_id": "python",
            "dirty": True,
            "selection": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 8},
                "text": "print(1)",
                "truncated": False,
            },
            "content_preview": {
                "text": "print(1)\n",
                "truncated": False,
                "source": "dirty_buffer",
            },
            "visible_ranges": [
                {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 1, "character": 0},
                }
            ],
        },
        "open_tabs": [
            {"path": "D:/repo/src/app.py", "language_id": "python", "dirty": True, "active": True, "visible": True}
        ],
        "diagnostics": [],
    }

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:editor-compiler",
        task_run={
            "task_run_id": "taskrun:editor-compiler",
            "diagnostics": {"executor_status": "running", "editor_context": editor_context},
        },
        contract={"task_run_goal": "verify editor context assembly", "completion_criteria": ["compiled"]},
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    kinds = [segment["kind"] for segment in result.packet.segment_plan["segments"]]
    editor_index_segment = _segment_by_kind(result.packet, "editor_context_index")
    editor_delta_segment = _segment_by_kind(result.packet, "current_editor_evidence_delta")
    current_state = _payload_with_title(result.packet, "Task execution current state")
    editor_index = _payload_with_title(result.packet, "Task execution editor context index")
    editor_delta = _payload_with_title(result.packet, "Task execution current editor evidence delta")

    assert kinds.index("editor_context_index") < kinds.index("current_editor_evidence_delta")
    assert kinds.index("current_editor_evidence_delta") < kinds.index("volatile_task_state")
    assert editor_index_segment["cache_role"] == "volatile"
    assert editor_index_segment["metadata"]["prompt_assembly_layer"] == "editor_context_index"
    assert editor_delta_segment["metadata"]["prompt_assembly_layer"] == "current_exact_evidence"
    assert "editor_context_index" not in current_state
    assert "current_editor_evidence_delta" not in current_state
    assert editor_index["editor_context_index"][0]["path"] == "src/app.py"
    assert "print(1)" not in json.dumps(editor_index, ensure_ascii=False)
    assert editor_delta["current_editor_evidence_delta"]["events"][0]["text"] == "print(1)"


def _segment_by_kind(packet, kind: str) -> dict[str, object]:
    for segment in packet.segment_plan["segments"]:
        if segment["kind"] == kind:
            return dict(segment)
    raise AssertionError(f"missing segment kind: {kind}")


def _payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    raise AssertionError(f"missing model message title: {title}")
