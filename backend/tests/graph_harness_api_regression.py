from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import orchestration as orchestration_api
from harness import AgentRuntimeServices, GraphHarness
from harness.runtime import SingleAgentRuntimeHost
from project_layout import ProjectLayout
from sessions import SessionManager
from task_system import TaskFlowRegistry
from task_system.compiler.graph_harness_config_publisher import (
    build_graph_harness_config_from_graph,
    publish_graph_harness_config_for_graph,
)
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition
from task_system.repositories import GraphHarnessConfigRepository


GRAPH_TEST_SCOPE = {
    "workspace_view": "task_environment",
    "task_environment_id": "",
    "project_id": "",
}


def _graph_test_session(runtime: SimpleNamespace, session_id: str = "session-test") -> str:
    manager = getattr(runtime, "session_manager", None)
    if manager is None:
        manager = SessionManager(runtime.base_dir)
        runtime.session_manager = manager
    created = manager.create_session(title="Graph API test", scope=GRAPH_TEST_SCOPE)
    return str(created["id"])


def _graph_start_request(runtime: SimpleNamespace, **kwargs) -> orchestration_api.TaskGraphRunStartRequest:
    return orchestration_api.TaskGraphRunStartRequest(
        session_id=_graph_test_session(runtime),
        session_scope=GRAPH_TEST_SCOPE,
        **kwargs,
    )


def _runtime_object_payload(graph_harness: GraphHarness, ref: str) -> dict:
    payload = graph_harness._services.runtime_objects.get_object(ref)
    assert payload, f"runtime object not found: {ref}"
    return payload


class TaskExecutionModelRuntimeStub:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def invoke_messages(self, messages, **kwargs):
        import json

        self.calls.append({"messages": list(messages or []), "kwargs": dict(kwargs or {})})
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:api-graph-node:complete",
                    "action_type": "respond",
                    "final_answer": "API 图节点执行完成。",
                    "public_progress_note": "API 图节点已完成当前职责，准备提交给图运行器。",
                    "public_action_state": {
                        "current_judgment": "当前节点结果可提交。",
                        "next_action": "提交结果给图运行器。"
                    },
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
    graph_harness = GraphHarness(services=services)
    return SimpleNamespace(
        base_dir=base_dir,
        session_manager=SessionManager(base_dir),
        harness_runtime=SimpleNamespace(
            graph_harness=graph_harness,
        ),
    )


