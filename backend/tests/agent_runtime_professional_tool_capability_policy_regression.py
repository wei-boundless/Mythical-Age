from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.agent_runtime.professional_control import (
    _filter_tool_names_by_capability_table,
    _tools_with_goal_contract_requirements,
)
from runtime.agent_runtime.professional.goal_contract import ProfessionalTaskGoalContract
from runtime.agent_runtime.environment.tool_capability_policy import prepare_runtime_tool_capability_table_for_turn


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Runtime:
    def get_instance(self, name: str):
        return _Tool(name) if name in {"terminal", "browser_control"} else None


class _Executor:
    tool_runtime = _Runtime()


def test_agent_runtime_professional_goal_requirements_cannot_expand_past_capability_table() -> None:
    table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={
            "task_id": "task:writing",
            "operation_requirement": {"required_operations": ["op.read_file"]},
        },
        file_management_policy={"enabled": True, "environment_id": "env.writing"},
        execution_permit={"allowed_operations": ["op.read_file", "op.shell", "op.browser_control"]},
        runtime_available_operations=["op.read_file", "op.shell", "op.browser_control"],
    )
    goal_contract = ProfessionalTaskGoalContract(
        contract_id="goal:verify",
        goal="write and run verification",
        requires_verification_command=True,
    )
    expanded = _tools_with_goal_contract_requirements(
        allowed_tool_names=["read_file"],
        tool_policy={},
        goal_contract=goal_contract,
        runtime_tool_instances=[_Tool("read_file")],
        tool_runtime_executor=_Executor(),
    )

    assert "terminal" in expanded
    assert "browser_control" in expanded

    narrowed = _filter_tool_names_by_capability_table(
        allowed_tool_names=expanded,
        task_operation={"tool_capability_table": table},
    )

    assert narrowed == ["read_file"]
