from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness import AgentHarness, GraphHarness
from harness.graph.models import NodeResultEnvelope
from query import QueryRuntime
from task_system import TaskFlowRegistry
from task_system.compiler.graph_harness_config_publisher import publish_graph_harness_config_for_graph
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
    SingleMessageModelRuntimeStub,
    isolated_backend_root,
)


class TaskExecutionModelRuntimeStub:
    async def invoke_messages(self, messages, **_kwargs):
        import json
        from types import SimpleNamespace

        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:graph-node:complete",
                    "action_type": "respond",
                    "final_answer": "图节点执行完成，可交给下游节点。",
                    "diagnostics": {"verification": "test graph node execution"},
                },
                ensure_ascii=False,
            )
        )


def _runtime(prefix: str = "graph-task-runtime-facade-") -> QueryRuntime:
    return QueryRuntime(
        base_dir=isolated_backend_root(prefix),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )


def test_query_runtime_exposes_graph_harness_facade() -> None:
    runtime = _runtime()

    assert isinstance(runtime.agent_harness, AgentHarness)
    assert isinstance(runtime.graph_harness, GraphHarness)
    assert runtime.runtime_components["agent_harness"] == "active"
    assert runtime.runtime_components["graph_harness"] == "active"
    assert not hasattr(runtime.graph_harness.graph_loop, "_engine")
    assert hasattr(runtime.graph_harness, "get_graph_run_monitor")


def test_graph_harness_starts_published_config_and_creates_node_work_order() -> None:
    runtime = _runtime("graph-task-runtime-start-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.new_harness_start",
        title="New Graph Harness Start",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "task_id": "task.test.draft",
                "agent_id": "agent:0",
                "metadata": {
                    "prompt_contract": {
                        "role_prompt": "你是一名内容起草员。",
                        "task_instruction": "请根据输入完成当前起草任务，并输出可交付结果。",
                    }
                },
            },
            {
                "node_id": "review",
                "node_type": "agent",
                "title": "审核",
                "task_id": "task.test.review",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "edge.draft.review",
                "source_node_id": "draft",
                "target_node_id": "review",
                "edge_type": "handoff",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)

    start = runtime.graph_harness.start_run(
        session_id="session:test",
        task_id="",
        graph_config=graph_config,
        initial_inputs={"goal": "smoke"},
    )

    assert start.task_run.status == "running"
    assert start.graph_run.graph_id == graph.graph_id
    assert start.loop_state.config_id == graph_config.config_id
    assert start.node_work_orders[0].node_id == "draft"
    assert start.node_work_orders[0].work_kind == "agent"
    assert start.node_work_orders[0].graph_run_id == start.graph_run.graph_run_id
    assert "内容起草员" in start.node_work_orders[0].message
    assert runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)["graph_id"] == graph.graph_id
    monitor = runtime.graph_harness.get_graph_run_monitor(start.graph_run.graph_run_id, graph_config=graph_config)
    assert monitor is not None
    assert monitor["graph_run_id"] == start.graph_run.graph_run_id
    assert monitor["graph_loop_state"]["graph_id"] == graph.graph_id


def test_graph_loop_accepts_node_result_and_advances_to_next_node() -> None:
    runtime = _runtime("graph-task-runtime-advance-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.new_harness_advance",
        title="New Graph Harness Advance",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "review", "node_type": "agent", "title": "审核", "task_id": "task.test.review", "agent_id": "agent:0"},
        ),
        edges=(
            {
                "edge_id": "edge.draft.review",
                "source_node_id": "draft",
                "target_node_id": "review",
                "edge_type": "handoff",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    first_order = start.node_work_order

    advance = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:draft",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=str(first_order["work_order_id"]),
            outputs={"draft": "ok"},
        ),
    )

    assert "draft" in advance.loop_state.completed_node_ids
    assert advance.node_work_orders
    assert advance.node_work_orders[0].node_id == "review"
    assert advance.graph_result is None


