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
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition
from task_system.repositories import GraphHarnessConfigRepository


def _runtime_object_payload(graph_harness: GraphHarness, ref: str) -> dict:
    payload = graph_harness._services.runtime_objects.get_object(ref)
    assert payload, f"runtime object not found: {ref}"
    return payload


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
    assert "input_package" not in monitor["active_node_work_orders"][0]


def test_graph_runtime_generates_managed_project_scope_for_project_scoped_memory(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = TaskGraphDefinition(
        graph_id="graph.test.project_scoped_memory_start",
        title="Project Scoped Memory Start",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="produce",
        output_node_id="produce",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="memory.project.baseline",
                node_type="memory_repository",
                title="Project Baseline",
                resource_lifecycle_policy={"scope_kind": "project_scoped", "scope_required": True},
                metadata={
                    "memory_repository": {
                        "repository_id": "memory.project.baseline",
                        "collections": ["baseline"],
                        "lifecycle_policy": {"scope_kind": "project_scoped", "scope_required": True},
                    }
                },
            ),
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="Produce",
                task_id="task.test.project_scoped_memory_start.produce",
                agent_id="agent:0",
            ),
        ),
    )
    graph_config = build_graph_harness_config_from_graph(graph=graph)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")

    started = runtime.query_runtime.graph_harness.start_run(
        session_id="session-test",
        task_id="task.test.project_scope",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )

    runtime_scope = dict(started.envelope.memory_scope["runtime_scope"])
    assert runtime_scope["project_id"].startswith("graphrun.")
    assert started.task_run.diagnostics["runtime_scope"]["project_id"] == runtime_scope["project_id"]
    assert started.loop_state.diagnostics["runtime_scope"]["project_id"] == runtime_scope["project_id"]
    assert started.node_work_orders[0].input_package["runtime_scope"]["project_id"] == runtime_scope["project_id"]
    repositories = runtime.query_runtime.graph_harness._services.formal_memory_service.overview()["repositories"]
    assert repositories[0]["effective_repository_id"] == f"project:{runtime_scope['project_id']}:memory.project.baseline"


def test_graph_node_task_run_receives_explicit_runtime_project_scope(tmp_path: Path) -> None:
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
                    initial_inputs={"project_id": "project:explicit"},
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
                    accept_result=False,
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    work_order_scope = dict(started["node_work_orders"][0]["input_package"]["runtime_scope"])
    task_run_summary = dict(executed["node_executor_task_run"])
    assert work_order_scope["project_id"] == "project:explicit"
    assert task_run_summary["project_id"] == "project:explicit"
    assert task_run_summary["runtime_scope"]["project_id"] == "project:explicit"


