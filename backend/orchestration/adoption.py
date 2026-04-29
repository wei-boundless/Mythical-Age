from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .plan import OrchestrationPlanPreview


@dataclass(slots=True, frozen=True)
class AdoptionCandidate:
    """Preview-only bridge from plan preview to future adopted plan.

    This is a report, not an adoption action. It records why the current
    preview cannot become executable yet.
    """

    candidate_id: str
    plan_ref: str
    resource_policy_ref: str = ""
    status: str = "blocked"
    reason: str = "preview_only"
    can_adopt_plan: bool = False
    can_adopt_resource_policy: bool = False
    preview_only: bool = True
    runtime_executable: bool = False
    authority: str = "candidate_only"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("AdoptionCandidate must remain candidate_only")
        if not self.preview_only:
            raise ValueError("AdoptionCandidate must remain preview_only")
        if self.runtime_executable:
            raise ValueError("AdoptionCandidate cannot be runtime executable")
        if self.can_adopt_plan or self.can_adopt_resource_policy:
            raise ValueError("AdoptionCandidate cannot adopt plans or resource policies in preview")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class AdoptedResourcePolicy:
    """Executable resource policy reference produced only after adoption.

    Adoption is deliberately separate from ResourcePolicyPreview. Even an
    adopted policy does not execute anything; OperationGate must still recheck
    each RuntimeDirective before an executor can run.
    """

    policy_id: str
    task_id: str
    source_policy_ref: str
    allowed_operations: tuple[str, ...] = ()
    denied_operations: tuple[str, ...] = ()
    requires_approval_operations: tuple[str, ...] = ()
    adopted: bool = True
    preview_only: bool = False
    runtime_executable: bool = False
    authority: str = "adopted_resource_policy"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "adopted_resource_policy":
            raise ValueError("AdoptedResourcePolicy authority must be adopted_resource_policy")
        if not self.adopted:
            raise ValueError("AdoptedResourcePolicy must be adopted")
        if self.preview_only:
            raise ValueError("AdoptedResourcePolicy cannot remain preview_only")
        if self.runtime_executable:
            raise ValueError("AdoptedResourcePolicy cannot grant execution by itself")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_operations"] = list(self.allowed_operations)
        payload["denied_operations"] = list(self.denied_operations)
        payload["requires_approval_operations"] = list(self.requires_approval_operations)
        return payload


@dataclass(slots=True, frozen=True)
class AdoptionBlock:
    """Structured reason why a preview cannot be adopted yet."""

    block_id: str
    plan_ref: str
    resource_policy_ref: str
    reason: str = "preview_only"
    blocked: bool = True
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.blocked:
            raise ValueError("AdoptionBlock cannot represent an allowed adoption")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_blocked_adoption_candidate(plan: OrchestrationPlanPreview) -> AdoptionCandidate:
    return AdoptionCandidate(
        candidate_id=f"adoption:{plan.plan_id}:blocked",
        plan_ref=plan.plan_id,
        resource_policy_ref=plan.resource_policy_ref,
        status="blocked",
        reason="preview_only",
        can_adopt_plan=False,
        can_adopt_resource_policy=False,
        preview_only=True,
        runtime_executable=False,
        diagnostics={
            "resource_policy_preview_only": True,
            "resource_policy_adopted": False,
            "runtime_directive_enabled": False,
            "operation_gate_required_before_execution": True,
            "commit_gate_required": True,
        },
    )


def build_preview_adoption_block(plan: OrchestrationPlanPreview) -> AdoptionBlock:
    return AdoptionBlock(
        block_id=f"adoption-block:{plan.plan_id}:preview-only",
        plan_ref=plan.plan_id,
        resource_policy_ref=plan.resource_policy_ref,
        reason="preview_only",
        blocked=True,
        diagnostics={
            "adopted_resource_policy_available": False,
            "runtime_directive_available": False,
            "operation_gate_required_before_execution": True,
        },
    )
