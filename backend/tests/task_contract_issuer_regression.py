from __future__ import annotations

import json
from pathlib import Path

from task_system.assembly import TaskContractIssuer


def test_contract_issuer_builds_runtime_and_loop_request_specs() -> None:
    contract = TaskContractIssuer().issue_specific_task_contract(
        session_id="session",
        task_record={
            "task_id": "task.dev.frontend_ui",
            "task_title": "Frontend UI",
            "description": "Update the frontend and verify it.",
            "environment_id": "env.development.sandbox",
        },
        objective="Polish the task editor.",
    )

    assert contract.authority == "task_system.task_contract"
    assert contract.schema_version == "task_contract.v1"
    assert contract.status == "issued"
    assert contract.environment_id == "env.development.sandbox"
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
            "environment_id": "env.creation.writing",
            "task_policy": {"graph_ref": "graph:writing-review"},
        },
        objective="Review the writing graph.",
    )

    assert contract.graph_contract["graph_ref"] == "graph:writing-review"
    assert contract.graph_runtime_assembly_plan["kind"] == "graph_harness_config_request"
    assert contract.graph_runtime_assembly_plan["schema_version"] == "graph_harness_config_request.v1"
    assert contract.graph_loop_plan["kind"] == "graph_loop_request"


def test_contract_issuer_uses_configured_task_environment(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    config_dir = backend_dir / "task_system" / "storage" / "task_environments"
    config_dir.mkdir(parents=True)
    (config_dir / "environments.json").write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "environment_id": "env.custom.contract",
                        "title": "Contract Custom",
                        "group_id": "environment_group.general",
                        "spec_id": "envspec.custom.contract.v1",
                        "file_management": {"file_profile_refs": ["file_profile.general_workspace"]},
                        "resource_space": {"storage_namespace": "custom/contract"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    contract = TaskContractIssuer(backend_dir=backend_dir).issue_specific_task_contract(
        session_id="session",
        task_record={
            "task_id": "task.custom.contract",
            "task_title": "Custom Contract",
            "environment_id": "env.custom.contract",
        },
    )

    assert contract.environment_id == "env.custom.contract"
    assert contract.metadata["environment_spec_id"] == "envspec.custom.contract.v1"


