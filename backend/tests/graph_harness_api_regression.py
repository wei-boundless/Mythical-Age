from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import orchestration as orchestration_api
from harness import AgentHarness, AgentRuntimeServices, GraphHarness
from harness.runtime import SingleAgentRuntimeHost
from project_layout import ProjectLayout
from task_system import TaskFlowRegistry
from task_system.compiler.graph_harness_config_publisher import (
    build_graph_harness_config_from_graph,
    publish_graph_harness_config_for_graph,
)
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphNodeDefinition
from task_system.repositories import GraphHarnessConfigRepository


class TaskExecutionModelRuntimeStub:
    async def invoke_messages(self, messages, **_kwargs):
        import json

        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:api-graph-node:complete",
                    "action_type": "respond",
                    "final_answer": "API 图节点执行完成。",
                    "diagnostics": {"verification": "api graph work order execution"},
                },
                ensure_ascii=False,
            )
        )


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


def _query_runtime_with_graph_executor(*, base_dir: Path):
    from tests.support.runtime_stubs import (
        DefaultPermissionStub,
        EmptySkillRegistryStub,
        EmptyToolRuntimeStub,
        InMemorySessionManagerStub,
        PrimarySettingsStub,
        QueryRuntimeMemoryFacadeStub,
    )
    from query import QueryRuntime

    return SimpleNamespace(
        base_dir=base_dir,
        query_runtime=QueryRuntime(
            base_dir=base_dir,
            settings_service=PrimarySettingsStub(),
            session_manager=InMemorySessionManagerStub(),
            memory_facade=QueryRuntimeMemoryFacadeStub(),
            retrieval_service=SimpleNamespace(),
            tool_runtime=EmptyToolRuntimeStub(),
            skill_registry=EmptySkillRegistryStub(),
            permission_service=DefaultPermissionStub(),
            model_runtime=TaskExecutionModelRuntimeStub(),
        ),
    )


def test_graph_harness_config_publication_requires_explicit_graph_binding(tmp_path: Path) -> None:
    graph = _graph()
    repository = GraphHarnessConfigRepository(tmp_path)
    config = build_graph_harness_config_from_graph(
        graph=graph,
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
    config = build_graph_harness_config_from_graph(
        graph=stored_graph,
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
    assert payload["graph_run_id"]
    assert payload["graph_harness_config_id"]
    assert payload["node_work_orders"][0]["node_id"] == "produce"
    assert payload["node_work_orders"][0]["work_kind"] == "agent"
    assert payload["graph_run"]["graph_id"] == graph.graph_id
    assert set(payload).issuperset({"graph_run", "graph_loop_state", "node_work_orders", "checkpoint"})
    assert payload["checkpoint"]["state"]["graph_id"] == graph.graph_id


def test_task_graph_start_api_rejects_stale_published_config_as_conflict(tmp_path: Path) -> None:
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
    config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    registry.graph_harness_config_repository.storage.write_object(
        "graph_harness_configs.json",
        {
            "configs": [
                {
                    **config.to_dict(),
                    "content_hash": "stale-content-hash",
                }
            ],
            "published_bindings": {graph.graph_id: config.config_id},
        },
    )
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
                        dispatch_ready=True,
                    ),
                )
            )
            raised = None
        except Exception as exc:  # noqa: BLE001 - assert FastAPI error contract directly.
            raised = exc
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert getattr(raised, "status_code", None) == 409
    assert "content_hash mismatch" in str(getattr(raised, "detail", ""))


