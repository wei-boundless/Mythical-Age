from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .plan import OrchestrationPlanPreview
from .validation import PlanValidationResult


@dataclass(slots=True, frozen=True)
class RuntimeDirectiveCandidate:
    """Candidate-only shape of a future RuntimeDirective."""

    directive_candidate_id: str
    plan_ref: str
    stage_ref: str
    executor_type: str
    operation_refs: tuple[str, ...] = ()
    resource_policy_ref: str = ""
    input_contract_ref: str = ""
    output_contract_ref: str = ""
    blocked_reason: str = "preview_only"
    preview_only: bool = True
    runtime_executable: bool = False
    authority: str = "candidate_only"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("RuntimeDirectiveCandidate must remain candidate_only")
        if not self.preview_only:
            raise ValueError("RuntimeDirectiveCandidate must remain preview_only")
        if self.runtime_executable:
            raise ValueError("RuntimeDirectiveCandidate cannot be runtime executable")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_refs"] = list(self.operation_refs)
        return payload


def build_runtime_directive_candidates(
    plan: OrchestrationPlanPreview,
    validation: PlanValidationResult,
) -> tuple[RuntimeDirectiveCandidate, ...]:
    return tuple(
        RuntimeDirectiveCandidate(
            directive_candidate_id=f"directive-candidate:{stage.stage_id}",
            plan_ref=plan.plan_id,
            stage_ref=stage.stage_id,
            executor_type=stage.executor_hint,
            operation_refs=stage.operation_refs,
            resource_policy_ref=plan.resource_policy_ref,
            input_contract_ref=plan.task_prompt_contract_ref,
            output_contract_ref=plan.task_prompt_contract_ref,
            blocked_reason=validation.reason or stage.blocked_reason,
            diagnostics={
                "plan_validation_ref": validation.validation_id,
                "plan_validation_status": validation.status,
                "can_build_runtime_directive": validation.can_build_runtime_directive,
                "runtime_directive_enabled": False,
                "runtime_executable": False,
            },
        )
        for stage in plan.stages
    )
