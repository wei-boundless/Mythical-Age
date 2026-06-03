from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness import GraphHarness
from harness.graph.model_overrides import work_order_with_model_overrides
from harness.graph.models import NodeResultEnvelope, stable_safe_id
from harness.graph.runner import GraphRunRunner
from harness.loop.task_executor_controller import TaskExecutorController
from runtime.shared.models import TaskRun
from harness.entrypoint import HarnessRuntimeFacade
from harness.graph.work_order_contract import _graph_node_task_run_id
from task_system import TaskFlowRegistry
from task_system.compiler.graph_harness_config_publisher import publish_graph_harness_config_for_graph
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    HarnessRuntimeFacadeMemoryFacadeStub,
    SingleMessageModelRuntimeStub,
    isolated_backend_root,
)


def _message_content_with_title(packet, title: str) -> str:
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if content.startswith(title):
            return content
    raise AssertionError(f"message title not found: {title}")


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
                    "public_progress_note": "图节点已完成当前职责，准备交给下游节点继续处理。",
                    "public_action_state": {
                        "current_judgment": "结果满足当前节点要求。",
                        "next_action": "提交给下游节点继续处理。"
                    },
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


class TimeoutThenTaskExecutionModelRuntimeStub:
    def __init__(self) -> None:
        self.call_count = 0

    async def invoke_messages(self, messages, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            raise asyncio.TimeoutError()
        return await TaskExecutionModelRuntimeStub().invoke_messages(messages, **kwargs)


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
                    "public_progress_note": "图节点产物已生成，正在提交给图任务运行。",
                    "public_action_state": {
                        "current_judgment": "产物可作为节点输出提交。",
                        "next_action": "提交产物给图任务运行。"
                    },
                    "diagnostics": {"artifacts": [{"path": self.artifact_path}]},
                },
                ensure_ascii=False,
            )
        )


def _runtime(prefix: str = "graph-task-runtime-facade-") -> HarnessRuntimeFacade:
    return HarnessRuntimeFacade(
        base_dir=isolated_backend_root(prefix),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=HarnessRuntimeFacadeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )


def _task_execution_runtime(prefix: str) -> HarnessRuntimeFacade:
    return HarnessRuntimeFacade(
        base_dir=isolated_backend_root(prefix),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=HarnessRuntimeFacadeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=TaskExecutionModelRuntimeStub(),
    )


def _runtime_object_payload(runtime: HarnessRuntimeFacade, ref: str) -> dict:
    payload = runtime.single_agent_runtime_host.runtime_objects.get_object(ref)
    assert payload, f"runtime object not found: {ref}"
    return payload


def test_harness_runtime_exposes_graph_harness_facade() -> None:
    runtime = _runtime()

    assert isinstance(runtime.graph_harness, GraphHarness)
    assert runtime.runtime_components["graph_harness"] == "active"
    assert not hasattr(runtime.graph_harness.graph_loop, "_engine")
    assert hasattr(runtime.graph_harness, "get_graph_run_monitor")


