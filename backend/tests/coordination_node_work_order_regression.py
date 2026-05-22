from __future__ import annotations

from pathlib import Path

from runtime.agent_assembly import (
    HumanWorkOrder,
    NodeWorkOrder,
    SubRuntimeWorkOrder,
    build_agent_assembly_contract,
    validate_work_order,
)
from runtime.coordination_runtime.runtime import LangGraphCoordinationRuntimeResult
from runtime.coordination_runtime.work_order_builder import build_node_work_order_from_request
from runtime.execution.node_execution_request import NodeExecutionRequest


def test_node_execution_request_builds_shadow_node_work_order() -> None:
    request = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:shadow",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="world_review",
        node_id="world_review",
        task_ref="task.test.world_review",
        agent_id="agent:reviewer",
        agent_profile_id="review_profile",
        runtime_lane="readonly_exploration",
        executor_type="agent",
        executor_binding={"selected_executor": "agent"},
        explicit_inputs={"world_ref": "artifact:world.md"},
        standard_input_package={"package_id": "nodeinput:test", "execution_permit_id": "permit:test"},
        runtime_assembly={"assembly_id": "runtime-assembly:test", "prompt_manifest_ref": "manifest:test"},
        dispatch_context={"dispatch_event_id": "tlevent:1", "clock_seq": 1},
        artifact_context_packet={"packet_id": "artifact-packet:test", "artifact_refs": ["artifact:world.md"]},
        working_memory_refs=("wm:1",),
    )

    work_order = build_node_work_order_from_request(
        request,
        state={
            "coordination_run_id": "coordrun:shadow",
            "root_task_run_id": "taskrun:root",
            "active_stage_id": "world_review",
            "active_node_id": "world_review",
            "active_task_ref": "task.test.world_review",
            "stage_order": ["world_review"],
            "node_statuses": {"world_review": "running"},
            "contract_manifest": {"manifest_id": "contract-manifest:test"},
            "diagnostics": {"graph_ref": "graph.test.shadow"},
        },
    )

    assert isinstance(work_order, NodeWorkOrder)
    assert work_order.work_order_id == request.request_id
    assert work_order.idempotency_key == request.idempotency_key
    assert work_order.task_ref == request.task_ref
    assert work_order.agent_id == request.agent_id
    assert work_order.agent_profile_id == request.agent_profile_id
    assert work_order.input_package["package_id"] == "nodeinput:test"
    assert work_order.explicit_inputs["world_ref"] == "artifact:world.md"
    assert work_order.artifact_context_packet["artifact_refs"] == ["artifact:world.md"]
    assert work_order.graph_state["contract_manifest_ref"] == "contract-manifest:test"
    assert validate_work_order(work_order).passed


def test_human_request_builds_human_work_order_and_keeps_packet() -> None:
    request = NodeExecutionRequest(
        request_id="nodeexec:human",
        coordination_run_id="coordrun:human",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="manual_review",
        node_id="manual_review",
        task_ref="task.test.manual_review",
        agent_id="agent:reviewer",
        agent_profile_id="review_profile",
        executor_type="human",
        executor_binding={"selected_executor": "human"},
        standard_input_package={"package_id": "nodeinput:human"},
        human_work_packet={"work_packet_id": "humanwork:review", "title": "人工审核"},
    )

    work_order = build_node_work_order_from_request(request)

    assert isinstance(work_order, HumanWorkOrder)
    assert work_order.executor_type == "human"
    assert work_order.work_kind == "human"
    assert work_order.human_work_packet["work_packet_id"] == "humanwork:review"
    assert validate_work_order(work_order).passed


def test_human_continuation_uses_work_order_boundary() -> None:
    request = NodeExecutionRequest(
        request_id="nodeexec:human-continuation",
        coordination_run_id="coordrun:human-continuation",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="manual_review",
        node_id="manual_review",
        task_ref="task.test.manual_review",
        agent_id="agent:reviewer",
        agent_profile_id="review_profile",
        executor_type="human",
        executor_binding={"selected_executor": "human"},
        standard_input_package={"package_id": "nodeinput:human"},
        human_work_packet={"work_packet_id": "humanwork:review"},
    )
    work_order = build_node_work_order_from_request(request)
    result = LangGraphCoordinationRuntimeResult(
        stage_execution_request=request,
        node_work_order=work_order.to_dict(),
    )

    payload = result.continuation_payload(
        session_id="session",
        current_turn_context={"agent_id": "agent:stale", "node_work_order": {"work_order_id": "stale"}},
    )

    assert payload["requires_human_executor"] is True
    assert payload["node_work_order"]["work_order_id"] == work_order.work_order_id
    assert payload["current_turn_context"]["agent_id"] == "agent:reviewer"
    assert payload["current_turn_context"]["node_work_order"]["work_kind"] == "human"
    assert payload["next_stage_id"] == "manual_review"


def test_graph_module_request_is_normalized_to_subruntime_work_order() -> None:
    handle = {
        "authority": "runtime.subruntime.graph_module_runtime_handle",
        "handle_id": "graphmodrun:test",
        "linked_graph_id": "graph.test.child",
        "graph_module_runtime_plan_id": "graph_module_runtime.child",
    }
    request = NodeExecutionRequest(
        request_id="nodeexec:graph-module",
        coordination_run_id="coordrun:graph-module",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="graph_module.child",
        node_id="graph_module.child",
        task_ref="task_graph.node.graph.parent.graph_module.child",
        executor_type="graph_module",
        executor_binding={"selected_executor": "graph_module", "graph_module_runtime_handle": handle},
        runtime_assembly={"authority": "runtime.subruntime.graph_module_runtime_assembly", "graph_module_runtime_handle": handle},
        standard_input_package={"package_id": "nodeinput:graph-module"},
    )

    work_order = build_node_work_order_from_request(request)

    assert isinstance(work_order, SubRuntimeWorkOrder)
    assert work_order.executor_type == "subruntime"
    assert work_order.work_kind == "subruntime"
    assert work_order.subruntime_kind == "graph_module"
    assert work_order.runtime_assembly["graph_module_runtime_handle"]["linked_graph_id"] == "graph.test.child"
    assert validate_work_order(work_order).passed


def test_runtime_can_assemble_shadow_work_order_before_cutover(tmp_path: Path) -> None:
    request = NodeExecutionRequest(
        request_id="nodeexec:assemble",
        coordination_run_id="coordrun:assemble",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="draft",
        node_id="draft",
        task_ref="task.test.draft",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        executor_type="agent",
        executor_binding={"selected_executor": "agent"},
        standard_input_package={"package_id": "nodeinput:assemble"},
    )
    work_order = build_node_work_order_from_request(request)

    assembly = build_agent_assembly_contract(work_order, base_dir=tmp_path)

    assert assembly.work_order_id == work_order.work_order_id
    assert assembly.task_ref == request.task_ref
    assert assembly.executor_type == "agent"
    assert assembly.agent_id == "agent:0"
    assert assembly.output_boundary.selected_channel == "graph_node_result"
