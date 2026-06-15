from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.authorization import build_tool_authorization_index
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definition_map, get_tool_definitions
from capability_system.tools.native_tool_runtime import ToolRuntime
from harness.runtime.assembly import assemble_runtime
from harness.runtime.dynamic_context.manager import DynamicContextManager
from harness.runtime.dynamic_context.models import DynamicContextInput
from harness.runtime.dynamic_context.replacement_store import ReplacementStore
from harness.runtime.dynamic_context.tool_result_projector import ToolResultProjector
from orchestration.runtime_directive import RuntimeDirective
from runtime.memory.file_evidence_scope import session_file_evidence_scope, task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import RuntimeExecutionStore, build_idempotency_token, build_request_fingerprint
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_executor import ToolRuntimeExecutor
from runtime.tool_runtime.tool_use_context import ToolUseContext
from runtime_objects.read_observation_artifacts import ReadObservationArtifactStore


def test_read_file_is_native_only_but_model_visible_with_schema() -> None:
    definitions = get_tool_definition_map()
    read_file = definitions["read_file"]

    assert read_file.native_runtime_only is True
    assert read_file.factory is None
    assert all(str(getattr(tool, "name", "") or "") != "read_file" for tool in build_tool_instances(BACKEND_DIR))

    profile = SimpleNamespace(
        agent_profile_id="read-file-authority-agent",
        allowed_operations=("op.model_response", "op.read_file"),
        blocked_operations=(),
        metadata={},
    )
    index = build_tool_authorization_index(get_tool_definitions())
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session-read-file-authority",
        turn_id="turn-read-file-authority",
        agent_invocation_id="agent-invocation-read-file-authority",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    ).to_dict()

    tools = {str(item.get("tool_name") or ""): dict(item) for item in list(assembly.get("available_tools") or [])}
    schema = dict(tools["read_file"].get("input_schema") or {})
    properties = dict(schema.get("properties") or {})

    assert "read_file" in tools
    assert schema["required"] == ["path"]
    assert schema["additionalProperties"] is False
    assert set(properties) == {"path", "start_line", "line_count", "read_intent"}
    assert properties["start_line"]["type"] == "integer"
    assert properties["read_intent"]["enum"] == [
        "edit_target",
        "verify_behavior",
        "understand_api",
        "locate_symbol",
        "inspect_dependency",
        "recover_failure",
    ]
    assert ToolRuntime(BACKEND_DIR).get_instance("read_file") is None
    assert ToolRuntime(BACKEND_DIR).get_definition("read_file") is not None


def test_read_persisted_tool_result_is_native_only_with_no_basetool_chain() -> None:
    definitions = get_tool_definition_map()
    rehydrator = definitions["read_persisted_tool_result"]

    assert rehydrator.native_runtime_only is True
    assert rehydrator.factory is None
    assert all(str(getattr(tool, "name", "") or "") != "read_persisted_tool_result" for tool in build_tool_instances(BACKEND_DIR))
    assert ToolRuntime(BACKEND_DIR).get_instance("read_persisted_tool_result") is None
    assert build_native_runtime_tool(capability_definition=rehydrator) is not None


def test_native_read_file_agent_turn_returns_structured_window_and_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta\ngamma", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None

    envelope = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 2, "line_count": 1},
            ToolUseContext(
                workspace_root=workspace,
                caller_kind="agent_turn",
                caller_ref="turn:read-file",
                tool_call_id="call:agent-read",
                execution_receipt={
                    "caller_kind": "agent_turn",
                    "caller_ref": "turn:read-file",
                    "tool_call_id": "call:agent-read",
                    "request_ref": "rtact:agent-read",
                },
            ),
        )
    )

    tool_result = envelope.structured_payload["tool_result"]
    event = envelope.file_state_events[0]

    assert envelope.text == "2 | beta"
    assert tool_result["authority"] == "runtime.tool_result.read_file_window.v1"
    assert tool_result["path"] == "notes.txt"
    assert tool_result["content_sha256"]
    assert tool_result["start_line"] == 2
    assert tool_result["end_line"] == 2
    assert tool_result["has_more"] is True
    assert event["event_type"] == "read"
    assert event["path"] == "notes.txt"
    assert event["content_sha256"] == tool_result["content_sha256"]


def test_native_read_file_writes_observation_to_runtime_assembly_root_before_file_policy_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    file_policy_state = tmp_path / "file_policy_state"
    workspace.mkdir()
    runtime_state.mkdir()
    file_policy_state.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    scope = session_file_evidence_scope("session:runtime-root-priority")

    envelope = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2},
            ToolUseContext(
                workspace_root=workspace,
                caller_kind="agent_turn",
                caller_ref="turnrun:runtime-root-priority",
                session_id="session:runtime-root-priority",
                tool_call_id="call:read-runtime-root-priority",
                file_evidence_scope=scope,
                runtime_assembly={
                    "runtime_storage_ref": {"runtime_state_root": str(runtime_state)},
                    "task_environment": {"storage_space": {"runtime_state_root": str(runtime_state)}},
                },
                file_management_policy={"storage_space": {"runtime_state_root": str(file_policy_state)}},
            ),
        )
    )
    artifact_ref = envelope.structured_payload["tool_result"]["exact_artifact_ref"]

    assert ReadObservationArtifactStore(runtime_state).artifact_exists(artifact_ref)
    assert not ReadObservationArtifactStore(file_policy_state).artifact_exists(artifact_ref)


