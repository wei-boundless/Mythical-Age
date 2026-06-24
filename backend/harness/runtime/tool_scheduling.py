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
    "op.read_persisted_tool_result",
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
_ATTACHMENT_PROCESSING_OPERATIONS = {
    "op.mcp_image_ocr",
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
    | _ATTACHMENT_PROCESSING_OPERATIONS
)
_DEVELOPMENT_WORKSPACE_OPERATIONS = (
    _CREATION_WORKSPACE_OPERATIONS
    | _CODE_INTELLIGENCE_OPERATIONS
    | _GIT_READ_OPERATIONS
    | _GIT_WRITE_OPERATIONS
    | _LOCAL_EXECUTION_OPERATIONS
    | _BROWSER_OPERATIONS
    | _DOCUMENT_ANALYSIS_OPERATIONS
    | _ATTACHMENT_PROCESSING_OPERATIONS
    | _CREATIVE_ASSET_OPERATIONS
)
_DEFAULT_ENVIRONMENT_ID = "env.general.workspace"
_UNKNOWN_ENVIRONMENT_OPERATIONS = {"op.model_response"}
_WRITE_ENABLED_POLICIES = {"allowed", "ask", "task_decided", "sandboxed", "draft_artifacts_allowed"}
_EXECUTION_ENABLED_POLICIES = {"allowed", "ask", "task_decided", "sandboxed"}
_NETWORK_ENABLED_POLICIES = {"allowed", "ask", "task_decided", "sandboxed"}
_CODE_ENVIRONMENT_KINDS = {"coding", "development"}


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
    allowed = operation in environment_allowed_operations(environment_payload)
    return _decision(
        operation,
        channel,
        allowed,
        "environment_allowed" if allowed else "environment_filtered",
        channel,
        environment_id,
        requested,
    )


def environment_allowed_operations(environment: dict[str, Any] | str | None) -> set[str]:
    payload = _environment_payload(environment)
    environment_id = _environment_id(payload)
    if not _has_environment_policy_payload(payload):
        if not environment_id or environment_id == _DEFAULT_ENVIRONMENT_ID:
            payload = _environment_payload(_DEFAULT_ENVIRONMENT_ID)
        else:
            return set(_UNKNOWN_ENVIRONMENT_OPERATIONS)
    environment_kind = _environment_kind(payload)
    if environment_kind == "chat":
        return {"op.model_response"}
    if environment_kind == "general":
        return set(_GENERAL_ALL_OPERATIONS)
    operations: set[str] = set(_CONTROL_OPERATIONS)
    operations.update(_operations_from_file_management(payload))
    operations.update(_operations_from_policies(payload))
    operations.update(_operations_from_environment_kind(payload))
    operations.update(_operations_from_memory_space(payload))
    return _known_operations(operations)


def operation_channel(operation_id: str) -> str:
    operation = str(operation_id or "").strip()
    if operation in _CONTROL_OPERATIONS:
        return "control"
    descriptor = _OPERATION_REGISTRY.get_operation(operation)
    if descriptor is None:
        return "other"
    if descriptor.operation_type in {"shell", "browser", "network", "mcp", "memory", "filesystem", "runtime_context", "vcs"}:
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


def operation_requests_from_runtime_contract(runtime_contract: dict[str, Any] | None) -> tuple[str, ...]:
    payload = dict(runtime_contract or {})
    values: list[Any] = []
    values.extend(list(payload.get("allowed_operations") or []))
    for key in ("operation_requirement", "tool_capability_requirements", "capability_requirements"):
        values.extend(_operations_from_requirement(payload.get(key)))
    for key in ("engagement_contract",):
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


def _environment_payload(environment: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(environment, dict):
        return dict(environment)
    environment_id = str(environment or "").strip()
    if not environment_id:
        environment_id = _DEFAULT_ENVIRONMENT_ID
    try:
        from task_system.environments import build_task_environment_catalog, default_task_environment_registry

        return build_task_environment_catalog(
            registry=default_task_environment_registry()
        ).runtime_environment_payload(environment_id)
    except Exception:
        return {"environment_id": environment_id}


def _has_environment_policy_payload(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "environment_kind",
            "group",
            "environment_boundary",
            "sandbox_policy",
            "execution_policy",
            "file_management",
            "resource_space",
            "memory_space",
        )
    )


def _environment_kind(payload: dict[str, Any]) -> str:
    direct = str(payload.get("environment_kind") or "").strip()
    if direct:
        return direct
    environment_id = str(payload.get("environment_id") or "").strip()
    for kind in ("coding", "development", "creation", "general", "office", "chat"):
        if environment_id.startswith(f"env.{kind}."):
            return kind
    record = payload.get("record")
    if isinstance(record, dict):
        record_kind = str(record.get("environment_kind") or "").strip()
        if record_kind:
            return record_kind
    group = payload.get("group")
    if isinstance(group, dict):
        group_id = str(group.get("group_id") or "").strip()
        if group_id.startswith("environment_group."):
            return group_id.rsplit(".", 1)[-1]
    boundary = payload.get("environment_boundary")
    if isinstance(boundary, dict):
        group_id = str(boundary.get("group_id") or "").strip()
        if group_id.startswith("environment_group."):
            return group_id.rsplit(".", 1)[-1]
    return ""


