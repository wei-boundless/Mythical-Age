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
from harness.loop.task_executor import recover_interrupted_task_executors
from runtime.shared.models import TaskRun
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
                    "diagnostics": {
                        "verification": "test graph node execution",
                        "world_memory_candidate": {
                            "record_key": "world.current",
                            "record_kind": "world_fact",
                            "canonical_text": "图节点确认世界观设定。",
                            "summary": "图节点确认世界观设定。",
                        },
                    },
                },
                ensure_ascii=False,
            )
        )


class ArtifactTaskExecutionModelRuntimeStub:
    def __init__(self, *, artifact_path: str) -> None:
        self.artifact_path = artifact_path

    async def invoke_messages(self, messages, **_kwargs):
        import json
        from types import SimpleNamespace

        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:graph-artifact:complete",
                    "action_type": "respond",
                    "final_answer": "已生成图节点产物。",
                    "diagnostics": {"artifacts": [{"path": self.artifact_path}]},
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


def _task_execution_runtime(prefix: str) -> QueryRuntime:
    return QueryRuntime(
        base_dir=isolated_backend_root(prefix),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=TaskExecutionModelRuntimeStub(),
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


def test_graph_edge_handoff_filters_outputs_by_delivery_policy() -> None:
    runtime = _runtime("graph-edge-filter-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.edge_filter",
        title="Edge Filter",
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
                "result_delivery_policy": "contract_payload_and_refs",
                "context_filter_policy": {"include_output_keys": ["public"], "max_chars": 6},
                "working_memory_handoff_policy": {"include_candidates": False},
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    advance = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:draft:filtered",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=start.node_work_orders[0].work_order_id,
            outputs={"public": "123456789", "secret": "must-not-leak"},
            memory_candidates=({"record_kind": "secret", "canonical_text": "hidden"},),
            handoff_summary="summary",
        ),
    )

    payload = advance.node_work_orders[0].input_package["handoff_packets"][0]["payload"]
    upstream = advance.node_work_orders[0].input_package["upstream_results"][0]

    assert payload["outputs"] == {"public": "123456"}
    assert "secret" not in payload["outputs"]
    assert payload["memory_candidates"] == []
    assert upstream["outputs"] == {"public": "123456"}


def test_graph_edge_summary_only_does_not_expose_outputs() -> None:
    runtime = _runtime("graph-edge-summary-only-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.summary_only",
        title="Summary Only",
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
                "result_delivery_policy": "summary_only",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    advance = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:draft:summary",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=start.node_work_orders[0].work_order_id,
            outputs={"secret": "must-not-leak"},
            handoff_summary="only summary",
        ),
    )

    payload = advance.node_work_orders[0].input_package["handoff_packets"][0]["payload"]

    assert payload["handoff_summary"] == "only summary"
    assert "outputs" not in payload


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
            {
                "node_id": "memory.missing",
                "node_type": "memory_repository",
                "title": "缺少 collection 的记忆库",
                "metadata": {"memory_repository": {"repository_id": "memory.missing"}},
            },
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
            {
                "node_id": "memory.missing",
                "node_type": "memory_repository",
                "title": "缺少 collection 的记忆库",
                "metadata": {"memory_repository": {"repository_id": "memory.missing"}},
            },
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


def test_graph_harness_config_locks_task_environment_and_work_order_refs() -> None:
    runtime = _runtime("graph-task-environment-lock-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.environment_lock",
        title="Environment Lock",
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
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )

    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    work_order = start.node_work_orders[0]
    environment = dict(graph_config.environment or {})

    assert graph_config.task_environment_id == "env.development.sandbox"
    assert environment["locked"] is True
    assert environment["storage_space"]["artifact_root"].endswith("/artifacts")
    assert environment["file_access_tables"]
    assert environment["memory_space"]
    assert environment["artifact_policy"]
    assert work_order.input_package["task_environment_id"] == "env.development.sandbox"
    assert work_order.file_access_table_refs
    assert work_order.file_view_request["file_access_tables"]
    assert work_order.artifact_space_ref == environment["storage_space"]["artifact_root"]
    assert work_order.artifact_repository_targets[0]["target_ref"] == work_order.artifact_space_ref
    assert work_order.memory_space_ref


