from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.projects.project_instance import ProjectInstance
from task_system.repositories.project_instance_repository import ProjectInstanceRepository
from tests.support.runtime_stubs import RuntimeBaseDirStub


def test_task_assignment_api_writes_first_class_environment_id(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            tasks_api.upsert_task_system_task_assignment(
                "task.review_outline",
                tasks_api.TaskAssignmentUpsertRequest(
                    task_id="task.review_outline",
                    task_title="Review Outline",
                    flow_id="flow.review_outline",
                    domain_id="general",
                    task_environment_id="env.office.file_search",
                    input_contract_id="contract.review.input",
                    output_contract_id="contract.review.output",
                    default_agent_id="agent:0",
                    metadata={"source": "test"},
                ),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assignment = next(
        item
        for item in payload["task_management"]["task_assignments"]
        if item["task_id"] == "task.review_outline"
    )
    inventory_item = next(
        item
        for item in payload["environment_task_inventory"]["items"]
        if item["task_id"] == "task.review_outline"
    )

    assert assignment["task_environment_id"] == "env.office.file_search"
    assert inventory_item["environment_id"] == "env.office.file_search"
    assert payload["environment_task_inventory"]["by_environment"]["env.office.file_search"][0]["task_id"] == "task.review_outline"


def test_environment_graph_inventory_uses_graph_runtime_environment_id(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.review.pipeline",
        title="Review Pipeline",
        domain_id="general",
        graph_kind="coordination",
        entry_node_id="node.start",
        output_node_id="node.finish",
        nodes=(
            {"node_id": "node.start", "node_type": "agent", "title": "Start", "agent_id": "agent:0"},
            {"node_id": "node.finish", "node_type": "output", "title": "Finish"},
        ),
        edges=(
            {
                "edge_id": "edge.start.finish",
                "source_node_id": "node.start",
                "target_node_id": "node.finish",
            },
        ),
        runtime_policy={"task_environment_id": "env.coding.vibe_workspace"},
        context_policy={"task_environment_id": "env.office.file_search"},
        publish_state="draft",
        enabled=True,
    )

    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    row = next(
        item
        for item in payload["environment_graph_inventory"]["items"]
        if item["graph_id"] == "graph.review.pipeline"
    )

    assert row["environment_id"] == "env.coding.vibe_workspace"
    assert row["node_count"] == 2
    assert row["edge_count"] == 1
    assert payload["environment_graph_inventory"]["by_environment"]["env.coding.vibe_workspace"][0]["graph_id"] == "graph.review.pipeline"


def test_project_instance_management_uses_task_environment_registry(tmp_path: Path) -> None:
    ProjectInstanceRepository(tmp_path).upsert(
        ProjectInstance(
            project_id="project.general.workspace.notes",
            environment_id="env.general.workspace",
            title="General Notes",
            project_kind="general_workspace",
            template_id="general.template.workspace",
            library_id="library.project.general.workspace.notes",
            schema_version="general_project_library.v1",
        )
    )

    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    management = payload["project_instance_management"]
    assert "env.general.workspace" in management["environment_ids"]
    assert management["by_environment"]["env.general.workspace"][0]["project_id"] == "project.general.workspace.notes"