def test_graph_loop_contract_drives_generic_repeated_node_progression(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = TaskGraphDefinition(
        graph_id="graph.test.generic_loop_contract",
        title="Generic Loop Contract Graph",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="produce",
        output_node_id="exit",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        loop_frames=(
            {
                "frame_id": "loop.units",
                "scope_id": "loop.units",
                "title": "Unit loop",
                "kind": "bounded_metric_iteration",
                "entry_node_id": "produce",
                "router_node_id": "router",
                "continue_node_id": "produce",
                "exit_node_id": "exit",
                "initial_inputs": {"done_units": 0, "target_units": 3},
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="Produce",
                task_id="task.test.loop.produce",
                agent_id="agent:0",
                loop={"scope_id": "loop.units", "kind": "bounded_metric_iteration"},
            ),
            TaskGraphNodeDefinition(
                node_id="commit",
                node_type="agent",
                title="Commit",
                task_id="task.test.loop.commit",
                agent_id="agent:0",
                loop={"scope_id": "loop.units", "kind": "bounded_metric_iteration"},
            ),
            TaskGraphNodeDefinition(
                node_id="router",
                node_type="agent",
                title="Router",
                task_id="task.test.loop.router",
                agent_id="agent:0",
                loop={
                    "scope_id": "loop.units",
                    "kind": "bounded_metric_iteration",
                    "route_policy": {
                        "mode": "metric_target",
                        "scope_id": "loop.units",
                        "continue_node_id": "produce",
                        "exit_node_id": "exit",
                        "metric_key": "unit_count",
                        "default_increment": 1,
                        "current_key": "done_units",
                        "target_key": "target_units",
                    },
                },
            ),
            TaskGraphNodeDefinition(
                node_id="exit",
                node_type="agent",
                title="Exit",
                task_id="task.test.loop.exit",
                agent_id="agent:0",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.produce.commit",
                source_node_id="produce",
                target_node_id="commit",
                edge_type="handoff",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.commit.router",
                source_node_id="commit",
                target_node_id="router",
                edge_type="handoff",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.router.exit",
                source_node_id="router",
                target_node_id="exit",
                edge_type="handoff",
            ),
        ),
    )
    graph_config = build_graph_harness_config_from_graph(graph=graph)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")
    loop = runtime.query_runtime.graph_harness.graph_loop
    started = runtime.query_runtime.graph_harness.start_run(
        session_id="session-test",
        task_id="task.test.loop",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )

    state = started.loop_state
    order = started.node_work_orders[0]
    completed_orders: list[str] = []
    for expected_node in ("produce", "commit", "router", "produce", "commit", "router", "produce", "commit", "router", "exit"):
        assert order.node_id == expected_node
        completed_orders.append(order.node_id)
        advance = loop.accept_node_result(
            graph_config=graph_config,
            graph_run_id=state.graph_run_id,
            result={
                "result_id": f"nresult:{expected_node}:{len(completed_orders)}",
                "graph_run_id": state.graph_run_id,
                "task_run_id": state.task_run_id,
                "node_id": order.node_id,
                "work_order_id": order.work_order_id,
                "outputs": {"unit_count": 1, "step": len(completed_orders)},
            },
        )
        state = advance.loop_state
        if advance.node_work_orders:
            order = advance.node_work_orders[0]

    assert state.status == "completed"
    assert state.initial_inputs["done_units"] == 3
    assert [item["action"] for item in state.loop_state["route_history"]] == ["continue", "continue", "exit"]
    assert len(state.result_history["produce"]) == 3
    assert len(state.result_history["commit"]) == 3
    assert len(state.result_history["router"]) == 3
    exit_summary = state.result_index["exit"]
    exit_result = _runtime_object_payload(runtime.query_runtime.graph_harness, exit_summary["result_ref"])
    assert "outputs" not in exit_summary
    assert exit_result["outputs"]["step"] == 10
    assert completed_orders == ["produce", "commit", "router", "produce", "commit", "router", "produce", "commit", "router", "exit"]


def test_graph_harness_config_publication_preserves_formal_node_loop_contract() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.loop_publication",
        title="Loop Publication",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="router",
        output_node_id="router",
        nodes=(
            TaskGraphNodeDefinition(
                node_id="router",
                node_type="agent",
                title="Router",
                task_id="task.test.router",
                loop={
                    "scope_id": "loop.units",
                    "kind": "bounded_metric_iteration",
                    "title_template": "Unit {done_units}",
                    "route_policy": {
                        "scope_id": "loop.units",
                        "continue_node_id": "router",
                        "exit_node_id": "exit",
                        "current_key": "done_units",
                        "target_key": "target_units",
                        "patch_rules": [{"key": "cursor", "mode": "increment", "step": 1}],
                    },
                },
            ),
        ),
    )

    config = build_graph_harness_config_from_graph(graph=graph)
    node = dict(config.nodes[0])
    loop_contract = dict(node.get("loop") or {})

    assert loop_contract["scope_id"] == "loop.units"
    assert loop_contract["title_template"] == "Unit {done_units}"
    assert loop_contract["route_policy"]["scope_id"] == "loop.units"
    assert loop_contract["route_policy"]["continue_node_id"] == "router"
    assert loop_contract["route_policy"]["exit_node_id"] == "exit"
    assert loop_contract["route_policy"]["patch_rules"] == [{"key": "cursor", "mode": "increment", "step": 1}]
    assert "title_template" not in node
    assert set(loop_contract["route_policy"]).issubset(
        {"scope_id", "continue_node_id", "exit_node_id", "mode", "current_key", "target_key", "patch_rules", "authority"}
    )