def test_graph_harness_starts_published_config_and_creates_node_work_order() -> None:
    from harness.runtime.compiler import RuntimeCompiler
    from harness.graph.work_order_contract import _graph_node_contract_from_work_order

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
    assert start.envelope.static_topology_view["start_node_ids"] == ["draft"]
    assert start.envelope.static_topology_view["terminal_node_ids"] == ["review"]
    assert start.envelope.contract_index["edge_protocol_index"]["edge.draft.review"]["edge_id"] == "edge.draft.review"
    assert start.loop_state.diagnostics["static_topology_view"]["executable_node_ids"] == ["draft", "review"]
    assert start.loop_state.config_id == graph_config.config_id
    assert start.node_work_orders[0].node_id == "draft"
    assert start.node_work_orders[0].work_kind == "agent"
    assert start.node_work_orders[0].graph_run_id == start.graph_run.graph_run_id
    assert "内容起草员" in start.node_work_orders[0].message
    assert start.node_work_orders[0].input_package["initial_inputs"] == {"goal": "smoke"}
    assert start.node_work_orders[0].input_package["materializer_authority"] == "harness.graph.context_materializer"
    assert start.node_work_orders[0].input_package["node_identity"]["node_id"] == "draft"
    assert "内容起草员" in start.node_work_orders[0].input_package["agent_instruction"]
    graph_slot = start.node_work_orders[0].graph_slot
    assert graph_slot["authority"] == "harness.graph.node_execution_slot"
    assert graph_slot["graph_identity"]["work_order_id"] == start.node_work_orders[0].work_order_id
    assert graph_slot["graph_identity"]["node_id"] == "draft"
    assert graph_slot["node_contract"]["prompt_contract"]["role_prompt"] == "你是一名内容起草员。"
    initial_context = graph_slot["edge_contracts"]["inbound_edge_contexts"][0]
    assert initial_context["packet_type"] == "graph_initial_input"
    assert initial_context["source_node_id"] == "__graph_input__"
    assert initial_context["target_input_slot"] == "initial_inputs"
    assert initial_context["payload"]["initial_inputs"] == {"goal": "smoke"}
    assert graph_slot["memory_contract"]["namespace_id"].startswith("graphmem:")
    contract = _graph_node_contract_from_work_order(start.node_work_orders[0]).to_dict()
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:test",
        task_run={
            "task_run_id": "gtask:test:start-node",
            "session_id": "session:test",
            "task_id": "task.test.draft",
            "task_contract_ref": "gcontract:test",
            "owner_agent_seat_id": "draft",
            "agent_id": "agent:0",
            "agent_profile_id": "main_interactive_agent",
            "execution_runtime_kind": "single_agent_task",
            "status": "running",
            "diagnostics": {"contract": contract, "graph_run_id": start.graph_run.graph_run_id, "graph_node_id": "draft"},
        },
        contract=contract,
        observations=[],
        runtime_assembly={
            "assembly_id": "rtasm:test",
            "profile": {"profile_ref": "main_interactive_agent", "interaction_policy": {"style": "task_execution"}},
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": []},
        },
    ).packet
    task_contract_content = _message_content_with_title(packet, "Task execution task contract")
    runtime_context_content = _message_content_with_title(packet, "Task execution graph node runtime context")
    stable_payload = json.loads(task_contract_content.split("\n", 1)[1])
    runtime_payload = json.loads(runtime_context_content.split("\n", 1)[1])
    graph_context = stable_payload["task_contract"]["graph_node_context"]
    stable_initial = graph_context["authorized_input_slots"][0]
    visible_initial = runtime_payload["graph_node_runtime_context"]["authorized_inputs"][0]["payload"]["initial_inputs"]
    assert stable_initial["content_omitted_reason"] == "available_in_graph_node_runtime_context"
    assert "payload" not in stable_initial
    assert visible_initial == {"goal": "smoke"}
    assert "input_package" not in task_contract_content
    assert "graph_slot" not in task_contract_content
    work_order_summary = start.loop_state.work_order_index[start.node_work_orders[0].work_order_id]
    assert work_order_summary["node_id"] == "draft"
    assert work_order_summary["work_order_ref"]
    assert "input_package" not in work_order_summary
    assert runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)["graph_id"] == graph.graph_id
    monitor = runtime.graph_harness.get_graph_run_monitor(start.graph_run.graph_run_id, graph_config=graph_config)
    assert monitor is not None
    assert monitor["graph_run_id"] == start.graph_run.graph_run_id
    assert monitor["graph_loop_state"]["graph_id"] == graph.graph_id
    assert monitor["task_run_monitor"]["authority"] == "runtime_monitor.v1.item"
    assert monitor["runtime_monitor"]["task_run_id"] == start.task_run.task_run_id
    assert monitor["active_node_work_order_count"] == 1
    assert monitor["active_node_work_orders"][0]["work_order_id"] == start.node_work_orders[0].work_order_id
    assert "input_package" not in monitor["active_node_work_orders"][0]
    assert "work_order_index" not in monitor["graph_loop_state"]
    assert "result_index" not in monitor["graph_loop_state"]
    assert "result_history" not in monitor["graph_loop_state"]
    assert "initial_inputs" not in monitor["graph_loop_state"]
    assert "events" not in monitor
    assert monitor["event_window"]["kind"] == "omitted"
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
    assert latest.state["work_order_index"][start.node_work_orders[0].work_order_id]["work_order_ref"]
    assert "input_package" not in latest.state["work_order_index"][start.node_work_orders[0].work_order_id]
    assert latest.pending_writes
    assert latest.pending_writes[0][1] == "active_work_order"
    assert latest.pending_writes[0][2]["work_order_id"] == start.node_work_orders[0].work_order_id
    assert "input_package" not in latest.pending_writes[0][2]
    assert latest.to_dict()["checkpoint_id"].startswith("gchk:")
    assert runtime.graph_harness.get_latest_checkpoint(start.graph_run.graph_run_id)["checkpoint_id"].startswith("gchk:")
    assert runtime.graph_harness.list_checkpoints(start.graph_run.graph_run_id, limit=1)[0]["checkpoint_id"].startswith("gchk:")
    assert runtime.single_agent_runtime_host.runtime_objects.get_object(
        f"rtobj:graph_loop_state:{start.graph_run.graph_run_id.replace(':', '_')}"
    ) == {}


