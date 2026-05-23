from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.assembler import assemble_runtime_prompt_contract


def test_assembler_only_emits_goal_understanding_section_for_understanding_step() -> None:
    contract = assemble_runtime_prompt_contract(
        base_dir=Path("backend"),
        task_id="task-runtime",
        user_goal="分析并修改任务系统",
        task_contract={
            "user_goal": "分析并修改任务系统",
            "mode_policy": {"interaction_mode": "professional_mode"},
            "task_requirement_contract": {
                "contract_id": "semantic-task:test:task-runtime",
                "task_goal_type": "implementation",
                "domain": "development",
                "diagnostics": {
                    "task_goal_spec": {
                        "task_goal_type": "implementation",
                        "unacceptable_outcomes": ["surface_only_summary"],
                    }
                },
            },
        },
        task_execution_assembly={"task_family": "runtime", "task_mode": "professional_mode", "requested_outputs": []},
        task_spec={},
        selected_recipe={"metadata": {}},
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[],
        projection_requirement={"interaction_mode": "professional_mode"},
        operation_requirement={},
        active_skill={},
        agent_id="agent:0",
        current_turn_context={
            "current_step_kind": "step_execution",
            "model_turn_decision": {
                "work_mode": "implementation",
                "action_intent": "edit_workspace",
            },
            "task_goal_spec": {
                "task_goal_type": "implementation",
                "unacceptable_outcomes": ["surface_only_summary"],
            },
        },
    )

    assert contract["goal_understanding_section"] == ""
