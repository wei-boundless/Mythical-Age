from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime import build_runtime_tool_plan
from harness.loop.task_tool_approval import (
    append_task_tool_approval_grant,
    approval_state_for_task_run,
    build_task_tool_approval_grant,
    tool_args_hash,
)
from permissions import OperationGate
from permissions.operations import build_default_operation_registry
from capability_system.tools.tool_units.subagent_control_tool import SpawnSubagentTool
from runtime.shared.models import TaskRun
from runtime.tool_runtime import RuntimeToolControlPlane, ToolInvocationRequest, ToolObservation
from runtime.tool_runtime.tool_invocation_control import ToolInvocationContext


def test_runtime_tool_plan_stably_orders_visible_tools_and_hashes_schema() -> None:
    assembly = _assembly(
        available_tools=[
            {"name": "search_text", "operation_id": "op.search_text"},
            {"name": "read_file", "operation_id": "op.read_file"},
        ],
    )

    plan_a = build_runtime_tool_plan(
        runtime_assembly=assembly,
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={
            "search_text": SimpleNamespace(operation_id="op.search_text", is_read_only=True),
            "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
        },
    )
    plan_b = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"operation_id": "op.read_file", "name": "read_file"},
                {"operation_id": "op.search_text", "name": "search_text"},
            ],
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={
            "search_text": SimpleNamespace(operation_id="op.search_text", is_read_only=True),
            "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
        },
    )

    assert [tool["name"] for tool in plan_a.model_visible_tools] == ["read_file", "search_text"]
    assert plan_a.dispatchable_tool_names == ("read_file", "search_text")
    assert plan_a.schema_hash == plan_b.schema_hash
    assert plan_a.registry_hash == plan_b.registry_hash


def test_needs_approval_tool_observation_is_control_plane_only() -> None:
    observation = ToolObservation(
        observation_id="toolobs:approval:one",
        invocation_id="toolinvoke:approval:one",
        caller_kind="task_run",
        caller_ref="taskrun:approval",
        tool_name="edit_file",
        operation_id="op.edit_file",
        status="needs_approval",
        text="operation requires approval",
    )

    task_observation = observation.to_task_observation(
        task_run_id="taskrun:approval",
        request_ref="action:edit",
        directive_ref="directive:edit",
    )

    assert task_observation["observation_type"] == "approval_request"
    assert task_observation["needs_model_followup"] is False
    assert task_observation["payload"]["status"] == "needs_approval"


def test_runtime_tool_plan_single_turn_keeps_authorized_side_effect_tools_visible_and_dispatchable() -> None:
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "write_file", "operation_id": "op.write_file", "read_only": False},
                {"name": "read_file", "operation_id": "op.read_file", "read_only": True},
            ],
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={
            "write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False),
            "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
        },
    )

    filtered = {
        item["tool_name"]: item["reason"]
        for item in plan.capability_table.to_dict()["filtered"]
        if item.get("tool_name")
    }

    assert [tool["name"] for tool in plan.model_visible_tools] == ["read_file", "write_file"]
    assert plan.dispatchable_tool_names == ("read_file", "write_file")
    assert "write_file" not in filtered


def test_runtime_tool_plan_hides_subagent_lifecycle_tools_outside_task_execution() -> None:
    definitions = {
        "spawn_subagent": SimpleNamespace(operation_id="op.subagent_spawn", is_read_only=False),
        "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "spawn_subagent", "operation_id": "op.subagent_spawn"},
                {"name": "read_file", "operation_id": "op.read_file"},
            ],
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name=definitions,
    )

    filtered = {
        item["tool_name"]: item["reason"]
        for item in plan.capability_table.to_dict()["filtered"]
        if item.get("tool_name")
    }

    assert [tool["name"] for tool in plan.model_visible_tools] == ["read_file"]
    assert "spawn_subagent" not in plan.dispatchable_tool_names
    assert filtered["spawn_subagent"] == "subagent_lifecycle_requires_task_execution"


def test_runtime_tool_plan_hides_task_memory_tools_outside_task_execution() -> None:
    definitions = {
        "memory_search": SimpleNamespace(
            operation_id="op.memory_read",
            is_read_only=True,
            contract=SimpleNamespace(owner_scope="task_memory"),
        ),
        "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "memory_search", "operation_id": "op.memory_read", "owner_scope": "task_memory"},
                {"name": "read_file", "operation_id": "op.read_file"},
            ],
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name=definitions,
    )

    filtered = {
        item["tool_name"]: item
        for item in plan.capability_table.to_dict()["filtered"]
        if item.get("tool_name")
    }

    assert [tool["name"] for tool in plan.model_visible_tools] == ["read_file"]
    assert "memory_search" not in plan.dispatchable_tool_names
    assert filtered["memory_search"]["reason"] == "task_scoped_tool_requires_task_run"
    assert filtered["memory_search"]["metadata"]["required_action"] == "request_task_run"


def test_runtime_tool_plan_hides_agent_todo_outside_task_execution() -> None:
    definitions = {
        "agent_todo": SimpleNamespace(
            operation_id="op.agent_todo",
            is_read_only=False,
            contract=SimpleNamespace(owner_scope="state"),
        ),
        "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "agent_todo", "operation_id": "op.agent_todo", "owner_scope": "state"},
                {"name": "read_file", "operation_id": "op.read_file"},
            ],
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name=definitions,
    )

    filtered = {
        item["tool_name"]: item
        for item in plan.capability_table.to_dict()["filtered"]
        if item.get("tool_name")
    }

    assert [tool["name"] for tool in plan.model_visible_tools] == ["read_file"]
    assert "agent_todo" not in plan.dispatchable_tool_names
    assert filtered["agent_todo"]["reason"] == "task_scoped_tool_requires_task_run"
    assert filtered["agent_todo"]["metadata"]["required_action"] == "request_task_run"


def test_runtime_tool_plan_keeps_agent_todo_for_task_execution() -> None:
    definitions = {
        "agent_todo": SimpleNamespace(
            operation_id="op.agent_todo",
            is_read_only=False,
            contract=SimpleNamespace(owner_scope="state"),
        ),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "agent_todo", "operation_id": "op.agent_todo", "owner_scope": "state"},
            ],
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name=definitions,
    )

    assert [tool["name"] for tool in plan.model_visible_tools] == ["agent_todo"]
    assert plan.dispatchable_tool_names == ("agent_todo",)


