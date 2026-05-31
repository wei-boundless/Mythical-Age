from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
from task_system.registry.flow_registry import TaskFlowRegistry
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
                    task_environment_id="env.creation.writing",
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

    assert assignment["task_environment_id"] == "env.creation.writing"
    assert inventory_item["environment_id"] == "env.creation.writing"
    assert payload["environment_task_inventory"]["by_environment"]["env.creation.writing"][0]["task_id"] == "task.review_outline"


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
        runtime_policy={"task_environment_id": "env.development.sandbox"},
        context_policy={"task_environment_id": "env.creation.writing"},
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

    assert row["environment_id"] == "env.development.sandbox"
    assert row["node_count"] == 2
    assert row["edge_count"] == 1
    assert payload["environment_graph_inventory"]["by_environment"]["env.development.sandbox"][0]["graph_id"] == "graph.review.pipeline"

