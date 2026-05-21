from __future__ import annotations

from typing import Any

from .models import CapabilityPermissionView


def build_capability_permission_views(units: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    views: dict[str, dict[str, Any]] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        capability_id = str(unit.get("capability_id") or "").strip()
        if not capability_id:
            continue
        existing = unit.get("permission_view") if isinstance(unit.get("permission_view"), dict) else {}
        operation_ids = tuple(
            str(item).strip()
            for item in list(existing.get("operation_ids") or unit.get("operation_ids") or [])
            if str(item).strip()
        )
        status = str(unit.get("status") or "").strip()
        provider_kind = str(unit.get("provider_kind") or "").strip()
        approval_state = str(existing.get("approval_state") or _approval_state_for_unit(unit))
        view = CapabilityPermissionView(
            capability_id=capability_id,
            operation_ids=operation_ids,
            profile_state=str(existing.get("profile_state") or "not_checked"),
            adoption_state=str(existing.get("adoption_state") or "not_checked"),
            gate_state=str(existing.get("gate_state") or ("unsupported" if status == "unsupported" else "not_checked")),
            approval_state=approval_state,
            sandbox_state=str(existing.get("sandbox_state") or "none"),
            reasons=tuple(
                str(item)
                for item in list(existing.get("reasons") or _reasons_for_unit(unit))
                if str(item)
            ),
            diagnostics={
                **(dict(existing.get("diagnostics") or {}) if isinstance(existing.get("diagnostics"), dict) else {}),
                "provider_kind": provider_kind,
                "management_view_only": True,
            },
        )
        views[capability_id] = view.to_dict()
    return views


def attach_capability_permission_views(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    views = build_capability_permission_views(units)
    result: list[dict[str, Any]] = []
    for unit in units:
        payload = dict(unit)
        capability_id = str(payload.get("capability_id") or "").strip()
        payload["permission_view"] = views.get(capability_id)
        result.append(payload)
    return result


def _approval_state_for_unit(unit: dict[str, Any]) -> str:
    risks = {str(item) for item in list(unit.get("risk") or [])}
    if risks & {"local_write", "shell_execution", "python_execution", "destructive", "network_open_world"}:
        return "policy_dependent"
    return "not_required"


def _reasons_for_unit(unit: dict[str, Any]) -> tuple[str, ...]:
    kind = str(unit.get("kind") or "")
    if kind == "skill":
        return ("skill_declares_operation_dependencies",) if unit.get("operation_ids") else ("skill_missing_operation_dependencies",)
    if kind == "tool":
        return ("tool_maps_to_operation",) if unit.get("operation_ids") else ("tool_missing_operation",)
    if kind == "mcp":
        return ("mcp_tool_maps_to_operation",) if unit.get("operation_ids") else ("mcp_provider_server",)
    return ("capability_permission_not_checked",)