def test_runtime_tool_plan_keeps_task_memory_tools_for_task_execution() -> None:
    definitions = {
        "memory_search": SimpleNamespace(
            operation_id="op.memory_read",
            is_read_only=True,
            contract=SimpleNamespace(owner_scope="task_memory"),
        ),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "memory_search", "operation_id": "op.memory_read", "owner_scope": "task_memory"},
            ],
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name=definitions,
    )

    assert [tool["name"] for tool in plan.model_visible_tools] == ["memory_search"]
    assert plan.dispatchable_tool_names == ("memory_search",)


def test_runtime_tool_plan_keeps_subagent_lifecycle_tools_for_task_execution() -> None:
    definitions = {
        "list_subagents": SimpleNamespace(operation_id="op.subagent_list", is_read_only=True),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "list_subagents", "operation_id": "op.subagent_list"},
            ],
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name=definitions,
    )

    assert [tool["name"] for tool in plan.model_visible_tools] == ["list_subagents"]
    assert plan.dispatchable_tool_names == ("list_subagents",)


def test_runtime_tool_plan_general_environment_keeps_agent_authorized_tools_dispatchable() -> None:
    definitions = {
        "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
        "web_search": SimpleNamespace(operation_id="op.web_search", is_read_only=True),
        "fetch_url": SimpleNamespace(operation_id="op.fetch_url", is_read_only=True),
        "browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False),
        "terminal": SimpleNamespace(operation_id="op.shell", is_read_only=False),
        "write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "read_file", "operation_id": "op.read_file", "read_only": True},
                {"name": "web_search", "operation_id": "op.web_search", "read_only": True},
                {"name": "fetch_url", "operation_id": "op.fetch_url", "read_only": True},
                {"name": "browser_control", "operation_id": "op.browser_control", "read_only": False},
                {"name": "terminal", "operation_id": "op.shell", "read_only": False},
                {"name": "write_file", "operation_id": "op.write_file", "read_only": False},
            ],
            task_environment={
                "environment_id": "env.general.workspace",
                "execution_policy": {
                    "real_workspace_access": "read_only",
                    "write_scope_policy": "artifact_only",
                    "shell_execution_policy": "denied",
                    "browser_execution_policy": "denied",
                    "network_execution_policy": "denied",
                },
                "resource_space": {"workspace_policy": "read_mostly"},
                "sandbox_policy": {},
            },
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name=definitions,
    )
    assert [tool["name"] for tool in plan.model_visible_tools] == [
        "browser_control",
        "fetch_url",
        "read_file",
        "terminal",
        "web_search",
        "write_file",
    ]
    assert plan.dispatchable_tool_names == (
        "browser_control",
        "fetch_url",
        "read_file",
        "terminal",
        "web_search",
        "write_file",
    )
    assert plan.capability_table.to_dict()["filtered"] == []


def test_runtime_tool_plan_intersects_available_tools_with_operation_authorization() -> None:
    definitions = {
        "read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True),
        "write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False),
    }
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[
                {"name": "read_file", "operation_id": "op.read_file", "read_only": True},
                {"name": "write_file", "operation_id": "op.write_file", "read_only": False},
            ],
            task_environment={
                "environment_id": "env.coding.vibe_workspace",
                "execution_policy": {
                    "real_workspace_access": "read_only_or_task_granted",
                    "write_scope_policy": "sandbox_or_file_access_table",
                    "shell_execution_policy": "sandboxed",
                    "browser_execution_policy": "sandboxed",
                    "network_execution_policy": "task_decided",
                },
                "sandbox_policy": {"side_effect_operations": ["op.write_file"]},
                "resource_space": {"workspace_policy": "project_workspace"},
            },
            operation_authorization={
                "allowed_operations": ["op.read_file"],
                "denied_operations": ["op.write_file"],
                "decisions": [
                    {
                        "operation_id": "op.read_file",
                        "final_decision": "allow",
                        "reason": "environment_allowed",
                    },
                    {
                        "operation_id": "op.write_file",
                        "final_decision": "deny",
                        "reason": "agent_permission_missing",
                    },
                ],
            },
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name=definitions,
    )
    filtered = {
        item["tool_name"]: item["reason"]
        for item in plan.capability_table.to_dict()["filtered"]
        if item.get("tool_name")
    }

    assert [tool["name"] for tool in plan.model_visible_tools] == ["read_file"]
    assert plan.dispatchable_tool_names == ("read_file",)
    assert filtered["write_file"] == "agent_permission_missing"


def test_runtime_tool_plan_records_local_mcp_routes_as_deferred_capabilities() -> None:
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[],
            task_environment={
                "environment_id": "env.coding.vibe_workspace",
                "execution_policy": {
                    "real_workspace_access": "none",
                    "write_scope_policy": "document_artifacts_only",
                    "shell_execution_policy": "denied",
                    "browser_execution_policy": "denied",
                    "network_execution_policy": "denied",
                },
                "resource_space": {"workspace_policy": "document_workspace"},
                "sandbox_policy": {},
            },
            operation_authorization={
                "allowed_operations": ["op.mcp_pdf"],
                "decisions": [
                    {
                        "operation_id": "op.mcp_pdf",
                        "final_decision": "allow",
                        "reason": "environment_allowed",
                        "task_requested": True,
                    }
                ],
            },
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name={},
    )

    capability = plan.capability_table.capability_for_operation("op.mcp_pdf")

    assert capability is not None
    assert capability.tool_name == "mcp__langchain_agent__pdf"
    assert capability.visible is False
    assert capability.dispatchable is False
    assert capability.metadata["runtime_exposure"] == "local_mcp_runtime"
    assert plan.dispatchable_tool_names == ()


def test_runtime_tool_plan_does_not_create_local_mcp_route_when_environment_lacks_it() -> None:
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[],
            task_environment={
                "environment_id": "env.office.file_search",
                "execution_policy": {
                    "real_workspace_access": "read_only",
                    "write_scope_policy": "artifact_only",
                    "shell_execution_policy": "denied",
                    "browser_execution_policy": "denied",
                    "network_execution_policy": "denied",
                },
                "resource_space": {"workspace_policy": "managed_writing_files"},
                "memory_space": {"retrieval_index_refs": ["conversation_index"]},
                "sandbox_policy": {},
            },
            operation_authorization={
                "allowed_operations": ["op.mcp_pdf"],
                "decisions": [
                    {
                        "operation_id": "op.mcp_pdf",
                        "final_decision": "allow",
                        "reason": "agent_allowed",
                    }
                ],
            },
        ),
        invocation_kind="task_execution",
        tool_definitions_by_name={},
    )
    filtered = {
        item["operation_id"]: item["reason"]
        for item in plan.capability_table.to_dict()["filtered"]
    }

    assert plan.capability_table.capability_for_operation("op.mcp_pdf") is None
    assert filtered["op.mcp_pdf"] == "environment_filtered"


