from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system import build_default_operation_registry
from capability_system.tool_authorization import build_tool_authorization_index
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions
from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from runtime.capabilities import build_current_turn_capability_plan, tool_instances_for_capability_plan
from permissions import (
    OperationGate,
    OperationGatePipelineContext,
    build_tool_request_runtime_admission,
    build_model_response_runtime_admission,
    build_runtime_capability_state,
)
from runtime.shared.action_request import RuntimeActionRequest


def main() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=(
            "op.model_response",
            "op.search_text",
            "op.write_file",
            "op.edit_file",
        ),
        blocked_operations=(),
    )
    task_operation = {
        "task_contract": {"task_id": "task:test:capability"},
        "operation_requirement": {
            "required_operations": ["op.model_response"],
            "optional_operations": [],
            "denied_operations": [],
            "metadata": {"approval_policy": "default", "safety_envelope": {"safety_class": "S0_readonly"}},
        },
    }
    _, resource_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=build_default_operation_registry(),
        agent_runtime_profile=profile,
    )
    state = build_runtime_capability_state(
        task_operation,
        resource_policy=resource_policy,
        agent_runtime_profile=profile,
        visible_tool_names=[],
    )

    assert state["profile_write_capable"] is True
    assert state["turn_write_operation_admitted"] is False
    assert state["turn_write_tool_visible"] is False
    assert "op.write_file" in state["agent_profile_operations"]
    assert "op.write_file" in state["blocked_by_turn_policy_operations"]


def test_execution_permit_operations_are_admitted_for_runtime_tools() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="writing_modular_creator_runtime",
        agent_id="agent:writing_modular_creator",
        allowed_operations=("op.model_response", "op.memory_read"),
        blocked_operations=(),
    )
    task_operation = {
        "task_contract": {"task_id": "task:test:memory-search"},
        "operation_requirement": {
            "required_operations": ["op.model_response"],
            "optional_operations": [],
            "denied_operations": [],
            "metadata": {"approval_policy": "default"},
        },
        "execution_permit": {
            "allowed_operations": ["op.model_response", "op.memory_read"],
            "visible_tools": ["memory_search"],
            "dispatchable_tools": ["memory_search"],
            "model_visible_tool_refs": ["memory_search"],
        },
    }

    _, resource_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=build_default_operation_registry(),
        agent_runtime_profile=profile,
    )

    registry = build_default_operation_registry()
    action_request = RuntimeActionRequest(
        request_id="rtact:test:memory-search",
        task_run_id="taskrun:test:memory-search",
        request_type="tool_call",
        operation_id="",
        payload={
            "tool_name": "memory_search",
            "tool_call": {
                "id": "call-memory-search",
                "name": "memory_search",
                "args": {"query": "云泽 大泽", "project_id": "project:test", "limit": 8},
            },
        },
    )
    tool_directive, tool_policy = build_tool_request_runtime_admission(
        action_request=action_request,
        task_id="task:test:memory-search",
        task_operation=task_operation,
        operation_id=registry.normalize_id("memory_search"),
        operation_descriptor=registry.get_operation("op.memory_read"),
        adopted_resource_policy=resource_policy,
    )
    gate_result = OperationGate(registry).check(
        "op.memory_read",
        resource_policy=tool_policy,
        directive_ref=tool_directive.directive_id,
        context=OperationGatePipelineContext(
            permission_mode="default",
            operation_input={"operation_id": "op.memory_read", "tool_name": "memory_search"},
        ),
    )

    assert "op.memory_read" in resource_policy.allowed_operations
    assert "op.memory_read" not in resource_policy.denied_operations
    assert "memory_search" in resource_policy.allowed_tools
    assert "op.memory_read" in tool_policy.allowed_operations
    assert gate_result.allowed is True


def test_model_visible_state_operation_uses_turn_permit_without_profile_duplication() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
    )
    task_operation = {
        "task_contract": {"task_id": "task:test:agent-todo"},
        "operation_requirement": {
            "required_operations": ["op.model_response"],
            "optional_operations": ["op.agent_todo"],
            "denied_operations": [],
            "metadata": {"approval_policy": "default"},
        },
    }

    _, resource_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=build_default_operation_registry(),
        agent_runtime_profile=profile,
    )

    assert "op.agent_todo" in resource_policy.allowed_operations
    assert "op.agent_todo" not in resource_policy.denied_operations


def test_agent_todo_reaches_current_turn_capability_plan_and_tool_instances() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=("op.model_response",),
        blocked_operations=(),
    )
    task_operation = {
        "task_contract": {"task_id": "task:test:agent-todo-final-tools"},
        "operation_requirement": {
            "required_operations": ["op.model_response"],
            "optional_operations": ["op.agent_todo"],
            "denied_operations": [],
            "metadata": {"approval_policy": "default"},
        },
        "execution_permit": {
            "allowed_operations": ["op.model_response", "op.agent_todo"],
            "visible_tools": ["agent_todo"],
            "dispatchable_tools": ["agent_todo"],
            "model_visible_tool_refs": ["agent_todo"],
        },
    }
    registry = build_default_operation_registry()
    _, resource_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=registry,
        agent_runtime_profile=profile,
    )
    tool_instances = build_tool_instances(ROOT)
    index = build_tool_authorization_index(get_tool_definitions())
    plan = build_current_turn_capability_plan(
        tool_instances=tool_instances,
        resource_policy=resource_policy,
        definitions_by_name=index.definitions_by_name,
        normalize_operation_id=registry.normalize_id,
        task_operation=task_operation,
        execution_permit=dict(task_operation["execution_permit"]),
    )
    final_tools = tool_instances_for_capability_plan(
        tool_instances=tool_instances,
        capability_plan=plan,
    )
    final_tool_names = {str(getattr(tool, "name", "") or "") for tool in final_tools}

    assert "op.agent_todo" in plan.allowed_operations
    assert "agent_todo" in plan.model_visible_tools
    assert "agent_todo" in plan.dispatchable_tools
    assert "agent_todo" in final_tool_names

    print("ALL PASSED (runtime capability state)")


if __name__ == "__main__":
    main()