def test_graph_node_task_run_contract_and_origin_are_explicit() -> None:
    runtime = _runtime("graph-node-contract-origin-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.node_contract_origin",
        title="Node Contract Origin",
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
                        "task_instruction": "只完成当前节点任务。",
                    },
                    "runtime_profile": {"mode": "professional"},
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    task_run = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=start.node_work_orders[0])
    contract = runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    diagnostics = dict(task_run.diagnostics or {})
    selection = dict(diagnostics.get("runtime_task_selection") or {})

    assert diagnostics["origin_kind"] == "graph_node_assigned"
    assert diagnostics["parent_run_ref"] == start.graph_run.graph_run_id
    assert contract["origin"]["origin_kind"] == "graph_node_assigned"
    assert contract["task_environment_id"] == "env.development.sandbox"
    assert contract["prompt_contract"]["role_prompt"] == "你是一名图节点执行员。"
    assert contract["runtime_profile"]["mode"] == "professional"
    assert selection["task_environment_id"] == "env.development.sandbox"
    assert selection["prompt_contract"]["task_instruction"] == "只完成当前节点任务。"
    assert selection["runtime_profile"]["tool_policy"] == {}


def test_graph_node_agent_profile_id_does_not_replace_agent_id() -> None:
    runtime = _runtime("graph-node-agent-profile-boundary-")
    runtime.agent_runtime_registry.upsert_profile(
        agent_id="agent:0",
        agent_profile_id="custom_graph_node_profile",
        enabled_runtime_modes=("professional",),
        default_runtime_mode="professional",
        allowed_operations=("op.model_response",),
        metadata={"work_role_prompt": "你是图节点专用执行员。"},
    )
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.agent_profile_boundary",
        title="Agent Profile Boundary",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "执行",
                "task_id": "task.test.execute",
                "metadata": {
                    "agent_profile_id": "custom_graph_node_profile",
                    "prompt_contract": {"role_prompt": "你是一名执行员。"},
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    task_run = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=start.node_work_orders[0])

    assert task_run.agent_id == "agent:0"
    assert task_run.agent_profile_id == "custom_graph_node_profile"