def test_tool_invocation_request_agent_turn_does_not_require_task_run() -> None:
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:1",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="read_file",
        tool_call_id="call:read",
        operation_id="op.read_file",
    )

    assert request.task_run_id == ""
    assert request.to_dict()["caller_kind"] == "agent_turn"


def test_runtime_tool_control_plane_denies_tool_outside_plan_without_dispatch() -> None:
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"name": "read_file", "operation_id": "op.read_file"}]),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:missing",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="terminal",
        tool_call_id="call:shell",
        operation_id="op.shell",
        action_request_ref="action:shell",
        action_permit=_permit(
            action_request_ref="action:shell",
            invocation_kind="agent_turn",
            tool_name="terminal",
            operation_id="op.shell",
        ),
    )

    observation = asyncio.run(RuntimeToolControlPlane().invoke(request, tool_plan=plan))

    assert observation.status == "denied"
    assert observation.diagnostics["stage"] == "capability_membership"
    assert "operation not present" in observation.text


def test_runtime_tool_control_plane_denies_missing_action_permit_before_membership() -> None:
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"name": "read_file", "operation_id": "op.read_file"}]),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:no-permit",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        action_request_ref="action:read",
        tool_name="read_file",
        tool_call_id="call:read",
        operation_id="op.read_file",
    )

    observation = asyncio.run(RuntimeToolControlPlane().invoke(request, tool_plan=plan))

    assert observation.status == "denied"
    assert observation.diagnostics["stage"] == "action_permit"
    assert observation.text == "action_permit_missing"


def test_runtime_tool_control_plane_dispatches_task_run_through_gate_and_executor() -> None:
    gate = _AllowingGate()
    executor = _RecordingToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "read_file", "operation_id": "op.read_file"}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:task:read",
        caller_kind="task_run",
        caller_ref="taskrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        task_run_id="taskrun:one",
        agent_run_id="agrun:one",
        action_request_ref="action:read",
        packet_ref="packet:task:one",
        tool_name="read_file",
        tool_call_id="call:read",
        tool_args={"path": "README.md"},
        operation_id="op.read_file",
        action_permit=_permit(
            action_request_ref="action:read",
            invocation_kind="task_execution",
            tool_name="read_file",
            operation_id="op.read_file",
        ),
        requested_constraints={
            "runtime_host": SimpleNamespace(
                execution_store=None,
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)}
                ),
            )
        },
    )

    observation = asyncio.run(RuntimeToolControlPlane(tool_runtime_executor=executor, operation_gate=gate).invoke(request, tool_plan=plan))

    assert observation.status == "ok"
    assert observation.text == "ok"
    assert observation.result_envelope["tool_name"] == "read_file"
    assert observation.diagnostics["handler_id"] == "task_tool_runtime"
    assert gate.checked == [("op.read_file", "runtime-directive:taskrun:one:tool:action:read")]
    assert executor.preflight_calls == 1
    assert executor.run_calls == 1
    assert executor.last_run["task_run_id"] == "taskrun:one"
    assert executor.last_run["tool_invocation_context"].caller_kind == "task_run"


def test_runtime_tool_control_plane_allows_managed_artifact_write_without_sandbox_approval(tmp_path: Path) -> None:
    executor = _RecordingToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"name": "write_file", "operation_id": "op.write_file", "read_only": False}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:task:artifact-write",
        caller_kind="task_run",
        caller_ref="taskrun:artifact-write",
        session_id="session:one",
        turn_id="turn:one:1",
        task_run_id="taskrun:artifact-write",
        agent_run_id="agrun:artifact-write",
        action_request_ref="action:artifact-write",
        packet_ref="packet:task:artifact-write",
        tool_name="write_file",
        tool_call_id="call:write",
        tool_args={"path": "reports/summary.md", "content": "managed artifact"},
        operation_id="op.write_file",
        sandbox_scope={
            "enabled": False,
            "workspace_root": str(tmp_path / "project"),
        },
        file_scope={
            "enabled": True,
            "profile_id": "file_profile.managed_project_workspace",
            "repositories": {"write": "repo.managed_project.artifacts"},
            "managed_storage_root": str(tmp_path / "project" / ".managed-files"),
        },
        action_permit=_permit(
            action_request_ref="action:artifact-write",
            invocation_kind="task_execution",
            tool_name="write_file",
            operation_id="op.write_file",
            read_only=False,
        ),
        requested_constraints={
            "runtime_host": SimpleNamespace(
                execution_store=None,
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False)}
                ),
            )
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "ok"
    assert observation.operation_gate["decision"] == "allow"
    assert executor.run_calls == 1
    assert executor.last_run["file_management_policy"]["repositories"]["write"] == "repo.managed_project.artifacts"


def test_runtime_tool_control_plane_keeps_project_workspace_write_approval_without_sandbox(tmp_path: Path) -> None:
    executor = _RecordingToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"name": "write_file", "operation_id": "op.write_file", "read_only": False}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:task:project-write",
        caller_kind="task_run",
        caller_ref="taskrun:project-write",
        session_id="session:one",
        turn_id="turn:one:1",
        task_run_id="taskrun:project-write",
        agent_run_id="agrun:project-write",
        action_request_ref="action:project-write",
        packet_ref="packet:task:project-write",
        tool_name="write_file",
        tool_call_id="call:write",
        tool_args={"path": "src/app.py", "content": "print('changed')"},
        operation_id="op.write_file",
        sandbox_scope={
            "enabled": False,
            "workspace_root": str(tmp_path / "project"),
        },
        file_scope={
            "enabled": True,
            "profile_id": "file_profile.managed_project_workspace",
            "repositories": {"write": "repo.managed_project.project_workspace"},
            "managed_storage_root": str(tmp_path / "project" / ".managed-files"),
        },
        action_permit=_permit(
            action_request_ref="action:project-write",
            invocation_kind="task_execution",
            tool_name="write_file",
            operation_id="op.write_file",
            read_only=False,
        ),
        requested_constraints={
            "runtime_host": SimpleNamespace(
                execution_store=None,
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False)}
                ),
            )
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "needs_approval"
    assert observation.operation_gate["decision"] == "requires_approval"
    assert executor.run_calls == 0


