from __future__ import annotations

from typing import Any


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


def _operations_from_requirement(value: Any) -> list[Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    result: list[Any] = []
    for key in ("required_operations", "optional_operations", "allowed_operations"):
        result.extend(list(payload.get(key) or []))
    return result


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
