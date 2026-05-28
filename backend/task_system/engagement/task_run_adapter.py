from __future__ import annotations

from typing import Any

from harness.loop.task_lifecycle import TaskRunContract

from .models import EngagementContract


def task_run_contract_from_engagement(contract: EngagementContract) -> TaskRunContract:
    output_contract = dict(contract.output_contract or {})
    acceptance_policy = dict(contract.acceptance_policy or {})
    required_artifacts = _dict_tuple(
        output_contract.get("required_artifacts")
        or output_contract.get("artifact_requirements")
        or acceptance_policy.get("required_artifacts")
    )
    required_verifications = _dict_tuple(
        output_contract.get("required_verifications")
        or acceptance_policy.get("required_verifications")
    )
    completion_criteria = _string_tuple(
        output_contract.get("completion_criteria")
        or acceptance_policy.get("completion_criteria")
    )
    if not required_artifacts and not required_verifications and not completion_criteria:
        raise ValueError("engagement task run requires output or acceptance completion evidence")
    goal = _goal(contract)
    return TaskRunContract(
        contract_id=f"taskrun-contract:{contract.contract_id}",
        contract_source="registered_engagement_plan",
        user_visible_goal=goal,
        task_run_goal=goal,
        required_artifacts=required_artifacts,
        required_verifications=required_verifications,
        completion_criteria=completion_criteria,
        resource_requirements=dict(contract.resource_requirements or {}),
        permission_requirements=dict(contract.capability_requirements or {}),
        acceptance_policy=acceptance_policy,
        recovery_policy=dict(contract.recovery_policy or {}),
        source_contract_ref=contract.contract_id,
        external_plan_ref=contract.plan_id,
        task_environment_id=contract.task_environment_id,
        runtime_profile=contract.runtime_profile.to_dict(),
        prompt_contract=dict(contract.prompt_contract or {}),
    )


def _goal(contract: EngagementContract) -> str:
    prompt = dict(contract.prompt_contract or {})
    output = dict(contract.output_contract or {})
    return str(
        prompt.get("user_visible_goal")
        or prompt.get("goal")
        or output.get("user_visible_goal")
        or output.get("goal")
        or contract.plan_id
    ).strip()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        values = []
    return tuple(str(item).strip() for item in values if str(item).strip())


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(value, dict):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        values = []
    return tuple(dict(item) for item in values if isinstance(item, dict))

