from __future__ import annotations

from pathlib import Path

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from runtime.agent_assembly import (
    AgentAssemblyContract,
    DirectWorkOrder,
    ExecutionPermit,
    HumanWorkOrder,
    NodeWorkOrder,
    SubRuntimeWorkOrder,
    WorkOrder,
    build_agent_assembly_contract,
    validate_assembly_contract,
    validate_execution_permit,
    validate_work_order,
)
from runtime.coordination_runtime.work_order_builder import build_node_work_order_from_request
from runtime.execution_permit import build_execution_permit
from runtime.execution.node_execution_request import NodeExecutionRequest


def _base_dir() -> Path:
    from tests.support.runtime_stubs import isolated_backend_root

    return isolated_backend_root("agent-assembly-")


def test_typed_work_orders_cover_human_and_subruntime_executors() -> None:
    human = HumanWorkOrder(
        work_order_id="",
        work_kind="human",
        task_ref="task.review",
        executor_type="human",
        coordination_run_id="coordrun:test",
        stage_id="review",
        node_id="review",
        agent_id="agent:reviewer",
        agent_profile_id="review_profile",
    )
    subruntime = SubRuntimeWorkOrder(
        work_order_id="",
        work_kind="subruntime",
        task_ref="task.graph",
        executor_type="subruntime",
        coordination_run_id="coordrun:test",
        stage_id="graph",
        node_id="graph",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        subruntime_kind="graph_module",
    )

    assert isinstance(human, HumanWorkOrder)
    assert isinstance(subruntime, SubRuntimeWorkOrder)
    assert subruntime.subruntime_kind == "graph_module"


def test_node_execution_request_round_trip_preserves_boundary_fields() -> None:
    request = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="review",
        node_id="review",
        task_ref="task.test.review",
        executor_type="human",
        executor_binding={"selected_executor": "human"},
        explicit_inputs={"world_ref": "artifact:world.md"},
        human_work_packet={"work_packet_id": "humanwork:test"},
    )

    work_order = build_node_work_order_from_request(request)

    assert isinstance(work_order, HumanWorkOrder)
    payload = work_order.to_dict()
    assert payload["authority"] == "runtime.agent_assembly.work_order"
    assert payload["human_work_packet"]["work_packet_id"] == "humanwork:test"
    assert payload["stage_id"] == "review"
    assert payload["node_id"] == "review"


def test_work_order_to_assembly_and_permit_close_the_boundary() -> None:
    base_dir = _base_dir()
    work_order = NodeWorkOrder(
        work_order_id="",
        task_ref="task.test.node",
        coordination_run_id="coordrun:test",
        thread_id="",
        root_task_run_id="taskrun:root",
        stage_id="review",
        node_id="review",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        runtime_lane="readonly_exploration",
        explicit_inputs={"goal": "审查"},
        input_package={"package_id": "input:test"},
        runtime_assembly={"prompt_manifest_ref": "manifest:test"},
    )
    runtime_profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_runtime_lanes=("readonly_exploration",),
        allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
    )

    assembly = build_agent_assembly_contract(work_order, base_dir=base_dir, agent_runtime_profile=runtime_profile)
    permit = build_execution_permit(assembly)

    assert isinstance(assembly, AgentAssemblyContract)
    assert assembly.agent_id == "agent:0"
    assert assembly.agent_profile_id == "main_interactive_agent"
    assert assembly.prompt_assembly is not None
    assert assembly.prompt_assembly.role_summary
    assert assembly.model_context["assembly_id"] == assembly.assembly_id
    assert assembly.model_context["visible_ports"]
    assert validate_work_order(work_order).passed
    assert validate_assembly_contract(assembly).passed
    assert isinstance(permit, ExecutionPermit)
    assert permit.assembly_id == assembly.assembly_id
    assert permit.work_order_id == assembly.work_order_id
    assert validate_execution_permit(permit).passed
    assert "read_file" in permit.visible_tools
    assert "search_text" in permit.dispatchable_tools


def test_direct_work_order_gets_agent_style_prompt_and_default_permit() -> None:
    base_dir = _base_dir()
    work_order = DirectWorkOrder(
        work_order_id="",
        task_ref="task.test.direct",
        coordination_run_id="",
        thread_id="",
        root_task_run_id="",
        explicit_inputs={"goal": "继续回答"},
        input_package={"package_id": "input:direct"},
    )

    assembly = build_agent_assembly_contract(work_order, base_dir=base_dir)
    permit = build_execution_permit(assembly)

    assert assembly.work_kind == "direct"
    assert assembly.prompt_assembly is not None
    assert "当前工作单" in assembly.prompt_assembly.instruction_text
    assert "runtime 节点" not in assembly.prompt_assembly.instruction_text
    assert permit.allowed_operations
    assert permit.model_visible_tool_refs == permit.visible_tools
    assert validate_work_order(work_order).passed
