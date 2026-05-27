from __future__ import annotations

from typing import Any

from .contract_adapter import build_execution_permit_from_payload


def resolve_agent_execution_permit(
    assembly_contract: dict[str, Any] | None,
    *,
    task_operation: dict[str, Any] | None = None,
    task_id: str = "",
    agent_id: str = "",
    agent_profile_id: str = "",
    agent_runtime_config: Any | None = None,
) -> dict[str, Any]:
    """Resolve the system execution permit for one agent invocation."""

    permit = build_execution_permit_from_payload(dict(assembly_contract or {}))
    if not permit:
        return {}

    operation = dict(task_operation or {})
    selected_recipe = dict(operation.get("selected_recipe") or {})
    metadata = dict(selected_recipe.get("metadata") or {})
    config_tool_policy = _tool_policy_from_config(agent_runtime_config)
    operation_policy = _operation_policy(operation, metadata)
    allowed_operation_refs = _dedupe_refs(
        [
            *_string_list(config_tool_policy.get("allowed_operation_refs")),
            *list(operation_policy.get("allowed_operations") or []),
            *list(operation_policy.get("required_operations") or []),
            *list(operation_policy.get("optional_operations") or []),
        ]
    )
    allowed_tool_names = _dedupe_refs(
        [
            *_string_list(config_tool_policy.get("allowed_tool_names")),
            *_tool_names_for_operation_refs(list(operation_policy.get("allowed_operations") or [])),
            *_tool_names_for_operation_refs(list(operation_policy.get("required_operations") or [])),
            *_tool_names_for_operation_refs(list(operation_policy.get("optional_operations") or [])),
        ]
    )
    if not allowed_operation_refs and not allowed_tool_names:
        return permit

    normalized_operations = _dedupe_refs(
        [
            *list(permit.get("allowed_operations") or []),
            *allowed_operation_refs,
            "op.model_response",
        ]
    )
    normalized_visible_tools = _dedupe_refs(
        [
            *list(permit.get("visible_tools") or []),
            *allowed_tool_names,
            *_tool_names_for_operation_refs(allowed_operation_refs),
        ]
    )
    if not normalized_visible_tools:
        normalized_visible_tools = _dedupe_refs(
            [
                str(item).removeprefix("op.")
                for item in normalized_operations
                if str(item).strip() and str(item).strip() != "op.model_response"
            ]
        )

    permit["allowed_operations"] = normalized_operations
    permit["visible_tools"] = normalized_visible_tools
    permit["dispatchable_tools"] = _dedupe_refs(
        [*list(permit.get("dispatchable_tools") or []), *normalized_visible_tools]
    )
    permit["model_visible_tool_refs"] = normalized_visible_tools
    permit["diagnostics"] = {
        **dict(permit.get("diagnostics") or {}),
        "agent_runtime_tool_policy_adopted": bool(
            config_tool_policy.get("allowed_operation_refs")
            or config_tool_policy.get("allowed_tool_names")
        ),
        "agent_runtime_allowed_operation_refs": allowed_operation_refs,
        "agent_runtime_allowed_tool_names": allowed_tool_names,
        "operation_policy_adopted": bool(operation_policy),
        "operation_policy": operation_policy,
        "agent_runtime_enabled_phases": _enabled_phases_from_config(agent_runtime_config),
        "authority": "harness.runtime.execution_policy",
        "task_id": task_id,
        "agent_id": agent_id,
        "agent_profile_id": agent_profile_id,
    }
    return permit


def execution_permit_diagnostics(execution_permit: dict[str, Any] | None) -> dict[str, Any]:
    permit = dict(execution_permit or {})
    if not permit:
        return {}
    return {
        "permit_id": str(permit.get("permit_id") or ""),
        "assembly_id": str(permit.get("assembly_id") or ""),
        "work_order_id": str(permit.get("work_order_id") or ""),
        "agent_id": str(permit.get("agent_id") or ""),
        "agent_profile_id": str(permit.get("agent_profile_id") or ""),
        "executor_type": str(permit.get("executor_type") or ""),
        "allowed_operations": list(permit.get("allowed_operations") or []),
        "visible_tools": list(permit.get("visible_tools") or []),
        "dispatchable_tools": list(permit.get("dispatchable_tools") or []),
    }


def _tool_policy_from_config(config: Any | None) -> dict[str, Any]:
    if config is not None and not isinstance(config, dict) and hasattr(config, "tool_policy"):
        tool_policy = getattr(config, "tool_policy")
        if hasattr(tool_policy, "to_dict"):
            return dict(tool_policy.to_dict())
        return {
            "allowed_tool_names": list(getattr(tool_policy, "allowed_tool_names", ()) or ()),
            "allowed_operation_refs": list(getattr(tool_policy, "allowed_operation_refs", ()) or ()),
        }
    payload = dict(config or {})
    return dict(payload.get("tool_policy") or {})


def _enabled_phases_from_config(config: Any | None) -> list[str]:
    if config is not None and not isinstance(config, dict) and hasattr(config, "enabled_phases"):
        return [str(item) for item in tuple(getattr(config, "enabled_phases") or ()) if str(item).strip()]
    payload = dict(config or {})
    return [str(item) for item in list(payload.get("enabled_phases") or []) if str(item).strip()]


def _operation_policy(task_operation: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    current_turn = dict(task_operation.get("current_turn_context") or {})
    policies = [
        dict(metadata.get("operation_policy") or {}),
        dict(current_turn.get("operation_policy") or {}),
    ]
    merged: dict[str, list[str]] = {
        "allowed_operations": [],
        "required_operations": [],
        "optional_operations": [],
    }
    for policy in policies:
        for key in tuple(merged):
            merged[key].extend(
                str(item).strip()
                for item in list(dict(policy).get(key) or [])
                if str(item).strip()
            )
    return {key: _dedupe_refs(values) for key, values in merged.items() if _dedupe_refs(values)}


def _tool_names_for_operation_refs(operation_refs: list[Any]) -> list[str]:
    requested = {str(item or "").strip() for item in list(operation_refs or []) if str(item or "").strip()}
    if not requested:
        return []
    try:
        from capability_system.tool_definitions import get_tool_definitions
    except Exception:
        return [item.removeprefix("op.") for item in requested if item != "op.model_response"]
    tools: list[str] = []
    for definition in get_tool_definitions():
        operation_id = str(getattr(definition, "operation_id", "") or "").strip()
        tool_name = str(getattr(definition, "name", "") or "").strip()
        if operation_id in requested and tool_name:
            tools.append(tool_name)
    return _dedupe_refs(tools)


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _dedupe_refs(values: list[Any] | tuple[Any, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


