from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.capabilities import CurrentTurnCapabilityPlan
from runtime.agent_runtime.environment.tool_capability_policy import (
    apply_tool_capability_table_to_turn_plan,
    prepare_runtime_tool_capability_table_for_turn,
)


def test_runtime_tool_capability_table_uses_task_environment_file_policy() -> None:
    table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={
            "task_id": "task:writing",
            "operation_requirement": {
                "required_operations": ["op.read_file", "op.write_file", "op.shell"],
            },
        },
        file_management_policy={"enabled": True, "environment_id": "env.writing"},
        execution_permit={"allowed_operations": ["op.read_file", "op.write_file", "op.shell"]},
        runtime_available_operations=["op.read_file", "op.write_file", "op.shell"],
    )

    assert table is not None
    assert "read_file" in table.dispatchable_tools
    assert "write_file" in table.dispatchable_tools
    assert "terminal" not in table.dispatchable_tools
    assert any(issue.operation_id == "op.shell" and issue.source == "task_environment" for issue in table.filtered)


def test_runtime_turn_capability_plan_is_narrowed_by_tool_capability_table() -> None:
    table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={
            "task_id": "task:writing",
            "operation_requirement": {
                "required_operations": ["op.read_file", "op.shell"],
            },
        },
        file_management_policy={"enabled": True, "environment_id": "env.writing"},
        execution_permit={"allowed_operations": ["op.read_file", "op.shell"]},
        runtime_available_operations=["op.read_file", "op.shell"],
    )
    plan = CurrentTurnCapabilityPlan(
        allowed_operations=("op.model_response", "op.read_file", "op.shell"),
        model_visible_tools=("read_file", "terminal"),
        dispatchable_tools=("read_file", "terminal"),
        denied_operations=(),
        filtered_tools=(),
        diagnostics={},
    )

    narrowed = apply_tool_capability_table_to_turn_plan(plan, table)

    assert narrowed.allowed_operations == ("op.read_file",)
    assert narrowed.model_visible_tools == ("read_file",)
    assert narrowed.dispatchable_tools == ("read_file",)
    assert narrowed.diagnostics["capability_plan_overlay_source"] == "runtime.tool_capability_table"


def test_runtime_turn_capability_plan_keeps_environment_approved_dispatch_tools_visible() -> None:
    table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={
            "task_id": "task:coding",
            "operation_requirement": {
                "required_operations": ["op.shell"],
            },
        },
        file_management_policy={"enabled": True, "environment_id": "env.vibe_coding"},
        execution_permit={"allowed_operations": ["op.shell"]},
        runtime_available_operations=["op.shell"],
    )
    plan = CurrentTurnCapabilityPlan(
        allowed_operations=("op.shell",),
        model_visible_tools=(),
        dispatchable_tools=("terminal",),
        denied_operations=(),
        filtered_tools=(),
        diagnostics={},
    )

    narrowed = apply_tool_capability_table_to_turn_plan(plan, table)

    assert narrowed.model_visible_tools == ("terminal",)
    assert narrowed.dispatchable_tools == ("terminal",)


def test_runtime_tool_capability_table_consumes_specific_task_policy_payload() -> None:
    table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={
            "task_id": "task:specific-writing",
            "specific_task_assembly_policy": {
                "policy_id": "taskasm:specific-writing",
                "task_id": "task.specific.writing",
                "environment_id": "env.writing",
                "tool_capability_requirements": {
                    "required_operations": ["op.read_file", "op.write_file"],
                    "optional_operations": ["op.agent_todo"],
                    "denied_operations": ["op.shell"],
                },
            },
            "operation_requirement": {
                "required_operations": ["op.model_response"],
            },
        },
        file_management_policy={"enabled": True, "environment_id": "env.writing"},
        execution_permit={"allowed_operations": ["op.model_response", "op.read_file", "op.write_file", "op.agent_todo", "op.shell"]},
        runtime_available_operations=["op.model_response", "op.read_file", "op.write_file", "op.agent_todo", "op.shell"],
    )

    assert table is not None
    assert "read_file" in table.dispatchable_tools
    assert "write_file" in table.dispatchable_tools
    assert "agent_todo" not in table.dispatchable_tools
    assert "terminal" not in table.dispatchable_tools
    assert any(issue.operation_id == "op.agent_todo" and issue.source == "task_environment" for issue in table.filtered)
    assert any(issue.operation_id == "op.shell" and issue.source == "task_environment" for issue in table.filtered)
    assert any(trace.source == "specific_task_assembly_policy" and trace.metadata.get("specific_task_assembly_policy_ref") == "taskasm:specific-writing" for trace in table.source_trace)
