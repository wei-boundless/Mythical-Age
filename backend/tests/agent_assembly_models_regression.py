from __future__ import annotations

from pathlib import Path

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from runtime.agent_assembly import (
    AgentAssemblyContract,
    AgentInvocation,
    DirectWorkOrder,
    ExecutionPermit,
    HumanWorkOrder,
    NodeWorkOrder,
    SubRuntimeWorkOrder,
    WorkOrder,
    build_agent_assembly_contract,
    build_agent_invocation,
    build_task_selection_payload,
    build_turn_context_payload,
    validate_assembly_contract,
    validate_agent_invocation,
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


def test_direct_work_order_operation_policy_extends_visible_tools() -> None:
    base_dir = _base_dir()
    work_order = DirectWorkOrder(
        work_order_id="",
        task_ref="task.test.browser",
        runtime_assembly={
            "operation_policy": {
                "allowed_operations": ["op.model_response", "op.browser_control"],
                "required_operations": ["op.browser_control"],
            }
        },
    )
    runtime_profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=("op.model_response", "op.fetch_url"),
    )

    invocation = build_agent_invocation(work_order, base_dir=base_dir, agent_runtime_profile=runtime_profile)
    permit = invocation.execution_permit

    assert "op.browser_control" in permit["allowed_operations"]
    assert "browser_control" in permit["visible_tools"]
    assert "browser_control" in permit["model_visible_tool_refs"]


def test_agent_invocation_is_single_boundary_for_node_work_order() -> None:
    base_dir = _base_dir()
    work_order = NodeWorkOrder(
        work_order_id="nodeexec:world-review",
        task_ref="task.test.world_review",
        coordination_run_id="coordrun:test",
        thread_id="coordrun:test",
        root_task_run_id="taskrun:root",
        stage_id="world_review",
        node_id="world_review",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        runtime_lane="readonly_exploration",
        explicit_inputs={
            "world_candidate_ref": "artifact:world.md",
            "__internal_protocol": "must-not-leak",
        },
        input_package={"package_id": "nodeinput:world-review"},
        current_turn_context={
            "agent_id": "agent:stale",
            "stage_execution_request": {"request_id": "raw-leak"},
            "node_work_order": {"work_order_id": "raw-leak"},
            "agent_assembly_contract": {"assembly_id": "raw-leak"},
            "runtime_control": {"raw": True},
            "a2a_payload": {"raw": True},
            "task_graph_id": "graph:test",
        },
    )
    runtime_profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_runtime_lanes=("readonly_exploration",),
        allowed_operations=("op.model_response", "op.read_file"),
    )

    invocation = build_agent_invocation(work_order, base_dir=base_dir, agent_runtime_profile=runtime_profile)
    payload = invocation.to_dict()

    assert isinstance(invocation, AgentInvocation)
    assert payload["authority"] == "runtime.agent_assembly.invocation"
    assert payload["assembly_contract"]["work_order_id"] == "nodeexec:world-review"
    assert payload["execution_permit"]["assembly_id"] == invocation.assembly_id
    assert payload["runtime_control"]["node_work_order"]["work_order_id"] == "nodeexec:world-review"
    assert payload["runtime_control"]["agent_assembly_contract"]["assembly_id"] == invocation.assembly_id
    assert payload["model_context"]["agent_id"] == "agent:0"
    assert payload["model_context"]["agent_profile_id"] == "main_interactive_agent"
    assert payload["model_context"]["task_graph_id"] == "graph:test"
    assert payload["model_context"]["explicit_inputs"] == {"world_candidate_ref": "artifact:world.md"}
    for key in (
        "stage_execution_request",
        "node_work_order",
        "agent_assembly_contract",
        "execution_permit",
        "runtime_control",
        "a2a_payload",
    ):
        assert key not in payload["model_context"]
        assert key not in payload["task_selection"]
    assert payload["task_selection"]["agent_id"] == "agent:0"
    assert payload["task_selection"]["assembly_id"] == invocation.assembly_id
    assert validate_agent_invocation(invocation).passed


def test_task_semantics_survive_boundary_projection_without_control_leak() -> None:
    payload = {
        "interaction_mode": "professional_mode",
        "intent_decision": {
            "execution_strategy": "professional_task_run",
            "interaction_mode": "professional_mode",
        },
        "runtime_assembly_hint": {
            "execution_strategy": "professional_task_run",
            "runtime_mode": "professional_task",
            "interaction_mode": "professional_mode",
        },
        "mode_policy": {
            "interaction_mode": "professional_mode",
            "tool_policy": {"max_tool_rounds_per_task_run": 3},
        },
        "semantic_task_type": "test_report_triage",
        "runtime_control": {"must": "not leak"},
        "stage_execution_request": {"request_id": "raw"},
        "node_work_order": {"work_order_id": "raw"},
    }

    turn_context = build_turn_context_payload(current_turn_context=payload)
    task_selection = build_task_selection_payload(task_selection=payload)

    assert turn_context["interaction_mode"] == "professional_mode"
    assert turn_context["mode_policy"]["tool_policy"]["max_tool_rounds_per_task_run"] == 3
    assert task_selection["semantic_task_type"] == "test_report_triage"
    assert task_selection["intent_decision"]["execution_strategy"] == "professional_task_run"
    for key in ("runtime_control", "stage_execution_request", "node_work_order"):
        assert key not in turn_context
        assert key not in task_selection


def test_direct_invocation_does_not_export_graph_continuation_stage() -> None:
    base_dir = _base_dir()
    work_order = DirectWorkOrder(
        work_order_id="",
        task_ref="task.test.direct",
        explicit_inputs={"goal": "继续回答"},
    )

    invocation = build_agent_invocation(work_order, base_dir=base_dir).to_dict()

    assert invocation["work_order"]["work_kind"] == "direct"
    assert "continuation_stage_id" not in invocation["model_context"]
    assert "continuation_stage_id" not in invocation["task_selection"]
