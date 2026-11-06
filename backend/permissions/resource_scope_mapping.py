from __future__ import annotations

from dataclasses import asdict, dataclass

from capability_system.mcp.local_registry import default_local_mcp_units
from permissions.operations import OperationRegistry


_BUILTIN_OPERATION_TO_TOOL = {
    "op.workspace_search": "workspace_search",
    "op.workspace_read": "workspace_read",
    "op.workspace_write": "workspace_edit",
    "op.workspace_edit": "workspace_edit",
    "op.code_structure_read": "code_structure",
    "op.web_search": "web",
    "op.fetch_url": "web",
    "op.git_read": "git",
    "op.git_write": "git",
    "op.git_remote": "git",
    "op.project_network_read": "project_network",
    "op.project_network_build": "project_network",
    "op.project_network_maintenance": "project_network",
    "op.project_network_semantic_submit": "project_network",
    "op.project_network_control": "project_network",
    "op.subagent_spawn": "subagent",
    "op.subagent_message": "subagent",
    "op.subagent_wait": "subagent",
    "op.subagent_list": "subagent",
    "op.subagent_close": "subagent",
    "op.office_document": "office_document",
    "op.shell": "local_execution",
    "op.agent_todo": "agent_state",
    "op.memory_read": "memory",
    "op.browser_control": "browser",
    "op.image_generate": "image",
}


@dataclass(frozen=True, slots=True)
class ResourceScopeMapping:
    operation_ids: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    mcp_routes: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    unmapped_operations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        payload = asdict(self)
        return {key: list(value) for key, value in payload.items()}


def map_operations_to_resource_scopes(
    operation_ids: tuple[str, ...] | list[str],
    registry: OperationRegistry,
) -> ResourceScopeMapping:
    normalized = _dedupe([registry.normalize_id(item) for item in operation_ids])
    local_mcp_routes = _local_mcp_routes_by_operation()
    tool_names: list[str] = []
    mcp_routes: list[str] = []
    agent_ids: list[str] = []
    unmapped: list[str] = []

    for operation_id in normalized:
        descriptor = registry.get_operation(operation_id)
        if descriptor is None:
            unmapped.append(operation_id)
            continue
        if descriptor.operation_type == "mcp":
            route = local_mcp_routes.get(descriptor.operation_id)
            if route:
                mcp_routes.append(route)
            else:
                mcp_routes.append(descriptor.operation_id)
            continue
        if descriptor.operation_type == "external_mcp":
            server_id = str(descriptor.metadata.get("server_id") or "").strip()
            mcp_routes.append(server_id or descriptor.provider.removeprefix("external_mcp:") or descriptor.operation_id)
            continue
        if descriptor.operation_type in {"agent", "agent_capability"}:
            tool_name = _BUILTIN_OPERATION_TO_TOOL.get(descriptor.operation_id)
            if tool_name:
                tool_names.append(tool_name)
                continue
            agent_id = str(descriptor.metadata.get("agent_id") or "").strip()
            agent_ids.append(agent_id or descriptor.operation_id)
            continue
        tool_name = _BUILTIN_OPERATION_TO_TOOL.get(descriptor.operation_id)
        if tool_name:
            tool_names.append(tool_name)
            continue
        metadata_tool_names = [
            str(item or "").strip()
            for item in list(descriptor.metadata.get("model_visible_tools") or ())
            if str(item or "").strip()
        ]
        if metadata_tool_names:
            tool_names.extend(metadata_tool_names)
            continue
        unmapped.append(descriptor.operation_id)

    return ResourceScopeMapping(
        operation_ids=tuple(normalized),
        tool_names=tuple(_dedupe(tool_names)),
        mcp_routes=tuple(_dedupe(mcp_routes)),
        agent_ids=tuple(_dedupe(agent_ids)),
        unmapped_operations=tuple(_dedupe(unmapped)),
    )


def _local_mcp_routes_by_operation() -> dict[str, str]:
    return {unit.operation_id: unit.route for unit in default_local_mcp_units()}


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


