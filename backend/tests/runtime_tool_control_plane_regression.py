from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime import build_runtime_tool_plan
from runtime.tool_runtime import RuntimeToolControlPlane, ToolInvocationRequest


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


def test_runtime_tool_plan_single_turn_filters_side_effect_tools_from_dispatch() -> None:
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

    assert [tool["name"] for tool in plan.model_visible_tools] == ["read_file"]
    assert plan.dispatchable_tool_names == ("read_file",)


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
                "environment_id": "env.development.sandbox",
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
                "environment_id": "env.development.sandbox",
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
                "environment_id": "env.creation.writing",
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
    )

    observation = asyncio.run(RuntimeToolControlPlane().invoke(request, tool_plan=plan))

    assert observation.status == "denied"
    assert observation.diagnostics["stage"] == "capability_membership"
    assert "operation not present" in observation.text


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
    assert gate.checked == [("op.read_file", "runtime-directive:taskrun:one:tool:action:read")]
    assert executor.preflight_calls == 1
    assert executor.run_calls == 1
    assert executor.last_run["task_run_id"] == "taskrun:one"
    assert executor.last_run["tool_invocation_context"].caller_kind == "task_run"


def test_runtime_tool_control_plane_fail_closes_agent_turn_when_core_dispatch_is_missing() -> None:
    executor = _RecordingToolExecutor()
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
    assert observation.diagnostics["stage"] == "tool_runtime_executor_core_unavailable"
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
    assert observation.diagnostics["stage"] == "tool_runtime_executor_core"
    assert gate.checked == [("op.read_file", "tool-permit:turnrun:one:call:read")]
    assert executor.run_calls == 0
    assert executor.core_calls == 1
    assert executor.last_core["caller_kind"] == "agent_turn"
    assert executor.last_core["session_id"] == "session:one"
    assert executor.last_core["turn_id"] == "turn:one:1"
    assert "task_run_id" not in executor.last_core


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


class _RecordingCoreToolExecutor(_RecordingToolExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.core_calls = 0
        self.last_core: dict[str, object] = {}

    async def run_core(self, **kwargs):
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
