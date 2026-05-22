from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.operation_registry import OperationDescriptor, OperationRegistry

from permissions.resource_policy import ResourcePolicy


PERMISSION_MODE_DEFAULT = "default"
PERMISSION_MODE_DONT_ASK = "dont_ask"
PERMISSION_MODE_HEADLESS = "headless"
BYPASS_PERMISSION_MODES = {"bypass", "dangerous_bypass"}
DANGEROUS_ALLOW_RISK_TAGS = {
    "shell_execution",
    "python_execution",
    "local_write",
    "destructive",
    "network_open_world",
}
DEFAULT_MAX_CONSECUTIVE_DENIALS = 3
DEFAULT_MAX_TOTAL_DENIALS = 20


@dataclass(frozen=True, slots=True)
class OperationGateResult:
    operation_id: str
    decision: str
    reason: str
    allowed: bool = False
    requires_approval: bool = False
    pipeline_stage: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DenialTrackingState:
    consecutive_denials: int = 0
    total_denials: int = 0
    max_consecutive_denials: int = DEFAULT_MAX_CONSECUTIVE_DENIALS
    max_total_denials: int = DEFAULT_MAX_TOTAL_DENIALS

    def record_denial(self) -> None:
        self.consecutive_denials += 1
        self.total_denials += 1

    def record_allow(self) -> None:
        self.consecutive_denials = 0

    @property
    def tripped(self) -> bool:
        return (
            self.consecutive_denials >= self.max_consecutive_denials
            or self.total_denials >= self.max_total_denials
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ApprovalToken:
    token_id: str
    operation_id: str
    directive_ref: str
    granted: bool = False
    source: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalState:
    """Serializable approval snapshot for future RuntimeCheckpoint storage."""

    tokens: tuple[ApprovalToken, ...] = ()

    def find_granted_token(self, *, operation_id: str, directive_ref: str) -> ApprovalToken | None:
        for token in self.tokens:
            if token.granted and token.operation_id == operation_id and token.directive_ref == directive_ref:
                return token
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OperationGatePipelineContext:
    permission_mode: str = PERMISSION_MODE_DEFAULT
    headless_mode: bool = False
    approval_token: ApprovalToken | None = None
    approval_state: ApprovalState | None = None
    operation_input: dict[str, Any] = field(default_factory=dict)
    denial_tracking: DenialTrackingState | None = None
    validators: dict[str, Any] = field(default_factory=dict)
    strip_dangerous_allow_rules: bool = True


class OperationGate:
    def __init__(self, registry: OperationRegistry) -> None:
        self.registry = registry

    def check(
        self,
        operation_id: str,
        *,
        resource_policy: ResourcePolicy | None,
        directive_ref: str = "",
        context: OperationGatePipelineContext | None = None,
    ) -> OperationGateResult:
        pipeline_context = context or OperationGatePipelineContext()
        result = self._check_pipeline(
            operation_id,
            resource_policy=resource_policy,
            directive_ref=directive_ref,
            context=pipeline_context,
        )
        if result.allowed and pipeline_context.denial_tracking is not None:
            pipeline_context.denial_tracking.record_allow()
        elif not result.allowed and pipeline_context.denial_tracking is not None:
            pipeline_context.denial_tracking.record_denial()
        return result

    def _check_pipeline(
        self,
        operation_id: str,
        *,
        resource_policy: ResourcePolicy | None,
        directive_ref: str,
        context: OperationGatePipelineContext,
    ) -> OperationGateResult:
        normalized_id = self.registry.normalize_id(operation_id)
        descriptor = self.registry.get_operation(normalized_id)
        if descriptor is None:
            return OperationGateResult(
                operation_id=normalized_id,
                decision="deny",
                reason="unknown operation",
                pipeline_stage="descriptor_exists",
                diagnostics={"fail_closed": True},
            )
        if not directive_ref:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="missing directive_ref",
                pipeline_stage="runtime_directive_exists",
                diagnostics={"fail_closed": True},
            )
        if resource_policy is None:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="missing resource policy",
                pipeline_stage="adopted_resource_policy_exists",
                diagnostics={"fail_closed": True},
            )
        if resource_policy.runtime_view_only or not resource_policy.adopted or not resource_policy.runtime_executable:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="resource policy is not adopted for execution",
                pipeline_stage="adopted_resource_policy_exists",
                diagnostics={
                    "runtime_view_only": resource_policy.runtime_view_only,
                    "adopted": resource_policy.adopted,
                    "runtime_executable": resource_policy.runtime_executable,
                },
            )
        if context.denial_tracking is not None and context.denial_tracking.tripped:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="denial tracking circuit is open",
                pipeline_stage="denial_tracking",
                diagnostics={
                    "fail_closed": True,
                    "denial_tracking": context.denial_tracking.to_dict(),
                },
            )
        if descriptor.operation_id in resource_policy.denied_operations:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="operation denied by resource policy",
                pipeline_stage="deny_rule",
            )
        approval_satisfied = False
        if descriptor.operation_id in resource_policy.requires_approval_operations:
            approval_result = self._check_approval(
                descriptor,
                directive_ref=directive_ref,
                context=context,
            )
            if approval_result is not None:
                return approval_result
            approval_satisfied = True
        if not approval_satisfied and descriptor.operation_id not in resource_policy.allowed_operations:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="operation not allowed by resource policy",
                pipeline_stage="allow_rule",
            )
        dangerous_allow = self._check_dangerous_allow_rule(descriptor, context)
        if dangerous_allow is not None:
            return dangerous_allow
        safety_result = self._check_operation_safety(descriptor, context)
        if safety_result is not None:
            return safety_result
        return OperationGateResult(
            operation_id=descriptor.operation_id,
            decision="allow",
            reason="operation allowed by adopted resource policy",
            allowed=True,
            pipeline_stage="allow_rule",
            diagnostics={
                "interrupt_behavior": descriptor.interrupt_behavior,
                "max_result_size_chars": descriptor.max_result_size_chars,
                "concurrency_safe": descriptor.concurrency_safe,
                "read_only": descriptor.read_only,
            },
        )

    def _check_approval(
        self,
        descriptor: OperationDescriptor,
        *,
        directive_ref: str,
        context: OperationGatePipelineContext,
    ) -> OperationGateResult | None:
        approval_token = self._resolve_approval_token(
            descriptor.operation_id,
            directive_ref=directive_ref,
            context=context,
        )
        if context.permission_mode in {PERMISSION_MODE_DONT_ASK, PERMISSION_MODE_HEADLESS} or context.headless_mode:
            if approval_token is None:
                return OperationGateResult(
                    operation_id=descriptor.operation_id,
                    decision="deny",
                    reason="approval required but unavailable in non-interactive context",
                    pipeline_stage="headless_policy",
                    diagnostics={
                        "permission_mode": context.permission_mode,
                        "headless_mode": context.headless_mode,
                        "requires_user_interaction": descriptor.requires_user_interaction,
                    },
                )
        if approval_token is not None:
            return None
        if context.approval_token is None:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="requires_approval",
                reason="operation requires approval",
                requires_approval=True,
                pipeline_stage="requires_approval_rule",
            )
        return OperationGateResult(
            operation_id=descriptor.operation_id,
            decision="deny",
            reason="approval token does not match operation or directive",
            pipeline_stage="approval_token",
            diagnostics={
                "approval_token_operation_id": context.approval_token.operation_id,
                "approval_token_directive_ref": context.approval_token.directive_ref,
            },
        )

    def _resolve_approval_token(
        self,
        operation_id: str,
        *,
        directive_ref: str,
        context: OperationGatePipelineContext,
    ) -> ApprovalToken | None:
        if (
            context.approval_token is not None
            and context.approval_token.granted
            and context.approval_token.operation_id == operation_id
            and context.approval_token.directive_ref == directive_ref
        ):
            return context.approval_token
        if context.approval_state is not None:
            return context.approval_state.find_granted_token(
                operation_id=operation_id,
                directive_ref=directive_ref,
            )
        return None

    def _check_dangerous_allow_rule(
        self,
        descriptor: OperationDescriptor,
        context: OperationGatePipelineContext,
    ) -> OperationGateResult | None:
        if not context.strip_dangerous_allow_rules:
            return None
        if context.permission_mode not in {"auto", *BYPASS_PERMISSION_MODES}:
            return None
        if descriptor.destructive or set(descriptor.risk_tags) & DANGEROUS_ALLOW_RISK_TAGS:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="dangerous allow rule stripped in auto/bypass permission mode",
                pipeline_stage="dangerous_allow_rule_stripper",
                diagnostics={
                    "permission_mode": context.permission_mode,
                    "risk_tags": list(descriptor.risk_tags),
                    "destructive": descriptor.destructive,
                },
            )
        return None

    def _check_operation_safety(
        self,
        descriptor: OperationDescriptor,
        context: OperationGatePipelineContext,
    ) -> OperationGateResult | None:
        if not descriptor.safety_validator_ref:
            return None
        validator = context.validators.get(descriptor.safety_validator_ref)
        if validator is None:
            return OperationGateResult(
                operation_id=descriptor.operation_id,
                decision="deny",
                reason="operation safety validator is unavailable",
                pipeline_stage="operation_specific_safety_validator",
                diagnostics={
                    "safety_validator_ref": descriptor.safety_validator_ref,
                    "fail_closed": True,
                },
            )
        outcome = validator(context.operation_input)
        if isinstance(outcome, OperationGateResult):
            return outcome
        if outcome is True or outcome is None:
            return None
        if isinstance(outcome, tuple):
            allowed = bool(outcome[0])
            reason = str(outcome[1] if len(outcome) > 1 else "operation safety validator blocked")
        else:
            allowed = bool(outcome)
            reason = "operation safety validator blocked"
        if allowed:
            return None
        return OperationGateResult(
            operation_id=descriptor.operation_id,
            decision="deny",
            reason=reason,
            pipeline_stage="operation_specific_safety_validator",
            diagnostics={
                "safety_validator_ref": descriptor.safety_validator_ref,
                "fail_closed": True,
            },
        )
