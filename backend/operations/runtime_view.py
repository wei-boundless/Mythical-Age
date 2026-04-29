from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .policies import ResourceDecision, ResourcePolicy
from .registry import OperationRegistry


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
    preview_only: bool = True
    preview_available: bool = False
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
    return [_view_from_decision(decision, registry) for decision in policy.decisions]


def _view_from_decision(decision: ResourceDecision, registry: OperationRegistry) -> ResourceRuntimeView:
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
    preview_available = decision.decision in {"allow", "preview_only"}
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
        preview_only=True,
        preview_available=preview_available,
        runtime_executable=False,
        policy_decision=decision.decision,
        input_contract_ref=str(descriptor.input_contract.get("contract_ref") or ""),
        output_contract_ref=str(descriptor.output_contract.get("contract_ref") or ""),
        read_only=descriptor.read_only,
        concurrency_safe=descriptor.concurrency_safe,
        destructive=descriptor.destructive,
        permission_check_required=True,
        metadata={
            "operation_type": descriptor.operation_type,
            "authorization_owner": "ResourcePolicy",
            "execution_time_revalidation_required": True,
            "operation_descriptor_source": descriptor.provider,
        },
    )

