from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.memory.tool_observation_ledger import ToolObservationLedger
from runtime.agent_runtime.professional.action_gate import ActionGateDecision
from runtime.agent_runtime.professional.action_gate import decide_next_action_gate
from runtime.agent_runtime.professional_control import (
    _delivery_budget_remaining,
    _round_tool_call_limit_for_gate,
    _runtime_feedback_payload,
)
from runtime.agent_runtime.professional.goal_contract import ProfessionalTaskGoalContract
from runtime.agent_runtime.professional.deliverable_progress import build_deliverable_progress


def _goal_contract() -> ProfessionalTaskGoalContract:
    return ProfessionalTaskGoalContract(
        contract_id="contract:feedback",
        goal="接手已有浏览器肉鸽游戏项目并写入目标输出目录。",
        required_material_paths=["frontend/public/games/arcane_dungeon_studio/index.html"],
        required_output_paths=["frontend/public/games/arcane_dungeon_studio/game.js"],
        required_tool_kinds=["read_file", "write_file", "terminal"],
        required_output_kinds=["source_changes"],
        requires_material_review=True,
        requires_write_output=True,
        requires_verification_command=True,
    )


def test_read_material_gate_exposes_path_recovery_tools() -> None:
    gate = decide_next_action_gate(
        goal_contract=_goal_contract(),
        tool_observation_ledger=ToolObservationLedger(ledger_id="ledger:feedback", task_run_id="taskrun:feedback"),
        allowed_tool_names=[
            "agent_todo",
            "read_file",
            "read_structured_file",
            "path_exists",
            "stat_path",
            "list_dir",
            "glob_paths",
            "search_files",
            "write_file",
        ],
    )

    assert gate.stage == "read_material"
    assert gate.forced is True
    assert "read_file" in gate.allowed_tool_names
    assert "agent_todo" not in gate.allowed_tool_names
    assert "path_exists" in gate.allowed_tool_names
    assert "stat_path" in gate.allowed_tool_names
    assert "list_dir" in gate.allowed_tool_names
    assert "search_files" in gate.allowed_tool_names
    assert "write_file" not in gate.allowed_tool_names
    assert gate.reserved_tool_calls == 4


def test_runtime_feedback_payload_is_actionable_for_agent_repair() -> None:
    ledger = ToolObservationLedger(ledger_id="ledger:feedback", task_run_id="taskrun:feedback")
    contract = _goal_contract()
    gate = decide_next_action_gate(
        goal_contract=contract,
        tool_observation_ledger=ledger,
        allowed_tool_names=["read_file", "path_exists", "list_dir", "write_file", "terminal"],
    )
    progress = build_deliverable_progress(goal_contract=contract, tool_observation_ledger=ledger)

    feedback = _runtime_feedback_payload(
        source="action_gate",
        requested_tool_name="write_file",
        action_gate=gate,
        deliverable_progress=progress,
        repair_instruction="先定位并读取缺失材料；如果路径不存在，使用 path_exists/list_dir/search_files 恢复路径。",
    )

    assert feedback["authority"] == "agent_runtime.professional.runtime_feedback"
    assert feedback["requested_tool"] == "write_file"
    assert "read_file" in feedback["allowed_tool_names"]
    assert "path_exists" in feedback["allowed_tool_names"]
    assert feedback["target_path"] == "frontend/public/games/arcane_dungeon_studio/index.html"
    assert "read_material:frontend/public/games/arcane_dungeon_studio/index.html" in feedback["missing_obligations"]
    assert "agent_chooses_next_valid_action" in feedback["principle"]


def test_read_material_gate_keeps_agent_todo_as_agent_optional_tool_not_system_gate() -> None:
    gate = ActionGateDecision(
        allowed_tool_names=("read_file", "path_exists", "list_dir", "search_files"),
        forced=True,
        stage="read_material",
        reason="required_material_missing",
        target_path="frontend/public/games/arcane_dungeon_studio/index.html",
        reserved_tool_calls=4,
    )
    pending_tool_calls = [
        {
            "id": "call-todo",
            "name": "agent_todo",
            "args": {"items": [{"content": "定位并读取入口文件", "status": "in_progress"}]},
            "type": "tool_call",
        }
    ]

    assert _round_tool_call_limit_for_gate(max_tool_calls=1, gate=gate) == 4
    assert "agent_todo" not in gate.allowed_tool_names
    assert _delivery_budget_remaining(
        pending_tool_calls,
        gate=gate,
        max_tool_calls_per_task_run=1,
    ) == 4
