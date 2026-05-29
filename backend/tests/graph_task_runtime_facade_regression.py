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
    assert start.node_work_orders[0].input_package["initial_inputs"] == {"goal": "smoke"}
    assert start.node_work_orders[0].input_package["materializer_authority"] == "harness.graph.context_materializer"
    assert start.node_work_orders[0].input_package["node_identity"]["node_id"] == "draft"
    assert "内容起草员" in start.node_work_orders[0].input_package["agent_instruction"]
    assert start.loop_state.work_order_index[start.node_work_orders[0].work_order_id]["node_id"] == "draft"
    assert runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)["graph_id"] == graph.graph_id
    monitor = runtime.graph_harness.get_graph_run_monitor(start.graph_run.graph_run_id, graph_config=graph_config)
    assert monitor is not None
    assert monitor["graph_run_id"] == start.graph_run.graph_run_id
    assert monitor["graph_loop_state"]["graph_id"] == graph.graph_id
    assert monitor["active_node_work_order_count"] == 1
    assert monitor["active_node_work_orders"][0]["work_order_id"] == start.node_work_orders[0].work_order_id
    trace = runtime.single_agent_runtime_host.get_trace(start.task_run.task_run_id)
    assert trace is not None
    assert trace["graph_run_count"] == 1
    assert trace["graph_runs"][0]["graph_run_id"] == start.graph_run.graph_run_id


def test_graph_loop_persists_state_through_langgraph_checkpoint_store() -> None:
    runtime = _runtime("graph-task-langgraph-checkpoint-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.langgraph_checkpoint_store",
        title="LangGraph Checkpoint Store",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "task_id": "task.test.draft",
                "agent_id": "agent:0",
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
        initial_inputs={"goal": "checkpoint"},
    )

    checkpoint_store = runtime.single_agent_runtime_host.graph_checkpoint_store
    latest = checkpoint_store.get_latest_checkpoint(start.graph_run.graph_run_id)

    assert latest is not None
    assert latest.metadata["backend"] == "harness.graph_checkpoint_store.langgraph"
    assert latest.state["graph_id"] == graph.graph_id
    assert latest.state["active_work_orders"] == {start.node_work_orders[0].node_id: start.node_work_orders[0].work_order_id}
    assert latest.pending_writes
    assert latest.pending_writes[0][1] == "active_work_order"
    assert latest.pending_writes[0][2]["work_order_id"] == start.node_work_orders[0].work_order_id
    assert latest.to_dict()["checkpoint_id"].startswith("gchk:")
    assert runtime.graph_harness.get_latest_checkpoint(start.graph_run.graph_run_id)["checkpoint_id"].startswith("gchk:")
    assert runtime.graph_harness.list_checkpoints(start.graph_run.graph_run_id, limit=1)[0]["checkpoint_id"].startswith("gchk:")
    assert runtime.single_agent_runtime_host.runtime_objects.get_object(
        f"rtobj:graph_loop_state:{start.graph_run.graph_run_id.replace(':', '_')}"
    ) == {}


