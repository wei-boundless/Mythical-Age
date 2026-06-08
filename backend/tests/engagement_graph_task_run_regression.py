from __future__ import annotations

from pathlib import Path

from harness.runtime import SingleAgentRuntimeHost
from sessions import SessionManager
from task_system.engagement import EngagementPlanRepository, EngagementService
from task_system.compiler.graph_harness_config_publisher import publish_graph_harness_config_for_graph
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphNodeDefinition
from task_system.registry.flow_registry import TaskFlowRegistry


def _graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.test.engagement_single_agent",
        title="Engagement Single Agent Graph",
        graph_kind="single_agent",
        publish_state="published",
        enabled=True,
        entry_node_id="main",
        output_node_id="main",
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        context_policy={"task_environment_id": "env.development.sandbox"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="main",
                node_type="agent",
                title="主执行节点",
                task_id="task.test.engagement_single_agent.main",
                agent_id="agent:0",
                contract_bindings={
                    "schema": {
                        "input_contract_id": "contract.test.input",
                        "output_contract_id": "contract.test.output",
                    },
                    "artifact": {
                        "artifact_policy": {
                            "required": True,
                            "artifact_target": "storage/task_environments/development/sandbox/artifacts/index.html",
                        }
                    },
                    "acceptance": {
                        "completion_criteria": ["write the requested artifact"],
                    },
                },
                metadata={
                    "prompt_contract": {
                        "role_prompt": "你是一名主执行节点。",
                        "task_instruction": "你只负责完成当前图节点交付物。",
                    }
                },
            ),
        ),
    )


def _plan() -> dict[str, object]:
    return {
        "plan_id": "engage.test.graph_task_run",
        "title": "Graph Task Run Engagement",
        "description": "Start a published task graph through engagement.",
        "version": "1.0.0",
        "status": "active",
        "task_environment_id": "env.development.sandbox",
        "assignee": {"kind": "agent", "agent_id": "agent:0"},
        "runtime_profile": {"runtime_policy": {}},
        "execution_strategy": {
            "kind": "graph_task_run",
            "startup_policy": {"graph_id": "graph.test.engagement_single_agent"},
            "lifecycle_policy": {},
        },
        "input_contract": {},
        "output_contract": {},
        "prompt_contract": {},
        "acceptance_policy": {},
    }


def test_engagement_graph_task_run_starts_published_graph_harness(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = _graph()
    registry = TaskFlowRegistry(backend_dir)
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        domain_id=graph.domain_id,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(node.to_dict() for node in graph.nodes),
        edges=tuple(edge.to_dict() for edge in graph.edges),
        runtime_policy=graph.runtime_policy,
        context_policy=graph.context_policy,
        publish_state=graph.publish_state,
        enabled=graph.enabled,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    EngagementPlanRepository(backend_dir).upsert(_plan())
    runtime_host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=backend_dir)

    result = EngagementService(backend_dir).start(
        runtime_host=runtime_host,
        plan_id="engage.test.graph_task_run",
        session_id="session:test",
        startup_parameters={},
    )

    assert result["decision"] == "started"
    assert result["execution_strategy"] == "graph_task_run"
    assert result["graph_run"]["graph_id"] == graph.graph_id
    assert result["graph_run"]["session_id"] != "session:test"
    assert result["graph_run"]["session_id"].startswith("graph-session-")
    assert result["graph_harness_config"]["config_id"] == graph_config.config_id
    assert result["task_run"]["diagnostics"]["graph_id"] == graph.graph_id
    assert result["task_run"]["diagnostics"]["launch_session_id"] == "session:test"
    assert result["node_work_orders"][0]["node_id"] == "main"
    assert result["engagement_run"]["task_run_id"] == result["task_run"]["task_run_id"]
    assert result["engagement_run"]["workflow_run_id"] == result["graph_run"]["graph_run_id"]
    graph_session = SessionManager(backend_dir).get_history(result["graph_run"]["session_id"])
    assert graph_session["task_binding"]["graph_run_id"] == result["graph_run"]["graph_run_id"]


def test_engagement_graph_task_run_requires_published_graph_config(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    graph = _graph()
    TaskFlowRegistry(backend_dir).upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(node.to_dict() for node in graph.nodes),
        runtime_policy=graph.runtime_policy,
        context_policy=graph.context_policy,
        publish_state=graph.publish_state,
        enabled=graph.enabled,
    )
    EngagementPlanRepository(backend_dir).upsert(_plan())
    runtime_host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=backend_dir)

    result = EngagementService(backend_dir).start(
        runtime_host=runtime_host,
        plan_id="engage.test.graph_task_run",
        session_id="session:test",
        startup_parameters={},
    )

    assert result["decision"] == "invalid"
    assert "published_graph_harness_config_required:graph.test.engagement_single_agent" in result["admission"]["environment_errors"]
