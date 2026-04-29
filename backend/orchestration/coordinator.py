from __future__ import annotations

from typing import Any

from .candidates import CandidateSet
from .plan import OrchestrationPlanPreview, build_single_agent_plan_preview


def build_preview_plan_from_task_operation(
    *,
    task_contract: dict[str, Any],
    operation_requirement: dict[str, Any],
    resource_policy: dict[str, Any],
    task_prompt_contract: dict[str, Any],
    prompt_manifest: dict[str, Any],
    topology_preview: dict[str, Any],
    candidates: CandidateSet,
) -> OrchestrationPlanPreview:
    task_id = str(task_contract.get("task_id") or "task-preview")
    operation_refs = tuple(
        str(operation_id)
        for operation_id in [
            *list(operation_requirement.get("required_operations") or []),
            *list(operation_requirement.get("optional_operations") or []),
        ]
        if str(operation_id or "").strip()
    )
    return build_single_agent_plan_preview(
        task_id=task_id,
        task_contract_ref=task_id,
        task_prompt_contract_ref=str(task_prompt_contract.get("contract_id") or ""),
        resource_policy_ref=str(resource_policy.get("policy_id") or ""),
        prompt_manifest_ref=str(prompt_manifest.get("manifest_id") or ""),
        topology_ref=str(topology_preview.get("topology_id") or ""),
        operation_refs=operation_refs,
        candidates=candidates,
    )