def test_runtime_tool_control_plane_requires_and_accepts_task_run_approval_state() -> None:
    executor = _RecordingToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "browser_control", "operation_id": "op.browser_control"}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)},
    )
    base_request = dict(
        invocation_id="toolinvoke:task:browser-approval",
        caller_kind="task_run",
        caller_ref="taskrun:approval",
        session_id="session:approval",
        turn_id="turn:approval:1",
        task_run_id="taskrun:approval",
        agent_run_id="agrun:approval",
        action_request_ref="action:browser",
        packet_ref="packet:task:approval",
        tool_name="browser_control",
        tool_call_id="call:browser",
        tool_args={"action": "open", "url": "https://example.com"},
        operation_id="op.browser_control",
        action_permit=_permit(
            action_request_ref="action:browser",
            invocation_kind="task_execution",
            tool_name="browser_control",
            operation_id="op.browser_control",
            read_only=False,
        ),
        requested_constraints={
            "runtime_host": SimpleNamespace(
                execution_store=None,
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)}
                ),
            )
        },
    )

    approval = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(ToolInvocationRequest(**base_request), tool_plan=plan)
    )
    fingerprint = str(
        dict(dict(approval.diagnostics.get("supervision") or {}).get("decision") or {}).get("approval_fingerprint")
        or ""
    )
    directive_ref = "runtime-directive:taskrun:approval:tool:action:browser"

    assert approval.status == "needs_approval"
    assert fingerprint
    assert executor.run_calls == 0

    approved = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(
            ToolInvocationRequest(
                **{
                    **base_request,
                    "approval_state": {
                        "tokens": [
                            {
                                "token_id": "approval-token:test",
                                "operation_id": "op.browser_control",
                                "directive_ref": directive_ref,
                                "granted": True,
                                "source": "test",
                                "risk_fingerprint": fingerprint,
                            }
                        ]
                    },
                    "approval_risk_fingerprint": fingerprint,
                }
            ),
            tool_plan=plan,
        )
    )

    assert approved.status == "ok"
    assert approved.operation_gate["decision"] == "allow"
    assert executor.run_calls == 1


def test_runtime_tool_control_plane_rejects_mismatched_approval_token() -> None:
    executor = _RecordingToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "browser_control", "operation_id": "op.browser_control"}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:task:browser-bad-approval",
        caller_kind="task_run",
        caller_ref="taskrun:approval",
        session_id="session:approval",
        turn_id="turn:approval:1",
        task_run_id="taskrun:approval",
        agent_run_id="agrun:approval",
        action_request_ref="action:browser",
        packet_ref="packet:task:approval",
        tool_name="browser_control",
        tool_call_id="call:browser",
        tool_args={"action": "open", "url": "https://example.com"},
        operation_id="op.browser_control",
        action_permit=_permit(
            action_request_ref="action:browser",
            invocation_kind="task_execution",
            tool_name="browser_control",
            operation_id="op.browser_control",
            read_only=False,
        ),
        approval_token={
            "token_id": "approval-token:wrong",
            "operation_id": "op.browser_control",
            "directive_ref": "runtime-directive:taskrun:approval:tool:action:browser",
            "granted": True,
            "source": "test",
            "risk_fingerprint": "wrong-fingerprint",
        },
        approval_risk_fingerprint="expected-fingerprint",
        requested_constraints={
            "runtime_host": SimpleNamespace(
                execution_store=None,
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)}
                ),
            )
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "denied"
    assert observation.operation_gate["pipeline_stage"] == "approval_token"
    assert executor.run_calls == 0


def test_runtime_tool_control_plane_consumes_task_run_approval_after_executor_error() -> None:
    executor = _FailingToolExecutor()
    tool_args = {"action": "open", "url": "https://example.com"}
    action_request_ref = "action:browser-error"
    task_run_id = "taskrun:approval-error"
    directive_ref = f"runtime-directive:{task_run_id}:tool:{action_request_ref}"
    fingerprint = "risk:browser:error"
    pending = {
        "status": "approved",
        "task_run_id": task_run_id,
        "action_request_ref": action_request_ref,
        "approval_request_id": "approval-request:browser-error",
        "tool_call_id": "call:browser",
        "tool_name": "browser_control",
        "operation_id": "op.browser_control",
        "directive_ref": directive_ref,
        "approval_risk_fingerprint": fingerprint,
        "tool_args_hash": tool_args_hash(tool_args),
    }
    task_run = TaskRun(
        task_run_id=task_run_id,
        session_id="session:approval-error",
        task_id="task:approval-error",
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={"pending_approval": pending},
    )
    grant = build_task_tool_approval_grant(
        task_run=task_run,
        pending_approval=pending,
        requested_by="user",
    )
    assert grant is not None
    task_run = TaskRun(
        task_run_id=task_run.task_run_id,
        session_id=task_run.session_id,
        task_id=task_run.task_id,
        execution_runtime_kind=task_run.execution_runtime_kind,
        status=task_run.status,
        diagnostics={**append_task_tool_approval_grant(task_run, grant), "pending_approval": pending},
    )
    state_index = _TaskRunStateIndex(task_run)
    runtime_host = SimpleNamespace(
        execution_store=None,
        backend_dir=BACKEND_DIR,
        state_index=state_index,
        tool_authorization_index=SimpleNamespace(
            definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)}
        ),
    )
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "browser_control", "operation_id": "op.browser_control"}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:task:browser-error",
        caller_kind="task_run",
        caller_ref=task_run_id,
        session_id="session:approval-error",
        turn_id="turn:approval-error:1",
        task_run_id=task_run_id,
        agent_run_id="agrun:approval-error",
        action_request_ref=action_request_ref,
        packet_ref="packet:task:approval-error",
        tool_name="browser_control",
        tool_call_id="call:browser",
        tool_args=tool_args,
        operation_id="op.browser_control",
        action_permit=_permit(
            action_request_ref=action_request_ref,
            invocation_kind="task_execution",
            tool_name="browser_control",
            operation_id="op.browser_control",
            read_only=False,
        ),
        approval_state=approval_state_for_task_run(task_run).to_dict(),
        approval_risk_fingerprint=fingerprint,
        requested_constraints={"runtime_host": runtime_host},
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    updated = state_index.get_task_run(task_run_id)
    approval_state = dict(dict(updated.diagnostics or {}).get("approval_state") or {}) if updated is not None else {}
    grants = [dict(item) for item in list(approval_state.get("grants") or [])]

    assert observation.status == "error"
    assert executor.run_calls == 1
    assert approval_state["status"] == "consumed"
    assert grants and grants[0]["consumed"] is True
    assert dict(dict(updated.diagnostics or {}).get("pending_approval") or {}).get("status") == "consumed"


