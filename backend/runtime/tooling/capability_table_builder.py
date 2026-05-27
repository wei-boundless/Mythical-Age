from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from capability_system.operation_registry import OperationRegistry, build_default_operation_registry
from capability_system.tool_definitions import ToolDefinition, get_tool_definitions
from file_management import FileAccessTable
from task_system.environments import TaskEnvironmentSpec
from task_system.tasks import SpecificTaskAssemblyPolicy

from .capability_table import (
    ToolCapability,
    ToolCapabilityFilterIssue,
    ToolCapabilitySourceTrace,
    ToolCapabilityTable,
)


FILE_OPERATION_ACTIONS = {
    "op.read_file": ("read",),
    "op.read_structured_file": ("read",),
    "op.search_files": ("search",),
    "op.search_text": ("search",),
    "op.list_dir": ("read",),
    "op.stat_path": ("read",),
    "op.path_exists": ("read",),
    "op.glob_paths": ("search",),
    "op.write_file": ("write",),
    "op.edit_file": ("edit",),
}


@dataclass(frozen=True, slots=True)
class ToolCapabilityBuildRequest:
    environment: TaskEnvironmentSpec
    file_access_tables: tuple[FileAccessTable, ...] = ()
    task_required_operations: tuple[str, ...] = ()
    task_optional_operations: tuple[str, ...] = ()
    task_denied_operations: tuple[str, ...] = ()
    agent_profile_allowed_operations: tuple[str, ...] = ()
    runtime_available_operations: tuple[str, ...] = ()
    table_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_assembly_policy(
        cls,
        *,
        environment: TaskEnvironmentSpec,
        assembly_policy: SpecificTaskAssemblyPolicy,
        file_access_tables: tuple[FileAccessTable, ...] = (),
        agent_profile_allowed_operations: tuple[str, ...] = (),
        runtime_available_operations: tuple[str, ...] = (),
        table_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "ToolCapabilityBuildRequest":
        requirements = assembly_policy.tool_capability_requirements
        return cls(
            environment=environment,
            file_access_tables=file_access_tables,
            task_required_operations=tuple(requirements.required_operations),
            task_optional_operations=tuple(requirements.optional_operations),
            task_denied_operations=tuple(requirements.denied_operations),
            agent_profile_allowed_operations=agent_profile_allowed_operations,
            runtime_available_operations=runtime_available_operations,
            table_id=table_id or f"tool-capability:{assembly_policy.policy_id}",
            metadata={
                "specific_task_assembly_policy_ref": assembly_policy.policy_id,
                "specific_task_ref": assembly_policy.task_id,
                "authority": assembly_policy.authority,
                **dict(metadata or {}),
            },
        )


def build_tool_capability_table(
    request: ToolCapabilityBuildRequest,
    *,
    tool_definitions: tuple[ToolDefinition, ...] | list[ToolDefinition] | None = None,
    operation_registry: OperationRegistry | None = None,
) -> ToolCapabilityTable:
    registry = operation_registry or build_default_operation_registry()
    tools = list(tool_definitions or get_tool_definitions())
    by_operation = {registry.normalize_id(tool.operation_id): tool for tool in tools}

    env_allowed = {registry.normalize_id(item) for item in request.environment.tool_space.allowed_operation_market}
    env_denied = {registry.normalize_id(item) for item in request.environment.tool_space.denied_operation_refs}
    task_required = {registry.normalize_id(item) for item in request.task_required_operations}
    task_optional = {registry.normalize_id(item) for item in request.task_optional_operations}
    task_denied = {registry.normalize_id(item) for item in request.task_denied_operations}
    agent_allowed = {registry.normalize_id(item) for item in request.agent_profile_allowed_operations}
    runtime_available = {registry.normalize_id(item) for item in request.runtime_available_operations}

    dispatch_requested = task_required | task_optional
    if not dispatch_requested:
        dispatch_requested = env_allowed
    audit_requested = dispatch_requested | task_denied | agent_allowed | runtime_available

    capabilities: list[ToolCapability] = []
    filtered: list[ToolCapabilityFilterIssue] = []

    for operation_id in sorted(audit_requested):
        tool = by_operation.get(operation_id)
        tool_name = tool.name if tool is not None else ""
        if operation_id in env_denied:
            filtered.append(_issue(operation_id, tool_name, "filtered by task environment deny list", "task_environment"))
            continue
        if env_allowed and operation_id not in env_allowed:
            filtered.append(_issue(operation_id, tool_name, "not in task environment tool market", "task_environment"))
            continue
        if operation_id in task_denied:
            filtered.append(_issue(operation_id, tool_name, "filtered by specific task deny list", "specific_task"))
            continue
        if agent_allowed and operation_id not in agent_allowed:
            filtered.append(_issue(operation_id, tool_name, "filtered by agent profile ceiling", "agent_profile"))
            continue
        if runtime_available and operation_id not in runtime_available:
            filtered.append(_issue(operation_id, tool_name, "runtime operation unavailable", "runtime_availability"))
            continue
        if tool is None:
            filtered.append(_issue(operation_id, "", "no registered tool for operation", "tool_registry"))
            continue
        if operation_id not in dispatch_requested:
            continue

        file_gate = _file_gate(operation_id, request.file_access_tables)
        if file_gate["denied"]:
            filtered.append(
                _issue(
                    operation_id,
                    tool.name,
                    str(file_gate["reason"]),
                    "file_access_table",
                    metadata={"actions": list(file_gate["actions"])},
                )
            )
            continue

        capabilities.append(
            ToolCapability(
                operation_id=operation_id,
                tool_name=tool.name,
                visible=tool.prompt_exposure_policy != "hidden" or operation_id in task_required or operation_id in task_optional,
                dispatchable=True,
                requires_approval=bool(file_gate["requires_approval"]),
                file_repository_grants=tuple(file_gate["repository_grants"]),
                source_trace=(
                    ToolCapabilitySourceTrace(source="tool_registry", detail=tool.name),
                    ToolCapabilitySourceTrace(source="task_environment", detail=request.environment.environment_id),
                    ToolCapabilitySourceTrace(source="file_access_table", detail=",".join(file_gate["repository_grants"])),
                ),
                metadata={
                    "display_name": tool.display_name,
                    "read_only": tool.is_read_only,
                    "destructive": tool.is_destructive,
                    "capability_tags": list(tool.capability_tags),
                },
            )
        )

    return ToolCapabilityTable(
        table_id=request.table_id or f"tool-capability:{request.environment.environment_id}",
        environment_id=request.environment.environment_id,
        capabilities=tuple(capabilities),
        filtered=tuple(filtered),
        source_trace=(
            ToolCapabilitySourceTrace(source="task_environment", detail=request.environment.environment_id),
            ToolCapabilitySourceTrace(source="specific_task", detail="tool requirements"),
            ToolCapabilitySourceTrace(source="agent_profile", detail="operation ceiling"),
            ToolCapabilitySourceTrace(source="file_access_table", detail="file grants"),
            ToolCapabilitySourceTrace(
                source="specific_task_assembly_policy",
                detail=str(request.metadata.get("specific_task_assembly_policy_ref") or ""),
                metadata=dict(request.metadata),
            ),
        ),
    )


def _file_gate(operation_id: str, file_access_tables: tuple[FileAccessTable, ...]) -> dict[str, Any]:
    actions = FILE_OPERATION_ACTIONS.get(operation_id, ())
    if not actions:
        return {"denied": False, "requires_approval": False, "repository_grants": (), "actions": ()}
    if not file_access_tables:
        return {
            "denied": True,
            "requires_approval": False,
            "repository_grants": (),
            "actions": actions,
            "reason": "file operation has no FileAccessTable",
        }
    repository_grants: list[str] = []
    requires_approval = False
    for table in file_access_tables:
        for grant in table.grants:
            if grant.action not in actions:
                continue
            repository_grants.append(f"{grant.repository_id}:{grant.action}")
            requires_approval = requires_approval or grant.requires_approval
    if not repository_grants:
        return {
            "denied": True,
            "requires_approval": False,
            "repository_grants": (),
            "actions": actions,
            "reason": "no file repository grant for operation",
        }
    return {
        "denied": False,
        "requires_approval": requires_approval,
        "repository_grants": tuple(dict.fromkeys(repository_grants)),
        "actions": actions,
        "reason": "",
    }


def _issue(
    operation_id: str,
    tool_name: str,
    reason: str,
    source: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ToolCapabilityFilterIssue:
    return ToolCapabilityFilterIssue(
        operation_id=operation_id,
        tool_name=tool_name,
        reason=reason,
        source=source,
        metadata=dict(metadata or {}),
    )


