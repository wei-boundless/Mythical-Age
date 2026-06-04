from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.validators import validate_filesystem_path, validate_shell_read_only
from permissions.operations import build_default_operation_registry
from permissions import OperationGate
from permissions.context_models import PermissionContext
from permissions.resource_policy import ResourcePolicy
from runtime.shared.action_request import build_tool_unavailable_observation
from runtime.tooling import ToolCapabilityBuildRequest, ToolSupervisor, build_tool_capability_table
from task_system.environments import resolve_task_environment


def test_tool_supervisor_denies_tool_outside_capability_table() -> None:
    resolved = resolve_task_environment("env.development.sandbox")
    table = build_tool_capability_table(
        ToolCapabilityBuildRequest(
            environment=resolved.spec,
            file_access_tables=resolved.file_access_tables,
            task_required_operations=("op.read_file",),
            agent_profile_allowed_operations=("op.read_file",),
        )
    )

    result = ToolSupervisor().supervise(
        task_run_id="taskrun:one",
        agent_run_id="agrun:one",
        tool_call_id="call:shell",
        operation_id="op.shell",
        tool_name="terminal",
        tool_args={"command": "echo hi"},
        directive=_Directive(),
        resource_policy=ResourcePolicy(
            policy_id="respol:one",
            task_id="task:one",
            allowed_operations=("op.shell",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        capability_table=table,
        permission_context=PermissionContext(
            context_id="permctx:one",
            task_run_id="taskrun:one",
            agent_run_id="agrun:one",
            environment_id="env.development.sandbox",
            tool_capability_table_id=table.table_id,
        ),
        operation_gate=OperationGate(build_default_operation_registry()),
    )

    assert result.decision.behavior == "deny"
    assert result.decision.reason == "operation not present in ToolCapabilityTable"
    assert result.receipt.operation_id == "op.shell"
    assert result.receipt.tool_name == "terminal"


def test_tool_supervisor_returns_ask_from_operation_gate_with_parameter_fingerprint() -> None:
    resolved = resolve_task_environment("env.development.sandbox")
    table = build_tool_capability_table(
        ToolCapabilityBuildRequest(
            environment=resolved.spec,
            file_access_tables=resolved.file_access_tables,
            task_required_operations=("op.shell",),
            agent_profile_allowed_operations=("op.shell",),
        )
    )

    result = ToolSupervisor().supervise(
        task_run_id="taskrun:two",
        agent_run_id="agrun:two",
        tool_call_id="call:shell",
        operation_id="op.shell",
        tool_name="terminal",
        tool_args={"command": "pytest backend/tests/tool_supervisor_regression.py -q"},
        directive=_Directive(),
        resource_policy=ResourcePolicy(
            policy_id="respol:two",
            task_id="task:two",
            requires_approval_operations=("op.shell",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        capability_table=table,
        permission_context=PermissionContext(
            context_id="permctx:two",
            task_run_id="taskrun:two",
            agent_run_id="agrun:two",
            environment_id="env.development.sandbox",
            tool_capability_table_id=table.table_id,
        ),
        operation_gate=OperationGate(build_default_operation_registry()),
        sandbox_policy={"enabled": True, "mode": "workspace_overlay"},
        file_management_policy={"enabled": True, "profile_id": "file_profile.managed_project_workspace"},
    )

    assert result.decision.behavior == "ask"
    assert result.decision.approval_fingerprint
    assert result.receipt.approval_fingerprint == result.decision.approval_fingerprint
    assert result.normalized_args["command"].startswith("pytest")


def test_tool_supervisor_stops_before_operation_gate_when_preflight_rejects_tool() -> None:
    gate = _NeverCalledOperationGate()

    result = ToolSupervisor().supervise(
        task_run_id="taskrun:preflight",
        agent_run_id="agrun:preflight",
        tool_call_id="call:missing",
        operation_id="op.missing_tool",
        tool_name="missing_tool",
        tool_args={},
        directive=_Directive(),
        resource_policy=ResourcePolicy(
            policy_id="respol:preflight",
            task_id="task:preflight",
            allowed_operations=("op.missing_tool",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        capability_table=None,
        permission_context=PermissionContext(
            context_id="permctx:preflight",
            task_run_id="taskrun:preflight",
            agent_run_id="agrun:preflight",
            environment_id="env.development.sandbox",
        ),
        operation_gate=gate,
        tool_runtime_executor=_PreflightRejectingExecutor(),
        action_request=SimpleNamespace(
            request_id="rtact:missing",
            payload={"tool_name": "missing_tool", "tool_call": {"id": "call:missing", "args": {}}},
        ),
    )

    assert result.decision.behavior == "repair"
    assert result.decision.reason == "tool_runtime_unavailable"
    assert result.preflight["allowed"] is False
    assert gate.called is False


def test_tool_supervisor_supplies_bound_workspace_root_to_filesystem_validator(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "backend" / "TOOLS_REGISTRY.json"
    inside.parent.mkdir()
    inside.write_text("{}", encoding="utf-8")

    result = ToolSupervisor().supervise(
        task_run_id="taskrun:workspace-path",
        agent_run_id="agrun:workspace-path",
        tool_call_id="call:read",
        operation_id="op.read_file",
        tool_name="read_file",
        tool_args={"path": str(inside)},
        directive=_Directive(),
        resource_policy=ResourcePolicy(
            policy_id="respol:workspace-path",
            task_id="task:workspace-path",
            allowed_operations=("op.read_file",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        capability_table=None,
        permission_context=PermissionContext(
            context_id="permctx:workspace-path",
            task_run_id="taskrun:workspace-path",
            agent_run_id="agrun:workspace-path",
            environment_id="env.development.sandbox",
        ),
        operation_gate=OperationGate(build_default_operation_registry()),
        sandbox_policy={"workspace_root": str(workspace)},
        safety_validators={"filesystem_path": validate_filesystem_path},
    )

    assert result.allowed is True
    assert result.gate_result.allowed is True


def test_tool_supervisor_rejects_filesystem_path_outside_bound_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("secret", encoding="utf-8")

    result = ToolSupervisor().supervise(
        task_run_id="taskrun:outside-path",
        agent_run_id="agrun:outside-path",
        tool_call_id="call:read-outside",
        operation_id="op.read_file",
        tool_name="read_file",
        tool_args={"path": str(outside)},
        directive=_Directive(),
        resource_policy=ResourcePolicy(
            policy_id="respol:outside-path",
            task_id="task:outside-path",
            allowed_operations=("op.read_file",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        capability_table=None,
        permission_context=PermissionContext(
            context_id="permctx:outside-path",
            task_run_id="taskrun:outside-path",
            agent_run_id="agrun:outside-path",
            environment_id="env.development.sandbox",
        ),
        operation_gate=OperationGate(build_default_operation_registry()),
        sandbox_policy={"workspace_root": str(workspace)},
        safety_validators={"filesystem_path": validate_filesystem_path},
    )

    assert result.allowed is False
    assert result.decision.reason == "filesystem path is outside workspace_root"
    assert result.gate_result.pipeline_stage == "operation_specific_safety_validator"


def test_tool_supervisor_supplies_normalized_command_to_shell_validator() -> None:
    result = ToolSupervisor().supervise(
        task_run_id="taskrun:shell-validator",
        agent_run_id="agrun:shell-validator",
        tool_call_id="call:shell-validator",
        operation_id="op.shell",
        tool_name="terminal",
        tool_args={"command": "rg TODO | cat"},
        directive=_Directive(),
        resource_policy=ResourcePolicy(
            policy_id="respol:shell-validator",
            task_id="task:shell-validator",
            allowed_operations=("op.shell",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        capability_table=None,
        permission_context=PermissionContext(
            context_id="permctx:shell-validator",
            task_run_id="taskrun:shell-validator",
            agent_run_id="agrun:shell-validator",
            environment_id="env.development.sandbox",
        ),
        operation_gate=OperationGate(build_default_operation_registry()),
        safety_validators={"shell_read_only": validate_shell_read_only},
    )

    assert result.allowed is False
    assert result.decision.reason == "shell command uses control operators"
    assert result.gate_result.pipeline_stage == "operation_specific_safety_validator"


def test_tool_supervisor_to_dict_serializes_preflight_runtime_observation() -> None:
    result = ToolSupervisor().supervise(
        task_run_id="taskrun:preflight-json",
        agent_run_id="agrun:preflight-json",
        tool_call_id="call:missing-json",
        operation_id="op.missing_tool",
        tool_name="missing_tool",
        tool_args={},
        directive=_Directive(),
        resource_policy=ResourcePolicy(
            policy_id="respol:preflight-json",
            task_id="task:preflight-json",
            allowed_operations=("op.missing_tool",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        capability_table=None,
        permission_context=PermissionContext(
            context_id="permctx:preflight-json",
            task_run_id="taskrun:preflight-json",
            agent_run_id="agrun:preflight-json",
            environment_id="env.development.sandbox",
        ),
        operation_gate=_NeverCalledOperationGate(),
        tool_runtime_executor=_PreflightRejectingObservationExecutor(),
        action_request=SimpleNamespace(
            request_id="rtact:missing-json",
            payload={"tool_name": "missing_tool", "tool_call": {"id": "call:missing-json", "args": {}}},
        ),
    )

    payload = result.to_dict()

    assert payload["preflight"]["observation"]["payload"]["repair_kind"] == "tool_not_available"
    json.dumps(payload, ensure_ascii=False)


class _Directive:
    directive_id = "directive:test"


class _PreflightRejectingExecutor:
    def preflight_validate(self, **_kwargs):
        return {"allowed": False, "error": "tool_runtime_unavailable", "observation": {"repair_kind": "tool_unavailable"}}


class _PreflightRejectingObservationExecutor:
    def preflight_validate(self, **_kwargs):
        return {
            "allowed": False,
            "error": "tool_not_available",
            "observation": build_tool_unavailable_observation(
                task_run_id="taskrun:preflight-json",
                request_ref="rtact:missing-json",
                directive_ref="directive:test",
                tool_name="missing_tool",
                error="tool_not_available: missing_tool",
                tool_call_id="call:missing-json",
                tool_args={},
                repair_kind="tool_not_available",
            ),
        }


class _NeverCalledOperationGate:
    called = False

    def check(self, *_args, **_kwargs):
        self.called = True
        raise AssertionError("operation_gate.check should not be called after preflight rejection")