def test_runtime_tool_control_plane_fail_closes_agent_turn_when_control_plane_dispatch_is_missing() -> None:
    executor = _RecordingExecutorWithoutControlPlaneDispatch()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "read_file", "operation_id": "op.read_file"}]),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:read",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="read_file",
        tool_call_id="call:read",
        tool_args={"path": "README.md"},
        operation_id="op.read_file",
        action_request_ref="action:read",
        action_permit=_permit(
            action_request_ref="action:read",
            invocation_kind="agent_turn",
            tool_name="read_file",
            operation_id="op.read_file",
        ),
        requested_constraints={
            "runtime_host": SimpleNamespace(
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)}
                ),
            ),
            "backend_dir": str(BACKEND_DIR),
        },
    )

    observation = asyncio.run(RuntimeToolControlPlane(tool_runtime_executor=executor, operation_gate=_AllowingGate()).invoke(request, tool_plan=plan))

    assert observation.status == "error"
    assert observation.diagnostics["stage"] == "tool_runtime_executor_dispatch_unavailable"
    assert observation.diagnostics["handler_id"] == "agent_turn_core"
    assert observation.caller_kind == "agent_turn"
    assert executor.run_calls == 0


def test_runtime_tool_control_plane_dispatches_agent_turn_through_core_without_task_run() -> None:
    gate = _AllowingGate()
    executor = _RecordingCoreToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "read_file", "operation_id": "op.read_file"}]),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:read-core",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="read_file",
        tool_call_id="call:read",
        tool_args={"path": "README.md"},
        operation_id="op.read_file",
        action_request_ref="action:read",
        action_permit=_permit(
            action_request_ref="action:read",
            invocation_kind="agent_turn",
            tool_name="read_file",
            operation_id="op.read_file",
        ),
        requested_constraints={
            "runtime_host": SimpleNamespace(
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)}
                ),
            ),
            "backend_dir": str(BACKEND_DIR),
            "runtime_assembly": _assembly(available_tools=[{"tool_name": "read_file", "operation_id": "op.read_file"}]).to_dict(),
        },
    )

    observation = asyncio.run(RuntimeToolControlPlane(tool_runtime_executor=executor, operation_gate=gate).invoke(request, tool_plan=plan))

    assert observation.status == "ok"
    assert observation.text == "read ok"
    assert observation.diagnostics["stage"] == "tool_runtime_executor_dispatch"
    assert observation.diagnostics["handler_id"] == "agent_turn_core"
    assert gate.checked == [("op.read_file", "tool-permit:turnrun:one:call:read")]
    assert executor.run_calls == 0
    assert executor.core_calls == 1
    assert executor.last_core["caller_kind"] == "agent_turn"
    assert executor.last_core["session_id"] == "session:one"
    assert executor.last_core["turn_id"] == "turn:one:1"
    assert "task_run_id" not in executor.last_core


def test_runtime_tool_control_plane_routes_task_subagent_by_reserved_tool_name() -> None:
    task_run = TaskRun(
        task_run_id="taskrun:subagent-list",
        session_id="session:subagent",
        task_id="task:subagent",
        execution_runtime_kind="single_agent_task",
        status="running",
    )
    state_index = _SubagentStateIndex(task_run)
    runtime_host = SimpleNamespace(
        execution_store=None,
        backend_dir=BACKEND_DIR,
        operation_gate=_AllowingGate(),
        state_index=state_index,
        tool_authorization_index=SimpleNamespace(
            definitions_by_name={"list_subagents": SimpleNamespace(operation_id="op.subagent_list", is_read_only=True)}
        ),
    )
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "list_subagents", "operation_id": "op.subagent_list"}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"list_subagents": SimpleNamespace(operation_id="op.subagent_list", is_read_only=True)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:task-subagent-list",
        caller_kind="task_run",
        caller_ref=task_run.task_run_id,
        session_id=task_run.session_id,
        turn_id="turn:subagent",
        task_run_id=task_run.task_run_id,
        agent_run_id="",
        action_request_ref="action:list-subagents",
        packet_ref="packet:subagent",
        tool_name="list_subagents",
        tool_call_id="call:list-subagents",
        tool_args={},
        operation_id="list_subagents",
        tool_plan_ref=plan.plan_id,
        admission_ref="admission:list-subagents",
        action_permit=_permit(
            action_request_ref="action:list-subagents",
            invocation_kind="task_execution",
            tool_name="list_subagents",
            operation_id="op.subagent_list",
            read_only=True,
        ),
        requested_constraints={
            "runtime_host": runtime_host,
            "runtime_assembly": {},
            "backend_dir": str(BACKEND_DIR),
        },
    )

    observation = asyncio.run(RuntimeToolControlPlane(operation_gate=runtime_host.operation_gate).invoke(request, tool_plan=plan))
    envelope = dict(observation.result_envelope or {})
    structured = dict(envelope.get("structured_payload") or {})
    control = dict(structured.get("subagent_control") or {})

    assert observation.status == "ok"
    assert observation.operation_id == "op.subagent_list"
    assert observation.diagnostics["handler_id"] == "subagent_control"
    assert control["ok"] is True
    assert control["count"] == 0
    assert runtime_host.operation_gate.checked == [("op.subagent_list", "runtime-directive:taskrun:subagent-list:tool:action:list-subagents")]