def test_graph_loop_fails_closed_when_no_schedulable_start_node_exists() -> None:
    runtime = _runtime("graph-task-unschedulable-start-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.unschedulable_cycle",
        title="Unschedulable Cycle",
        graph_kind="multi_agent",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "review", "node_type": "agent", "title": "审核", "task_id": "task.test.review", "agent_id": "agent:0"},
        ),
        edges=(
            {"edge_id": "edge.draft.review", "source_node_id": "draft", "target_node_id": "review", "edge_type": "handoff"},
            {"edge_id": "edge.review.draft", "source_node_id": "review", "target_node_id": "draft", "edge_type": "handoff"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)

    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(start.task_run.task_run_id)
    graph_run = runtime.graph_harness.get_graph_run(start.graph_run.graph_run_id)

    assert start.loop_state.status == "failed"
    assert start.loop_state.terminal_reason == "no_schedulable_start_nodes"
    assert start.task_run.status == "failed"
    assert start.graph_run.status == "failed"
    assert start.node_work_orders == ()
    assert start.checkpoint["state"]["status"] == "failed"
    assert start.checkpoint["state"]["terminal_reason"] == "no_schedulable_start_nodes"
    assert task_run is not None
    assert task_run.status == "failed"
    assert graph_run["status"] == "failed"


def test_graph_loop_fails_closed_for_resource_only_graph() -> None:
    runtime = _runtime("graph-task-resource-only-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.resource_only",
        title="Resource Only",
        graph_kind="multi_agent",
        nodes=(
            {"node_id": "memory.world", "node_type": "memory_repository", "title": "世界观记忆库"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)

    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(start.task_run.task_run_id)

    assert start.loop_state.status == "failed"
    assert start.loop_state.terminal_reason == "no_executable_nodes"
    assert start.task_run.status == "failed"
    assert start.graph_run.status == "failed"
    assert start.node_work_orders == ()
    assert task_run is not None
    assert task_run.status == "failed"


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
    assert advance.node_work_orders[0].input_package["materializer_authority"] == "harness.graph.context_materializer"
    assert advance.node_work_orders[0].input_package["upstream_results"][0]["source_node_id"] == "draft"
    assert advance.node_work_orders[0].input_package["upstream_results"][0]["outputs"] == {"draft": "ok"}
    assert advance.node_work_orders[0].input_package["upstream_handoff_packets"][0]["edge_id"] == "edge.draft.review"
    assert advance.node_work_orders[0].input_package["handoff_packets"][0]["edge_id"] == "edge.draft.review"
    assert advance.node_work_orders[0].input_package["handoff_packets"][0]["payload"]["outputs"] == {"draft": "ok"}
    assert advance.loop_state.edge_states["edge.draft.review"]["status"] == "ready"
    assert advance.loop_state.work_order_index[advance.node_work_orders[0].work_order_id]["node_id"] == "review"
    assert advance.graph_result is None


def test_node_result_envelope_fails_closed_on_invalid_payload() -> None:
    invalid_payloads = (
        {
            "result_id": "",
            "graph_run_id": "grun:test",
            "task_run_id": "taskrun:test",
            "node_id": "draft",
            "work_order_id": "gwork:test",
            "outputs": {"ok": True},
        },
        {
            "result_id": "nresult:test",
            "graph_run_id": "grun:test",
            "task_run_id": "taskrun:test",
            "node_id": "draft",
            "work_order_id": "gwork:test",
            "status": "waiting",
            "outputs": {"ok": True},
        },
        {
            "result_id": "nresult:test",
            "graph_run_id": "grun:test",
            "task_run_id": "taskrun:test",
            "node_id": "draft",
            "work_order_id": "gwork:test",
            "status": "failed",
        },
    )

    for payload in invalid_payloads:
        try:
            NodeResultEnvelope.from_dict(payload)
            raised = None
        except ValueError as exc:
            raised = exc
        assert raised is not None


def test_graph_resume_reconnects_active_work_orders_from_checkpoint() -> None:
    runtime = _runtime("graph-task-resume-active-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.resume_active",
        title="Resume Active",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    resumed = runtime.graph_harness.resume_run(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
    )

    assert resumed.resumed is True
    assert resumed.reason == "active_work_orders_reconnected"
    assert resumed.active_work_orders[0]["work_order_id"] == start.node_work_orders[0].work_order_id
    assert resumed.node_work_orders == ()


def test_graph_resume_fails_closed_on_config_hash_mismatch() -> None:
    runtime = _runtime("graph-task-resume-hash-mismatch-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.resume_hash_mismatch",
        title="Resume Hash Mismatch",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    wrong_config = type(graph_config)(
        **{
            **graph_config.to_dict(),
            "content_hash": "wrong-hash",
        }
    )

    try:
        runtime.graph_harness.resume_run(
            graph_config=wrong_config,
            graph_run_id=start.graph_run.graph_run_id,
        )
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "config_hash mismatch" in str(raised)


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
    stored_graph_result = runtime.single_agent_runtime_host.runtime_objects.get_object(
        "rtobj:graph_result:" + execution["graph_result"]["result_id"].replace(":", "_")
    )
    assert stored_graph_result["authority"] == "harness.graph_result_envelope"
    assert stored_graph_result["graph_run_id"] == start.graph_run.graph_run_id
    assert execution["node_executor_task_run"]["task_run_id"].startswith("gtask:")


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
    assert graph_config.composition_sources[0]["composition_node_id"] == "graph_module.child"
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