def test_langgraph_checkpoint_store_selects_numeric_latest_event_cursor() -> None:
    runtime = _runtime("graph-task-langgraph-checkpoint-order-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.langgraph_checkpoint_order",
        title="LangGraph Checkpoint Order",
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
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    store = runtime.single_agent_runtime_host.graph_checkpoint_store
    base_state = runtime.graph_harness._loop.get_state(start.graph_run.graph_run_id)
    assert base_state is not None

    stale_state = type(base_state).from_dict({**base_state.to_dict(), "status": "blocked", "event_cursor": 9})
    fresh_state = type(base_state).from_dict({**base_state.to_dict(), "status": "running", "event_cursor": 10})
    store.put_checkpoint(state=stale_state, metadata={"created_at": 1.0})
    store.put_checkpoint(state=fresh_state, metadata={"created_at": 2.0})

    latest = store.get_latest_checkpoint(start.graph_run.graph_run_id)
    assert latest is not None
    assert latest.event_cursor == 10
    assert latest.state["status"] == "running"
    assert latest.checkpoint_id.endswith(":00000000000000000010")


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
    assert "upstream_results" not in advance.node_work_orders[0].input_package
    assert "upstream_handoff_packets" not in advance.node_work_orders[0].input_package
    assert "handoff_packets" not in advance.node_work_orders[0].input_package
    inbound = advance.node_work_orders[0].input_package["inbound_context"][0]
    assert inbound["source_node_id"] == "draft"
    assert inbound["edge_id"] == "edge.draft.review"
    assert inbound["packet_ref"]
    assert inbound["packet_authority"] == "harness.graph_flow_packet"
    assert inbound["payload"]["handoff_summary"] == ""
    assert "bounded_outputs" not in inbound["payload"]
    review_slot = advance.node_work_orders[0].graph_slot
    assert review_slot["edge_contracts"]["inbound_edge_contexts"][0]["edge_id"] == "edge.draft.review"
    assert review_slot["edge_contracts"]["inbound_flow_packets"][0]["edge_id"] == "edge.draft.review"
    assert review_slot["state_refs"]["inbound_packet_refs"][0]["packet_ref"] == inbound["packet_ref"]
    edge_state = advance.loop_state.edge_states["edge.draft.review"]
    assert edge_state["status"] == "ready"
    assert edge_state["latest_packet_ref"] == inbound["packet_ref"]
    assert edge_state["packet_refs"][0]["authority"] == "harness.graph_flow_packet_summary"
    assert "source_result_ref" not in edge_state
    assert "handoff_packet_id" not in edge_state
    packet = _runtime_object_payload(runtime, inbound["packet_ref"])
    assert packet["authority"] == "harness.graph_flow_packet"
    assert packet["edge_id"] == "edge.draft.review"
    assert packet["result_refs"][0]["result_ref"] == advance.loop_state.result_index["draft"]["result_ref"]
    assert "outputs" not in packet
    assert "bounded_outputs" not in packet["visible_payload"]
    assert advance.loop_state.result_index["draft"]["result_ref"]
    assert advance.loop_state.node_states["draft"]["result_ref"] == advance.loop_state.result_index["draft"]["result_ref"]
    assert _runtime_object_payload(runtime, advance.loop_state.node_states["draft"]["result_ref"])["result_id"] == "nresult:test:draft"
    assert "outputs" not in advance.loop_state.result_index["draft"]
    assert advance.loop_state.work_order_index[advance.node_work_orders[0].work_order_id]["node_id"] == "review"
    assert "input_package" not in advance.loop_state.work_order_index[advance.node_work_orders[0].work_order_id]
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

    inbound = advance.node_work_orders[0].input_package["inbound_context"][0]
    payload = inbound["payload"]
    packet = _runtime_object_payload(runtime, inbound["packet_ref"])

    assert payload["bounded_outputs"] == {"public": "123456"}
    assert "secret" not in payload["bounded_outputs"]
    assert "memory_candidates" not in payload
    assert packet["visible_payload"]["bounded_outputs"] == {"public": "123456"}
    assert "secret" not in packet["visible_payload"]["bounded_outputs"]
    assert packet["visibility"]["delivery_policy"] == "contract_payload_and_refs"


def test_graph_edge_contract_payload_projects_artifact_text_without_agent_tool(tmp_path: Path) -> None:
    runtime = _runtime("graph-edge-artifact-text-")
    artifact_path = tmp_path / "world.md"
    artifact_path.write_text("世界设定正文\n" + "洪荒规则" * 200, encoding="utf-8")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.artifact_text_projection",
        title="Artifact Text Projection",
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
                "artifact_ref_policy": {"max_refs": 1, "max_text_chars": 12},
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
            result_id="nresult:test:draft:artifact-text",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=start.node_work_orders[0].work_order_id,
            artifact_refs=(str(artifact_path),),
            handoff_summary="summary",
        ),
    )

    inbound = advance.node_work_orders[0].input_package["inbound_context"][0]
    payload = inbound["payload"]
    packet = _runtime_object_payload(runtime, inbound["packet_ref"])

    assert [Path(item) for item in payload["artifact_refs"]] == [artifact_path]
    assert Path(payload["artifact_payloads"][0]["artifact_ref"]) == artifact_path
    assert payload["artifact_payloads"][0]["content"] == "世界设定正文\n洪荒规则洪"
    assert payload["artifact_payloads"][0]["truncated"] is True
    assert packet["visible_payload"]["artifact_payloads"][0]["authority"] == "harness.graph.flow_packet.artifact_text_projection"


def test_graph_node_task_contract_keeps_model_visible_artifact_payload(tmp_path: Path) -> None:
    from harness.runtime.compiler import RuntimeCompiler
    from harness.graph.work_order_contract import _graph_node_contract_from_work_order

    runtime = _runtime("graph-node-contract-artifact-payload-")
    artifact_path = tmp_path / "world.md"
    artifact_path.write_text("世界设定正文", encoding="utf-8")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.node_contract_artifact_payload",
        title="Node Contract Artifact Payload",
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
            result_id="nresult:test:draft:contract-artifact",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=start.node_work_orders[0].work_order_id,
            artifact_refs=(str(artifact_path),),
            handoff_summary="summary",
        ),
    )

    contract = _graph_node_contract_from_work_order(advance.node_work_orders[0]).to_dict()
    task_run = {
        "task_run_id": "gtask:test:artifact-payload",
        "session_id": "session-test",
        "task_id": "task.test.review",
        "task_contract_ref": "gcontract:test",
        "owner_agent_seat_id": "review",
        "agent_id": "agent:0",
        "agent_profile_id": "main_interactive_agent",
        "execution_runtime_kind": "single_agent_task",
        "status": "running",
        "diagnostics": {"contract": contract, "graph_run_id": start.graph_run.graph_run_id, "graph_node_id": "review"},
    }
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-test",
        task_run=task_run,
        contract=contract,
        observations=[],
        runtime_assembly={
            "assembly_id": "rtasm:test",
            "profile": {"profile_ref": "main_interactive_agent", "interaction_policy": {"style": "task_execution"}},
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": []},
        },
    ).packet
    task_contract_content = _message_content_with_title(packet, "Task execution task contract")
    runtime_context_content = _message_content_with_title(packet, "Task execution graph node runtime context")
    stable_payload = json.loads(task_contract_content.split("\n", 1)[1])
    runtime_payload = json.loads(runtime_context_content.split("\n", 1)[1])
    visible_contract = stable_payload["task_contract"]
    stable_inbound = visible_contract["graph_node_context"]["authorized_input_slots"][0]
    inbound = runtime_payload["graph_node_runtime_context"]["authorized_inputs"][0]

    assert stable_inbound["content_omitted_reason"] == "available_in_graph_node_runtime_context"
    assert "content" not in stable_inbound
    assert "payload" not in stable_inbound
    assert inbound["payload"]["artifact_payloads"][0]["content"] == "世界设定正文"
    assert "resource_requirements" not in visible_contract
    assert "input_package" not in json.dumps(stable_payload, ensure_ascii=False)
    assert "graph_slot" not in json.dumps(stable_payload, ensure_ascii=False)
    assert "upstream_results" not in json.dumps(visible_contract, ensure_ascii=False)
    assert "hidden_control_refs" not in json.dumps(visible_contract, ensure_ascii=False)


