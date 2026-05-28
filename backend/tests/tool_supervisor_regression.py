from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system import build_default_operation_registry
from permissions import OperationGate
from permissions.context_models import PermissionContext
from permissions.resource_policy import ResourcePolicy
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
        file_management_policy={"enabled": True, "profile_id": "file_profile.vibe_coding_project"},
    )

    assert result.decision.behavior == "ask"
    assert result.decision.approval_fingerprint
    assert result.receipt.approval_fingerprint == result.decision.approval_fingerprint
    assert result.normalized_args["command"].startswith("pytest")


class _Directive:
    directive_id = "directive:test"