def test_runtime_tool_control_plane_does_not_dispatch_agent_turn_subagent_to_core_executor() -> None:
    gate = _AllowingGate()
    executor = _RecordingCoreToolExecutor()
    runtime_host = SimpleNamespace(
        backend_dir=BACKEND_DIR,
        operation_gate=gate,
        tool_authorization_index=SimpleNamespace(
            definitions_by_name={"spawn_subagent": SimpleNamespace(operation_id="op.subagent_spawn", is_read_only=False)}
        ),
    )
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "spawn_subagent", "operation_id": "op.subagent_spawn"}]),
        invocation_kind="task_execution",
        tool_definitions_by_name={"spawn_subagent": SimpleNamespace(operation_id="op.subagent_spawn", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn-subagent-spawn",
        caller_kind="agent_turn",
        caller_ref="turnrun:subagent",
        session_id="session:subagent",
        turn_id="turn:subagent",
        action_request_ref="action:spawn-subagent",
        packet_ref="packet:subagent",
        tool_name="spawn_subagent",
        tool_call_id="call:spawn-subagent",
        tool_args={"target_agent_id": "agent:verifier", "goal": "verify"},
        operation_id="op.subagent_spawn",
        tool_plan_ref=plan.plan_id,
        admission_ref="admission:spawn-subagent",
        action_permit=_permit(
            action_request_ref="action:spawn-subagent",
            invocation_kind="agent_turn",
            tool_name="spawn_subagent",
            operation_id="op.subagent_spawn",
            read_only=False,
        ),
        requested_constraints={"runtime_host": runtime_host, "runtime_assembly": {}, "backend_dir": str(BACKEND_DIR)},
    )

    observation = asyncio.run(RuntimeToolControlPlane(tool_runtime_executor=executor, operation_gate=gate).invoke(request, tool_plan=plan))

    assert observation.status == "error"
    assert observation.text == "caller tool dispatch handler is not valid for this caller"
    assert observation.diagnostics["handler_id"] == "subagent_control"
    assert executor.core_calls == 0


def test_subagent_lifecycle_placeholder_tool_fails_closed_when_invoked_directly() -> None:
    tool = SpawnSubagentTool(root_dir=BACKEND_DIR)

    try:
        tool._run(target_agent_id="agent:verifier", goal="verify")
    except RuntimeError as exc:
        assert str(exc) == "subagent_lifecycle_requires_task_runtime"
    else:
        raise AssertionError("subagent lifecycle placeholder tool must not return a success-looking result")


def test_runtime_tool_control_plane_agent_turn_side_effect_runs_without_default_approval_gate() -> None:
    executor = _RecordingCoreToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "image_generate", "operation_id": "op.image_generate"}]),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"image_generate": SimpleNamespace(operation_id="op.image_generate", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:image-direct",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="image_generate",
        tool_call_id="call:image",
        tool_args={"prompt": "pixel tower"},
        operation_id="op.image_generate",
        action_request_ref="action:image",
        action_permit=_permit(
            action_request_ref="action:image",
            invocation_kind="agent_turn",
            tool_name="image_generate",
            operation_id="op.image_generate",
            read_only=False,
        ),
        sandbox_scope={"enabled": False},
        requested_constraints={
            "runtime_host": SimpleNamespace(
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"image_generate": SimpleNamespace(operation_id="op.image_generate", is_read_only=False)}
                ),
            ),
            "backend_dir": str(BACKEND_DIR),
            "runtime_assembly": _assembly(available_tools=[{"tool_name": "image_generate", "operation_id": "op.image_generate"}]).to_dict(),
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "ok"
    assert observation.diagnostics["stage"] == "tool_runtime_executor_dispatch"
    assert observation.operation_gate["decision"] == "allow"
    assert observation.operation_gate["reason"] == "operation allowed by adopted resource policy"
    assert executor.core_calls == 1
    assert executor.last_core["tool_name"] == "image_generate"


def test_runtime_tool_control_plane_agent_turn_explicit_approval_policy_requires_task_run() -> None:
    executor = _RecordingCoreToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(available_tools=[{"tool_name": "image_generate", "operation_id": "op.image_generate"}]),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"image_generate": SimpleNamespace(operation_id="op.image_generate", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:image-human-approval",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="image_generate",
        tool_call_id="call:image",
        tool_args={"prompt": "pixel tower"},
        operation_id="op.image_generate",
        action_request_ref="action:image",
        action_permit=_permit(
            action_request_ref="action:image",
            invocation_kind="agent_turn",
            tool_name="image_generate",
            operation_id="op.image_generate",
            read_only=False,
        ),
        sandbox_scope={"enabled": False, "approval_policy": "manual_approval_required"},
        requested_constraints={
            "runtime_host": SimpleNamespace(
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"image_generate": SimpleNamespace(operation_id="op.image_generate", is_read_only=False)}
                ),
            ),
            "backend_dir": str(BACKEND_DIR),
            "runtime_assembly": _assembly(available_tools=[{"tool_name": "image_generate", "operation_id": "op.image_generate"}]).to_dict(),
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "denied"
    assert observation.operation_gate["decision"] == "deny"
    assert observation.operation_gate["pipeline_stage"] == "deny_rule"
    assert "resumable task approval flow" in observation.text
    assert executor.core_calls == 0


def test_runtime_tool_control_plane_agent_turn_side_effect_sandbox_metadata_does_not_create_approval_gate() -> None:
    executor = _RecordingCoreToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[{"tool_name": "image_generate", "operation_id": "op.image_generate"}],
            task_environment=_sandbox_task_environment("op.image_generate"),
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"image_generate": SimpleNamespace(operation_id="op.image_generate", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:image-sandbox",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="image_generate",
        tool_call_id="call:image",
        tool_args={"prompt": "pixel tower"},
        operation_id="op.image_generate",
        action_request_ref="action:image",
        action_permit=_permit(
            action_request_ref="action:image",
            invocation_kind="agent_turn",
            tool_name="image_generate",
            operation_id="op.image_generate",
            read_only=False,
        ),
        sandbox_scope={
            "enabled": True,
            "side_effect_policy": "sandbox_boundary",
            "side_effect_operations": ["op.image_generate"],
        },
        requested_constraints={
            "runtime_host": SimpleNamespace(
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"image_generate": SimpleNamespace(operation_id="op.image_generate", is_read_only=False)}
                ),
            ),
            "backend_dir": str(BACKEND_DIR),
            "runtime_assembly": _assembly(
                available_tools=[{"tool_name": "image_generate", "operation_id": "op.image_generate"}],
                task_environment=_sandbox_task_environment("op.image_generate"),
            ).to_dict(),
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "ok"
    assert observation.diagnostics["stage"] == "tool_runtime_executor_dispatch"
    assert observation.operation_gate["decision"] == "allow"
    assert observation.operation_gate["reason"] == "operation allowed by adopted resource policy"
    assert executor.core_calls == 1
    assert executor.last_core["tool_name"] == "image_generate"


def test_runtime_tool_control_plane_agent_turn_native_side_effect_runs_inside_concrete_sandbox_boundary(tmp_path: Path) -> None:
    executor = _RecordingCoreToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[{"tool_name": "write_file", "operation_id": "op.write_file"}],
            task_environment=_sandbox_task_environment("op.write_file"),
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:write-sandbox",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="write_file",
        tool_call_id="call:write",
        tool_args={"path": "artifacts/note.txt", "content": "hello"},
        operation_id="op.write_file",
        action_request_ref="action:write",
        action_permit=_permit(
            action_request_ref="action:write",
            invocation_kind="agent_turn",
            tool_name="write_file",
            operation_id="op.write_file",
            read_only=False,
        ),
        sandbox_scope={
            "enabled": True,
            "sandbox_root": str(tmp_path / "sandbox"),
            "side_effect_policy": "sandbox_boundary",
            "side_effect_operations": ["op.write_file"],
            "write_scopes": ["artifacts"],
        },
        requested_constraints={
            "runtime_host": SimpleNamespace(
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"write_file": SimpleNamespace(operation_id="op.write_file", is_read_only=False)}
                ),
            ),
            "backend_dir": str(BACKEND_DIR),
            "runtime_assembly": _assembly(
                available_tools=[{"tool_name": "write_file", "operation_id": "op.write_file"}],
                task_environment=_sandbox_task_environment("op.write_file"),
            ).to_dict(),
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "ok"
    assert observation.diagnostics["stage"] == "tool_runtime_executor_dispatch"
    assert observation.operation_gate["decision"] == "allow"
    assert executor.core_calls == 1
    assert executor.last_core["tool_name"] == "write_file"