def test_graph_harness_executes_agent_work_order_and_advances_loop() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("graph-task-runtime-execute-work-order-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=TaskExecutionModelRuntimeStub(),
    )
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.execute_work_order",
        title="Execute Work Order",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "执行",
                "task_id": "task.test.execute",
                "agent_id": "agent:0",
                "metadata": {
                    "prompt_contract": {
                        "role_prompt": "你是一名图节点执行员。",
                        "task_instruction": "请完成当前节点任务，并输出可被下游消费的结果。",
                    }
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    execution = asyncio.run(
        runtime.graph_harness.execute_work_order(
            graph_config=graph_config,
            work_order=start.node_work_orders[0],
            max_steps=1,
        )
    )

    assert execution["node_result"]["status"] == "completed"
    assert execution["accepted_result"]["node_id"] == "draft"
    assert execution["graph_loop_state"]["status"] == "completed"
    assert execution["graph_result"]["status"] == "completed"
    assert execution["node_executor_task_run"]["task_run_id"].startswith("gtask:")
    assert "stage_execution_request" not in str(execution)
    assert "coordination_run_id" not in str(execution)


def test_graph_module_is_expanded_before_graph_harness_runtime() -> None:
    runtime = _runtime("graph-task-module-expansion-")
    registry = TaskFlowRegistry(runtime.base_dir)
    registry.upsert_task_graph(
        graph_id="graph.test.imported_child",
        title="Imported Child",
        graph_kind="multi_agent",
        entry_node_id="child_draft",
        output_node_id="child_review",
        nodes=(
            {
                "node_id": "child_draft",
                "node_type": "agent",
                "title": "子图起草",
                "task_id": "task.test.child_draft",
                "agent_id": "agent:0",
            },
            {
                "node_id": "child_review",
                "node_type": "agent",
                "title": "子图审核",
                "task_id": "task.test.child_review",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "edge.child_draft.review",
                "source_node_id": "child_draft",
                "target_node_id": "child_review",
                "edge_type": "handoff",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    parent = registry.upsert_task_graph(
        graph_id="graph.test.parent_with_composition",
        title="Parent With Composition",
        graph_kind="multi_agent",
        entry_node_id="prepare",
        output_node_id="finalize",
        nodes=(
            {
                "node_id": "prepare",
                "node_type": "agent",
                "title": "准备",
                "task_id": "task.test.prepare",
                "agent_id": "agent:0",
            },
            {
                "node_id": "graph_module.child",
                "node_type": "graph_module",
                "title": "导入子图",
                "metadata": {
                    "linked_graph_id": "graph.test.imported_child",
                    "graph_module_runtime_plan_id": "graph_module_runtime.child",
                },
            },
            {
                "node_id": "finalize",
                "node_type": "agent",
                "title": "收口",
                "task_id": "task.test.finalize",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "edge.prepare.child",
                "source_node_id": "prepare",
                "target_node_id": "graph_module.child",
                "edge_type": "handoff",
            },
            {
                "edge_id": "edge.child.finalize",
                "source_node_id": "graph_module.child",
                "target_node_id": "finalize",
                "edge_type": "handoff",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )

    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=parent.graph_id)

    node_ids = {str(node.get("node_id")) for node in graph_config.nodes}
    edge_pairs = {(str(edge.get("source_node_id")), str(edge.get("target_node_id"))) for edge in graph_config.edges}
    executor_types = {str(dict(node.get("executor") or {}).get("executor_type")) for node in graph_config.nodes}

    assert "graph_module.child" not in node_ids
    assert "graph_module.child::child_draft" in node_ids
    assert "graph_module.child::child_review" in node_ids
    assert ("prepare", "graph_module.child::child_draft") in edge_pairs
    assert ("graph_module.child::child_review", "finalize") in edge_pairs
    assert "graph_module" not in executor_types
    assert not hasattr(graph_config, "modules")
    assert graph_config.composition_sources[0]["runtime_node_id"] == "graph_module.child"
    assert graph_config.control["start_node_ids"] == ["prepare"]
    assert graph_config.control["terminal_node_ids"] == ["finalize"]

    start = runtime.graph_harness.start_run(
        session_id="session:test",
        task_id="",
        graph_config=graph_config,
        initial_inputs={"goal": "module expansion"},
    )

    assert start.node_work_orders[0].node_id == "prepare"
    assert start.node_work_orders[0].work_kind == "agent"