def _operations_from_file_management(payload: dict[str, Any]) -> set[str]:
    file_management = dict(payload.get("file_management") or {})
    profile_refs = _string_set(file_management.get("file_profile_refs"))
    repository_kinds = _string_set(file_management.get("required_repository_kinds"))
    constraints = dict(file_management.get("constraints") or {})
    operations: set[str] = set()
    if profile_refs or repository_kinds or constraints:
        operations.update(_FILE_READ_OPERATIONS)
        operations.update(_LOCAL_SEARCH_OPERATIONS)
    if _file_write_enabled(payload):
        operations.update(_FILE_WRITE_OPERATIONS)
    if "git_worktree_view" in repository_kinds:
        operations.update(_GIT_READ_OPERATIONS)
    return operations


def _operations_from_policies(payload: dict[str, Any]) -> set[str]:
    sandbox_policy = dict(payload.get("sandbox_policy") or {})
    execution_policy = dict(payload.get("execution_policy") or {})
    operations = _string_set(sandbox_policy.get("side_effect_operations"))
    if _policy_enabled(sandbox_policy.get("shell_policy"), _EXECUTION_ENABLED_POLICIES) or _policy_enabled(
        execution_policy.get("shell_execution_policy"),
        _EXECUTION_ENABLED_POLICIES,
    ):
        operations.update(_LOCAL_EXECUTION_OPERATIONS)
    if _policy_enabled(sandbox_policy.get("browser_policy"), _EXECUTION_ENABLED_POLICIES) or _policy_enabled(
        execution_policy.get("browser_execution_policy"),
        _EXECUTION_ENABLED_POLICIES,
    ):
        operations.update(_BROWSER_OPERATIONS)
    if _policy_enabled(sandbox_policy.get("network_policy"), _NETWORK_ENABLED_POLICIES) or _policy_enabled(
        execution_policy.get("network_execution_policy"),
        _NETWORK_ENABLED_POLICIES,
    ):
        operations.update(_NETWORK_SEARCH_OPERATIONS)
    if _file_write_enabled(payload):
        operations.update(_FILE_WRITE_OPERATIONS)
    return operations


def _operations_from_environment_kind(payload: dict[str, Any]) -> set[str]:
    environment_kind = _environment_kind(payload)
    if environment_kind in _CODE_ENVIRONMENT_KINDS:
        return set(
            _FILE_READ_OPERATIONS
            | _LOCAL_SEARCH_OPERATIONS
            | _TEXT_UTILITY_OPERATIONS
            | _CODE_INTELLIGENCE_OPERATIONS
            | _GIT_READ_OPERATIONS
            | _DOCUMENT_ANALYSIS_OPERATIONS
            | _ATTACHMENT_PROCESSING_OPERATIONS
        )
    if environment_kind == "creation":
        return set(_TEXT_UTILITY_OPERATIONS)
    return set()


def _operations_from_memory_space(payload: dict[str, Any]) -> set[str]:
    memory_space = dict(payload.get("memory_space") or {})
    retrieval_refs = _string_set(memory_space.get("retrieval_index_refs"))
    operations: set[str] = set()
    if "code_search_index" in retrieval_refs:
        operations.update(_CODE_INTELLIGENCE_OPERATIONS)
    return operations


def _file_write_enabled(payload: dict[str, Any]) -> bool:
    sandbox_policy = dict(payload.get("sandbox_policy") or {})
    execution_policy = dict(payload.get("execution_policy") or {})
    file_management = dict(payload.get("file_management") or {})
    if _FILE_WRITE_OPERATIONS & _string_set(sandbox_policy.get("side_effect_operations")):
        return True
    if _policy_enabled(sandbox_policy.get("write_policy"), _WRITE_ENABLED_POLICIES):
        return True
    if _policy_enabled(execution_policy.get("write_scope_policy"), _WRITE_ENABLED_POLICIES):
        return True
    canonical_write_policy = str(file_management.get("canonical_write_policy") or "").strip()
    if not canonical_write_policy:
        return False
    return canonical_write_policy not in {"none", "denied", "read_only"}


def _policy_enabled(value: Any, enabled_values: set[str]) -> bool:
    return str(value or "").strip() in enabled_values


def _string_set(values: Any) -> set[str]:
    return {str(item or "").strip() for item in list(values or []) if str(item or "").strip()}


def _known_operations(operations: set[str]) -> set[str]:
    return {operation for operation in operations if operation in _GENERAL_ALL_OPERATIONS}


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
