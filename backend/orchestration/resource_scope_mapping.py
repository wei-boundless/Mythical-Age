from __future__ import annotations

from dataclasses import asdict, dataclass

from capability_system.local_mcp_registry import default_local_mcp_units
from capability_system.operation_registry import OperationRegistry


_BUILTIN_OPERATION_TO_TOOL = {
    "op.read_file": "read_file",
    "op.search_files": "search_files",
    "op.search_text": "search_text",
    "op.list_dir": "list_dir",
    "op.stat_path": "stat_path",
    "op.path_exists": "path_exists",
    "op.glob_paths": "glob_paths",
    "op.read_structured_file": "read_structured_file",
    "op.web_search": "web_search",
    "op.fetch_url": "fetch_url",
    "op.git_status": "git_status",
    "op.git_diff": "git_diff",
    "op.git_log": "git_log",
    "op.git_show": "git_show",
    "op.analyze_multimodal_file": "analyze_multimodal_file",
    "op.index_multimodal_file": "index_multimodal_file",
    "op.write_file": "write_file",
    "op.edit_file": "edit_file",
    "op.shell": "terminal",
    "op.python_repl": "python_repl",
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
        if descriptor.operation_type == "agent":
            agent_id = str(descriptor.metadata.get("agent_id") or "").strip()
            agent_ids.append(agent_id or descriptor.operation_id)
            continue
        tool_name = _BUILTIN_OPERATION_TO_TOOL.get(descriptor.operation_id)
        if tool_name:
            tool_names.append(tool_name)

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
