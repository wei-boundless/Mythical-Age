from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import orchestration as orchestration_api
from harness import AgentHarness, AgentRuntimeServices, GraphHarness
from harness.runtime import SingleAgentRuntimeHost
from project_layout import ProjectLayout
from task_system import TaskFlowRegistry
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.compiler.graph_harness_config_publisher import (
    build_graph_harness_config_from_runtime_spec,
    publish_graph_harness_config_for_graph,
)
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphNodeDefinition
from task_system.repositories import GraphHarnessConfigRepository


def _graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.test.api_new_harness",
        title="API New Harness Graph",
        graph_kind="multi_agent",
        publish_state="published",
        enabled=True,
        entry_node_id="produce",
        output_node_id="produce",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="生产节点",
                task_id="task.test.produce",
                agent_id="agent:0",
                metadata={
                    "prompt_contract": {
                        "role_prompt": "你是一名生产节点执行员。",
                        "task_instruction": "请完成当前生产节点任务。",
                    }
                },
            ),
        ),
    )


def _runtime_with_graph_harness(*, base_dir: Path, runtime_root: Path) -> SimpleNamespace:
    host = SingleAgentRuntimeHost(
        ProjectLayout.from_backend_dir(base_dir).runtime_state_dir
        if runtime_root.name != "runtime_state"
        else runtime_root,
        backend_dir=base_dir,
    )
    services = AgentRuntimeServices.from_runtime_host(host)
    agent_harness = AgentHarness(services=services)
    graph_harness = GraphHarness(services=services, agent_harness=agent_harness)
    return SimpleNamespace(
        base_dir=base_dir,
        query_runtime=SimpleNamespace(
            agent_harness=agent_harness,
            graph_harness=graph_harness,
        ),
    )


def test_graph_harness_config_publication_requires_explicit_graph_binding(tmp_path: Path) -> None:
    graph = _graph()
    repository = GraphHarnessConfigRepository(tmp_path)
    config = build_graph_harness_config_from_runtime_spec(
        graph=graph,
        runtime_spec=compile_task_graph_definition_runtime_spec(graph=graph),
        contract_manifest={"manifest_id": f"contract-manifest:{graph.graph_id}", "valid": True},
    )

    repository.upsert(config, publish=False)
    assert repository.get(config.config_id) is not None
    assert repository.get_published_for_graph(graph.graph_id) is None

    repository.upsert(config, publish=True)
    published = repository.get_published_for_graph(graph.graph_id)
    assert published is not None
    assert published.config_id == config.config_id
    assert published.content_hash == config.content_hash


def test_task_graph_start_api_requires_published_config_binding(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = _graph()
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(node.to_dict() for node in graph.nodes),
        runtime_policy=graph.runtime_policy,
        publish_state="published",
        enabled=True,
    )
    stored_graph = registry.get_task_graph(graph.graph_id)
    assert stored_graph is not None
    config = build_graph_harness_config_from_runtime_spec(
        graph=stored_graph,
        runtime_spec=compile_task_graph_definition_runtime_spec(graph=stored_graph),
        contract_manifest={"manifest_id": f"contract-manifest:{graph.graph_id}", "valid": True},
    )
    registry.upsert_graph_harness_config(config, publish=False)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        try:
            asyncio.run(
                orchestration_api.start_task_graph_harness_run(
                    graph.graph_id,
                    orchestration_api.TaskGraphRunStartRequest(
                        session_id="session-test",
                        execute_initial_stage=False,
                    ),
                )
            )
            raised = None
        except Exception as exc:  # noqa: BLE001 - assert FastAPI error contract directly.
            raised = exc
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert getattr(raised, "status_code", None) == 409
    assert "published GraphHarnessConfig" in str(getattr(raised, "detail", ""))


def test_task_graph_start_api_returns_node_work_order_for_published_config(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = _graph()
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(node.to_dict() for node in graph.nodes),
        runtime_policy=graph.runtime_policy,
        publish_state="published",
        enabled=True,
    )
    publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id="session-test",
                    execute_initial_stage=False,
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["graph_id"] == graph.graph_id
    assert payload["graph_harness_config_id"]
    assert payload["node_work_order"]["node_id"] == "produce"
    assert payload["stage_execution_request"] is None
    assert payload["checkpoint"]["state"]["graph_id"] == graph.graph_id
