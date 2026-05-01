from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from operations import ResourcePolicy
from operations import OperationGate, build_default_operation_registry
from orchestration.runtime_loop.task_run_loop import TaskRunLoop
from tools.authorization import build_authorized_tool_set, build_tool_authorization_index, resolve_tool_operation_id
from tools.definitions import build_tool_instances, get_tool_definitions


def test_all_builtin_tools_have_explicit_operation_id() -> None:
    definitions = get_tool_definitions()

    assert definitions
    assert all(definition.operation_id.startswith("op.") for definition in definitions)


def test_tool_operation_resolution_does_not_use_operation_alias_collision() -> None:
    index = build_tool_authorization_index(get_tool_definitions())

    assert resolve_tool_operation_id("pdf_analysis", definitions_by_name=index.definitions_by_name) == "op.pdf_analysis"
    assert resolve_tool_operation_id("structured_data_analysis", definitions_by_name=index.definitions_by_name) == (
        "op.structured_data_analysis"
    )
    assert resolve_tool_operation_id("index_multimodal_file", definitions_by_name=index.definitions_by_name) == (
        "op.index_multimodal_file"
    )


def test_authorized_tool_set_filters_by_explicit_operation_and_main_runtime_visibility() -> None:
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    instances = build_tool_instances(Path.cwd())
    authorized = build_authorized_tool_set(
        tool_instances=instances,
        definitions_by_name=index.definitions_by_name,
        allowed_operations={"op.read_file", "op.pdf_analysis", "op.shell"},
        runtime_lane="main_runtime",
    )

    assert "read_file" in authorized.tool_names
    assert "pdf_analysis" not in authorized.tool_names
    assert "terminal" not in authorized.tool_names
    assert "op.read_file" in authorized.operation_ids
    assert any(item["tool_name"] == "pdf_analysis" and item["reason"] == "not_main_runtime_visible" for item in authorized.filtered_out)
    assert any(item["tool_name"] == "terminal" and item["reason"] == "not_main_runtime_visible" for item in authorized.filtered_out)


def test_task_run_loop_tool_filter_uses_tool_definition_operation_id() -> None:
    loop = TaskRunLoop(Path("runtime-loop-test"))
    instances = build_tool_instances(Path.cwd())
    policy = ResourcePolicy(
        policy_id="respol-test",
        task_id="task-test",
        allowed_operations=("op.pdf_analysis",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    visible = loop._tool_instances_for_resource_policy(instances, policy)

    assert visible == []


def test_write_and_edit_tools_are_registered_as_main_runtime_schema_tools() -> None:
    definitions = {definition.name: definition for definition in get_tool_definitions()}

    assert definitions["write_file"].operation_id == "op.write_file"
    assert definitions["edit_file"].operation_id == "op.edit_file"
    assert definitions["write_file"].runtime_visibility == "main_runtime"
    assert definitions["edit_file"].runtime_visibility == "main_runtime"
    assert definitions["write_file"].prompt_exposure_policy == "schema_only"
    assert definitions["edit_file"].prompt_exposure_policy == "schema_only"


def test_requires_approval_operations_can_be_schema_visible_before_gate_execution() -> None:
    loop = TaskRunLoop(Path("runtime-loop-test"))
    instances = build_tool_instances(Path.cwd())
    policy = ResourcePolicy(
        policy_id="respol-test-approval-visible",
        task_id="task-test",
        allowed_operations=("op.read_file",),
        requires_approval_operations=("op.write_file", "op.edit_file"),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    visible = loop._tool_instances_for_resource_policy(instances, policy)
    names = {getattr(tool, "name", "") for tool in visible}

    assert {"read_file", "write_file", "edit_file"} <= names
    assert "terminal" not in names
    assert "python_repl" not in names


def test_requires_approval_schema_visible_tool_still_needs_gate_approval_token() -> None:
    registry = build_default_operation_registry()
    gate = OperationGate(registry)
    policy = ResourcePolicy(
        policy_id="respol-test-approval-gate",
        task_id="task-test",
        allowed_operations=("op.model_response",),
        requires_approval_operations=("op.write_file",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
    )

    result = gate.check(
        "op.write_file",
        resource_policy=policy,
        directive_ref="runtime-directive:test:write-file",
    )

    assert result.allowed is False
    assert result.requires_approval is True
    assert result.decision == "requires_approval"