def test_runtime_tool_control_plane_agent_turn_browser_side_effect_runs_inside_sandbox_boundary(tmp_path: Path) -> None:
    executor = _RecordingCoreToolExecutor()
    plan = build_runtime_tool_plan(
        runtime_assembly=_assembly(
            available_tools=[{"tool_name": "browser_control", "operation_id": "op.browser_control"}],
            task_environment=_sandbox_task_environment("op.browser_control"),
        ),
        invocation_kind="single_agent_turn",
        tool_definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)},
    )
    request = ToolInvocationRequest(
        invocation_id="toolinvoke:turn:browser-sandbox",
        caller_kind="agent_turn",
        caller_ref="turnrun:one",
        session_id="session:one",
        turn_id="turn:one:1",
        tool_name="browser_control",
        tool_call_id="call:browser",
        tool_args={"action": "open", "url": "https://example.com"},
        operation_id="op.browser_control",
        action_request_ref="action:browser",
        action_permit=_permit(
            action_request_ref="action:browser",
            invocation_kind="agent_turn",
            tool_name="browser_control",
            operation_id="op.browser_control",
            read_only=False,
        ),
        sandbox_scope={
            "enabled": True,
            "sandbox_root": str(tmp_path / "sandbox"),
            "side_effect_policy": "sandbox_boundary",
            "side_effect_operations": ["op.browser_control"],
        },
        requested_constraints={
            "runtime_host": SimpleNamespace(
                backend_dir=BACKEND_DIR,
                tool_authorization_index=SimpleNamespace(
                    definitions_by_name={"browser_control": SimpleNamespace(operation_id="op.browser_control", is_read_only=False)}
                ),
            ),
            "backend_dir": str(BACKEND_DIR),
            "runtime_assembly": _assembly(
                available_tools=[{"tool_name": "browser_control", "operation_id": "op.browser_control"}],
                task_environment=_sandbox_task_environment("op.browser_control"),
            ).to_dict(),
        },
    )

    observation = asyncio.run(
        RuntimeToolControlPlane(
            tool_runtime_executor=executor,
            operation_gate=OperationGate(build_default_operation_registry()),
        ).invoke(request, tool_plan=plan)
    )

    assert observation.status == "ok"
    assert observation.diagnostics["stage"] == "tool_runtime_executor_dispatch"
    assert observation.operation_gate["decision"] == "allow"
    assert executor.core_calls == 1
    assert executor.last_core["tool_name"] == "browser_control"


class _assembly:
    def __init__(
        self,
        *,
        available_tools: list[dict[str, object]],
        task_environment: dict[str, object] | None = None,
        operation_authorization: dict[str, object] | None = None,
    ) -> None:
        self.available_tools = list(available_tools)
        self.task_environment = dict(task_environment or {"environment_id": "env.general.workspace"})
        self.operation_authorization = dict(operation_authorization or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": "session:one",
            "turn_id": "turn:one:1",
            "agent_invocation_id": "aginvoke:one",
            "available_tools": list(self.available_tools),
            "task_environment": dict(self.task_environment),
            "operation_authorization": dict(self.operation_authorization),
        }


def _permit(
    *,
    action_request_ref: str,
    invocation_kind: str,
    tool_name: str,
    operation_id: str,
    read_only: bool = True,
) -> dict[str, object]:
    return {
        "permit_id": f"action-permit:{action_request_ref}",
        "action_request_ref": action_request_ref,
        "action_type": "tool_call",
        "decision": "allow",
        "invocation_kind": invocation_kind,
        "tool_name": tool_name,
        "operation_id": operation_id,
        "read_only": read_only,
        "permission_mode": "default",
        "side_effect_policy": "runtime_authorized",
        "allowed_action_types": ["respond", "ask_user", "tool_call", "block"],
        "allowed_tool_names": [tool_name],
        "authority": "harness.loop.action_permit",
        "diagnostics": {"test_permit": True},
    }


def _sandbox_task_environment(*side_effect_operations: str) -> dict[str, object]:
    return {
        "environment_id": "env.coding.vibe_workspace",
        "environment_kind": "development",
        "sandbox_policy": {
            "enabled": True,
            "sandbox_mode": "workspace_overlay",
            "write_policy": "sandbox_or_task_granted",
            "shell_policy": "sandboxed",
            "browser_policy": "sandboxed",
            "network_policy": "task_decided",
            "side_effect_policy": "sandbox_boundary",
            "side_effect_operations": list(side_effect_operations),
        },
        "execution_policy": {
            "write_scope_policy": "sandbox_or_file_access_table",
            "shell_execution_policy": "sandboxed",
            "browser_execution_policy": "sandboxed",
            "network_execution_policy": "task_decided",
        },
        "file_management": {
            "canonical_write_policy": "sandbox_write_real_workspace_requires_task_grant",
            "constraints": {
                "project_workspace_read": "allowed",
                "project_workspace_write": "task_granted",
            },
        },
        "resource_space": {"workspace_policy": "project_workspace"},
    }


class _AllowingGate:
    def __init__(self) -> None:
        self.checked: list[tuple[str, str]] = []

    def check(self, operation_id: str, *, resource_policy, directive_ref: str = "", context=None):
        self.checked.append((operation_id, directive_ref))
        return SimpleNamespace(
            operation_id=operation_id,
            decision="allow",
            reason="test gate allowed",
            allowed=True,
            requires_approval=False,
            pipeline_stage="test_gate",
            diagnostics={},
            to_dict=lambda: {
                "operation_id": operation_id,
                "decision": "allow",
                "reason": "test gate allowed",
                "allowed": True,
                "requires_approval": False,
                "pipeline_stage": "test_gate",
                "diagnostics": {},
            },
        )


class _RecordingExecutorWithoutControlPlaneDispatch:
    def __init__(self) -> None:
        self.run_calls = 0