def test_graph_edge_artifact_text_projection_accepts_project_root_relative_refs(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime("graph-edge-artifact-root-relative-")
    project_root = Path(__file__).resolve().parents[2]
    artifact_dir = project_root / ".tmp" / "graph_edge_artifact_text"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "world.md"
    artifact_path.write_text("项目根相对正文", encoding="utf-8")
    relative_ref = artifact_path.relative_to(project_root).as_posix()
    monkeypatch.chdir(BACKEND_DIR)
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.artifact_project_root_relative",
        title="Artifact Project Root Relative",
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
            result_id="nresult:test:draft:artifact-root-relative",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=start.node_work_orders[0].work_order_id,
            artifact_refs=(relative_ref,),
            handoff_summary="summary",
        ),
    )

    payload = advance.node_work_orders[0].input_package["inbound_context"][0]["payload"]

    assert payload["artifact_payloads"][0]["artifact_ref"] == relative_ref
    assert payload["artifact_payloads"][0]["content"] == "项目根相对正文"


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

    inbound = advance.node_work_orders[0].input_package["inbound_context"][0]
    payload = inbound["payload"]
    packet = _runtime_object_payload(runtime, inbound["packet_ref"])

    assert payload["handoff_summary"] == "only summary"
    assert "bounded_outputs" not in payload
    assert packet["visible_payload"] == {"handoff_summary": "only summary"}


def test_review_revise_requeues_revision_target_before_downstream_commit() -> None:
    runtime = _runtime("graph-review-revise-requeues-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.review_revise_requeues",
        title="Review Revise Requeues",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="commit",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "review", "node_type": "review_gate", "title": "审核", "task_id": "task.test.review", "agent_id": "agent:0"},
            {"node_id": "commit", "node_type": "memory_commit", "title": "提交", "task_id": "task.test.commit", "agent_id": "agent:0"},
        ),
        edges=(
            {
                "edge_id": "edge.draft.review",
                "source_node_id": "draft",
                "target_node_id": "review",
                "edge_type": "handoff",
                "result_delivery_policy": "contract_payload_and_refs",
            },
            {
                "edge_id": "edge.review.commit",
                "source_node_id": "review",
                "target_node_id": "commit",
                "edge_type": "handoff",
                "result_delivery_policy": "contract_payload_and_refs",
            },
            {
                "edge_id": "edge.review.revise",
                "source_node_id": "review",
                "target_node_id": "draft",
                "edge_type": "revision_request",
                "semantic_role": "revision",
                "result_delivery_policy": "contract_payload_and_refs",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    review = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:draft:revise-route",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=start.node_work_orders[0].work_order_id,
            handoff_summary="候选草稿",
        ),
    )

    assert [order.node_id for order in review.node_work_orders] == ["review"]

    revised = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:review:revise-route",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="review",
            work_order_id=review.node_work_orders[0].work_order_id,
            handoff_summary="审核裁决：返修\n\n必须修改后才能进入提交。",
        ),
    )

    assert revised.loop_state.status == "running"
    assert [order.node_id for order in revised.node_work_orders] == ["draft"]
    assert revised.loop_state.node_states["commit"]["status"] == "pending"
    assert revised.loop_state.node_states["draft"]["status"] == "running"
    assert "draft" in revised.loop_state.active_work_orders
    assert "commit" not in revised.loop_state.active_work_orders


def test_baseline_memory_seed_waits_for_accepted_outline_review() -> None:
    runtime = _runtime("graph-baseline-waits-review-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.baseline_waits_review",
        title="Baseline Waits Review",
        graph_kind="multi_agent",
        entry_node_id="outline_design",
        output_node_id="baseline_memory_seed",
        nodes=(
            {"node_id": "outline_design", "node_type": "agent", "title": "细纲设计", "task_id": "task.test.outline_design", "agent_id": "agent:0"},
            {"node_id": "outline_review", "node_type": "review_gate", "title": "细纲审核", "task_id": "task.test.outline_review", "agent_id": "agent:0"},
            {
                "node_id": "baseline_memory_seed",
                "node_type": "memory_commit",
                "title": "基准库初始化",
                "task_id": "task.test.baseline_memory_seed",
                "agent_id": "agent:0",
            },
        ),
        edges=(
            {
                "edge_id": "edge.outline.review",
                "source_node_id": "outline_design",
                "target_node_id": "outline_review",
                "edge_type": "handoff",
                "result_delivery_policy": "contract_payload_and_refs",
            },
            {
                "edge_id": "edge.outline_review.baseline",
                "source_node_id": "outline_review",
                "target_node_id": "baseline_memory_seed",
                "edge_type": "handoff",
                "result_delivery_policy": "contract_payload_and_refs",
            },
            {
                "edge_id": "edge.outline_review.revise",
                "source_node_id": "outline_review",
                "target_node_id": "outline_design",
                "edge_type": "revision_request",
                "semantic_role": "revision",
                "result_delivery_policy": "contract_payload_and_refs",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    review = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:outline:baseline-waits",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="outline_design",
            work_order_id=start.node_work_orders[0].work_order_id,
            handoff_summary="全书细纲候选。",
        ),
    )
    revised = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:outline-review:baseline-waits-revise",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="outline_review",
            work_order_id=review.node_work_orders[0].work_order_id,
            handoff_summary="审核裁决：返修\n\n进入分卷规划前必须处理。",
        ),
    )

    assert [order.node_id for order in revised.node_work_orders] == ["outline_design"]
    assert revised.loop_state.node_states["baseline_memory_seed"]["status"] == "pending"

    review_again = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:outline:baseline-waits-after-revise",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="outline_design",
            work_order_id=revised.node_work_orders[0].work_order_id,
            handoff_summary="已修订的全书细纲。",
        ),
    )
    passed = runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=NodeResultEnvelope(
            result_id="nresult:test:outline-review:baseline-waits-pass",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="outline_review",
            work_order_id=review_again.node_work_orders[0].work_order_id,
            handoff_summary="审核裁决：通过\n\n允许进入基准库初始化。",
        ),
    )

    assert [order.node_id for order in passed.node_work_orders] == ["baseline_memory_seed"]
    baseline_order = passed.node_work_orders[0]
    assert baseline_order.tool_scope == {}
    inbound = baseline_order.input_package["inbound_context"][0]
    assert inbound["payload"]["handoff_summary"].startswith("审核裁决：通过")


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


