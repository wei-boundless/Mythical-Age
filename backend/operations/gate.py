from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .policies import ResourcePolicy
from .registry import OperationRegistry


@dataclass(frozen=True, slots=True)
class OperationGateResult:
    operation_id: str
    decision: str
    reason: str
    allowed: bool = False
    requires_approval: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OperationGate:
    def __init__(self, registry: OperationRegistry) -> None:
        self.registry = registry

    def check(
        self,
        operation_id: str,
        *,
        resource_policy: ResourcePolicy | None,
        directive_ref: str = "",
    ) -> OperationGateResult:
        normalized_id = self.registry.normalize_id(operation_id)
        descriptor = self.registry.get_operation(normalized_id)
        if descriptor is None:
            return OperationGateResult(
                operation_id=normalized_id,
                decision="deny",
                reason="unknown operation",
                diagnostics={"fail_closed": True},
            )
        if not directive_ref:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="missing directive_ref",
                diagnostics={"fail_closed": True},
            )
        if resource_policy is None:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="missing resource policy",
                diagnostics={"fail_closed": True},
            )
        if resource_policy.preview_only or not resource_policy.adopted or not resource_policy.runtime_executable:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="resource policy is preview-only and not executable",
                diagnostics={
                    "preview_only": resource_policy.preview_only,
                    "adopted": resource_policy.adopted,
                    "runtime_executable": resource_policy.runtime_executable,
                },
            )
        if descriptor.operation_id in resource_policy.denied_operations:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="operation denied by resource policy",
            )
        if descriptor.operation_id in resource_policy.requires_approval_operations:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="requires_approval",
                reason="operation requires approval",
                requires_approval=True,
            )
        if descriptor.operation_id not in resource_policy.allowed_operations:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="operation not allowed by resource policy",
            )
        return OperationGateResult(
            operation_id=descriptor.operation_id,
            decision="allow",
            reason="operation allowed by adopted resource policy",
            allowed=True,
        )