class _RecordingToolExecutor:
    def __init__(self) -> None:
        self.preflight_calls = 0
        self.run_calls = 0
        self.last_run: dict[str, object] = {}

    def preflight_validate(self, **kwargs):
        self.preflight_calls += 1
        action_request = kwargs["action_request"]
        tool_call = dict(dict(action_request.payload).get("tool_call") or {})
        return {
            "allowed": True,
            "normalized_args": dict(tool_call.get("args") or {}),
        }

    async def run(self, **kwargs):
        self.run_calls += 1
        self.last_run = dict(kwargs)
        action_request = kwargs["action_request"]
        tool_call = dict(dict(action_request.payload).get("tool_call") or {})
        return {
            "observation": {
                "payload": {
                    "result": "ok",
                    "result_envelope": {
                        "tool_name": "read_file",
                        "tool_args": dict(tool_call.get("args") or {}),
                        "status": "ok",
                        "text": "ok",
                        "structured_payload": {},
                        "artifact_refs": [],
                    },
                    "execution_receipt": {},
                }
            },
            "error": "",
        }

    async def execute_control_plane_request(self, **kwargs):
        request = kwargs["request"]
        if str(getattr(request, "caller_kind", "") or "") != "task_run":
            return {
                "status": "error",
                "text": "test_executor_only_supports_task_run",
                "error": "test_executor_only_supports_task_run",
            }
        return await self.run(
            task_run_id=str(getattr(request, "task_run_id", "") or ""),
            action_request=kwargs["runtime_action"],
            directive=kwargs["directive"],
            execution_record=kwargs.get("execution_record"),
            execution_store=kwargs.get("execution_store"),
            sandbox_policy=kwargs.get("sandbox_policy"),
            file_management_policy=kwargs.get("file_management_policy"),
            tool_invocation_context=_invocation_context_from_request(request),
        )


class _FailingToolExecutor(_RecordingToolExecutor):
    async def execute_control_plane_request(self, **kwargs):
        self.run_calls += 1
        self.last_run = dict(kwargs)
        return {
            "observation": {
                "payload": {
                    "error": "executor failed after approval",
                    "result_envelope": {
                        "tool_name": str(getattr(kwargs["request"], "tool_name", "") or ""),
                        "tool_args": dict(getattr(kwargs["request"], "tool_args", {}) or {}),
                        "status": "error",
                        "text": "executor failed after approval",
                        "structured_payload": {},
                        "artifact_refs": [],
                    },
                    "execution_receipt": {},
                }
            },
            "error": "executor failed after approval",
        }


class _RecordingCoreToolExecutor(_RecordingToolExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.core_calls = 0
        self.last_core: dict[str, object] = {}

    async def _record_agent_turn_dispatch(self, **kwargs):
        self.core_calls += 1
        self.last_core = dict(kwargs)
        return {
            "status": "ok",
            "text": "read ok",
            "result_ref": "tool-result:read",
            "result_envelope": {
                "tool_name": "read_file",
                "tool_args": dict(kwargs.get("tool_args") or {}),
                "status": "ok",
                "text": "read ok",
                "structured_payload": {},
                "artifact_refs": [],
                "result_ref": "tool-result:read",
            },
            "artifact_refs": [],
            "error": "",
        }

    async def execute_control_plane_request(self, **kwargs):
        request = kwargs["request"]
        if str(getattr(request, "caller_kind", "") or "") == "task_run":
            return await self.run(
                task_run_id=str(getattr(request, "task_run_id", "") or ""),
                action_request=kwargs["runtime_action"],
                directive=kwargs["directive"],
                execution_record=kwargs.get("execution_record"),
                execution_store=kwargs.get("execution_store"),
                sandbox_policy=kwargs.get("sandbox_policy"),
                file_management_policy=kwargs.get("file_management_policy"),
                tool_invocation_context=_invocation_context_from_request(request),
            )
        return await self._record_agent_turn_dispatch(
            caller_kind=str(getattr(request, "caller_kind", "") or ""),
            caller_ref=str(getattr(request, "caller_ref", "") or ""),
            session_id=str(getattr(request, "session_id", "") or ""),
            turn_id=str(getattr(request, "turn_id", "") or ""),
            tool_invocation_id=str(getattr(request, "invocation_id", "") or ""),
            tool_name=str(getattr(request, "tool_name", "") or ""),
            tool_call_id=str(getattr(request, "tool_call_id", "") or ""),
            tool_args=dict(kwargs.get("normalized_args") or getattr(request, "tool_args", {}) or {}),
            operation_id=str(getattr(request, "operation_id", "") or ""),
            sandbox_policy=kwargs.get("sandbox_policy"),
            file_management_policy=kwargs.get("file_management_policy"),
        )


def _invocation_context_from_request(request) -> ToolInvocationContext:
    return ToolInvocationContext(
        tool_invocation_id=str(getattr(request, "invocation_id", "") or ""),
        caller_kind=str(getattr(request, "caller_kind", "") or ""),
        caller_ref=str(getattr(request, "caller_ref", "") or ""),
        session_id=str(getattr(request, "session_id", "") or ""),
        turn_id=str(getattr(request, "turn_id", "") or ""),
        task_run_id=str(getattr(request, "task_run_id", "") or ""),
        tool_call_id=str(getattr(request, "tool_call_id", "") or ""),
        idempotency_key="test-idempotency-key",
    )


class _TaskRunStateIndex:
    def __init__(self, task_run: TaskRun) -> None:
        self.task_run = task_run

    def get_task_run(self, task_run_id: str) -> TaskRun | None:
        return self.task_run if self.task_run.task_run_id == task_run_id else None

    def upsert_task_run(self, task_run: TaskRun) -> None:
        self.task_run = task_run


class _SubagentStateIndex(_TaskRunStateIndex):
    def __init__(self, task_run: TaskRun) -> None:
        super().__init__(task_run)
        self.agent_runs: list[object] = []

    def list_task_agent_runs(self, task_run_id: str) -> list[object]:
        return [item for item in self.agent_runs if str(getattr(item, "task_run_id", "") or "") == task_run_id]

    def upsert_agent_run(self, agent_run: object) -> None:
        agent_run_id = str(getattr(agent_run, "agent_run_id", "") or "")
        self.agent_runs = [
            item for item in self.agent_runs if str(getattr(item, "agent_run_id", "") or "") != agent_run_id
        ]
        self.agent_runs.append(agent_run)

    def read_snapshot(self) -> dict[str, object]:
        return {
            "agent_runs": {
                str(getattr(item, "agent_run_id", "") or ""): item.to_dict() if hasattr(item, "to_dict") else {}
                for item in self.agent_runs
            }
        }
