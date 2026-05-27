from __future__ import annotations

from pathlib import Path

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from runtime.agent_assembly import (
    AgentAssemblyContract,
    AgentInvocation,
    DirectWorkOrder,
    ExecutionPermit,
    GraphModuleWorkOrder,
    HumanWorkOrder,
    NodeWorkOrder,
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
from harness.loop.graph_coordination.work_order_builder import build_node_work_order_from_request
from harness.runtime.execution_policy import build_execution_permit
from harness.execution.node_protocol.node_execution_request import NodeExecutionRequest


def _base_dir() -> Path:
    from tests.support.runtime_stubs import isolated_backend_root

    return isolated_backend_root("agent-assembly-")


def test_typed_work_orders_cover_human_and_graph_module_executors() -> None:
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
    graph_module = GraphModuleWorkOrder(
        work_order_id="",
        work_kind="graph_module",
        task_ref="task.graph",
        executor_type="graph_module",
        coordination_run_id="coordrun:test",
        stage_id="graph",
        node_id="graph",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
    )

    assert isinstance(human, HumanWorkOrder)
    assert isinstance(graph_module, GraphModuleWorkOrder)
    assert graph_module.executor_type == "graph_module"


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


def test_node_runtime_assembly_contract_drives_role_tools_and_model_budget() -> None:
    base_dir = _base_dir()
    role_prompt = (
        "你是一名名家级中文商业网文长篇写手。\n"
        "你必须先按需使用 memory_search 搜索任务记忆数据库，再依据大纲、细纲、人物和世界设定写出连续章节。"
    )
    runtime_assembly = {
        "assembly_id": "runtime-assembly:chapter-draft",
        "metadata": {
            "role_prompt": role_prompt,
            "dynamic_memory_read_policy": {
                "allow_dynamic_read": True,
                "dynamic_read_tool_name": "memory_search",
            },
            "contract_bindings": {
                "runtime": {
                    "model_requirement": {
                        "profile_ref": "llm.deepseek.long_output_65536",
                        "preferred_output_tokens": 65536,
                        "min_output_tokens": 8192,
                    },
                    "tool_execution_policy": {
                        "allowed_tool_names": ["memory_search"],
                        "allowed_operation_refs": ["op.memory_read"],
                        "denied_tool_names": [
                            "read_file",
                            "search_text",
                            "search_files",
                            "web_search",
                            "fetch_url",
                            "write_file",
                            "delegate_to_agent",
                        ],
                        "database_search_only": True,
                    },
                },
                "memory": {
                    "dynamic_memory_read_policy": {
                        "allow_dynamic_read": True,
                        "dynamic_read_tool_name": "memory_search",
                    },
                },
            },
        },
    }
    work_order = NodeWorkOrder(
        work_order_id="nodeexec:chapter-draft",
        task_ref="task.writing.modular_novel.chapter_draft",
        coordination_run_id="coordrun:test",
        root_task_run_id="taskrun:root",
        stage_id="chapter_draft",
        node_id="chapter_draft",
        agent_id="agent:writing_modular_creator",
        agent_profile_id="writing_modular_creator_runtime",
        runtime_lane="coordination_task",
        runtime_assembly=runtime_assembly,
    )
    runtime_profile = AgentRuntimeProfile(
        agent_profile_id="writing_modular_creator_runtime",
        agent_id="agent:writing_modular_creator",
        allowed_runtime_lanes=("coordination_task",),
        allowed_operations=("op.model_response", "op.memory_read", "op.text_metric"),
    )

    assembly = build_agent_assembly_contract(work_order, base_dir=base_dir, agent_runtime_profile=runtime_profile)
    permit = build_execution_permit(assembly)

    assert assembly.prompt_assembly is not None
    assert "名家级中文商业网文长篇写手" in assembly.prompt_assembly.role_name
    assert assembly.prompt_assembly.instruction_text == role_prompt
    assert "阶段任务执行者" not in assembly.prompt_assembly.instruction_text
    assert assembly.metadata["model_requirement"]["preferred_output_tokens"] == 65536
    assert assembly.prompt_assembly.metadata["model_requirement"]["preferred_output_tokens"] == 65536
    assert "op.memory_read" in permit.allowed_operations
    assert "memory_search" in permit.visible_tools
    assert "memory_search" in permit.model_visible_tool_refs
    assert "memory_read" not in permit.visible_tools
    for forbidden in ("read_file", "search_text", "search_files", "web_search", "fetch_url", "write_file", "delegate_to_agent"):
        assert forbidden not in permit.visible_tools
        assert forbidden not in permit.dispatchable_tools
    assert permit.metadata["model_requirement"]["preferred_output_tokens"] == 65536
    assert permit.metadata["dynamic_memory_read_policy"]["dynamic_read_tool_name"] == "memory_search"


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


def test_task_semantics_survive_boundary_without_control_leak() -> None:
    payload = {
        "interaction_mode": "professional_mode",
        "mode_policy": {
            "interaction_mode": "professional_mode",
            "execution_strategy": "interaction_mode_run",
            "runtime_lane": "professional_task",
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
    assert task_selection["mode_policy"]["execution_strategy"] == "interaction_mode_run"
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
