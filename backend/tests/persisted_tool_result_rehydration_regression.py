from __future__ import annotations

import asyncio
import json
from pathlib import Path

from capability_system.tools.native_tool_catalog import get_tool_definition_map
from capability_system.tools.tool_units.persisted_tool_result_tool import ReadPersistedToolResultTool
from harness.runtime.dynamic_context.replacement_store import ReplacementStore
from harness.runtime.dynamic_context.tool_result_projector import ToolResultProjector
from harness.runtime.tool_scheduling import environment_allowed_operations, operation_channel
from permissions.operation_packages import default_tool_packages
from permissions.operations import build_default_operation_registry
from runtime.tool_runtime.native_tools import build_native_runtime_tool
from runtime.tool_runtime.tool_use_context import ToolUseContext


def test_rehydration_plan_executes_with_persisted_tool_result_tool(tmp_path: Path) -> None:
    large_text = "exact header\n" + ("exact omitted marker\n" * 500)
    projection = _large_tool_result_projection(tmp_path, large_text=large_text)
    persisted = projection["rehydration_plan"]["capabilities"][0]

    assert persisted["tool_name"] == "read_persisted_tool_result"
    assert persisted["next_request"] == {"tool_name": "read_persisted_tool_result", "args": persisted["args"]}

    tool = ReadPersistedToolResultTool(root_dir=tmp_path)
    restored = tool._run(**persisted["args"])

    assert restored == large_text


def test_native_runtime_tool_reads_persisted_result_from_rehydration_args(tmp_path: Path) -> None:
    large_text = "native header\n" + ("native omitted marker\n" * 500)
    projection = _large_tool_result_projection(tmp_path, large_text=large_text)
    args = projection["rehydration_plan"]["capabilities"][0]["args"]
    definition = get_tool_definition_map()["read_persisted_tool_result"]
    runtime_tool = build_native_runtime_tool(capability_definition=definition)

    envelope = asyncio.run(
        runtime_tool.call(
            args,
            ToolUseContext(
                workspace_root=tmp_path,
                task_run_id="taskrun:rehydrate",
                execution_receipt={"execution_id": "exec:rehydrate"},
            ),
        )
    )

    assert envelope.status == "ok"
    assert envelope.text == large_text
    assert envelope.structured_payload["tool_result"]["kind"] == "persisted_tool_result"
    assert envelope.structured_payload["tool_result"]["path"] == args["path"]


def test_native_runtime_tool_allows_environment_runtime_state_root_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    runtime_state_root = tmp_path / "external-runtime-state"
    large_text = "environment header\n" + ("environment omitted marker\n" * 500)
    projection = _large_tool_result_projection(runtime_state_root, large_text=large_text)
    args = projection["rehydration_plan"]["capabilities"][0]["args"]
    definition = get_tool_definition_map()["read_persisted_tool_result"]
    runtime_tool = build_native_runtime_tool(capability_definition=definition)

    envelope = asyncio.run(
        runtime_tool.call(
            args,
            ToolUseContext(
                workspace_root=workspace,
                task_run_id="taskrun:rehydrate",
                file_management_policy={"storage_space": {"runtime_state_root": str(runtime_state_root)}},
                execution_receipt={"execution_id": "exec:environment-rehydrate"},
            ),
        )
    )

    assert envelope.status == "ok"
    assert envelope.text == large_text


def test_persisted_tool_result_tool_rejects_paths_outside_trusted_storage(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside" / "storage" / "runtime_context" / "tool-results" / "run" / "text-deadbeefdeadbeef.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("outside secret", encoding="utf-8")

    tool = ReadPersistedToolResultTool(root_dir=tmp_path)
    payload = json.loads(tool._run(path=str(outside), replacement_id="tool_result:deadbeefdeadbeef"))

    assert payload["ok"] is False
    assert payload["structured_error"]["code"] == "persisted_tool_result_read_failed"
    assert "outside trusted runtime context storage" in payload["error"]


def test_persisted_tool_result_tool_is_registered_as_read_only_runtime_context_operation() -> None:
    definition = get_tool_definition_map()["read_persisted_tool_result"]
    operation = build_default_operation_registry().get_operation("op.read_persisted_tool_result")
    packages = {item.package_id: item for item in default_tool_packages()}

    assert definition.operation_id == "op.read_persisted_tool_result"
    assert definition.is_read_only is True
    assert definition.resource_exposure_policy == "none"
    assert operation is not None
    assert operation.read_only is True
    assert operation.operation_type == "runtime_context"
    assert "op.read_persisted_tool_result" in packages["pkg.filesystem.read"].operation_ids


def test_persisted_tool_result_operation_is_allowed_in_coding_environment() -> None:
    operation_id = "op.read_persisted_tool_result"

    assert operation_channel(operation_id) == "runtime_context"
    assert operation_id in environment_allowed_operations({"environment_kind": "coding"})


def _large_tool_result_projection(tmp_path: Path, *, large_text: str) -> dict:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))
    projection, _record = projector.project(
        {
            "result_envelope": {
                "envelope_id": "tool-result:rehydrate",
                "tool_name": "terminal",
                "status": "ok",
                "text": large_text,
            }
        },
        task_run_id="taskrun:rehydrate",
        projection_policy={"tool_result_preview_chars": 300},
    )
    return projection