def test_native_read_file_preserves_intent_and_returns_exact_repeated_window(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta\ngamma", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    task_run_id = "taskrun:read-file-unchanged"
    scope = task_run_file_evidence_scope(task_run_id)
    context = ToolUseContext(
        workspace_root=workspace,
        task_run_id=task_run_id,
        tool_call_id="call:read-1",
        file_evidence_scope=scope,
        file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
    )

    first = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2, "read_intent": "edit_target"},
            context,
        )
    )
    FileStateAuthorityStore(runtime_state).apply_events_scope(
        scope,
        first.file_state_events,
        observation_ref="obs:first-read",
        tool_call_id="call:read-1",
    )

    second = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read-2",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    tool_result = second.structured_payload["tool_result"]
    event = second.file_state_events[0]

    assert first.text == "1 | alpha\n2 | beta"
    assert second.text == "1 | alpha\n2 | beta"
    assert "file_unchanged" not in tool_result
    assert "content_omitted" not in tool_result
    assert "previous_observation_ref" not in tool_result
    assert tool_result["exact_artifact_ref"].startswith("read_observation:")
    assert tool_result["read_intent"] == "edit_target"
    assert event["read_intent"] == "edit_target"
    assert "file_unchanged" not in event
    assert "content_omitted" not in event


def test_native_read_file_session_scope_returns_exact_repeated_window(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta\ngamma", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    scope = session_file_evidence_scope("session:read-file-unchanged")

    first = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2},
            ToolUseContext(
                workspace_root=workspace,
                caller_kind="agent_turn",
                caller_ref="turnrun:session-read",
                session_id="session:read-file-unchanged",
                tool_call_id="call:session-read-1",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    FileStateAuthorityStore(runtime_state).apply_events_scope(
        scope,
        first.file_state_events,
        observation_ref="obs:session-first-read",
        tool_call_id="call:session-read-1",
    )

    second = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2},
            ToolUseContext(
                workspace_root=workspace,
                caller_kind="agent_turn",
                caller_ref="turnrun:session-read",
                session_id="session:read-file-unchanged",
                tool_call_id="call:session-read-2",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    tool_result = second.structured_payload["tool_result"]

    assert first.text == "1 | alpha\n2 | beta"
    assert second.text == "1 | alpha\n2 | beta"
    assert "file_unchanged" not in tool_result
    assert "content_omitted" not in tool_result
    assert "previous_observation_ref" not in tool_result
    assert tool_result["exact_artifact_ref"].startswith("read_observation:")


def test_native_read_file_returns_exact_subwindow_covered_by_larger_current_read(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta\ngamma", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    task_run_id = "taskrun:read-file-covered-subwindow"
    scope = task_run_file_evidence_scope(task_run_id)

    first = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 3},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read-full",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    FileStateAuthorityStore(runtime_state).apply_events_scope(
        scope,
        first.file_state_events,
        observation_ref="obs:read-full",
        tool_call_id="call:read-full",
    )

    second = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 2, "line_count": 1},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read-subwindow",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    tool_result = dict(second.structured_payload["tool_result"])

    assert first.text == "1 | alpha\n2 | beta\n3 | gamma"
    assert second.text == "2 | beta"
    assert "file_unchanged" not in tool_result
    assert "content_omitted" not in tool_result
    assert "covered_by_previous_read" not in tool_result
    assert "previous_observation_ref" not in tool_result
    assert tool_result["exact_artifact_ref"].startswith("read_observation:")


