from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from permissions.operations import build_default_operation_registry
from capability_system.tools.authorization import build_tool_authorization_index
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definitions
from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from harness.runtime import build_runtime_tool_plan, tool_instances_for_runtime_tool_plan
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
    plan = build_runtime_tool_plan(
        runtime_assembly=_runtime_assembly_for_tools(
            "task:test:agent-todo-final-tools",
            tool_names=("agent_todo",),
            definitions_by_name=index.definitions_by_name,
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name=index.definitions_by_name,
    )
    final_tools = tool_instances_for_runtime_tool_plan(
        tool_instances=tool_instances,
        tool_plan=plan,
    )
    final_tool_names = {str(getattr(tool, "name", "") or "") for tool in final_tools}

    assert "op.agent_todo" in plan.capability_table.dispatchable_operations
    assert "agent_todo" in {str(item.get("tool_name") or "") for item in plan.model_visible_tools}
    assert "agent_todo" in plan.dispatchable_tool_names
    assert "agent_todo" in final_tool_names


def test_full_access_runtime_mode_does_not_emit_approval_required_operations() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=("op.model_response", "op.edit_file"),
        blocked_operations=(),
        approval_policy="manual_approval_required",
    )
    task_operation = {
        "task_contract": {"task_id": "task:test:full-access-approval"},
        "operation_requirement": {
            "required_operations": ["op.model_response", "op.edit_file"],
            "optional_operations": [],
            "denied_operations": [],
            "metadata": {"approval_policy": "manual_approval_required"},
        },
    }

    _, resource_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=build_default_operation_registry(),
        agent_runtime_profile=profile,
        permission_mode="full_access",
    )

    assert "op.edit_file" in resource_policy.allowed_operations
    assert "op.edit_file" not in resource_policy.requires_approval_operations
    decisions = {item.operation_id: item for item in resource_policy.decisions}
    assert decisions["op.edit_file"].decision == "allow"
    assert decisions["op.edit_file"].diagnostics["permission_mode"] == "full_access"


def test_tool_request_admission_full_access_satisfies_adopted_approval_policy() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=("op.model_response", "op.edit_file"),
        blocked_operations=(),
        approval_policy="manual_approval_required",
    )
    task_operation = {
        "task_contract": {"task_id": "task:test:tool-full-access-approval"},
        "operation_requirement": {
            "required_operations": ["op.model_response", "op.edit_file"],
            "optional_operations": [],
            "denied_operations": [],
            "metadata": {"approval_policy": "manual_approval_required"},
        },
    }
    registry = build_default_operation_registry()
    _, adopted_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=registry,
        agent_runtime_profile=profile,
    )
    action_request = RuntimeActionRequest(
        request_id="rtact:test:edit-full-access",
        task_run_id="taskrun:test:edit-full-access",
        request_type="tool_call",
        operation_id="op.edit_file",
        payload={
            "tool_name": "edit_file",
            "tool_call": {
                "id": "call-edit-full-access",
                "name": "edit_file",
                "args": {"path": "backend/permissions/tool_admission.py", "old_text": "x", "new_text": "y"},
            },
        },
    )

    directive, tool_policy = build_tool_request_runtime_admission(
        action_request=action_request,
        task_id="task:test:tool-full-access-approval",
        task_operation=task_operation,
        operation_id="op.edit_file",
        operation_descriptor=registry.get_operation("op.edit_file"),
        adopted_resource_policy=adopted_policy,
        permission_mode="full_access",
    )

    assert "op.edit_file" in adopted_policy.requires_approval_operations
    assert "op.edit_file" in tool_policy.allowed_operations
    assert "op.edit_file" not in tool_policy.requires_approval_operations
    assert tool_policy.diagnostics["tool_requires_approval"] is False
    assert tool_policy.diagnostics["permission_mode"] == "full_access"
    assert directive.diagnostics["permission_mode"] == "full_access"


class _runtime_assembly_for_tools:
    def __init__(self, turn_id: str, *, tool_names: tuple[str, ...], definitions_by_name: dict[str, object]) -> None:
        self.turn_id = turn_id
        self.tool_names = tool_names
        self.definitions_by_name = definitions_by_name

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": "session:test",
            "turn_id": self.turn_id,
            "agent_invocation_id": f"aginvoke:{self.turn_id}",
            "available_tools": [
                {
                    "tool_name": name,
                    "operation_id": str(getattr(self.definitions_by_name[name], "operation_id", "") or name),
                }
                for name in self.tool_names
            ],
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {},
        }


if __name__ == "__main__":
    main()


