from __future__ import annotations

from typing import Any

from .models import EngagementAdmissionResult, ResolvedEngagementPlan


SUPPORTED_STRATEGIES = {"turn_contract", "turn_execution", "single_agent_task_run", "workflow_run", "human_gate"}


def admit_engagement(resolved: ResolvedEngagementPlan) -> EngagementAdmissionResult:
    input_errors = _input_errors(resolved.request.startup_parameters, resolved.plan.input_contract)
    environment_errors: list[str] = []
    capability_errors: list[str] = list(resolved.missing_refs)
    strategy_kind = resolved.execution_strategy.kind
    if resolved.plan.status != "active":
        environment_errors.append(f"plan_status_not_active:{resolved.plan.status}")
    if strategy_kind not in SUPPORTED_STRATEGIES:
        environment_errors.append(f"unsupported_strategy:{strategy_kind}")
    if strategy_kind == "single_agent_task_run":
        if not _has_completion_contract(resolved.plan.output_contract, resolved.plan.acceptance_policy):
            input_errors.append("task_run_completion_contract_required")
    decision = "allow"
    reason = ""
    if input_errors:
        decision = "ask_user" if any(item.startswith("missing_input:") for item in input_errors) else "invalid"
        reason = "启动参数不满足任务合同。"
    if capability_errors:
        decision = "invalid"
        reason = "承接者配置不完整。"
    if environment_errors:
        decision = "invalid"
        reason = "任务计划状态、环境或执行策略无效。"
    return EngagementAdmissionResult(
        decision=decision,  # type: ignore[arg-type]
        plan_ref=resolved.plan.plan_id,
        resolved_task_environment_id=resolved.plan.task_environment_id,
        resolved_agent_profile_id=str(resolved.assignee_profile.get("agent_profile_id") or ""),
        execution_strategy=resolved.execution_strategy.to_dict(),
        input_errors=tuple(input_errors),
        capability_errors=tuple(capability_errors),
        environment_errors=tuple(environment_errors),
        user_visible_reason=reason,
    )


def _input_errors(parameters: dict[str, Any], input_contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = input_contract.get("required") or input_contract.get("required_fields") or ()
    if isinstance(required, str):
        required = [required]
    if not isinstance(required, (list, tuple)):
        return errors
    for field in required:
        key = str(field or "").strip()
        if key and key not in parameters:
            errors.append(f"missing_input:{key}")
    return errors


def _has_completion_contract(output_contract: dict[str, Any], acceptance_policy: dict[str, Any]) -> bool:
    if output_contract.get("required_artifacts") or output_contract.get("required_verifications"):
        return True
    if output_contract.get("completion_criteria") or output_contract.get("artifact_requirements"):
        return True
    if acceptance_policy.get("required_artifacts") or acceptance_policy.get("required_verifications"):
        return True
    if acceptance_policy.get("completion_criteria"):
        return True
    return False