def test_graph_harness_api_accepts_node_result_and_returns_next_work_order(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = TaskGraphDefinition(
        graph_id="graph.test.api_result_accept",
        title="API Result Accept Graph",
        graph_kind="multi_agent",
        publish_state="published",
        enabled=True,
        entry_node_id="first",
        output_node_id="second",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="first",
                node_type="agent",
                title="第一节点",
                task_id="task.test.first",
                agent_id="agent:0",
                metadata={
                    "prompt_contract": {
                        "role_prompt": "你是一名第一节点执行员。",
                        "task_instruction": "请完成第一节点任务。",
                    }
                },
            ),
            TaskGraphNodeDefinition(
                node_id="second",
                node_type="agent",
                title="第二节点",
                task_id="task.test.second",
                agent_id="agent:0",
            ),
        ),
        edges=(
            {
                "edge_id": "edge.first.second",
                "source_node_id": "first",
                "target_node_id": "second",
                "edge_type": "structured_handoff",
            },
        ),
    )
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(node.to_dict() for node in graph.nodes),
        edges=tuple(dict(edge) for edge in graph.edges),
        runtime_policy=graph.runtime_policy,
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id="session-test",
                    dispatch_ready=True,
                ),
            )
        )
        first_order = dict(started["node_work_orders"][0])
        accepted = asyncio.run(
            orchestration_api.accept_graph_node_result(
                str(started["graph_run_id"]),
                orchestration_api.GraphNodeResultRequest(
                    graph_harness_config_id=graph_config.config_id,
                    result={
                        "result_id": "nresult:api:first",
                        "task_run_id": str(started["task_run_id"]),
                        "node_id": "first",
                        "work_order_id": str(first_order["work_order_id"]),
                        "outputs": {"first": "ok"},
                    },
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert accepted["accepted_result"]["node_id"] == "first"
    assert accepted["node_work_orders"][0]["node_id"] == "second"
    assert accepted["graph_loop_state"]["completed_node_ids"] == ["first"]
    assert accepted["checkpoint"]["state"]["completed_node_ids"] == ["first"]


def test_graph_harness_dispatch_ready_api_checkpoints_active_work_orders(tmp_path: Path) -> None:
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
    graph_config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id="session-test",
                    dispatch_ready=False,
                ),
            )
        )
        first_dispatch = asyncio.run(
            orchestration_api.dispatch_graph_run_ready_nodes(
                str(started["graph_run_id"]),
                orchestration_api.GraphRunDispatchReadyRequest(
                    graph_harness_config_id=graph_config.config_id,
                    max_requests=1,
                ),
            )
        )
        second_dispatch = asyncio.run(
            orchestration_api.dispatch_graph_run_ready_nodes(
                str(started["graph_run_id"]),
                orchestration_api.GraphRunDispatchReadyRequest(
                    graph_harness_config_id=graph_config.config_id,
                    max_requests=1,
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert first_dispatch["work_order_count"] == 1
    assert first_dispatch["graph_loop_state"]["running_node_ids"] == ["produce"]
    assert second_dispatch["work_order_count"] == 0
    assert second_dispatch["graph_loop_state"]["running_node_ids"] == ["produce"]


def test_graph_harness_api_executes_work_order_and_accepts_result(tmp_path: Path) -> None:
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
    graph_config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _query_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id="session-test",
                    dispatch_ready=True,
                ),
            )
        )
        executed = asyncio.run(
            orchestration_api.execute_graph_work_order(
                str(started["graph_run_id"]),
                orchestration_api.GraphWorkOrderExecuteRequest(
                    graph_harness_config_id=graph_config.config_id,
                    work_order=dict(started["node_work_orders"][0]),
                    max_steps=1,
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert executed["node_result"]["status"] == "completed"
    assert executed["accepted_result"]["node_id"] == "produce"
    assert executed["graph_loop_state"]["status"] == "completed"
    assert executed["graph_result"]["status"] == "completed"
    assert executed["checkpoint"]["state"]["status"] == "completed"


def test_graph_harness_api_runs_graph_until_idle(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = TaskGraphDefinition(
        graph_id="graph.test.api_run_until_idle",
        title="API Run Until Idle Graph",
        graph_kind="multi_agent",
        publish_state="published",
        enabled=True,
        entry_node_id="first",
        output_node_id="second",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="first",
                node_type="agent",
                title="第一节点",
                task_id="task.test.first",
                agent_id="agent:0",
            ),
            TaskGraphNodeDefinition(
                node_id="second",
                node_type="agent",
                title="第二节点",
                task_id="task.test.second",
                agent_id="agent:0",
            ),
        ),
        edges=(
            {
                "edge_id": "edge.first.second",
                "source_node_id": "first",
                "target_node_id": "second",
                "edge_type": "handoff",
            },
        ),
    )
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(node.to_dict() for node in graph.nodes),
        edges=tuple(dict(edge) for edge in graph.edges),
        runtime_policy=graph.runtime_policy,
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _query_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id="session-test",
                    dispatch_ready=True,
                ),
            )
        )
        runner = asyncio.run(
            orchestration_api.run_graph_run_until_idle(
                str(started["graph_run_id"]),
                orchestration_api.GraphRunUntilIdleRequest(
                    graph_harness_config_id=graph_config.config_id,
                    max_node_executions=3,
                    max_node_steps=1,
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert runner["authority"] == "harness.graph_run_runner"
    assert runner["status"] == "completed"
    assert runner["executed_work_order_count"] == 2
    assert runner["graph_loop_state"]["completed_node_ids"] == ["first", "second"]
    assert runner["graph_result"]["status"] == "completed"


def test_task_graph_start_api_can_auto_run_graph(tmp_path: Path) -> None:
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
    runtime = _query_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id="session-test",
                    dispatch_ready=True,
                    run_mode="auto_run",
                    runner_budget={"max_node_executions": 2, "max_node_steps": 1},
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["runner_result"]["status"] == "completed"
    assert payload["runner_result"]["executed_work_order_count"] == 1
    assert payload["runner_result"]["graph_loop_state"]["status"] == "completed"
    assert payload["graph_loop_state"]["status"] == "completed"
    assert payload["task_run"]["status"] == "completed"
    assert payload["graph_run"]["status"] == "completed"
    assert payload["node_work_orders"] == []


def test_graph_run_monitor_returns_recoverable_active_work_orders(tmp_path: Path) -> None:
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
    graph_config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id="session-test",
                    dispatch_ready=True,
                ),
            )
        )
        monitor = asyncio.run(
            orchestration_api.get_graph_run_monitor(
                str(started["graph_run_id"]),
                graph_harness_config_id=graph_config.config_id,
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert monitor["active_node_work_order_count"] == 1
    assert monitor["active_node_work_orders"][0]["work_order_id"] == started["node_work_orders"][0]["work_order_id"]
    assert monitor["active_node_work_orders"][0]["node_id"] == "produce"
