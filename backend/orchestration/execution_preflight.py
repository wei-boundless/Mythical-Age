from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .directives import RuntimeDirectiveCandidate
from .plan import OrchestrationPlanPreview


@dataclass(slots=True, frozen=True)
class OperationGatePreflightCheck:
    check_id: str
    operation_id: str
    directive_candidate_ref: str
    resource_policy_ref: str
    decision: str = "deny"
    reason: str = "runtime_directive_missing"
    required_input_type: str = "RuntimeDirective"
    received_input_type: str = "RuntimeDirectiveCandidate"
    operation_gate_passed: bool = False
    runtime_executable: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision != "deny":
            raise ValueError("OperationGatePreflightCheck must deny preview execution")
        if self.operation_gate_passed:
            raise ValueError("OperationGatePreflightCheck cannot pass in preview")
        if self.runtime_executable:
            raise ValueError("OperationGatePreflightCheck cannot be runtime executable")
        if self.required_input_type != "RuntimeDirective":
            raise ValueError("OperationGatePreflightCheck must require RuntimeDirective")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class OperationGatePreflightPreview:
    preflight_id: str
    task_id: str
    plan_ref: str
    resource_policy_ref: str
    checks: tuple[OperationGatePreflightCheck, ...] = ()
    status: str = "blocked"
    reason: str = "runtime_directive_missing"
    operation_gate_required: bool = True
    operation_gate_passed: bool = False
    preview_only: bool = True
    runtime_executable: bool = False
    authority: str = "operation_gate_preflight_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "operation_gate_preflight_preview":
            raise ValueError("OperationGatePreflightPreview cannot carry execution authority")
        if self.status != "blocked":
            raise ValueError("OperationGatePreflightPreview must stay blocked")
        if not self.operation_gate_required:
            raise ValueError("OperationGatePreflightPreview must require OperationGate")
        if self.operation_gate_passed:
            raise ValueError("OperationGatePreflightPreview cannot pass in preview")
        if not self.preview_only:
            raise ValueError("OperationGatePreflightPreview must remain preview_only")
        if self.runtime_executable:
            raise ValueError("OperationGatePreflightPreview cannot be runtime executable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "preflight_id": self.preflight_id,
            "task_id": self.task_id,
            "plan_ref": self.plan_ref,
            "resource_policy_ref": self.resource_policy_ref,
            "checks": [check.to_dict() for check in self.checks],
            "status": self.status,
            "reason": self.reason,
            "operation_gate_required": self.operation_gate_required,
            "operation_gate_passed": self.operation_gate_passed,
            "preview_only": self.preview_only,
            "runtime_executable": self.runtime_executable,
            "authority": self.authority,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(slots=True, frozen=True)
class DirectiveOnlyExecutorPreview:
    preview_id: str
    task_id: str
    plan_ref: str
    operation_gate_preflight_ref: str
    accepted_input_type: str = "RuntimeDirective"
    rejected_input_types: tuple[str, ...] = (
        "RuntimeDirectiveCandidate",
        "QueryExecutionPlan",
        "WorkerExecutionPlan",
        "query_understanding.tool_name",
        "worker_plan",
    )
    status: str = "blocked"
    reason: str = "runtime_directive_missing"
    operation_gate_passed: bool = False
    will_dispatch: bool = False
    preview_only: bool = True
    runtime_executable: bool = False
    authority: str = "directive_only_executor_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "directive_only_executor_preview":
            raise ValueError("DirectiveOnlyExecutorPreview cannot carry execution authority")
        if self.accepted_input_type != "RuntimeDirective":
            raise ValueError("DirectiveOnlyExecutorPreview must accept only RuntimeDirective")
        if "RuntimeDirectiveCandidate" not in self.rejected_input_types:
            raise ValueError("DirectiveOnlyExecutorPreview must reject RuntimeDirectiveCandidate")
        if self.status != "blocked":
            raise ValueError("DirectiveOnlyExecutorPreview must stay blocked")
        if self.operation_gate_passed:
            raise ValueError("DirectiveOnlyExecutorPreview cannot pass OperationGate in preview")
        if self.will_dispatch:
            raise ValueError("DirectiveOnlyExecutorPreview cannot dispatch in preview")
        if not self.preview_only:
            raise ValueError("DirectiveOnlyExecutorPreview must remain preview_only")
        if self.runtime_executable:
            raise ValueError("DirectiveOnlyExecutorPreview cannot be runtime executable")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rejected_input_types"] = list(self.rejected_input_types)
        return payload


def build_operation_gate_preflight_preview(
    *,
    plan: OrchestrationPlanPreview,
    directive_candidates: tuple[RuntimeDirectiveCandidate, ...],
) -> OperationGatePreflightPreview:
    checks: list[OperationGatePreflightCheck] = []
    for candidate in directive_candidates:
        operation_refs = candidate.operation_refs or ("model.main_response",)
        for operation_id in operation_refs:
            checks.append(
                OperationGatePreflightCheck(
                    check_id=f"opgate-preflight:{candidate.directive_candidate_id}:{operation_id}",
                    operation_id=operation_id,
                    directive_candidate_ref=candidate.directive_candidate_id,
                    resource_policy_ref=candidate.resource_policy_ref or plan.resource_policy_ref,
                    decision="deny",
                    reason="runtime directive candidate cannot enter OperationGate as executable input",
                    required_input_type="RuntimeDirective",
                    received_input_type="RuntimeDirectiveCandidate",
                    operation_gate_passed=False,
                    runtime_executable=False,
                    diagnostics={
                        "resource_policy_ref": candidate.resource_policy_ref or plan.resource_policy_ref,
                        "resource_policy_adopted": False,
                        "adopted_resource_policy_required": True,
                        "runtime_directive_required": True,
                    },
                )
            )
    return OperationGatePreflightPreview(
        preflight_id=f"opgate-preflight:{plan.task_id}:preview",
        task_id=plan.task_id,
        plan_ref=plan.plan_id,
        resource_policy_ref=plan.resource_policy_ref,
        checks=tuple(checks),
        status="blocked",
        reason="runtime_directive_missing",
        operation_gate_required=True,
        operation_gate_passed=False,
        preview_only=True,
        runtime_executable=False,
        diagnostics={
            "check_count": len(checks),
            "operation_gate_passed": False,
            "runtime_directive_required": True,
            "adopted_resource_policy_required": True,
            "resource_policy_preview_only": True,
            "runtime_executable": False,
        },
    )


def build_directive_only_executor_preview(
    *,
    plan: OrchestrationPlanPreview,
    operation_gate_preflight: OperationGatePreflightPreview,
) -> DirectiveOnlyExecutorPreview:
    return DirectiveOnlyExecutorPreview(
        preview_id=f"executor-preflight:{plan.task_id}:directive-only:preview",
        task_id=plan.task_id,
        plan_ref=plan.plan_id,
        operation_gate_preflight_ref=operation_gate_preflight.preflight_id,
        accepted_input_type="RuntimeDirective",
        status="blocked",
        reason="runtime_directive_missing",
        operation_gate_passed=operation_gate_preflight.operation_gate_passed,
        will_dispatch=False,
        preview_only=True,
        runtime_executable=False,
        diagnostics={
            "directive_only": True,
            "operation_gate_required": True,
            "operation_gate_passed": False,
            "legacy_query_execution_rejected": True,
            "runtime_directive_candidate_rejected": True,
            "executor_dispatch_enabled": False,
        },
    )
