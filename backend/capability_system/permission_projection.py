from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.catalog_models import CapabilityPermissionView
from permissions.operations import OperationRegistry
from permissions.resource_policy import ResourceDecision, ResourcePolicy


@dataclass(frozen=True, slots=True)
class ResourceRuntimeView:
    resource_id: str
    title: str
    capability_summary: str
    authorized: bool = False
    authorization_owner: str = "ResourcePolicy"
    risk_summary: str = ""
    denied_reason: str = ""
    requires_approval: bool = False
    available_to_model: bool = False
    runtime_executable: bool = False
    policy_decision: str = "unknown"
    input_contract_ref: str = ""
    output_contract_ref: str = ""
    read_only: bool = False
    concurrency_safe: bool = False
    destructive: bool = False
    permission_check_required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_resource_runtime_views(policy: ResourcePolicy, registry: OperationRegistry) -> list[ResourceRuntimeView]:
    return [_view_from_decision(decision, registry, policy) for decision in policy.decisions]


def _view_from_decision(decision: ResourceDecision, registry: OperationRegistry, policy: ResourcePolicy) -> ResourceRuntimeView:
    descriptor = registry.get_operation(decision.operation_id)
    if descriptor is None:
        return ResourceRuntimeView(
            resource_id=decision.operation_id,
            title=decision.operation_id,
            capability_summary="Unknown operation.",
            denied_reason=decision.reason or "unknown operation",
            policy_decision=decision.decision,
            metadata={"source": "ResourceDecision"},
        )

    authorized = decision.decision == "allow"
    runtime_executable = authorized and policy.adopted and policy.runtime_executable
    available_to_model = authorized
    requires_approval = decision.decision == "requires_approval"
    denied_reason = "" if authorized else decision.reason
    return ResourceRuntimeView(
        resource_id=descriptor.operation_id,
        title=descriptor.title,
        capability_summary=descriptor.capability_summary,
        authorized=authorized,
        risk_summary=", ".join(decision.risk_tags),
        denied_reason=denied_reason,
        requires_approval=requires_approval,
        available_to_model=available_to_model,
        runtime_executable=runtime_executable,
        policy_decision=decision.decision,
        input_contract_ref=descriptor.input_contract_ref or str(descriptor.input_contract.get("contract_ref") or ""),
        output_contract_ref=descriptor.output_contract_ref or str(descriptor.output_contract.get("contract_ref") or ""),
        read_only=descriptor.read_only,
        concurrency_safe=descriptor.concurrency_safe,
        destructive=descriptor.destructive,
        permission_check_required=True,
        metadata={
            "operation_type": descriptor.operation_type,
            "authorization_owner": "ResourcePolicy",
            "execution_time_revalidation_required": True,
            "operation_descriptor_source": descriptor.provider,
            "requires_user_interaction": descriptor.requires_user_interaction,
            "interrupt_behavior": descriptor.interrupt_behavior,
            "max_result_size_chars": descriptor.max_result_size_chars,
            "deferred_loading": descriptor.deferred_loading,
            "always_load": descriptor.always_load,
            "safety_validator_ref": descriptor.safety_validator_ref,
        },
    )


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
