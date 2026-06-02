from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from permissions.operations import build_default_operation_registry


_OPERATION_REGISTRY = build_default_operation_registry()

_CONTROL_OPERATIONS = {
    "op.model_response",
    "op.agent_todo",
    "op.subagent_spawn",
    "op.subagent_message",
    "op.subagent_wait",
    "op.subagent_list",
    "op.subagent_close",
}
_FILE_READ_OPERATIONS = {
    "op.read_file",
    "op.list_dir",
    "op.stat_path",
    "op.path_exists",
    "op.glob_paths",
    "op.read_structured_file",
}
_FILE_WRITE_OPERATIONS = {
    "op.write_file",
    "op.edit_file",
}
_LOCAL_SEARCH_OPERATIONS = {
    "op.search_files",
    "op.search_text",
    "op.glob_paths",
    "op.mcp_retrieval",
    "op.memory_read",
}
_TEXT_UTILITY_OPERATIONS = {
    "op.text_metric",
}
_CODE_INTELLIGENCE_OPERATIONS = {
    "op.codebase_search",
    "op.python_code_outline",
    "op.python_parse_check",
    "op.python_symbol_search",
}
_GIT_READ_OPERATIONS = {
    "op.git_status",
    "op.git_diff",
    "op.git_log",
    "op.git_show",
    "op.git_branch_list",
}
_GIT_WRITE_OPERATIONS = {
    "op.git_branch_create",
    "op.git_stage",
    "op.git_unstage",
    "op.git_commit",
    "op.git_restore",
    "op.git_push",
}
_LOCAL_EXECUTION_OPERATIONS = {
    "op.shell",
    "op.python_repl",
}
_BROWSER_OPERATIONS = {
    "op.browser_control",
}
_NETWORK_SEARCH_OPERATIONS = {
    "op.web_search",
    "op.fetch_url",
    "op.search_agent",
}
_DOCUMENT_ANALYSIS_OPERATIONS = {
    "op.mcp_pdf",
    "op.mcp_structured_data",
}
_CREATIVE_ASSET_OPERATIONS = {
    "op.image_generate",
}
_GENERAL_ALL_OPERATIONS = {operation.operation_id for operation in _OPERATION_REGISTRY.list_operations()}
_CREATION_WORKSPACE_OPERATIONS = (
    _CONTROL_OPERATIONS
    | _FILE_READ_OPERATIONS
    | _FILE_WRITE_OPERATIONS
    | _LOCAL_SEARCH_OPERATIONS
    | _NETWORK_SEARCH_OPERATIONS
    | _TEXT_UTILITY_OPERATIONS
)
_DEVELOPMENT_WORKSPACE_OPERATIONS = (
    _CREATION_WORKSPACE_OPERATIONS
    | _CODE_INTELLIGENCE_OPERATIONS
    | _GIT_READ_OPERATIONS
    | _GIT_WRITE_OPERATIONS
    | _LOCAL_EXECUTION_OPERATIONS
    | _BROWSER_OPERATIONS
    | _DOCUMENT_ANALYSIS_OPERATIONS
    | _CREATIVE_ASSET_OPERATIONS
)
_ENVIRONMENT_OPERATION_ALLOWLISTS: dict[str, set[str]] = {
    "env.creation.writing": set(_CREATION_WORKSPACE_OPERATIONS),
    "env.development.sandbox": set(_DEVELOPMENT_WORKSPACE_OPERATIONS),
    "env.general.workspace": set(_GENERAL_ALL_OPERATIONS),
}
_DEFAULT_ENVIRONMENT_ID = "env.general.workspace"
_UNKNOWN_ENVIRONMENT_OPERATIONS = {"op.model_response"}


@dataclass(frozen=True, slots=True)
class EnvironmentOperationDecision:
    operation_id: str
    channel: str
    allowed: bool
    reason: str
    constraint_channel: str = ""
    environment_constraint: str = ""
    task_requested: bool = False
    authority: str = "harness.runtime.tool_scheduling"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_environment_operation(
    operation_id: str,
    *,
    environment_payload: dict[str, Any],
    task_requested_operations: tuple[str, ...] | list[str] | set[str] = (),
) -> EnvironmentOperationDecision:
    operation = str(operation_id or "").strip()
    requested = operation in _operation_set(task_requested_operations)
    environment_id = _environment_id(environment_payload)
    channel = operation_channel(operation)
    if not operation:
        return _decision(operation, channel, False, "missing_operation_id", channel, environment_id, requested)
    allowed = operation in environment_allowed_operations(environment_id)
    return _decision(
        operation,
        channel,
        allowed,
        "environment_allowed" if allowed else "environment_filtered",
        channel,
        environment_id,
        requested,
    )