def test_read_file_projection_does_not_create_generic_persisted_output(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    content = "\n".join(f"value_{line} = {line}" for line in range(1, 90))
    (workspace / "notes.py").write_text(content, encoding="utf-8")
    reader = build_native_runtime_tool(capability_definition=get_tool_definition_map()["read_file"])
    assert reader is not None
    task_run_id = "taskrun:read-file-no-generic-persist"
    scope = task_run_file_evidence_scope(task_run_id)
    context = ToolUseContext(
        workspace_root=workspace,
        task_run_id=task_run_id,
        tool_call_id="call:read",
        file_evidence_scope=scope,
        file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
    )

    read = asyncio.run(reader.call({"path": "notes.py", "start_line": 1, "line_count": 89, "read_intent": "edit_target"}, context))
    store = FileStateAuthorityStore(runtime_state)
    store.apply_events_scope(scope, read.file_state_events, observation_ref="obs:read-large", tool_call_id="call:read")
    projection, _ = ToolResultProjector(
        root_dir=runtime_state,
        replacement_store=ReplacementStore(runtime_state),
    ).project(
        {"result_envelope": read.to_dict()},
        task_run_id=task_run_id,
        projection_policy={"tool_result_preview_chars": 160},
    )

    tool_result = read.structured_payload["tool_result"]
    state = store.snapshot_scope(scope)[0]

    assert read.status == "ok"
    assert tool_result["exact_artifact_ref"].startswith("read_observation:")
    assert tool_result["visible_exact"] is True
    assert "content_replacements" not in projection
    assert projection["preview"] == read.text
    assert projection["evidence_policy"]["visible_content_authority"] == "exact_visible_line_window"
    assert projection["rehydration_plan"]["capabilities"][0]["capability"] == "read_file_range"
    assert state["read_ranges"][0]["exact_artifact_ref"] == tool_result["exact_artifact_ref"]
    assert state["read_ranges"][0]["visible_exact"] is True


def test_generic_persisted_output_does_not_emit_file_read_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    definitions = get_tool_definition_map()
    rehydrator = build_native_runtime_tool(capability_definition=definitions["read_persisted_tool_result"])
    assert rehydrator is not None
    task_run_id = "taskrun:generic-persisted-no-file-state"
    scope = task_run_file_evidence_scope(task_run_id)
    large_output = "diagnostic\n" * 500
    projection, _ = ToolResultProjector(
        root_dir=runtime_state,
        replacement_store=ReplacementStore(runtime_state),
    ).project(
        {
            "result_envelope": {
                "envelope_id": "tool-result:terminal-large",
                "tool_name": "terminal",
                "status": "ok",
                "text": large_output,
            }
        },
        task_run_id=task_run_id,
        projection_policy={"tool_result_preview_chars": 160},
    )
    replacement = projection["content_replacements"][0]

    restored = asyncio.run(
        rehydrator.call(
            {
                "replacement_id": replacement["replacement_id"],
                "path": replacement["path"],
                "task_run_id": task_run_id,
            },
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:rehydrate",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )

    assert restored.status == "ok"
    assert "diagnostic" in restored.text
    assert restored.file_state_events == ()
    assert FileStateAuthorityStore(runtime_state).snapshot_scope(scope) == []


def test_native_edit_file_requires_current_read_for_existing_non_empty_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("hello old", encoding="utf-8")
    definition = get_tool_definition_map()["edit_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None

    result = asyncio.run(
        tool.call(
            {"path": "notes.txt", "old_text": "old", "new_text": "new"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id="taskrun:edit-requires-read",
                tool_call_id="call:edit",
                file_evidence_scope=task_run_file_evidence_scope("taskrun:edit-requires-read"),
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )

    assert result.status == "error"
    assert result.structured_payload["structured_error"]["code"] == "edit_file_requires_current_read"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello old"


def test_native_edit_file_rejects_empty_old_text_for_existing_non_empty_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("hello old", encoding="utf-8")
    definition = get_tool_definition_map()["edit_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None

    result = asyncio.run(
        tool.call(
            {"path": "notes.txt", "old_text": "", "new_text": "replacement"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id="taskrun:edit-empty-old-nonempty",
                tool_call_id="call:edit",
                file_evidence_scope=task_run_file_evidence_scope("taskrun:edit-empty-old-nonempty"),
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )

    assert result.status == "error"
    assert result.structured_payload["structured_error"]["code"] == "edit_file_empty_old_text_requires_empty_or_new_target"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello old"


def test_native_edit_file_uses_read_evidence_and_updates_current_file_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("hello old", encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    editor = build_native_runtime_tool(capability_definition=definitions["edit_file"])
    assert reader is not None
    assert editor is not None
    task_run_id = "taskrun:edit-after-read"
    scope = task_run_file_evidence_scope(task_run_id)

    read = asyncio.run(
        reader.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 1, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    store = FileStateAuthorityStore(runtime_state)
    store.apply_events_scope(scope, read.file_state_events, observation_ref="obs:read", tool_call_id="call:read")

    edit = asyncio.run(
        editor.call(
            {"path": "notes.txt", "old_text": "old", "new_text": "new"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:edit",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    state = store.apply_events_scope(scope, edit.file_state_events, observation_ref="obs:edit", tool_call_id="call:edit").projection()[0]
    active_ranges = [item for item in state["read_ranges"] if item.get("stale") is not True]

    assert edit.status == "ok"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello new"
    assert [event["event_type"] for event in edit.file_state_events] == ["edit", "read"]
    assert state["status"] == "complete"
    assert state["content_sha256"] == edit.structured_payload["tool_result"]["sha256"]
    assert len(active_ranges) == 1
    assert active_ranges[0]["start_line"] == 1
    assert active_ranges[0]["end_line"] == 1
    assert active_ranges[0]["observation_ref"] == "obs:edit"
    assert active_ranges[0]["content_sha256"] == edit.structured_payload["tool_result"]["sha256"]
    assert active_ranges[0]["mtime_ns"] == edit.structured_payload["tool_result"]["mtime_ns"]
    assert active_ranges[0]["read_intent"] == "edit_target"


def test_native_edit_file_prefers_current_read_state_over_stale_storage_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stale_runtime_state = tmp_path / "runtime_state_stale"
    current_runtime_state = tmp_path / "runtime_state_current"
    workspace.mkdir()
    stale_runtime_state.mkdir()
    current_runtime_state.mkdir()
    target = workspace / "notes.txt"
    target.write_text("hello old\n", encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    editor = build_native_runtime_tool(capability_definition=definitions["edit_file"])
    assert reader is not None
    assert editor is not None
    scope = session_file_evidence_scope("session:stale-root")

    stale_store = FileStateAuthorityStore(stale_runtime_state)
    stale_store.apply_events_scope(
        scope,
        (
            {
                "event_type": "read",
                "path": "notes.txt",
                "start_line": 1,
                "end_line": 1,
                "returned_lines": 1,
                "line_count": 1,
                "total_lines": 1,
                "has_more": False,
                "content_sha256": _sha256_text("hello old\n"),
                "mtime_ns": 1,
                "read_intent": "edit_target",
                "exact_artifact_ref": "read_observation:stale",
                "artifact_ref_status": "exact",
                "visible_exact": True,
            },
        ),
        observation_ref="obs:stale-read",
        tool_call_id="call:stale-read",
    )
    read = asyncio.run(
        reader.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 1, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                session_id="session:stale-root",
                tool_call_id="call:current-read",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(current_runtime_state)}},
            ),
        )
    )
    current_state = FileStateAuthorityStore(current_runtime_state).apply_events_scope(
        scope,
        read.file_state_events,
        observation_ref="obs:current-read",
        tool_call_id="call:current-read",
    ).projection()[0]

    edit = asyncio.run(
        editor.call(
            {"path": "notes.txt", "old_text": "old", "new_text": "new"},
            ToolUseContext(
                workspace_root=workspace,
                session_id="session:stale-root",
                tool_call_id="call:edit",
                file_evidence_scope=scope,
                runtime_assembly={
                    "runtime_storage_ref": {"runtime_state_root": str(stale_runtime_state)},
                    "task_environment": {
                        "storage_space": {"runtime_state_root": str(current_runtime_state)}
                    }
                },
            ),
        )
    )

    assert read.status == "ok"
    assert read.file_state_events[0]["mtime_ns"] == read.structured_payload["tool_result"]["mtime_ns"]
    assert current_state["mtime_ns"] == read.structured_payload["tool_result"]["mtime_ns"]
    assert edit.status == "ok"
    assert target.read_text(encoding="utf-8") == "hello new\n"


def test_native_batch_edit_file_applies_multiple_disjoint_edits_atomically(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    target = workspace / "notes.txt"
    target.write_text("alpha old\nbeta old\ngamma stay\n", encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    batch_editor = build_native_runtime_tool(capability_definition=definitions["batch_edit_file"])
    assert reader is not None
    assert batch_editor is not None
    task_run_id = "taskrun:batch-edit-after-read"
    scope = task_run_file_evidence_scope(task_run_id)
    store = FileStateAuthorityStore(runtime_state)

    read = _native_read_for_edit(
        reader=reader,
        workspace=workspace,
        runtime_state=runtime_state,
        scope=scope,
        task_run_id=task_run_id,
        path="notes.txt",
        line_count=3,
    )
    store.apply_events_scope(scope, read.file_state_events, observation_ref="obs:batch-read", tool_call_id="call:batch-read")
    read_result = dict(read.structured_payload["tool_result"])

    edit = asyncio.run(
        batch_editor.call(
            {
                "path": "notes.txt",
                "base_sha256": read_result["content_sha256"],
                "base_mtime_ns": read_result["mtime_ns"],
                "edits": [
                    {"old_text": "alpha old", "new_text": "alpha new"},
                    {"old_text": "beta old", "new_text": "beta new"},
                ],
            },
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:batch-edit",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    state = store.apply_events_scope(scope, edit.file_state_events, observation_ref="obs:batch-edit", tool_call_id="call:batch-edit").projection()[0]
    active_ranges = [item for item in state["read_ranges"] if item.get("stale") is not True]

    assert edit.status == "ok"
    assert target.read_text(encoding="utf-8") == "alpha new\nbeta new\ngamma stay\n"
    assert edit.structured_payload["tool_result"]["kind"] == "file_batch_edit"
    assert edit.structured_payload["tool_result"]["edit_count"] == 2
    assert [event["event_type"] for event in edit.file_state_events] == ["edit", "read"]
    assert state["status"] == "complete"
    assert state["content_sha256"] == edit.structured_payload["tool_result"]["sha256"]
    assert len(active_ranges) == 1
    assert active_ranges[0]["observation_ref"] == "obs:batch-edit"
    assert active_ranges[0]["visible_exact"] is True


def test_native_batch_edit_file_rejects_overlapping_or_non_unique_or_missing_spans_without_partial_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    target = workspace / "notes.txt"
    original = "abcdef\nrepeat\nrepeat\n"
    target.write_text(original, encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    batch_editor = build_native_runtime_tool(capability_definition=definitions["batch_edit_file"])
    assert reader is not None
    assert batch_editor is not None
    task_run_id = "taskrun:batch-edit-rejections"
    scope = task_run_file_evidence_scope(task_run_id)
    store = FileStateAuthorityStore(runtime_state)

    read = _native_read_for_edit(
        reader=reader,
        workspace=workspace,
        runtime_state=runtime_state,
        scope=scope,
        task_run_id=task_run_id,
        path="notes.txt",
        line_count=3,
    )
    store.apply_events_scope(scope, read.file_state_events, observation_ref="obs:batch-reject-read", tool_call_id="call:batch-reject-read")
    read_result = dict(read.structured_payload["tool_result"])
    context = ToolUseContext(
        workspace_root=workspace,
        task_run_id=task_run_id,
        tool_call_id="call:batch-reject-edit",
        file_evidence_scope=scope,
        file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
    )

    overlap = asyncio.run(
        batch_editor.call(
            {
                "path": "notes.txt",
                "base_sha256": read_result["content_sha256"],
                "base_mtime_ns": read_result["mtime_ns"],
                "edits": [
                    {"old_text": "abc", "new_text": "ABC"},
                    {"old_text": "bcde", "new_text": "BCDE"},
                ],
            },
            context,
        )
    )
    non_unique = asyncio.run(
        batch_editor.call(
            {
                "path": "notes.txt",
                "base_sha256": read_result["content_sha256"],
                "base_mtime_ns": read_result["mtime_ns"],
                "edits": [{"old_text": "repeat", "new_text": "single"}],
            },
            context,
        )
    )
    missing = asyncio.run(
        batch_editor.call(
            {
                "path": "notes.txt",
                "base_sha256": read_result["content_sha256"],
                "base_mtime_ns": read_result["mtime_ns"],
                "edits": [{"old_text": "not present", "new_text": "replacement"}],
            },
            context,
        )
    )

    assert overlap.status == "error"
    assert overlap.structured_payload["structured_error"]["code"] == "batch_edit_overlapping_ranges"
    assert non_unique.status == "error"
    assert non_unique.structured_payload["structured_error"]["code"] == "batch_edit_old_text_not_unique"
    assert missing.status == "error"
    assert missing.structured_payload["structured_error"]["code"] == "batch_edit_old_text_not_found"
    assert target.read_text(encoding="utf-8") == original


def test_native_batch_edit_file_rejects_missing_old_text_during_input_validation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    definitions = get_tool_definition_map()
    batch_editor = build_native_runtime_tool(capability_definition=definitions["batch_edit_file"])
    assert batch_editor is not None

    validation = batch_editor.validate_input(
        {"path": "notes.txt", "edits": [{"new_text": "replacement"}]},
        ToolUseContext(
            workspace_root=workspace,
            task_run_id="taskrun:batch-edit-invalid-input",
            tool_call_id="call:batch-edit-invalid-input",
            file_evidence_scope=task_run_file_evidence_scope("taskrun:batch-edit-invalid-input"),
            file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
        ),
    )

    assert validation.allowed is False
    assert validation.reason == "invalid_tool_input"
    assert "old_text" in validation.repair_instruction
    assert not (workspace / "notes.txt").exists()


def test_native_batch_edit_file_rejects_stale_base_hash_or_mtime_without_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    target = workspace / "notes.txt"
    original = "hello old\n"
    target.write_text(original, encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    batch_editor = build_native_runtime_tool(capability_definition=definitions["batch_edit_file"])
    assert reader is not None
    assert batch_editor is not None
    task_run_id = "taskrun:batch-edit-stale-base"
    scope = task_run_file_evidence_scope(task_run_id)
    store = FileStateAuthorityStore(runtime_state)

    read = _native_read_for_edit(
        reader=reader,
        workspace=workspace,
        runtime_state=runtime_state,
        scope=scope,
        task_run_id=task_run_id,
        path="notes.txt",
        line_count=1,
    )
    store.apply_events_scope(scope, read.file_state_events, observation_ref="obs:batch-stale-read", tool_call_id="call:batch-stale-read")
    read_result = dict(read.structured_payload["tool_result"])
    context = ToolUseContext(
        workspace_root=workspace,
        task_run_id=task_run_id,
        tool_call_id="call:batch-stale-edit",
        file_evidence_scope=scope,
        file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
    )

    stale_hash = asyncio.run(
        batch_editor.call(
            {
                "path": "notes.txt",
                "base_sha256": _sha256_text("older version"),
                "base_mtime_ns": read_result["mtime_ns"],
                "edits": [{"old_text": "old", "new_text": "new"}],
            },
            context,
        )
    )
    stale_mtime = asyncio.run(
        batch_editor.call(
            {
                "path": "notes.txt",
                "base_sha256": read_result["content_sha256"],
                "base_mtime_ns": int(read_result["mtime_ns"]) - 1,
                "edits": [{"old_text": "old", "new_text": "new"}],
            },
            context,
        )
    )

    assert stale_hash.status == "error"
    assert stale_hash.structured_payload["structured_error"]["code"] == "batch_edit_base_sha256_mismatch"
    assert stale_mtime.status == "error"
    assert stale_mtime.structured_payload["structured_error"]["code"] == "batch_edit_base_mtime_mismatch"
    assert target.read_text(encoding="utf-8") == original


def test_native_edit_file_can_continue_after_post_edit_read_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    target = workspace / "notes.txt"
    target.write_text("first old\nsecond old\n", encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    editor = build_native_runtime_tool(capability_definition=definitions["edit_file"])
    assert reader is not None
    assert editor is not None
    task_run_id = "taskrun:edit-after-edit-post-read"
    scope = task_run_file_evidence_scope(task_run_id)
    store = FileStateAuthorityStore(runtime_state)

    read = _native_read_for_edit(
        reader=reader,
        workspace=workspace,
        runtime_state=runtime_state,
        scope=scope,
        task_run_id=task_run_id,
        path="notes.txt",
        line_count=2,
    )
    store.apply_events_scope(scope, read.file_state_events, observation_ref="obs:post-read-initial", tool_call_id="call:post-read-initial")
    first = asyncio.run(
        editor.call(
            {"path": "notes.txt", "old_text": "first old", "new_text": "first new"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:first-edit",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    store.apply_events_scope(scope, first.file_state_events, observation_ref="obs:first-edit", tool_call_id="call:first-edit")

    second = asyncio.run(
        editor.call(
            {"path": "notes.txt", "old_text": "second old", "new_text": "second new"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:second-edit",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )

    assert first.status == "ok"
    assert second.status == "ok"
    assert target.read_text(encoding="utf-8") == "first new\nsecond new\n"
    assert first.file_state_events[1]["visible_exact"] is True


def test_native_read_file_empty_file_commits_complete_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "empty.txt").write_text("", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    reader = build_native_runtime_tool(capability_definition=definition)
    assert reader is not None
    task_run_id = "taskrun:read-empty-file"
    scope = task_run_file_evidence_scope(task_run_id)

    read = asyncio.run(
        reader.call(
            {"path": "empty.txt", "start_line": 1, "line_count": 1, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read-empty",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    state = FileStateAuthorityStore(runtime_state).apply_events_scope(
        scope,
        read.file_state_events,
        observation_ref="obs:read-empty",
        tool_call_id="call:read-empty",
    ).projection()[0]

    assert read.status == "ok"
    assert read.structured_payload["tool_result"]["total_lines"] == 0
    assert read.structured_payload["tool_result"]["end_line"] == 0
    assert state["status"] == "complete"
    assert state["total_lines"] == 0
    assert state["has_more"] is False
    assert state["read_ranges"][0]["start_line"] == 1
    assert state["read_ranges"][0]["end_line"] == 0
    assert state["read_ranges"][0]["exact_artifact_ref"].startswith("read_observation:")
    assert state["read_ranges"][0]["visible_exact"] is True
    assert state["coverage"]["complete"] is True
    assert state["exact_coverage"]["complete"] is True
    assert state["coverage"]["missing_ranges"] == []
    assert "next_suggested_read" not in state


def test_native_edit_file_to_empty_content_updates_current_file_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("remove me", encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    editor = build_native_runtime_tool(capability_definition=definitions["edit_file"])
    assert reader is not None
    assert editor is not None
    task_run_id = "taskrun:edit-to-empty"
    scope = task_run_file_evidence_scope(task_run_id)

    read = asyncio.run(
        reader.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 1, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read-before-empty",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    store = FileStateAuthorityStore(runtime_state)
    store.apply_events_scope(scope, read.file_state_events, observation_ref="obs:read-before-empty", tool_call_id="call:read-before-empty")

    edit = asyncio.run(
        editor.call(
            {"path": "notes.txt", "old_text": "remove me", "new_text": ""},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:edit-to-empty",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    state = store.apply_events_scope(scope, edit.file_state_events, observation_ref="obs:edit-to-empty", tool_call_id="call:edit-to-empty").projection()[0]

    assert edit.status == "ok"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == ""
    assert [event["event_type"] for event in edit.file_state_events] == ["edit", "read"]
    assert edit.file_state_events[1]["total_lines"] == 0
    assert edit.file_state_events[1]["end_line"] == 0
    assert state["status"] == "complete"
    assert state["total_lines"] == 0
    assert state["has_more"] is False
    assert any(item.get("stale") is True for item in state["read_ranges"])
    assert any(item.get("start_line") == 1 and item.get("end_line") == 0 for item in state["read_ranges"])
    assert state["coverage"]["complete"] is True
    assert state["coverage"]["missing_ranges"] == []
    assert "next_suggested_read" not in state


def test_native_edit_file_rejects_when_file_changed_after_read(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    target = workspace / "notes.txt"
    target.write_text("hello old", encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    editor = build_native_runtime_tool(capability_definition=definitions["edit_file"])
    assert reader is not None
    assert editor is not None
    task_run_id = "taskrun:edit-stale-after-read"
    scope = task_run_file_evidence_scope(task_run_id)

    read = asyncio.run(
        reader.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 1, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    FileStateAuthorityStore(runtime_state).apply_events_scope(scope, read.file_state_events, observation_ref="obs:read", tool_call_id="call:read")
    target.write_text("hello old but changed", encoding="utf-8")

    edit = asyncio.run(
        editor.call(
            {"path": "notes.txt", "old_text": "old", "new_text": "new"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:edit",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )

    assert edit.status == "error"
    assert edit.structured_payload["structured_error"]["code"] == "edit_file_read_evidence_stale"
    assert target.read_text(encoding="utf-8") == "hello old but changed"


def test_native_edit_file_rejects_ambiguous_old_text(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("old\nold", encoding="utf-8")
    definitions = get_tool_definition_map()
    reader = build_native_runtime_tool(capability_definition=definitions["read_file"])
    editor = build_native_runtime_tool(capability_definition=definitions["edit_file"])
    assert reader is not None
    assert editor is not None
    task_run_id = "taskrun:edit-ambiguous-old-text"
    scope = task_run_file_evidence_scope(task_run_id)

    read = asyncio.run(
        reader.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:read",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    FileStateAuthorityStore(runtime_state).apply_events_scope(scope, read.file_state_events, observation_ref="obs:read", tool_call_id="call:read")

    edit = asyncio.run(
        editor.call(
            {"path": "notes.txt", "old_text": "old", "new_text": "new"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id="call:edit",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )

    assert edit.status == "error"
    assert "exactly one location" in edit.text
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "old\nold"


def test_native_edit_file_allows_empty_old_text_for_new_target_and_requires_read_for_empty_existing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    definition = get_tool_definition_map()["edit_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    scope = task_run_file_evidence_scope("taskrun:edit-empty-target")
    context = ToolUseContext(
        workspace_root=workspace,
        task_run_id="taskrun:edit-empty-target",
        tool_call_id="call:edit-empty",
        file_evidence_scope=scope,
        file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
    )

    created = asyncio.run(tool.call({"path": "created.txt", "old_text": "", "new_text": "created"}, context))
    (workspace / "empty.txt").write_text("", encoding="utf-8")
    initialized = asyncio.run(tool.call({"path": "empty.txt", "old_text": "", "new_text": "initialized"}, context))

    assert created.status == "ok"
    assert initialized.status == "error"
    assert initialized.structured_payload["structured_error"]["code"] == "edit_file_empty_old_text_requires_current_empty_read"
    assert (workspace / "created.txt").read_text(encoding="utf-8") == "created"
    assert (workspace / "empty.txt").read_text(encoding="utf-8") == ""


def test_native_read_file_does_not_infer_evidence_scope_from_session_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runtime_state = tmp_path / "runtime_state"
    workspace.mkdir()
    runtime_state.mkdir()
    (workspace / "notes.txt").write_text("alpha\nbeta\ngamma", encoding="utf-8")
    definition = get_tool_definition_map()["read_file"]
    tool = build_native_runtime_tool(capability_definition=definition)
    assert tool is not None
    scope = session_file_evidence_scope("session:read-file-explicit-scope")

    first = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2},
            ToolUseContext(
                workspace_root=workspace,
                caller_kind="agent_turn",
                caller_ref="turnrun:session-read",
                session_id="session:read-file-explicit-scope",
                tool_call_id="call:session-read-1",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    FileStateAuthorityStore(runtime_state).apply_events_scope(
        scope,
        first.file_state_events,
        observation_ref="obs:session-first-read",
        tool_call_id="call:session-read-1",
    )

    second = asyncio.run(
        tool.call(
            {"path": "notes.txt", "start_line": 1, "line_count": 2},
            ToolUseContext(
                workspace_root=workspace,
                caller_kind="agent_turn",
                caller_ref="turnrun:session-read",
                session_id="session:read-file-explicit-scope",
                tool_call_id="call:session-read-2",
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )
    tool_result = second.structured_payload["tool_result"]

    assert "file_unchanged" not in tool_result
    assert "content_omitted" not in tool_result
    assert second.text == "1 | alpha\n2 | beta"


def test_task_run_read_file_commits_file_state_and_dynamic_context_projects_injected_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("line1\nline2\nline3\nline4", encoding="utf-8")
    execution_store = RuntimeExecutionStore(workspace / ".runtime")
    task_run_id = "taskrun:read-file-authority-chain"

    result = _run_read_file(
        workspace=workspace,
        execution_store=execution_store,
        task_run_id=task_run_id,
        tool_args={"path": "src/app.py", "start_line": 1, "line_count": 2},
    )

    envelope = result["observation"].payload["result_envelope"]
    tool_result = envelope["structured_payload"]["tool_result"]
    snapshot = FileStateAuthorityStore(execution_store.root_dir).snapshot_scope(task_run_file_evidence_scope(task_run_id))

    assert result["error"] == ""
    assert result["file_state_commit"]["event_count"] == 1
    assert tool_result["path"] == "src/app.py"
    assert envelope["file_state_events"][0]["event_type"] == "read"
    assert snapshot[0]["status"] == "partial"
    assert snapshot[0]["read_ranges"][0]["observation_ref"] == result["observation"].observation_id
    assert snapshot[0]["next_suggested_read"]["start_line"] == 3

    projection = DynamicContextManager(base_dir=workspace).project(
        DynamicContextInput(
            invocation_kind="task_execution",
            session_id="session:read-file-authority-chain",
            task_run_id=task_run_id,
            task_run={"task_run_id": task_run_id},
            execution_state={
                "system_projection": {
                    "runtime_status": "running",
                    "file_state": snapshot,
                    "file_state_source": "runtime.memory.file_state_store",
                }
            },
            runtime_assembly={
                "task_environment": {
                },
            },
        )
    )
    file_state = projection.volatile_state_projection["task_state"]["file_state"]
    read_resource_state = projection.volatile_state_projection["task_state"]["read_resource_state"]

    assert file_state[0]["path"] == "src/app.py"
    assert file_state[0]["status"] == "partial"
    assert file_state[0]["next_suggested_read"]["start_line"] == 3
    assert read_resource_state["authority_boundary"] == "resource_state_only"
    assert read_resource_state["status"] == "available"
    assert read_resource_state["available_range_count"] == 1
    assert "recommended_next_actions" not in read_resource_state

    store = FileStateAuthorityStore(execution_store.root_dir)
    stale = store.apply_events_scope(
        task_run_file_evidence_scope(task_run_id),
        [{"event_type": "edit", "path": "src/app.py", "content_sha256": "sha256:after"}],
        observation_ref="obs:edit",
        tool_call_id="call:edit",
    ).projection()[0]

    assert stale["status"] == "stale"
    assert stale["read_ranges"][0]["stale"] is True
    assert stale["write_events"][0]["operation"] == "edit"


def _run_read_file(
    *,
    workspace: Path,
    execution_store: RuntimeExecutionStore,
    task_run_id: str,
    tool_args: dict[str, object],
) -> dict:
    action_request = RuntimeActionRequest(
        request_id="rtact:read-file-authority",
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id="step:read-file-authority",
        directive_ref="rtdir:read-file-authority",
        operation_id="op.read_file",
        payload={
            "tool_name": "read_file",
            "tool_call": {"id": "call:read-file-authority", "name": "read_file", "args": tool_args},
        },
    )
    directive = RuntimeDirective(
        directive_id="rtdir:read-file-authority",
        task_id="task:read-file-authority",
        plan_ref="plan:read-file-authority",
        stage_ref="stage:read-file-authority",
        executor_type="tool",
        adopted_resource_policy_ref="respol:read-file-authority",
        operation_refs=("op.read_file",),
    )
    fingerprint = build_request_fingerprint(
        step_id="step:read-file-authority",
        operation_id="op.read_file",
        payload=action_request.payload,
    )
    record = execution_store.create_record(
        task_run_id=task_run_id,
        step_id="step:read-file-authority",
        action_request=action_request,
        directive_ref=directive.directive_id,
        operation_id="op.read_file",
        executor_type="tool",
        replay_policy="replay_read",
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=task_run_id,
            step_id="step:read-file-authority",
            operation_id="op.read_file",
            request_fingerprint=fingerprint,
        ),
    )
    return asyncio.run(
        ToolRuntimeExecutor(tool_runtime=ToolRuntime(workspace)).run(
            task_run_id=task_run_id,
            action_request=action_request,
            directive=directive,
            execution_record=record,
            execution_store=execution_store,
            sandbox_policy={"workspace_root": str(workspace)},
        )
    )


def _native_read_for_edit(
    *,
    reader: Any,
    workspace: Path,
    runtime_state: Path,
    scope: dict[str, Any],
    task_run_id: str,
    path: str,
    start_line: int = 1,
    line_count: int = 1,
):
    return asyncio.run(
        reader.call(
            {"path": path, "start_line": start_line, "line_count": line_count, "read_intent": "edit_target"},
            ToolUseContext(
                workspace_root=workspace,
                task_run_id=task_run_id,
                tool_call_id=f"call:read:{path}",
                file_evidence_scope=scope,
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state)}},
            ),
        )
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