def test_failed_node_result_does_not_leave_flow_packet_on_edge() -> None:
    runtime = _runtime("graph-failed-node-no-packet-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.failed_no_packet",
        title="Failed No Packet",
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
            result_id="nresult:test:draft:failed",
            graph_run_id=start.graph_run.graph_run_id,
            task_run_id=start.task_run.task_run_id,
            node_id="draft",
            work_order_id=start.node_work_orders[0].work_order_id,
            status="failed",
            error={"reason": "model_failed"},
        ),
    )

    edge_state = advance.loop_state.edge_states["edge.draft.review"]

    assert advance.loop_state.status == "failed"
    assert edge_state["status"] == "source_failed"
    assert "packet_refs" not in edge_state
    assert "latest_packet_ref" not in edge_state
    assert advance.node_work_orders == ()


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


def test_graph_resume_recovers_stale_active_graph_node_executor() -> None:
    runtime = _runtime("graph-task-resume-stale-active-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.resume_stale_active",
        title="Resume Stale Active",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "next", "node_type": "agent", "title": "下游", "task_id": "task.test.next", "agent_id": "agent:0"},
        ),
        edges=(
            {
                "edge_id": "edge.draft.next",
                "source_node_id": "draft",
                "target_node_id": "next",
                "edge_type": "handoff",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    work_order = start.node_work_orders[0]
    task_run_id = _graph_node_task_run_id(work_order)
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session:test",
            task_id="task.test.draft",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "executor_status": "running",
                "origin_kind": "graph_node_assigned",
                "origin": {
                    "origin_kind": "graph_node_assigned",
                    "origin_authority": "harness.graph_loop",
                    "origin_ref": work_order.work_order_id,
                    "parent_run_ref": work_order.graph_run_id,
                    "graph_run_id": work_order.graph_run_id,
                    "node_id": work_order.node_id,
                },
                "graph_run_id": work_order.graph_run_id,
                "graph_work_order_id": work_order.work_order_id,
                "graph_node_id": work_order.node_id,
            },
        )
    )

    resumed = runtime.graph_harness.resume_run(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
    )
    recovered = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert resumed.resumed is True
    assert resumed.reason == "active_work_orders_reconnected"
    assert recovered is not None
    assert recovered.status == "waiting_executor"
    diagnostics = dict(recovered.diagnostics or {})
    assert diagnostics["executor_status"] == "waiting_executor"
    assert diagnostics["recovery_action"] == "rerun_task_executor"
    assert resumed.events[0]["event_type"] == "graph_node_executor_recovered_after_runtime_restart"


def test_graph_runner_executes_recovered_stale_graph_node_executor() -> None:
    runtime = _task_execution_runtime("graph-task-run-recovered-stale-active-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.run_recovered_stale_active",
        title="Run Recovered Stale Active",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "next", "node_type": "agent", "title": "下游", "task_id": "task.test.next", "agent_id": "agent:0"},
        ),
        edges=(
            {
                "edge_id": "edge.draft.next",
                "source_node_id": "draft",
                "target_node_id": "next",
                "edge_type": "handoff",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    work_order = start.node_work_orders[0]
    task_run = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=work_order)
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        TaskRun(
            **{
                **task_run.to_dict(),
                "status": "running",
                "created_at": 1.0,
                "updated_at": 1.0,
                "diagnostics": {
                    **dict(task_run.diagnostics or {}),
                    "executor_status": "running",
                    "latest_step": "model_action_invocation_started",
                },
            }
        )
    )

    resumed = runtime.graph_harness.resume_run(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
    )
    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=4,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)

    assert resumed.events[0]["event_type"] == "graph_node_executor_recovered_after_runtime_restart"
    assert result.executed_work_order_count == 1
    assert result.accepted_result_count == 1
    assert state["status"] == "completed"
    assert state["completed_node_ids"] == ["draft"]


