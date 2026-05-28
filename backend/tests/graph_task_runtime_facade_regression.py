from __future__ import annotations

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