def test_graph_node_agent_profile_id_drives_task_executor_runtime_assembly() -> None:
    runtime = _task_execution_runtime("graph-node-profile-runtime-assembly-")
    runtime.agent_runtime_registry.upsert_profile(
        agent_id="agent:0",
        agent_profile_id="custom_graph_node_profile",
        enabled_runtime_modes=("professional",),
        default_runtime_mode="professional",
        allowed_operations=("op.model_response",),
        metadata={"work_role_prompt": "你是图节点专用执行员。"},
    )
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.agent_profile_runtime_assembly",
        title="Agent Profile Runtime Assembly",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "执行",
                "task_id": "task.test.execute",
                "metadata": {
                    "agent_profile_id": "custom_graph_node_profile",
                    "prompt_contract": {"role_prompt": "你是一名执行员。"},
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    node_task_run_id = result.graph_result["outputs"]["draft"]["node_executor_task_run_id"]
    trace = runtime.single_agent_runtime_host.get_trace(node_task_run_id, include_payloads=True)
    started_event = next(item for item in trace["events"] if item["event_type"] == "task_run_executor_started")
    assembly = started_event["payload"]["runtime_assembly"]

    assert result.status == "completed"
    assert assembly["agent_profile_ref"] == "custom_graph_node_profile"
    assert assembly["agent_prompt_refs"] == ["agent.custom_graph_node_profile.work_role.v1"]


def test_graph_node_missing_agent_profile_fails_closed() -> None:
    runtime = _runtime("graph-node-profile-missing-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.agent_profile_missing",
        title="Missing Agent Profile",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "执行",
                "task_id": "task.test.execute",
                "metadata": {"agent_profile_id": "missing_graph_node_profile"},
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    try:
        runtime._create_graph_node_task_run(graph_config=graph_config, work_order=start.node_work_orders[0])
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "AgentRuntimeProfile not found: missing_graph_node_profile" in str(raised)


def test_graph_node_task_runs_are_hidden_from_global_monitor_and_recovery() -> None:
    runtime = _runtime("graph-node-monitor-recovery-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.node_monitor_recovery",
        title="Node Monitor Recovery",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "执行", "task_id": "task.test.execute", "agent_id": "agent:0"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    task_run = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=start.node_work_orders[0])
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        TaskRun(
            **{
                **task_run.to_dict(),
                "status": "running",
                "diagnostics": {**dict(task_run.diagnostics or {}), "executor_status": "scheduled"},
            }
        )
    )

    recovery = recover_interrupted_task_executors(runtime.single_agent_runtime_host)
    monitor = runtime.single_agent_runtime_host.list_global_live_monitor(limit=20)
    stored = runtime.single_agent_runtime_host.state_index.get_task_run(task_run.task_run_id)

    assert task_run.task_run_id in recovery["skipped_graph_node_task_run_ids"]
    assert task_run.task_run_id not in recovery["task_run_ids"]
    assert stored is not None
    assert stored.status == "running"
    assert {item["task_run_id"] for item in monitor["task_runs"]} == {start.task_run.task_run_id}


def test_graph_run_runner_executes_linear_graph_to_completion() -> None:
    runtime = _task_execution_runtime("graph-run-runner-linear-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runner_linear",
        title="Runner Linear",
        graph_kind="multi_agent",
        entry_node_id="plan",
        output_node_id="publish",
        nodes=(
            {"node_id": "plan", "node_type": "agent", "title": "规划", "task_id": "task.test.plan", "agent_id": "agent:0"},
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "publish", "node_type": "agent", "title": "发布", "task_id": "task.test.publish", "agent_id": "agent:0"},
        ),
        edges=(
            {"edge_id": "edge.plan.draft", "source_node_id": "plan", "target_node_id": "draft", "edge_type": "handoff"},
            {"edge_id": "edge.draft.publish", "source_node_id": "draft", "target_node_id": "publish", "edge_type": "handoff"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=5,
            max_node_steps=1,
        )
    )

    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    monitor = runtime.single_agent_runtime_host.list_global_live_monitor(limit=20)

    assert result.status == "completed"
    assert result.executed_work_order_count == 3
    assert result.accepted_result_count == 3
    assert state["status"] == "completed"
    assert set(state["completed_node_ids"]) == {"plan", "draft", "publish"}
    assert state["active_work_orders"] == {}
    assert result.graph_result["status"] == "completed"
    assert {item["task_run_id"] for item in monitor["task_runs"]} == {start.task_run.task_run_id}


def test_graph_run_monitor_exposes_node_runtime_views_after_runner() -> None:
    runtime = _task_execution_runtime("graph-run-monitor-node-views-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.monitor_node_views",
        title="Monitor Node Views",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "review", "node_type": "agent", "title": "审核", "task_id": "task.test.review", "agent_id": "agent:0"},
        ),
        edges=(
            {"edge_id": "edge.draft.review", "source_node_id": "draft", "target_node_id": "review", "edge_type": "handoff"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=2,
            max_node_steps=1,
        )
    )
    monitor = runtime.graph_harness.get_graph_run_monitor(start.graph_run.graph_run_id, graph_config=graph_config)
    views = {item["node_id"]: item for item in monitor["node_runtime_views"]}

    assert result.status == "completed"
    assert set(views) == {"draft", "review"}
    assert views["draft"]["status"] == "completed"
    assert views["draft"]["node_executor_task_run_id"]
    assert views["draft"]["result"]["outputs"]["node_executor_task_run_id"] == views["draft"]["node_executor_task_run_id"]
    assert views["review"]["status"] == "completed"


def test_graph_agent_node_records_artifact_repository_receipts(tmp_path: Path) -> None:
    artifact_rel = "storage/task_environments/development/sandbox/artifacts/graph-node-artifact.md"
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("graph-artifact-repository-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=ArtifactTaskExecutionModelRuntimeStub(artifact_path=artifact_rel),
    )
    artifact_path = runtime.base_dir.parent / artifact_rel
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("real graph artifact", encoding="utf-8")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.artifact_repository",
        title="Artifact Repository",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    node_result = state["result_index"]["draft"]
    overview = runtime.graph_harness._services.artifact_repository_service.overview(
        task_run_id=start.task_run.task_run_id,
        graph_run_id=start.graph_run.graph_run_id,
    )

    assert result.status == "completed"
    assert node_result["artifact_materialization_receipts"][0]["authority"] == "artifact_repository.service"
    assert overview["artifact_count"] == 1
    assert overview["artifacts"][0]["graph_run_id"] == start.graph_run.graph_run_id
    assert overview["artifacts"][0]["producer_node_id"] == "draft"