def test_graph_resume_resets_source_failed_edge_for_active_requeued_node() -> None:
    runtime = _runtime("graph-task-resume-active-source-failed-edge-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.resume_active_source_failed_edge",
        title="Resume Active Source Failed Edge",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="next",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "next", "node_type": "agent", "title": "下游", "task_id": "task.test.next", "agent_id": "agent:0"},
        ),
        edges=(
            {"edge_id": "edge.draft.next", "source_node_id": "draft", "target_node_id": "next", "edge_type": "handoff"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    active_order = start.node_work_orders[0]
    dirty_state = type(runtime.graph_harness.graph_loop.get_state(start.graph_run.graph_run_id))(
        **{
            **runtime.graph_harness.graph_loop.get_state(start.graph_run.graph_run_id).to_dict(),
            "edge_states": {
                **dict(state["edge_states"]),
                "edge.draft.next": {
                    **dict(state["edge_states"]["edge.draft.next"]),
                    "status": "source_failed",
                    "latest_packet": {"packet_ref": "stale"},
                },
            },
            "active_work_orders": {"draft": active_order.work_order_id},
        }
    )
    runtime.graph_harness.graph_loop._write_state(dirty_state)

    resumed = runtime.graph_harness.resume_run(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        dispatch_ready=False,
    )

    assert resumed.reason == "active_work_orders_reconnected"
    assert resumed.loop_state is not None
    assert resumed.loop_state.status == "running"
    assert resumed.loop_state.terminal_reason == ""
    assert resumed.loop_state.edge_states["edge.draft.next"]["status"] == "pending"
    assert "latest_packet" not in resumed.loop_state.edge_states["edge.draft.next"]
    assert resumed.events[-1]["event_type"] == "graph_source_failed_edges_reset_for_active_nodes"


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


def test_graph_resume_requeues_blocked_agent_node_after_recoverable_model_failure() -> None:
    model_runtime = TimeoutThenTaskExecutionModelRuntimeStub()
    runtime = HarnessRuntimeFacade(
        base_dir=isolated_backend_root("graph-task-resume-blocked-agent-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=HarnessRuntimeFacadeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=model_runtime,
    )
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.resume_blocked_agent",
        title="Resume Blocked Agent",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "起草", "task_id": "task.test.draft", "agent_id": "agent:0"},
            {"node_id": "next", "node_type": "agent", "title": "下游", "task_id": "task.test.next", "agent_id": "agent:0"},
        ),
        edges=(
            {
                "edge_id": "edge.draft.next",
                "source_node_id": "draft",
                "target_node_id": "next",
                "edge_type": "handoff",
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    blocked = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    blocked_state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    blocked_result = _runtime_object_payload(
        runtime,
        blocked_state["result_index"]["draft"]["result_ref"],
    )

    assert blocked.status == "blocked"
    assert blocked_state["status"] == "blocked"
    assert blocked_state["node_states"]["draft"]["status"] == "blocked"
    assert blocked_state["blocked_node_ids"][0] == "draft"
    assert blocked_state["edge_states"]["edge.draft.next"]["status"] == "source_failed"
    assert blocked_result["status"] == "blocked"
    assert blocked_result["error"]["reason"] == "model_call_recovery_required"
    assert not blocked_result["artifact_refs"]

    resumed = runtime.graph_harness.resume_run(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
    )

    assert resumed.reason == "blocked_nodes_requeued"
    assert resumed.node_work_orders
    assert resumed.node_work_orders[0].node_id == "draft"
    assert resumed.node_work_orders[0].work_order_id != start.node_work_orders[0].work_order_id
    assert resumed.loop_state is not None
    assert resumed.loop_state.edge_states["edge.draft.next"]["status"] == "pending"
    assert "latest_packet" not in resumed.loop_state.edge_states["edge.draft.next"]

    completed = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    completed_state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)

    assert model_runtime.call_count == 2
    assert completed.executed_work_order_count == 1
    assert completed.accepted_result_count == 1
    assert completed_state["node_states"]["draft"]["status"] == "completed"
    assert completed_state["edge_states"]["edge.draft.next"]["status"] == "ready"
    assert "draft" not in completed_state["active_work_orders"]


def test_graph_node_result_refs_remain_unique_for_long_retry_ids() -> None:
    model_runtime = TimeoutThenTaskExecutionModelRuntimeStub()
    runtime = HarnessRuntimeFacade(
        base_dir=isolated_backend_root("graph-task-long-result-ref-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=HarnessRuntimeFacadeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=model_runtime,
    )
    registry = TaskFlowRegistry(runtime.base_dir)
    long_node_id = "graph_module.design_init::memory_commit_world_with_extra_long_identifier_for_retry_collision_check"
    graph = registry.upsert_task_graph(
        graph_id="graph.test.long_result_ref_retry_collision",
        title="Long Result Ref Retry Collision",
        graph_kind="multi_agent",
        entry_node_id=long_node_id,
        output_node_id=long_node_id,
        nodes=(
            {"node_id": long_node_id, "node_type": "agent", "title": "长节点", "task_id": "task.test.long.retry", "agent_id": "agent:0"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    first = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    first_state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    first_ref = first_state["result_index"][long_node_id]["result_ref"]
    runtime.graph_harness.resume_run(graph_config=graph_config, graph_run_id=start.graph_run.graph_run_id)
    second = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    second_state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    second_ref = second_state["result_index"][long_node_id]["result_ref"]

    assert first.status == "blocked"
    assert second.executed_work_order_count == 1
    assert first_ref != second_ref
    assert _runtime_object_payload(runtime, first_ref)["status"] == "blocked"
    assert _runtime_object_payload(runtime, second_ref)["status"] == "completed"


def test_graph_runtime_object_safe_ids_include_stable_hash_for_normalized_collisions() -> None:
    assert stable_safe_id("node:a") != stable_safe_id("node/a")
    assert stable_safe_id("node:a").startswith("node_a_")
    assert stable_safe_id("node/a").startswith("node_a_")


def test_graph_resume_does_not_requeue_nonrecoverable_blocked_node() -> None:
    runtime = _task_execution_runtime("graph-task-nonrecoverable-blocked-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.nonrecoverable_blocked",
        title="Nonrecoverable Blocked",
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
    order = start.node_work_orders[0]
    blocked_result = NodeResultEnvelope(
        result_id=f"nresult:test:{order.work_order_id}:nonrecoverable",
        graph_run_id=order.graph_run_id,
        task_run_id=order.task_run_id,
        node_id=order.node_id,
        work_order_id=order.work_order_id,
        executor_type=order.executor_type,
        status="blocked",
        outputs={},
        error={"reason": "loop_continue_node_missing"},
    )

    runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        result=blocked_result,
    )
    resumed = runtime.graph_harness.resume_run(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
    )

    assert resumed.reason == "blocked_not_recoverable"
    assert resumed.node_work_orders == ()
    assert resumed.loop_state is not None
    assert resumed.loop_state.status == "blocked"
    assert resumed.loop_state.node_states["draft"]["status"] == "blocked"


def test_graph_harness_executes_agent_work_order_and_advances_loop() -> None:
    runtime = HarnessRuntimeFacade(
        base_dir=isolated_backend_root("graph-task-runtime-execute-work-order-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=HarnessRuntimeFacadeMemoryFacadeStub(),
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
                    "graph_module_expansion_plan_id": "graph_module_expansion.child",
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
                        "runtime_profile": {"runtime_policy": {}},
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
    assert contract["runtime_profile"]["runtime_policy"]["source"] == "graph_slot.node_contract"
    assert selection["task_environment_id"] == "env.development.sandbox"
    assert selection["prompt_contract"]["task_instruction"] == "只完成当前节点任务。"
    assert selection["runtime_profile"]["tool_policy"] == {}


def test_graph_node_task_run_records_runtime_model_override() -> None:
    runtime = _runtime("graph-node-runtime-model-override-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runtime_model_override",
        title="Runtime Model Override",
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
    work_order, override_diagnostics = work_order_with_model_overrides(
        graph_config=graph_config,
        work_order=start.node_work_orders[0],
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
    )

    task_run = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=work_order)
    diagnostics = dict(task_run.diagnostics or {})
    runtime_profile = dict(dict(diagnostics.get("runtime_task_selection") or {}).get("runtime_profile") or {})
    contract = _runtime_object_payload(runtime, task_run.task_contract_ref)

    assert override_diagnostics["effective"]["model"] == "deepseek-v4-pro"
    assert dict(runtime_profile.get("model_requirement") or {})["model"] == "deepseek-v4-pro"
    assert dict(contract["runtime_profile"]["model_requirement"])["model"] == "deepseek-v4-pro"
    assert diagnostics["graph_model_override"]["matched_scope"] == "role_group"


def test_existing_waiting_graph_node_task_run_refreshes_runtime_model_override() -> None:
    runtime = _runtime("graph-node-runtime-model-override-refresh-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.runtime_model_override_refresh",
        title="Runtime Model Override Refresh",
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
                "metadata": {"prompt_contract": {"role_prompt": "你是一名执行员。"}},
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.development.sandbox"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)
    original_task = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=start.node_work_orders[0])
    runtime.single_agent_runtime_host.state_index.upsert_task_run(
        TaskRun(
            **{
                **original_task.to_dict(),
                "diagnostics": {
                    **dict(original_task.diagnostics or {}),
                    "model_selection": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                },
            }
        )
    )
    work_order, _diagnostics = work_order_with_model_overrides(
        graph_config=graph_config,
        work_order=start.node_work_orders[0],
        runtime_overrides={
            "model_overrides": {
                "nodes": {
                    "draft": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-pro",
                        "credential_ref": "env:DEEPSEEK_WRITING_API_KEY",
                    }
                }
            }
        },
    )

    refreshed = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=work_order)
    diagnostics = dict(refreshed.diagnostics or {})
    runtime_profile = dict(dict(diagnostics.get("runtime_task_selection") or {}).get("runtime_profile") or {})
    contract = _runtime_object_payload(runtime, refreshed.task_contract_ref)

    assert "model_selection" not in diagnostics
    assert dict(runtime_profile.get("model_requirement") or {})["model"] == "deepseek-v4-pro"
    assert dict(contract["runtime_profile"]["model_requirement"])["model"] == "deepseek-v4-pro"
    assert diagnostics["graph_model_override"]["matched_key"] == "draft"


def test_graph_node_agent_profile_id_does_not_replace_agent_id() -> None:
    runtime = _runtime("graph-node-agent-profile-boundary-")
    runtime.agent_runtime_registry.upsert_profile(
        agent_id="agent:0",
        agent_profile_id="custom_graph_node_profile",
        allowed_operations=("op.model_response",),
        metadata={},
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
        allowed_operations=("op.model_response",),
        metadata={},
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
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    node_task_run_id = state["result_index"]["draft"]["node_executor_task_run_id"]
    trace = runtime.single_agent_runtime_host.get_trace(node_task_run_id, include_payloads=True)
    started_event = next(item for item in trace["events"] if item["event_type"] == "task_run_executor_started")
    assembly = started_event["payload"]["runtime_assembly"]

    assert result.status == "completed"
    assert result.graph_result["node_result_refs"][0] == state["result_index"]["draft"]["result_ref"]
    assert assembly["agent_profile_ref"] == "custom_graph_node_profile"
    assert assembly["agent_prompt_refs"] == []
    assert assembly["agent_prompt_refs_by_invocation"] == {}


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


def test_graph_node_task_run_id_uses_full_work_order_hash_to_avoid_safe_id_collision() -> None:
    runtime = _runtime("graph-node-task-run-id-work-order-hash-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.work_order_hash",
        title="Work Order Hash",
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
    first = start.node_work_orders[0]
    second = type(first)(
        **{
            **first.to_dict(),
            "work_order_id": f"{first.work_order_id}999999999999999999999999999999999999999999999999",
        }
    )

    first_task = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=first)
    second_task = runtime._create_graph_node_task_run(graph_config=graph_config, work_order=second)

    assert first_task.task_run_id != second_task.task_run_id
    assert len(first_task.task_run_id) <= 180
    assert len(second_task.task_run_id) <= 180
    assert first_task.diagnostics["graph_work_order_id"] == first.work_order_id
    assert second_task.diagnostics["graph_work_order_id"] == second.work_order_id


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

    recovery = TaskExecutorController(
        runtime_host=runtime.single_agent_runtime_host,
        execute_task_run_callback=runtime.execute_task_run,
    ).recover_interrupted_executor_leases()
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
    assert start.task_run.task_run_id not in {item["task_run_id"] for item in monitor["task_runs"]}
    assert runtime.single_agent_runtime_host.get_task_run_live_monitor(start.task_run.task_run_id)["bucket"] == "completed"


def test_graph_run_monitor_exposes_only_active_node_runtime_views_after_runner() -> None:
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
    views = {item["node_id"]: item for item in monitor["active_node_runtime_views"]}

    assert result.status == "completed"
    assert views == {}
    assert "node_runtime_views" not in monitor
    assert "events" not in monitor
    assert "work_order_index" not in monitor["graph_loop_state"]
    assert "result_index" not in monitor["graph_loop_state"]
    assert monitor["graph_loop_state"]["completed_node_ids"] == ["draft", "review"]


def test_graph_agent_node_records_artifact_repository_receipts(tmp_path: Path) -> None:
    artifact_rel = "storage/task_environments/development/sandbox/artifacts/graph-node-artifact.md"
    runtime = HarnessRuntimeFacade(
        base_dir=isolated_backend_root("graph-artifact-repository-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=HarnessRuntimeFacadeMemoryFacadeStub(),
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
    node_result_summary = state["result_index"]["draft"]
    node_result = _runtime_object_payload(runtime, node_result_summary["result_ref"])
    overview = runtime.graph_harness._services.artifact_repository_service.overview(
        task_run_id=start.task_run.task_run_id,
        graph_run_id=start.graph_run.graph_run_id,
    )

    assert result.status == "completed"
    assert "outputs" not in node_result_summary
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
    node_result_summary = state["result_index"]["draft"]
    node_result = _runtime_object_payload(runtime, node_result_summary["result_ref"])
    artifact_path = (
        runtime.base_dir.parent
        / "storage"
        / "task_environments"
        / "development"
        / "sandbox"
        / "artifacts"
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
    assert "outputs" not in node_result_summary
    assert node_result["artifact_refs"] == [
        "storage/task_environments/development/sandbox/artifacts/project-artifact-test/world/world_candidate_round_002.md"
    ]
    assert node_result["artifact_materialization_receipts"][0]["authority"] == "artifact_repository.service"
    assert overview["artifact_count"] == 1
    assert (
        overview["artifacts"][0]["path"]
        == "storage/task_environments/development/sandbox/artifacts/project-artifact-test/world/world_candidate_round_002.md"
    )


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
    node_result_summary = state["result_index"]["draft"]
    node_result = _runtime_object_payload(runtime, node_result_summary["result_ref"])
    overview = runtime.graph_harness._services.formal_memory_service.overview(
        task_run_id=start.task_run.task_run_id,
        repository_id="memory.world",
        collection_id="world",
    )

    assert result.status == "completed"
    assert "outputs" not in node_result_summary
    assert node_result["memory_commit_receipts"]
    assert {item["authority"] for item in node_result["memory_commit_receipts"]} == {"formal_memory.service"}
    assert overview["version_count"] == 1
    assert overview["versions"][0]["status"] == "committed"
    assert overview["versions"][0]["canonical_text"] == "图节点确认世界观设定。"


def test_graph_memory_commit_preserves_plural_record_kinds_for_required_reads() -> None:
    runtime = _task_execution_runtime("graph-formal-memory-record-kinds-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.formal_memory_record_kinds",
        title="Formal Memory Record Kinds",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="reader",
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
            {"node_id": "reader", "node_type": "agent", "title": "读取", "task_id": "task.test.reader", "agent_id": "agent:0"},
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
                    "record_kinds": ["world_fact"],
                    "source_output_key": "world_memory_candidate",
                    "commit_visibility_policy": {"visible_after": "same_clock"},
                },
            },
            {
                "edge_id": "edge.memory.reader",
                "source_node_id": "memory.world",
                "target_node_id": "reader",
                "edge_type": "memory_read",
                "metadata": {
                    "repository": "memory.world",
                    "collection": "world",
                    "record_kinds": ["world_fact"],
                    "on_missing": "block",
                    "model_visible_label": "世界观记忆",
                },
            },
            {"edge_id": "edge.draft.reader", "source_node_id": "draft", "target_node_id": "reader", "edge_type": "handoff"},
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
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    reader_order_ref = (state.get("result_index") or {}).get("reader", {}).get("result_ref")
    reader_result = _runtime_object_payload(runtime, reader_order_ref)
    overview = runtime.graph_harness._services.formal_memory_service.overview(
        task_run_id=start.task_run.task_run_id,
        repository_id="memory.world",
        collection_id="world",
    )

    assert result.status == "completed"
    assert overview["versions"][0]["record_kind"] == "world_fact"
    assert reader_result["status"] == "completed"


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
    node_result_summary = state["result_index"]["draft"]
    node_result = _runtime_object_payload(runtime, node_result_summary["result_ref"])

    assert result.status == "failed"
    assert "outputs" not in node_result_summary
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
    event_text = json.dumps([dict(item.get("payload") or {}) for item in result.events], ensure_ascii=False)
    assert '"final_answer"' not in event_text
    assert '"input_package"' not in event_text


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
    task_run = runtime.graph_harness.get_task_run(start.task_run.task_run_id)
    graph_run = runtime.graph_harness.get_graph_run(start.graph_run.graph_run_id)

    assert result.status == "budget_exhausted"
    assert result.budget_exhausted is True
    assert result.executed_work_order_count == 1
    assert state["status"] == "running"
    assert state["completed_node_ids"] == ["first"]
    assert state["active_work_orders"]
    assert state["active_work_orders"]["second"]
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "max_node_executions_exhausted"
    assert dict(task_run.diagnostics)["runner_status"] == "budget_exhausted"
    assert graph_run is not None
    assert graph_run["status"] == "budget_exhausted"
    assert graph_run["terminal_reason"] == "max_node_executions_exhausted"


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
    hijacked_id = _graph_node_task_run_id(work_order)
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


def test_graph_run_runner_validates_executor_origin_from_persisted_task_run() -> None:
    task_run = TaskRun(
        task_run_id="gtask:persisted",
        session_id="session:test",
        task_id="task.test.execute",
        execution_runtime_kind="single_agent_task",
        status="completed",
        diagnostics={
            "origin": {
                "origin_kind": "graph_node_assigned",
                "origin_authority": "harness.graph_loop",
                "origin_ref": "gwork:test",
                "parent_run_ref": "grun:test",
                "graph_run_id": "grun:test",
                "node_id": "draft",
            },
            "graph_run_id": "grun:test",
            "graph_work_order_id": "gwork:test",
            "graph_node_id": "draft",
        },
    )
    state_index = SimpleNamespace(get_task_run=lambda task_run_id: task_run if task_run_id == task_run.task_run_id else None)
    runner = GraphRunRunner(services=SimpleNamespace(state_index=state_index), graph_loop=None, execute_work_order=lambda **_: None)

    runner._validate_executor_origin(
        graph_run_id="grun:test",
        work_order=SimpleNamespace(work_order_id="gwork:test"),
        execution={"node_executor_task_run": {"task_run_id": task_run.task_run_id}},
    )


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