def environment_allowed_operations(environment_id: str | None) -> set[str]:
    resolved = str(environment_id or "").strip()
    if not resolved:
        resolved = _DEFAULT_ENVIRONMENT_ID
    if resolved not in _ENVIRONMENT_OPERATION_ALLOWLISTS:
        return set(_UNKNOWN_ENVIRONMENT_OPERATIONS)
    return set(_ENVIRONMENT_OPERATION_ALLOWLISTS[resolved])


def operation_channel(operation_id: str) -> str:
    operation = str(operation_id or "").strip()
    if operation in _CONTROL_OPERATIONS:
        return "control"
    descriptor = _OPERATION_REGISTRY.get_operation(operation)
    if descriptor is None:
        return "other"
    if descriptor.operation_type in {"shell", "browser", "network", "mcp", "memory", "filesystem", "vcs"}:
        return descriptor.operation_type
    if descriptor.open_world:
        return "network"
    if descriptor.read_only:
        return "read"
    return "side_effect"


def operation_environment_constraint(
    operation_id: str,
    *,
    environment_payload: dict[str, Any],
) -> tuple[str, str]:
    return operation_channel(operation_id), _environment_id(environment_payload)


def operation_requests_from_runtime_selection(selection: dict[str, Any] | None) -> tuple[str, ...]:
    payload = dict(selection or {})
    values: list[Any] = []
    values.extend(list(payload.get("allowed_operations") or []))
    for key in ("operation_requirement", "tool_capability_requirements", "capability_requirements"):
        values.extend(_operations_from_requirement(payload.get(key)))
    for key in ("task_contract", "engagement_contract"):
        nested = dict(payload.get(key) or {})
        for nested_key in ("operation_requirement", "tool_capability_requirements", "capability_requirements"):
            values.extend(_operations_from_requirement(nested.get(nested_key)))
    execution_permit = dict(payload.get("execution_permit") or {})
    values.extend(list(execution_permit.get("allowed_operations") or []))
    runtime_profile = dict(payload.get("runtime_profile") or {})
    runtime_execution_permit = dict(runtime_profile.get("execution_permit") or {})
    values.extend(list(runtime_execution_permit.get("allowed_operations") or []))
    return tuple(_dedupe_operations(values))


def operation_requests_from_authorization(operation_authorization: dict[str, Any] | None) -> tuple[str, ...]:
    result: list[str] = []
    for item in list(dict(operation_authorization or {}).get("decisions") or []):
        if not isinstance(item, dict):
            continue
        if item.get("task_requested") is True:
            operation_id = str(item.get("operation_id") or "").strip()
            if operation_id:
                result.append(operation_id)
    return tuple(_dedupe_operations(result))


def _decision(
    operation_id: str,
    channel: str,
    allowed: bool,
    reason: str,
    constraint_channel: str,
    constraint: str,
    requested: bool,
) -> EnvironmentOperationDecision:
    return EnvironmentOperationDecision(
        operation_id=operation_id,
        channel=channel,
        allowed=allowed,
        reason=reason,
        constraint_channel=constraint_channel,
        environment_constraint=constraint,
        task_requested=requested,
    )


def _environment_id(environment_payload: dict[str, Any]) -> str:
    return str(environment_payload.get("environment_id") or "").strip() or _DEFAULT_ENVIRONMENT_ID


def _operations_from_requirement(value: Any) -> list[Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    result: list[Any] = []
    for key in ("required_operations", "optional_operations", "allowed_operations"):
        result.extend(list(payload.get(key) or []))
    return result


def _operation_set(value: Any) -> set[str]:
    return {str(item or "").strip() for item in list(value or []) if str(item or "").strip()}


def _dedupe_operations(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        operation = str(item or "").strip()
        if not operation or operation in seen:
            continue
        seen.add(operation)
        result.append(operation)
    return result
