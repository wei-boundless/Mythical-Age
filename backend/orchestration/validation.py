from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .plan import OrchestrationPlanPreview


ValidationStatus = Literal["pass", "blocked"]


@dataclass(slots=True, frozen=True)
class ValidationCheck:
    check_id: str
    status: ValidationStatus
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class PlanValidationResult:
    validation_id: str
    plan_id: str
    status: str = "blocked"
    reason: str = "preview_only"
    checks: tuple[ValidationCheck, ...] = ()
    can_adopt_resource_policy: bool = False
    can_build_runtime_directive: bool = False
    runtime_executable: bool = False
    preview_only: bool = True
    authority: str = "plan_validation_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("PlanValidationResult must remain preview_only")
        if self.runtime_executable:
            raise ValueError("PlanValidationResult cannot be runtime executable")
        if self.can_build_runtime_directive:
            raise ValueError("PlanValidationResult cannot enable runtime directives")
        if self.authority != "plan_validation_preview":
            raise ValueError("PlanValidationResult cannot carry execution authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [check.to_dict() for check in self.checks]
        return payload


def validate_preview_plan(
    plan: OrchestrationPlanPreview,
    *,
    resource_policy_preview_only: bool = True,
    resource_policy_adopted: bool = False,
) -> PlanValidationResult:
    checks = (
        _check("task_contract_exists", bool(plan.task_contract_ref), "task contract ref is required"),
        _check(
            "task_prompt_contract_exists",
            bool(plan.task_prompt_contract_ref),
            "task prompt contract ref is required",
        ),
        _check("resource_policy_exists", bool(plan.resource_policy_ref), "resource policy ref is required"),
        _check(
            "resource_policy_preview_only",
            bool(resource_policy_preview_only),
            "resource policy is still preview-only",
        ),
        _check(
            "resource_policy_not_adopted",
            not bool(resource_policy_adopted),
            "resource policy has not been adopted",
        ),
        _check(
            "topology_single_agent_only",
            plan.topology_mode == "single_agent",
            "only single_agent topology is enabled in this phase",
        ),
        ValidationCheck(
            check_id="runtime_directive_disabled",
            status="blocked",
            reason="runtime directive generation is disabled in preview phase",
        ),
        ValidationCheck(
            check_id="operation_gate_required",
            status="blocked",
            reason="operation gate is required before real execution",
        ),
        ValidationCheck(
            check_id="commit_gate_required",
            status="blocked",
            reason="commit gate is required before writeback",
        ),
    )
    hard_blocked = any(check.status == "blocked" for check in checks)
    return PlanValidationResult(
        validation_id=f"validation:{plan.plan_id}",
        plan_id=plan.plan_id,
        status="blocked" if hard_blocked else "valid_preview",
        reason="preview_only",
        checks=checks,
        can_adopt_resource_policy=False,
        can_build_runtime_directive=False,
        runtime_executable=False,
        diagnostics={
            "preview_only": True,
            "fail_closed": True,
            "check_count": len(checks),
            "blocked_check_count": sum(1 for check in checks if check.status == "blocked"),
            "runtime_directive_enabled": False,
            "runtime_executable": False,
        },
    )


def _check(check_id: str, condition: bool, reason: str) -> ValidationCheck:
    return ValidationCheck(
        check_id=check_id,
        status="pass" if condition else "blocked",
        reason=reason,
    )