def test_graph_agent_node_materializes_declared_final_content_artifact() -> None:
    runtime = _task_execution_runtime("graph-contract-artifact-materialization-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.contract_artifact_materialization",
        title="Contract Artifact Materialization",
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
                "artifact_policy": {
                    "enabled": True,
                    "required": True,
                    "default_artifact_root": "output/test_graph_artifacts",
                    "subdir_template": "{project_slug}",
                    "artifacts": [
                        {
                            "path": "world/world_candidate_round_{round_index:03d}.md",
                            "required": True,
                            "content_source": "final_content",
                            "fallback_to_full_content": True,
                        }
                    ],
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(
        session_id="session:test",
        task_id="",
        graph_config=graph_config,
        initial_inputs={"project_id": "project:artifact-test", "round_index": 2},
    )

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    node_result = state["result_index"]["draft"]
    artifact_path = (
        runtime.base_dir.parent
        / "output"
        / "test_graph_artifacts"
        / "project-artifact-test"
        / "world"
        / "world_candidate_round_002.md"
    )
    overview = runtime.graph_harness._services.artifact_repository_service.overview(
        task_run_id=start.task_run.task_run_id,
        graph_run_id=start.graph_run.graph_run_id,
    )

    assert result.status == "completed"
    assert artifact_path.exists()
    assert "图节点执行完成" in artifact_path.read_text(encoding="utf-8")
    assert node_result["artifact_refs"] == [
        "output/test_graph_artifacts/project-artifact-test/world/world_candidate_round_002.md"
    ]
    assert node_result["artifact_materialization_receipts"][0]["authority"] == "artifact_repository.service"
    assert overview["artifact_count"] == 1
    assert overview["artifacts"][0]["path"] == "output/test_graph_artifacts/project-artifact-test/world/world_candidate_round_002.md"


def test_graph_agent_node_writes_formal_memory_candidate_and_commit() -> None:
    runtime = _task_execution_runtime("graph-formal-memory-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.formal_memory_commit",
        title="Formal Memory Commit",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {
                "node_id": "memory.world",
                "node_type": "memory_repository",
                "title": "世界观记忆库",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory.world",
                        "collections": [{"collection_id": "world"}],
                    }
                },
            },
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
        ),
        edges=(
            {
                "edge_id": "edge.draft.memory",
                "source_node_id": "draft",
                "target_node_id": "memory.world",
                "edge_type": "memory_commit",
                "metadata": {
                    "repository": "memory.world",
                    "collection": "world",
                    "record_key": "world.current",
                    "record_kind": "world_fact",
                    "source_output_key": "world_memory_candidate",
                    "commit_visibility_policy": {"visible_after": "same_clock"},
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    node_result = state["result_index"]["draft"]
    overview = runtime.graph_harness._services.formal_memory_service.overview(
        task_run_id=start.task_run.task_run_id,
        repository_id="memory.world",
        collection_id="world",
    )

    assert result.status == "completed"
    assert node_result["memory_commit_receipts"]
    assert {item["authority"] for item in node_result["memory_commit_receipts"]} == {"formal_memory.service"}
    assert overview["version_count"] == 1
    assert overview["versions"][0]["status"] == "committed"
    assert overview["versions"][0]["canonical_text"] == "图节点确认世界观设定。"


def test_graph_formal_memory_write_fails_when_repository_not_declared() -> None:
    runtime = _task_execution_runtime("graph-formal-memory-undeclared-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.formal_memory_undeclared",
        title="Formal Memory Undeclared",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {
                "node_id": "memory.missing",
                "node_type": "memory_repository",
                "title": "缺少 collection 的记忆库",
                "metadata": {"memory_repository": {"repository_id": "memory.missing"}},
            },
        ),
        edges=(
            {
                "edge_id": "edge.draft.memory",
                "source_node_id": "draft",
                "target_node_id": "memory.missing",
                "edge_type": "memory_commit",
                "metadata": {
                    "repository": "memory.missing",
                    "collection": "world",
                    "record_key": "world.current",
                    "record_kind": "world_fact",
                    "source_output_key": "world_memory_candidate",
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    node_result = state["result_index"]["draft"]

    assert result.status == "failed"
    assert node_result["error"]["postprocess_errors"][0]["reason"] == "formal_memory_repository_or_collection_not_declared"


def test_graph_run_runner_reconnects_active_work_orders_from_checkpoint() -> None:
    runtime = _task_execution_runtime("graph-run-runner-reconnect-active-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runner_reconnect",
        title="Runner Reconnect",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "review", "node_type": "agent", "title": "审核", "task_id": "task.test.review", "agent_id": "agent:0"},
        ),
        edges=(
            {"edge_id": "edge.draft.review", "source_node_id": "draft", "target_node_id": "review", "edge_type": "handoff"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=2,
            max_node_steps=1,
        )
    )

    assert result.status == "completed"
    assert result.executed_work_order_count == 2
    assert result.events[0]["event_type"] == "graph_run_runner_started"
    assert any(item["event_type"] == "graph_node_work_order_executed" for item in result.events)
    assert any(item["event_type"] == "graph_node_result_accepted" for item in result.events)


def test_graph_run_runner_fails_closed_on_config_hash_mismatch() -> None:
    runtime = _task_execution_runtime("graph-run-runner-hash-mismatch-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runner_hash_mismatch",
        title="Runner Hash Mismatch",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "执行", "task_id": "task.test.execute", "agent_id": "agent:0"},
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
        asyncio.run(
            runtime.graph_harness.run_until_idle(
                graph_config=wrong_config,
                graph_run_id=start.graph_run.graph_run_id,
                max_node_executions=1,
            )
        )
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "content_hash mismatch" in str(raised)


def test_graph_run_runner_budget_stops_without_fake_completion() -> None:
    runtime = _task_execution_runtime("graph-run-runner-budget-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runner_budget",
        title="Runner Budget",
        graph_kind="multi_agent",
        entry_node_id="first",
        output_node_id="second",
        nodes=(
            {"node_id": "first", "node_type": "agent", "title": "第一步", "task_id": "task.test.first", "agent_id": "agent:0"},
            {"node_id": "second", "node_type": "agent", "title": "第二步", "task_id": "task.test.second", "agent_id": "agent:0"},
        ),
        edges=(
            {"edge_id": "edge.first.second", "source_node_id": "first", "target_node_id": "second", "edge_type": "handoff"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)

    assert result.status == "budget_exhausted"
    assert result.budget_exhausted is True
    assert result.executed_work_order_count == 1
    assert state["status"] == "running"
    assert state["completed_node_ids"] == ["first"]
    assert state["active_work_orders"]
    assert state["active_work_orders"]["second"]


def test_graph_run_runner_rejects_reused_non_graph_node_task_run() -> None:
    runtime = _task_execution_runtime("graph-run-runner-origin-guard-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runner_origin_guard",
        title="Runner Origin Guard",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "执行", "task_id": "task.test.execute", "agent_id": "agent:0"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    work_order = start.node_work_orders[0]
    hijacked_id = f"gtask:{work_order.graph_run_id.replace(':', '_')}:{work_order.node_id}:{work_order.work_order_id.replace(':', '_')}"
    existing = TaskRun(
        task_run_id=hijacked_id,
        session_id="session:test",
        task_id="task.agent.requested",
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        diagnostics={"origin_kind": "agent_requested"},
    )
    runtime.single_agent_runtime_host.state_index.upsert_task_run(existing)

    try:
        asyncio.run(
            runtime.graph_harness.run_until_idle(
                graph_config=graph_config,
                graph_run_id=start.graph_run.graph_run_id,
                max_node_executions=1,
                max_node_steps=1,
            )
        )
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "origin_kind mismatch" in str(raised)


def test_graph_run_runner_persists_human_gate_waiting_state() -> None:
    runtime = _runtime("graph-run-runner-human-gate-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runner_human_gate",
        title="Runner Human Gate",
        graph_kind="multi_agent",
        entry_node_id="approval",
        output_node_id="approval",
        nodes=(
            {
                "node_id": "approval",
                "node_type": "human_gate",
                "title": "人工审批",
                "task_id": "task.test.approval",
                "executor_policy": {"default_executor": "human_gate"},
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)

    assert result.status == "waiting_human_gate"
    assert state["status"] == "waiting_human_gate"
    assert state["node_states"]["approval"]["status"] == "waiting_human_gate"
    assert state["blocked_node_ids"] == ["approval"]
    assert state["active_work_orders"] == {}


def test_graph_run_runner_persists_tool_node_blocked_state() -> None:
    runtime = _runtime("graph-run-runner-tool-blocked-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runner_tool_blocked",
        title="Runner Tool Blocked",
        graph_kind="multi_agent",
        entry_node_id="tool_step",
        output_node_id="tool_step",
        nodes=(
            {
                "node_id": "tool_step",
                "node_type": "tool",
                "title": "工具节点",
                "task_id": "task.test.tool",
                "executor_policy": {"default_executor": "tool"},
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)

    assert result.status == "blocked"
    assert state["status"] == "blocked"
    assert state["node_states"]["tool_step"]["status"] == "blocked"
    assert state["blocked_node_ids"] == ["tool_step"]
    assert state["active_work_orders"] == {}
