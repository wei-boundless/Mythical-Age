from __future__ import annotations

from task_system.assembly import TaskContractIssuer


def test_contract_issuer_builds_runtime_and_loop_request_specs() -> None:
    contract = TaskContractIssuer().issue_specific_task_contract(
        session_id="session",
        task_record={
            "task_id": "task.dev.frontend_ui",
            "task_title": "Frontend UI",
            "description": "Update the frontend and verify it.",
            "environment_id": "env.vibe_coding",
        },
        objective="Polish the task editor.",
    )

    assert contract.authority == "task_system.task_contract"
    assert contract.schema_version == "task_contract.v1"
    assert contract.status == "issued"
    assert contract.environment_id == "env.vibe_coding"
    assert contract.objective == "Polish the task editor."
    assert contract.runtime_assembly_plan["kind"] == "runtime_assembly_request"
    assert contract.runtime_assembly_plan["schema_version"] == "runtime_assembly_plan.request.v1"
    assert contract.loop_plan["kind"] == "loop_request"
    assert contract.loop_plan["schema_version"] == "loop_plan.request.v1"
    assert "extension_slots" in contract.to_dict()
    assert "task_run_id" not in contract.to_dict()
    assert "loop_state" not in contract.to_dict()


def test_contract_issuer_emits_graph_request_specs_for_graph_task() -> None:
    contract = TaskContractIssuer().issue_specific_task_contract(
        session_id="session",
        task_record={
            "task_id": "task.graph.review",
            "task_title": "Graph Review",
            "description": "Review a graph node.",
            "environment_id": "env.writing",
            "task_policy": {"graph_ref": "graph:writing-review"},
        },
        objective="Review the writing graph.",
    )

    assert contract.graph_contract["graph_ref"] == "graph:writing-review"
    assert contract.graph_runtime_assembly_plan["kind"] == "graph_harness_config_request"
    assert contract.graph_runtime_assembly_plan["schema_version"] == "graph_harness_config_request.v1"
    assert contract.graph_loop_plan["kind"] == "graph_loop_request"


