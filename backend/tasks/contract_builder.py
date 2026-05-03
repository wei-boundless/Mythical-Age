from __future__ import annotations

from typing import Any

from operations import RuntimeApprovalContext
from soul.task_runtime_compat import build_legacy_task_runtime_compat_surface
from understanding.candidate_layer import build_understanding_candidates


def build_task_runtime_contract(
    *,
    session_id: str,
    user_goal: str,
    task_id: str = "task-runtime",
    source: str = "runtime",
    approval_context: RuntimeApprovalContext | None = None,
    memory_runtime_view: dict[str, Any] | None = None,
    context_policy_result: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    active_skill: dict[str, Any] | None = None,
    runtime_required_operations: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    from .assembly_builder import build_task_execution_assembly_bundle

    assembly_bundle = build_task_execution_assembly_bundle(
        session_id=session_id,
        user_goal=user_goal,
        task_id=task_id,
        source=source,
        approval_context=approval_context,
        query_understanding=query_understanding,
        current_turn_context=current_turn_context,
        active_skill=active_skill,
        runtime_required_operations=runtime_required_operations,
    )
    compat_surface = build_legacy_task_runtime_compat_surface(
        assembly_bundle=assembly_bundle,
        user_goal=user_goal,
        fallback_task_id=task_id,
    )
    task_contract_payload = dict(assembly_bundle["task_contract"] or {})
    understanding_candidates = build_understanding_candidates(
        task_id=str(task_contract_payload.get("task_id") or task_id),
        message=user_goal,
    )
    return {
        "task_contract": task_contract_payload,
        "definitions": list(assembly_bundle["definitions"] or []),
        "task_intent_contract": dict(assembly_bundle["task_intent_contract"] or {}),
        "template_match": dict(assembly_bundle["template_match"] or {}),
        "selected_template": dict(assembly_bundle["selected_template"] or {}),
        "bundle_spec": dict(assembly_bundle["bundle_spec"] or {}),
        "task_spec": dict(assembly_bundle["task_spec"] or {}),
        "binding": dict(assembly_bundle["binding"] or {}),
        "skill_runtime_views": list(assembly_bundle["skill_runtime_views"] or []),
        "projection_selection": dict(assembly_bundle["projection_selection"] or {}),
        "task_execution_assembly": dict(assembly_bundle["task_execution_assembly"] or {}),
        "specific_task_record": dict(assembly_bundle["specific_task_record"] or {}),
        "task_projection_binding": dict(assembly_bundle["task_projection_binding"] or {}),
        "task_flow_contract_binding": dict(assembly_bundle["task_flow_contract_binding"] or {}),
        "task_agent_adoption_plan": dict(assembly_bundle["task_agent_adoption_plan"] or {}),
        "task_memory_request_profile": dict(assembly_bundle["task_memory_request_profile"] or {}),
        "task_communication_protocol": dict(assembly_bundle["task_communication_protocol"] or {}),
        "coordination_task_record": dict(assembly_bundle["coordination_task_record"] or {}),
        "operation_requirement": dict(assembly_bundle["operation_requirement"] or {}),
        "projection_requirement": dict(compat_surface["projection_requirement"] or {}),
        "task_prompt_contract": dict(compat_surface["task_prompt_contract"] or {}),
        "soul_runtime_view": dict(compat_surface["soul_runtime_view"] or {}),
        "soul_projection_request": dict(compat_surface["soul_projection_request"] or {}),
        "prompt_manifest": dict(compat_surface["prompt_manifest"] or {}),
        "agent_prompt_bundle": dict(compat_surface["agent_prompt_bundle"] or {}),
        "memory_runtime_view": dict(memory_runtime_view or {}),
        "context_policy_result": dict(context_policy_result or {}),
        "query_understanding": dict(assembly_bundle["query_understanding"] or {}),
        "current_turn_context": dict(assembly_bundle["current_turn_context"] or {}),
        "active_skill": dict(assembly_bundle["active_skill"] or {}),
        "understanding_candidates": [candidate.to_dict() for candidate in understanding_candidates],
        "registered_task": dict(assembly_bundle["registered_task"] or {}),
        "runtime_executable": True,
        "status": "runtime",
    }
