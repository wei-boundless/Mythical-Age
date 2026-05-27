from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime.environment.tool_capability_policy import prepare_runtime_tool_capability_table_for_turn


def test_agent_runtime_tool_capability_table_is_environment_and_permit_bound() -> None:
    table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={
            "task_id": "task:writing",
            "operation_requirement": {"required_operations": ["op.read_file"]},
        },
        file_management_policy={"enabled": True, "environment_id": "env.writing"},
        execution_permit={"allowed_operations": ["op.read_file", "op.shell", "op.browser_control"]},
        runtime_available_operations=["op.read_file", "op.shell", "op.browser_control"],
    )

    assert table is not None
    assert "read_file" in table.dispatchable_tools
    assert "terminal" not in table.dispatchable_tools
    assert "browser_control" not in table.dispatchable_tools
    filtered_operations = {(issue.operation_id, issue.source) for issue in table.filtered}
    assert ("op.shell", "task_environment") in filtered_operations
    assert ("op.browser_control", "task_environment") in filtered_operations
