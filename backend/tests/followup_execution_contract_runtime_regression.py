from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.runtime_loop.task_run_loop import TaskRunLoop


def test_delegation_payload_inherits_active_subset_contract() -> None:
    runtime = TaskRunLoop.__new__(TaskRunLoop)
    runtime.state_index = SimpleNamespace(
        get_task_run=lambda _task_run_id: SimpleNamespace(session_id="session-contract")
    )
    action_request = SimpleNamespace(
        operation_id="op.delegate_to_agent",
        payload={
            "tool_call": {
                "id": "call-1",
                "args": {
                    "target_agent_id": "agent:table_analyst",
                    "delegation_kind": "table_analysis",
                    "instruction": "只基于刚才这前五名员工按部门总结。",
                    "input_payload": {"query": "按部门总结。"},
                },
            }
        },
    )
    task_operation = {
        "task_spec": {
            "inputs": {
                "followup_execution_contract": {
                    "authority": "task_system.followup_execution_contract",
                    "constraint_policy": "result_subset_only_do_not_expand_to_full_object",
                    "followup_scope": "active_subset",
                    "followup_target_kind": "active_subset",
                    "followup_target_refs": [
                        "subset:selection:employees:top5",
                        "result:structured:employees:top5",
                    ],
                    "active_subset_handle_id": "subset:selection:employees:top5",
                    "active_result_handle_id": "result:structured:employees:top5",
                    "source_kind": "dataset",
                    "source_path": "Data/employees.xlsx",
                    "subset_filter_column": "name",
                    "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                }
            }
        }
    }

    request = TaskRunLoop._build_delegation_request(
        runtime,
        task_run_id="task-run-contract",
        action_request=action_request,
        parent_agent_run_ref="agentrun:main",
        source_agent_id="agent:main",
        user_message="只基于刚才这前五名员工，按部门做一个归类总结，不要回到全表重算。",
        task_operation=task_operation,
    )

    assert request.input_payload["path"] == "Data/employees.xlsx"
    assert request.input_payload["active_dataset"] == "Data/employees.xlsx"
    assert request.input_payload["followup_scope"] == "active_subset"
    assert request.input_payload["followup_constraint_policy"] == "result_subset_only_do_not_expand_to_full_object"
    assert request.input_payload["followup_target_refs"] == [
        "subset:selection:employees:top5",
        "result:structured:employees:top5",
    ]
    assert request.input_payload["active_subset_handle_id"] == "subset:selection:employees:top5"
    assert request.input_payload["active_result_handle_id"] == "result:structured:employees:top5"
    assert request.input_payload["subset_filter_column"] == "name"
    assert request.input_payload["subset_labels"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]
    assert request.input_payload["semantic_hints"]["subset_filter_column"] == "name"
    assert request.input_payload["semantic_hints"]["subset_allowed_values"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]


def test_recipe_mcp_constraints_inherit_active_subset_contract() -> None:
    runtime = TaskRunLoop.__new__(TaskRunLoop)
    _, operation_id, bindings, constraints, _ = TaskRunLoop._recipe_mcp_request_parts(
        runtime,
        user_message="只基于刚才这前五名员工按部门总结。",
        current_turn_context={},
        query_understanding={"source_kind": "dataset", "parameters": {"query": "按部门总结。"}},
        selected_recipe_payload={"source_kind": "dataset"},
        task_spec_payload={
            "inputs": {
                "followup_execution_contract": {
                    "authority": "task_system.followup_execution_contract",
                    "constraint_policy": "result_subset_only_do_not_expand_to_full_object",
                    "followup_scope": "active_subset",
                    "followup_target_kind": "active_subset",
                    "followup_target_refs": ["subset:selection:employees:top5"],
                    "source_kind": "dataset",
                    "source_path": "Data/employees.xlsx",
                    "subset_filter_column": "name",
                    "subset_labels": ["Alice", "Bob", "Chen", "Diaz", "Eve"],
                }
            }
        },
    )

    assert operation_id == "op.mcp_structured_data"
    assert bindings == {"active_dataset": "Data/employees.xlsx"}
    assert constraints["path"] == "Data/employees.xlsx"
    assert constraints["followup_constraint_policy"] == "result_subset_only_do_not_expand_to_full_object"
    assert constraints["followup_scope"] == "active_subset"
    assert constraints["followup_target_refs"] == ["subset:selection:employees:top5"]
    assert constraints["subset_filter_column"] == "name"
    assert constraints["subset_labels"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]
    assert constraints["semantic_hints"]["subset_filter_column"] == "name"
    assert constraints["semantic_hints"]["subset_allowed_values"] == ["Alice", "Bob", "Chen", "Diaz", "Eve"]