def _harness_runtime_with_graph_executor(*, base_dir: Path):
    from tests.support.runtime_stubs import (
        DefaultPermissionStub,
        EmptySkillRegistryStub,
        EmptyToolRuntimeStub,
        InMemorySessionManagerStub,
        PrimarySettingsStub,
        HarnessRuntimeFacadeMemoryFacadeStub,
    )
    from harness.entrypoint import HarnessRuntimeFacade

    session_manager = SessionManager(base_dir)
    model_runtime = TaskExecutionModelRuntimeStub()
    harness_runtime = HarnessRuntimeFacade(
        base_dir=base_dir,
        settings_service=PrimarySettingsStub(),
        session_manager=session_manager,
        memory_facade=HarnessRuntimeFacadeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=model_runtime,
    )
    return SimpleNamespace(
        base_dir=base_dir,
        session_manager=session_manager,
        harness_runtime=harness_runtime,
        model_runtime=model_runtime,
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
                    _graph_start_request(runtime, execute_initial_stage=False),
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
        request = _graph_start_request(runtime, execute_initial_stage=False)
        payload = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                request,
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["graph_id"] == graph.graph_id
    assert payload["graph_run_id"]
    assert payload["graph_harness_config_id"]
    assert payload["launch_session_id"] == request.session_id
    assert payload["graph_session_id"] != request.session_id
    assert payload["node_work_orders"][0]["node_id"] == "produce"
    assert payload["node_work_orders"][0]["work_kind"] == "agent"
    assert payload["graph_run"]["graph_id"] == graph.graph_id
    assert payload["graph_run"]["session_id"] == payload["graph_session_id"]
    assert runtime.session_manager.get_task_binding(request.session_id) == {}
    assert runtime.session_manager.get_task_binding(payload["graph_session_id"])["graph_run_id"] == payload["graph_run_id"]
    assert set(payload).issuperset({"graph_run", "graph_loop_state", "node_work_orders", "checkpoint"})
    assert payload["checkpoint"]["state"]["graph_id"] == graph.graph_id


def test_task_graph_start_api_uses_published_project_binding_without_conversation_scope(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = TaskGraphDefinition(
        graph_id="graph.test.project_bound_start",
        title="Project Bound Start",
        graph_kind="multi_agent",
        publish_state="published",
        enabled=True,
        entry_node_id="produce",
        output_node_id="produce",
        runtime_policy={
            "coordinator_agent_id": "agent:0",
            "task_environment_id": "env.coding.vibe_workspace",
            "project_id": "project.development.codebase.langchain_agent",
        },
        nodes=(
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="Produce",
                task_id="task.test.project_bound_start.produce",
                agent_id="agent:0",
            ),
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
        runtime_policy=graph.runtime_policy,
        publish_state="published",
        enabled=True,
    )
    publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")
    launch_session = runtime.session_manager.create_session(title="Launch chat")

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                orchestration_api.TaskGraphRunStartRequest(
                    session_id=str(launch_session["id"]),
                    session_scope=None,
                    initial_inputs={"project_id": "project.user.supplied"},
                    dispatch_ready=True,
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["launch_session_id"] == launch_session["id"]
    assert payload["graph_session_id"] != launch_session["id"]
    assert payload["graph_run"]["workspace_view"] == "project"
    assert payload["graph_run"]["task_environment_id"] == "env.coding.vibe_workspace"
    assert payload["graph_run"]["project_id"] == "project.development.codebase.langchain_agent"
    assert payload["task_run"]["diagnostics"]["runtime_scope"]["project_id"] == "project.development.codebase.langchain_agent"
    assert runtime.session_manager.get_task_binding(str(launch_session["id"])) == {}
    graph_session = runtime.session_manager.get_history(payload["graph_session_id"])
    assert graph_session["scope"]["project_id"] == "project.development.codebase.langchain_agent"
    assert runtime.session_manager.get_task_binding(payload["graph_session_id"])["graph_run_id"] == payload["graph_run_id"]


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
                    _graph_start_request(runtime, dispatch_ready=True),
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
                _graph_start_request(runtime, dispatch_ready=True),
            )
        )
        first_order = dict(started["node_work_orders"][0])
        accepted = asyncio.run(
            orchestration_api.accept_graph_node_result(
                str(started["graph_run_id"]),
                orchestration_api.GraphNodeResultRequest(
                    graph_harness_config_id=graph_config.config_id,
                    session_scope=GRAPH_TEST_SCOPE,
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
                _graph_start_request(runtime, dispatch_ready=False),
            )
        )
        first_dispatch = asyncio.run(
            orchestration_api.dispatch_graph_run_ready_nodes(
                str(started["graph_run_id"]),
                orchestration_api.GraphRunDispatchReadyRequest(
                    graph_harness_config_id=graph_config.config_id,
                    session_scope=GRAPH_TEST_SCOPE,
                    max_requests=1,
                ),
            )
        )
        second_dispatch = asyncio.run(
            orchestration_api.dispatch_graph_run_ready_nodes(
                str(started["graph_run_id"]),
                orchestration_api.GraphRunDispatchReadyRequest(
                    graph_harness_config_id=graph_config.config_id,
                    session_scope=GRAPH_TEST_SCOPE,
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
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                _graph_start_request(runtime, dispatch_ready=True),
            )
        )
        executed = asyncio.run(
            orchestration_api.execute_graph_work_order(
                str(started["graph_run_id"]),
                orchestration_api.GraphWorkOrderExecuteRequest(
                    graph_harness_config_id=graph_config.config_id,
                    session_scope=GRAPH_TEST_SCOPE,
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
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                _graph_start_request(runtime, dispatch_ready=True),
            )
        )
        runner = asyncio.run(
            orchestration_api.run_graph_run_until_idle(
                str(started["graph_run_id"]),
                orchestration_api.GraphRunUntilIdleRequest(
                    graph_harness_config_id=graph_config.config_id,
                    session_scope=GRAPH_TEST_SCOPE,
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
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                _graph_start_request(runtime, dispatch_ready=True, run_mode="auto_run", runner_budget={"max_node_executions": 2, "max_node_steps": 1}),
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
    assert payload["graph_harness_config"]["authority"] == "harness.graph_harness_config.summary"
    assert "nodes" not in payload["graph_harness_config"]


def test_task_graph_start_auto_run_passes_runtime_model_overrides(tmp_path: Path) -> None:
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
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                _graph_start_request(
                    runtime,
                    dispatch_ready=True,
                    run_mode="auto_run",
                    runner_budget={"max_node_executions": 1, "max_node_steps": 1},
                    runtime_overrides={
                        "model_overrides": {
                            "role_groups": {
                                "writing": {
                                    "provider": "deepseek",
                                    "model": "deepseek-v4-pro",
                                    "credential_ref": "env:DEEPSEEK_WRITING_API_KEY",
                                }
                            }
                        }
                    },
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert payload["runner_result"]["status"] == "completed"
    assert runtime.model_runtime.calls
    model_spec = dict(dict(runtime.model_runtime.calls[0]).get("kwargs") or {}).get("model_spec")
    assert dict(model_spec or {})["model"] == "deepseek-v4-pro"
    assert dict(model_spec or {})["credential_ref"] == "env:DEEPSEEK_WRITING_API_KEY"


def test_task_graph_start_auto_run_persists_runtime_settings_patch(tmp_path: Path) -> None:
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
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                _graph_start_request(
                    runtime,
                    dispatch_ready=True,
                    run_mode="auto_run",
                    runner_budget={"max_node_executions": 1, "max_node_steps": 1},
                    runtime_settings_patch={
                        "model_overrides": {
                            "role_groups": {
                                "writing": {
                                    "provider": "deepseek",
                                    "model": "deepseek-v4-pro",
                                    "credential_ref": "env:DEEPSEEK_WRITING_API_KEY",
                                }
                            }
                        }
                    },
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    runtime_settings = dict(dict(payload["graph_loop_state"]["diagnostics"]).get("runtime_settings") or {})
    model_spec = dict(dict(runtime.model_runtime.calls[0]).get("kwargs") or {}).get("model_spec")
    assert runtime_settings["model_overrides"]["role_groups"]["writing"]["model"] == "deepseek-v4-pro"
    assert dict(model_spec or {})["model"] == "deepseek-v4-pro"


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
                _graph_start_request(runtime, dispatch_ready=True),
            )
        )
        monitor = asyncio.run(
            orchestration_api.get_graph_run_monitor(
                str(started["graph_run_id"]),
                graph_harness_config_id=graph_config.config_id,
                workspace_view=GRAPH_TEST_SCOPE["workspace_view"],
                task_environment_id=GRAPH_TEST_SCOPE["task_environment_id"],
                project_id=GRAPH_TEST_SCOPE["project_id"],
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert monitor["active_node_work_order_count"] == 1
    assert monitor["active_node_work_orders"][0]["work_order_id"] == started["node_work_orders"][0]["work_order_id"]
    assert monitor["active_node_work_orders"][0]["node_id"] == "produce"
    assert "input_package" not in monitor["active_node_work_orders"][0]
    assert "events" not in monitor
    assert "node_runtime_views" not in monitor
    assert "work_order_index" not in monitor["graph_loop_state"]
    assert "result_index" not in monitor["graph_loop_state"]
    assert "result_history" not in monitor["graph_loop_state"]
    assert "initial_inputs" not in monitor["graph_loop_state"]
    assert monitor["graph_harness_config"]["authority"] == "harness.graph_harness_config.summary"
    assert "nodes" not in monitor["graph_harness_config"]


def test_graph_run_monitor_missing_session_returns_not_found(tmp_path: Path) -> None:
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
                _graph_start_request(runtime, dispatch_ready=True),
            )
        )
        runtime.session_manager.delete_session(str(dict(started["graph_run"]).get("session_id") or ""))
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                orchestration_api.get_graph_run_monitor(
                    str(started["graph_run_id"]),
                    graph_harness_config_id=graph_config.config_id,
                    workspace_view=GRAPH_TEST_SCOPE["workspace_view"],
                    task_environment_id=GRAPH_TEST_SCOPE["task_environment_id"],
                    project_id=GRAPH_TEST_SCOPE["project_id"],
                )
            )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert raised.value.status_code == 404
    assert dict(raised.value.detail)["message"] == "GraphRun session is missing"


def test_graph_run_until_idle_result_includes_active_work_orders_when_budget_stops(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = TaskGraphDefinition(
        graph_id="graph.test.runner_active_orders",
        title="Runner Active Orders",
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
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                _graph_start_request(runtime, dispatch_ready=True),
            )
        )
        runner = asyncio.run(
            orchestration_api.run_graph_run_until_idle(
                str(started["graph_run_id"]),
                orchestration_api.GraphRunUntilIdleRequest(
                    graph_harness_config_id=graph_config.config_id,
                    session_scope=GRAPH_TEST_SCOPE,
                    max_node_executions=1,
                    max_node_steps=1,
                ),
            )
        )
    finally:
        orchestration_api.require_runtime = original  # type: ignore[assignment]

    assert runner["status"] == "budget_exhausted"
    assert runner["active_node_work_order_count"] == 1
    assert runner["active_node_work_orders"][0]["node_id"] == "second"
    assert runner["graph_loop_state"]["running_node_ids"] == ["second"]


def test_graph_runtime_requires_explicit_project_scope_for_project_scoped_memory(tmp_path: Path) -> None:
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

    with pytest.raises(ValueError, match="project_scoped formal memory requires project_id"):
        runtime.harness_runtime.graph_harness.start_run(
            session_id="session-test",
            task_id="task.test.project_scope",
            graph_config=graph_config,
            initial_inputs={},
            dispatch_ready=True,
        )


def test_graph_node_task_run_uses_session_scope_instead_of_initial_input_project_scope(tmp_path: Path) -> None:
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
    runtime = _harness_runtime_with_graph_executor(base_dir=backend_dir)

    original = orchestration_api.require_runtime
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        started = asyncio.run(
            orchestration_api.start_task_graph_harness_run(
                graph.graph_id,
                _graph_start_request(runtime, initial_inputs={"project_id": "project:explicit"}, dispatch_ready=True),
            )
        )
        executed = asyncio.run(
            orchestration_api.execute_graph_work_order(
                str(started["graph_run_id"]),
                orchestration_api.GraphWorkOrderExecuteRequest(
                    graph_harness_config_id=graph_config.config_id,
                    session_scope=GRAPH_TEST_SCOPE,
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
    assert work_order_scope.get("project_id", "") == ""
    assert task_run_summary.get("project_id", "") == ""
    assert task_run_summary["runtime_scope"].get("project_id", "") == ""


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
                "cursor_key": "unit_index",
                "start_key": "unit_index",
                "end_key": "target_units",
                "step": 1,
                "iteration_index_key": "unit_iteration",
                "iteration_identity_template": "unit-{unit_index}",
                "preserve_iteration_results": True,
                "initial_inputs": {"done_units": 0, "target_units": 3, "unit_index": 1},
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
    loop = runtime.harness_runtime.graph_harness.graph_loop
    started = runtime.harness_runtime.graph_harness.start_run(
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
        route_history = list(dict(state.loop_state or {}).get("route_history") or [])
        last_route_action = str(dict(route_history[-1] if route_history else {}).get("action") or "")
        if expected_node == "router" and last_route_action == "continue":
            assert advance.node_work_orders
            dispatched = advance.node_work_orders[0]
            assert dispatched.node_id == "produce"
            assert dispatched.input_package["loop_context"]["cursor_key"] == "unit_index"
            assert dispatched.input_package["loop_context"]["cursor_value"] == state.initial_inputs["unit_index"]
            assert dispatched.input_package["loop_context"]["iteration_id"] == f"unit-{state.initial_inputs['unit_index']}"
            assert state.active_work_orders == {"produce": dispatched.work_order_id}
            assert state.running_node_ids == ("produce",)
            assert state.ready_node_ids == ()
            assert "router" not in state.active_work_orders
        if advance.node_work_orders:
            order = advance.node_work_orders[0]

    assert state.status == "completed"
    assert state.initial_inputs["done_units"] == 3
    assert state.initial_inputs["unit_index"] == 3
    assert [item["action"] for item in state.loop_state["route_history"]] == ["continue", "continue", "exit"]
    assert set(state.loop_state["iteration_results"]["loop.units"]) == {"unit-1", "unit-2", "unit-3"}
    assert "produce" in state.loop_state["iteration_results"]["loop.units"]["unit-1"]
    assert "router" in state.loop_state["iteration_results"]["loop.units"]["unit-3"]
    assert len(state.result_history["produce"]) == 3
    assert len(state.result_history["commit"]) == 3
    assert len(state.result_history["router"]) == 3
    exit_summary = state.result_index["exit"]
    exit_result = _runtime_object_payload(runtime.harness_runtime.graph_harness, exit_summary["result_ref"])
    assert "outputs" not in exit_summary
    assert exit_result["outputs"]["step"] == 10
    assert completed_orders == ["produce", "commit", "router", "produce", "commit", "router", "produce", "commit", "router", "exit"]


def test_parent_loop_continue_resets_child_loop_cursor_from_child_start_key(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = TaskGraphDefinition(
        graph_id="graph.test.nested_cursor_reset",
        title="Nested Cursor Reset",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="outline",
        output_node_id="volume_review",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        loop_frames=(
            {
                "frame_id": "loop.chapter_unit",
                "scope_id": "loop.chapter_unit",
                "parent_scope_id": "loop.chapter_batch",
                "entry_node_id": "draft",
                "router_node_id": "unit_router",
                "continue_node_id": "draft",
                "exit_node_id": "assemble",
                "scope_node_ids": ["draft", "unit_router"],
                "cursor_key": "chapter_index",
                "start_key": "batch_start_index",
                "end_key": "batch_end_index",
                "step": 1,
                "iteration_identity_template": "chapter-{chapter_index}",
                "reset_scope_on_continue": True,
                "preserve_iteration_results": True,
                "initial_inputs": {"chapter_index": 1, "batch_start_index": 1, "batch_end_index": 10},
            },
            {
                "frame_id": "module.chapter::loop.chapter_batch",
                "scope_id": "module.chapter::loop.chapter_batch",
                "entry_node_id": "outline",
                "router_node_id": "batch_router",
                "continue_node_id": "outline",
                "exit_node_id": "volume_review",
                "scope_node_ids": ["outline", "draft", "unit_router", "assemble", "review", "commit", "batch_router"],
                "cursor_key": "batch_start_index",
                "start_key": "batch_start_index",
                "end_key": "target_unit_count",
                "step": 10,
                "iteration_identity_template": "chapter-batch-{batch_start_index}",
                "reset_scope_on_continue": True,
                "preserve_iteration_results": True,
                "initial_inputs": {
                    "chapter_index": 1,
                    "batch_start_index": 1,
                    "batch_end_index": 10,
                    "target_unit_count": 20,
                    "units_per_batch": 10,
                    "batch_words": 0,
                    "target_words": 999999,
                },
                "derived_fields": [
                    {"key": "batch_end_index", "op": "add", "from_key": "batch_start_index", "value": 9},
                ],
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(node_id="outline", node_type="agent", title="Outline", task_id="task.outline", agent_id="agent:0", loop={"scope_id": "module.chapter::loop.chapter_batch"}),
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="Draft",
                task_id="task.draft",
                agent_id="agent:0",
                loop={"scope_id": "loop.chapter_unit"},
            ),
            TaskGraphNodeDefinition(
                node_id="unit_router",
                node_type="agent",
                title="Unit Router",
                task_id="task.unit_router",
                agent_id="agent:0",
                loop={
                    "scope_id": "loop.chapter_unit",
                    "route_policy": {
                        "mode": "metric_target",
                        "scope_id": "loop.chapter_unit",
                        "continue_node_id": "draft",
                        "exit_node_id": "assemble",
                        "metric_key": "unit_count",
                        "default_increment": 1,
                        "current_key": "chapter_index",
                        "target_key": "batch_end_index",
                    },
                },
            ),
            TaskGraphNodeDefinition(node_id="assemble", node_type="agent", title="Assemble", task_id="task.assemble", agent_id="agent:0", loop={"scope_id": "module.chapter::loop.chapter_batch"}),
            TaskGraphNodeDefinition(node_id="review", node_type="agent", title="Review", task_id="task.review", agent_id="agent:0", loop={"scope_id": "module.chapter::loop.chapter_batch"}),
            TaskGraphNodeDefinition(node_id="commit", node_type="agent", title="Commit", task_id="task.commit", agent_id="agent:0", loop={"scope_id": "module.chapter::loop.chapter_batch"}),
            TaskGraphNodeDefinition(
                node_id="batch_router",
                node_type="agent",
                title="Batch Router",
                task_id="task.batch_router",
                agent_id="agent:0",
                loop={
                    "scope_id": "module.chapter::loop.chapter_batch",
                    "route_policy": {
                        "mode": "metric_target",
                        "scope_id": "module.chapter::loop.chapter_batch",
                        "continue_node_id": "outline",
                        "exit_node_id": "volume_review",
                        "metric_key": "batch_words",
                        "default_increment": 100,
                        "current_key": "batch_words",
                        "target_key": "target_words",
                        "derived_fields": [
                            {"key": "batch_end_index", "op": "add", "from_key": "batch_start_index", "value": 9},
                        ],
                    },
                },
            ),
            TaskGraphNodeDefinition(node_id="volume_review", node_type="agent", title="Volume Review", task_id="task.volume_review", agent_id="agent:0"),
        ),
        edges=(
            TaskGraphEdgeDefinition(edge_id="edge.outline.draft", source_node_id="outline", target_node_id="draft", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.draft.unit_router", source_node_id="draft", target_node_id="unit_router", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.unit_router.assemble", source_node_id="unit_router", target_node_id="assemble", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.assemble.review", source_node_id="assemble", target_node_id="review", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.review.commit", source_node_id="review", target_node_id="commit", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.commit.batch_router", source_node_id="commit", target_node_id="batch_router", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.batch_router.volume_review", source_node_id="batch_router", target_node_id="volume_review", edge_type="handoff"),
        ),
    )
    graph_config = build_graph_harness_config_from_graph(graph=graph)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir, runtime_root=tmp_path / "runtime_state")
    loop = runtime.harness_runtime.graph_harness.graph_loop
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session-test",
        task_id="task.test.nested_cursor_reset",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )

    state = started.loop_state
    order = started.node_work_orders[0]
    while order.node_id != "batch_router":
        advance = loop.accept_node_result(
            graph_config=graph_config,
            graph_run_id=state.graph_run_id,
            result={
                "result_id": f"nresult:{order.node_id}:{state.event_cursor}",
                "graph_run_id": state.graph_run_id,
                "task_run_id": state.task_run_id,
                "node_id": order.node_id,
                "work_order_id": order.work_order_id,
                "outputs": {"unit_count": 1, "batch_words": 100},
            },
        )
        state = advance.loop_state
        order = advance.node_work_orders[0]

    advance = loop.accept_node_result(
        graph_config=graph_config,
        graph_run_id=state.graph_run_id,
        result={
            "result_id": "nresult:batch_router:continue",
            "graph_run_id": state.graph_run_id,
            "task_run_id": state.task_run_id,
            "node_id": order.node_id,
            "work_order_id": order.work_order_id,
            "outputs": {"batch_words": 100},
        },
    )

    state = advance.loop_state
    frames = state.loop_state["frames"]
    assert state.initial_inputs["batch_start_index"] == 11
    assert state.initial_inputs["batch_end_index"] == 20
    assert state.initial_inputs["chapter_index"] == 11
    assert frames["module.chapter::loop.chapter_batch"]["cursor"] == 11
    assert frames["module.chapter::loop.chapter_batch"]["active_iteration_id"] == "chapter-batch-11"
    assert frames["loop.chapter_unit"]["cursor"] == 11
    assert frames["loop.chapter_unit"]["start"] == 11
    assert frames["loop.chapter_unit"]["end"] == 20
    assert frames["loop.chapter_unit"]["active_iteration_id"] == "chapter-11"
    assert "loop.chapter_unit" not in state.loop_state.get("iteration_results", {})
    assert advance.node_work_orders[0].node_id == "outline"


def test_metric_route_patch_cursor_is_not_incremented_twice(tmp_path: Path) -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.volume_cursor_patch",
        title="Volume Cursor Patch",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="next_volume_router",
        output_node_id="done",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        loop_frames=(
            {
                "frame_id": "loop.volume",
                "scope_id": "loop.volume",
                "entry_node_id": "next_volume_router",
                "router_node_id": "next_volume_router",
                "continue_node_id": "next_volume_router",
                "exit_node_id": "done",
                "scope_node_ids": ["next_volume_router"],
                "cursor_key": "volume_index",
                "start_key": "volume_index",
                "end_key": "target_group_count",
                "step": 1,
                "reset_scope_on_continue": True,
                "initial_inputs": {"volume_index": 1, "completed_groups": 0, "target_group_count": 5},
                "derived_fields": [{"key": "volume_index_padded", "op": "format", "template": "{volume_index:03d}"}],
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(
                node_id="next_volume_router",
                node_type="agent",
                title="Next Volume Router",
                task_id="task.next_volume_router",
                agent_id="agent:0",
                loop={
                    "scope_id": "loop.volume",
                    "route_policy": {
                        "mode": "metric_target",
                        "scope_id": "loop.volume",
                        "continue_node_id": "next_volume_router",
                        "exit_node_id": "done",
                        "default_increment": 1,
                        "current_key": "completed_groups",
                        "target_key": "target_group_count",
                        "patch_rules": [{"key": "volume_index", "mode": "increment", "step": 1}],
                        "derived_fields": [{"key": "volume_index_padded", "op": "format", "template": "{volume_index:03d}"}],
                    },
                },
            ),
            TaskGraphNodeDefinition(node_id="done", node_type="agent", title="Done", task_id="task.done", agent_id="agent:0"),
        ),
        edges=(TaskGraphEdgeDefinition(edge_id="edge.router.done", source_node_id="next_volume_router", target_node_id="done", edge_type="handoff"),),
    )
    graph_config = build_graph_harness_config_from_graph(graph=graph)
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    loop = runtime.harness_runtime.graph_harness.graph_loop
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session-test",
        task_id="task.test.volume_cursor_patch",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )

    order = started.node_work_orders[0]
    advance = loop.accept_node_result(
        graph_config=graph_config,
        graph_run_id=started.loop_state.graph_run_id,
        result={
            "result_id": "nresult:next_volume_router:continue",
            "graph_run_id": started.loop_state.graph_run_id,
            "task_run_id": started.loop_state.task_run_id,
            "node_id": order.node_id,
            "work_order_id": order.work_order_id,
            "outputs": {"volume_router_metric": 1},
        },
    )

    assert advance.loop_state.initial_inputs["completed_groups"] == 1
    assert advance.loop_state.initial_inputs["volume_index"] == 2
    assert advance.loop_state.initial_inputs["volume_index_padded"] == "002"


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


def test_graph_harness_config_publication_preserves_progress_receipt_route_source() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.progress_receipt_route_publication",
        title="Progress Receipt Route Publication",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="commit",
        output_node_id="router",
        nodes=(
            TaskGraphNodeDefinition(
                node_id="commit",
                node_type="agent",
                title="Commit",
                task_id="task.test.commit",
            ),
            TaskGraphNodeDefinition(
                node_id="router",
                node_type="agent",
                title="Router",
                task_id="task.test.router",
                loop={
                    "scope_id": "loop.units",
                    "route_policy": {
                        "mode": "progress_receipt",
                        "scope_id": "loop.units",
                        "continue_node_id": "commit",
                        "exit_node_id": "done",
                        "progress_receipt_key": "chapter_progress_receipt",
                        "receipt_source_node_ids": ["commit"],
                        "current_key": "done_units",
                        "target_key": "target_units",
                    },
                },
            ),
            TaskGraphNodeDefinition(
                node_id="done",
                node_type="agent",
                title="Done",
                task_id="task.test.done",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(edge_id="edge.commit.router", source_node_id="commit", target_node_id="router"),
            TaskGraphEdgeDefinition(edge_id="edge.router.done", source_node_id="router", target_node_id="done"),
        ),
    )

    config = build_graph_harness_config_from_graph(graph=graph)
    router = next(item for item in config.nodes if item["node_id"] == "router")
    route_policy = router["loop"]["route_policy"]

    assert route_policy["mode"] == "progress_receipt"
    assert route_policy["progress_receipt_key"] == "chapter_progress_receipt"
    assert route_policy["receipt_source_node_ids"] == ["commit"]
    assert "fallback_increment_key" not in route_policy
    assert "default_increment" not in route_policy


def test_graph_module_expansion_scopes_progress_receipt_route_source() -> None:
    child = TaskGraphDefinition(
        graph_id="graph.test.progress_receipt_child",
        title="Progress Receipt Child",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="commit",
        output_node_id="router",
        loop_frames=(
            {
                "frame_id": "loop.units",
                "scope_id": "loop.units",
                "parent_scope_id": "loop.batches",
                "entry_node_id": "commit",
                "router_node_id": "router",
                "continue_node_id": "commit",
                "exit_node_id": "done",
            },
            {
                "frame_id": "loop.batches",
                "scope_id": "loop.batches",
                "entry_node_id": "commit",
                "router_node_id": "router",
                "continue_node_id": "commit",
                "exit_node_id": "done",
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(node_id="commit", node_type="agent", title="Commit", task_id="task.test.commit"),
            TaskGraphNodeDefinition(
                node_id="router",
                node_type="agent",
                title="Router",
                task_id="task.test.router",
                loop={
                    "scope_id": "loop.units",
                    "route_policy": {
                        "mode": "progress_receipt",
                        "scope_id": "loop.units",
                        "continue_node_id": "commit",
                        "exit_node_id": "done",
                        "progress_receipt_key": "chapter_progress_receipt",
                        "receipt_source_node_ids": ["commit"],
                    },
                },
            ),
            TaskGraphNodeDefinition(node_id="done", node_type="agent", title="Done", task_id="task.test.done"),
        ),
        edges=(
            TaskGraphEdgeDefinition(edge_id="edge.commit.router", source_node_id="commit", target_node_id="router"),
            TaskGraphEdgeDefinition(edge_id="edge.router.done", source_node_id="router", target_node_id="done"),
        ),
    )
    parent = TaskGraphDefinition(
        graph_id="graph.test.progress_receipt_parent",
        title="Progress Receipt Parent",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="module.child",
        output_node_id="module.child",
        nodes=(
            TaskGraphNodeDefinition(
                node_id="module.child",
                node_type="graph_module",
                title="Child",
                executor_policy={
                    "default_executor": "graph_module",
                    "linked_graph_id": child.graph_id,
                },
                metadata={
                    "graph_module": True,
                    "linked_graph_id": child.graph_id,
                    "composition_scope_prefix": "module.child::",
                },
            ),
        ),
    )

    config = build_graph_harness_config_from_graph(
        graph=parent,
        graph_lookup={child.graph_id: child},
    )
    router = next(item for item in config.nodes if item["node_id"] == "module.child::router")
    route_policy = router["loop"]["route_policy"]
    unit_frame = next(item for item in config.loop_frames if item["frame_id"] == "module.child::loop.units")
    batch_frame = next(item for item in config.loop_frames if item["frame_id"] == "module.child::loop.batches")

    assert route_policy["continue_node_id"] == "module.child::commit"
    assert route_policy["exit_node_id"] == "module.child::done"
    assert route_policy["receipt_source_node_ids"] == ["module.child::commit"]
    assert unit_frame["parent_scope_id"] == "module.child::loop.batches"
    assert batch_frame["scope_id"] == "module.child::loop.batches"
