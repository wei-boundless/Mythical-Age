from __future__ import annotations

from typing import Any

from operations import RuntimeApprovalContext, build_operation_requirement
from soul.projection import build_soul_runtime_view
from understanding.candidate_layer import build_understanding_candidates

from .bindings import default_task_binding, merge_task_bindings
from .contracts import build_task_contract
from .definitions import select_runtime_task_definitions, select_task_definitions
from .runtime_contracts import (
    ProjectionRequirement,
    SkillRuntimeView,
    TaskPromptContract,
    skill_runtime_views_for_refs,
)
from .spec_models import TaskSpec
from .template_registry import TaskTemplateRegistry


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
    _ = approval_context
    definitions = select_runtime_task_definitions(
        user_goal,
        query_understanding=query_understanding,
    )
    current_turn_payload = dict(current_turn_context or {})
    template_registry = TaskTemplateRegistry()
    selected_template = template_registry.select_template(
        user_goal=user_goal,
        query_understanding=query_understanding,
        current_turn_context=current_turn_payload,
        definitions=definitions,
    )
    bindings = [default_task_binding(definition) for definition in definitions]
    merged_binding = merge_task_bindings(bindings)
    task_family = str(selected_template.task_family or "") or "+".join(_dedupe([definition.task_family for definition in definitions]))
    task_mode = str(selected_template.task_mode or "") or "+".join(definition.task_mode for definition in definitions)
    contract = build_task_contract(
        task_id=task_id,
        session_id=session_id,
        user_goal=user_goal,
        source=source,
        template_id=selected_template.template_id,
        task_family=task_family,
        task_mode=task_mode,
        task_spec_ref=f"taskspec:{task_id}",
    )
    skill_views = skill_runtime_views_for_refs(merged_binding.skill_scope)
    active_skill_payload = dict(active_skill or {})
    active_skill_view = _skill_runtime_view_from_active_skill(active_skill_payload)
    if active_skill_view is not None:
        skill_views = [active_skill_view, *[view for view in skill_views if view.skill_id != active_skill_view.skill_id]]
    runtime_operations = _dedupe(list(runtime_required_operations or ()))
    operation_requirement = build_operation_requirement(
        task_id=contract.task_id,
        source="task_binding",
        operation_scope=merged_binding.operation_scope,
        denied_operations=merged_binding.denied_operations,
        default_operation_requirements=tuple(
            _dedupe(
                [
                    "op.model_response",
                    *runtime_operations,
                    *list(selected_template.required_operations),
                    *[
                        operation
                        for definition in definitions
                        for operation in definition.default_operation_requirements
                    ],
                ]
            )
        ),
        skill_required_operations=tuple(
            _dedupe(
                [
                    *list(selected_template.optional_operations),
                    *[operation for skill in skill_views for operation in skill.required_operations],
                ]
            )
        ),
        approval_policy=merged_binding.approval_policy,
        review_policy=merged_binding.review_policy,
        reason="derived from TaskTemplate, TaskDefinition, TaskBinding, and SkillRuntimeView",
    )
    task_spec = _build_task_spec(
        task_id=task_id,
        session_id=session_id,
        user_goal=user_goal,
        selected_template=selected_template,
        definitions=definitions,
        current_turn_context=current_turn_payload,
        query_understanding=dict(query_understanding or {}),
        operation_requirement_ref=operation_requirement.requirement_id,
        active_skill=active_skill_payload,
    )
    projection_requirement = ProjectionRequirement(
        task_id=contract.task_id,
        role_type=merged_binding.projection_selector,
        posture_tags=tuple(_projection_tags(task_mode)),
        attention_focus=("task_goal", "method", "output"),
        reason="derived from task binding and selected definitions",
    )
    task_prompt_contract = TaskPromptContract(
        contract_id=f"task-prompt:{contract.task_id}:runtime",
        task_id=contract.task_id,
        definition_id=merged_binding.definition_id,
        binding_id=merged_binding.binding_id,
        task_section=_task_section(contract.user_goal, definitions),
        method_section=_method_section(skill_views),
        resource_section="",
        projection_section=_projection_section(projection_requirement),
        output_section=_output_section(definitions),
        guardrail_section="",
        metadata={
            "runtime_directive_enabled": True,
            "runtime_executable": True,
            "section_sources": {
                "task_section": "TaskContract/TaskTemplate/TaskDefinition",
                "method_section": "SkillRuntimeView",
                "projection_section": "ProjectionRequirement",
                "output_section": "TaskTemplate.output_schema + TaskDefinition.output_contract",
            },
        },
    )
    soul_runtime = build_soul_runtime_view(
        task_prompt_contract=task_prompt_contract,
        projection_requirement=projection_requirement,
        skill_views=skill_views,
        resource_views=[],
    )
    task_contract_payload = contract.to_dict()
    if current_turn_payload:
        task_contract_payload["execution_mode"] = _task_contract_execution_mode(current_turn_payload)
        task_contract_payload["current_turn_context_ref"] = str(
            current_turn_payload.get("authority") or "context.current_turn"
        )
        task_contract_payload["bindings"] = {
            **dict(task_contract_payload.get("bindings") or {}),
            "current_turn": current_turn_payload,
        }
    task_contract_payload["selected_template_id"] = selected_template.template_id
    task_contract_payload["requested_outputs"] = list(task_spec.requested_outputs)
    operation_requirement_payload = operation_requirement.to_dict()
    task_prompt_contract_payload = task_prompt_contract.to_dict()
    prompt_manifest_payload = soul_runtime["prompt_manifest"]
    understanding_candidates = build_understanding_candidates(
        task_id=contract.task_id,
        message=user_goal,
    )
    return {
        "task_contract": task_contract_payload,
        "definitions": [definition.to_dict() for definition in definitions],
        "selected_template": selected_template.to_dict(),
        "task_spec": task_spec.to_dict(),
        "binding": merged_binding.to_dict(),
        "skill_runtime_views": [view.to_dict() for view in skill_views],
        "operation_requirement": operation_requirement_payload,
        "projection_requirement": projection_requirement.to_dict(),
        "task_prompt_contract": task_prompt_contract_payload,
        "soul_runtime_view": soul_runtime["runtime_view"],
        "soul_projection_request": soul_runtime["projection_request"],
        "prompt_manifest": prompt_manifest_payload,
        "agent_prompt_bundle": soul_runtime["agent_prompt_bundle"],
        "memory_runtime_view": dict(memory_runtime_view or {}),
        "context_policy_result": dict(context_policy_result or {}),
        "query_understanding": dict(query_understanding or {}),
        "current_turn_context": current_turn_payload,
        "active_skill": active_skill_payload,
        "understanding_candidates": [candidate.to_dict() for candidate in understanding_candidates],
        "runtime_executable": True,
        "status": "runtime",
    }


def _task_section(user_goal: str, definitions: list[Any]) -> str:
    definition_ids = ", ".join(definition.definition_id for definition in definitions)
    criteria = "; ".join(
        criterion for definition in definitions for criterion in definition.completion_criteria
    )
    return f"Goal: {user_goal}\nTask definitions: {definition_ids}\nCompletion criteria: {criteria}"


def _method_section(skill_views: list[Any]) -> str:
    if not skill_views:
        return ""
    return "\n".join(f"- {view.title}: {view.method_summary}" for view in skill_views)


def _skill_runtime_view_from_active_skill(active_skill: dict[str, Any]) -> SkillRuntimeView | None:
    if not active_skill:
        return None
    prompt_view = dict(active_skill.get("prompt_view") or {})
    tool_scope = dict(active_skill.get("tool_scope") or {})
    skill_id = str(active_skill.get("name") or prompt_view.get("name") or "").strip()
    if not skill_id:
        return None
    title = str(active_skill.get("title") or prompt_view.get("title") or skill_id).strip()
    capability = str(prompt_view.get("capability") or "").strip()
    use_when = str(prompt_view.get("use_when") or "").strip()
    output_rule = str(prompt_view.get("output_rule") or "").strip()
    method_parts = [part for part in (capability, use_when, output_rule) if part]
    return SkillRuntimeView(
        skill_id=f"skill.{skill_id}",
        title=title,
        task_reason=", ".join(list(active_skill.get("reasons") or ())) or "Selected by skill policy.",
        method_summary=" ".join(method_parts) or title,
        output_boundary=output_rule,
        required_operations=tuple(
            _dedupe(
                [
                    str(item or "").strip()
                    for item in list(tool_scope.get("allowed_tools") or ())
                    if str(item or "").strip().startswith("op.")
                ]
            )
        ),
    )


def _resource_section(resource_views: list[Any]) -> str:
    runtime_tools = [view.resource_id for view in resource_views if view.runtime_executable]
    if not runtime_tools:
        return ""
    return f"可用工具: {', '.join(runtime_tools)}."


def _projection_section(requirement: ProjectionRequirement) -> str:
    return (
        f"Projection role: {requirement.role_type}. "
        f"Posture tags: {', '.join(requirement.posture_tags) or 'none'}."
    )


def _output_section(definitions: list[Any]) -> str:
    modes = ", ".join(definition.task_mode for definition in definitions)
    direct_execution = any(str(definition.task_mode or "") == "capability_execution" for definition in definitions)
    if direct_execution:
        return (
            f"Output should satisfy task modes: {modes}. "
            "If the request is clear and required inputs are already present, execute the relevant capability and "
            "return the result directly instead of asking for confirmation."
        )
    return f"Output should satisfy task modes: {modes}. Return a concise response."


def _projection_tags(task_mode: str) -> list[str]:
    if "capability_execution" in task_mode:
        return ["direct-execution", "result-first"]
    if "knowledge_retrieval" in task_mode:
        return ["evidence-first", "grounded-answer"]
    if "information_search" in task_mode:
        return ["evidence-first", "traceability"]
    if "inspection_and_correction" in task_mode:
        return ["risk-review", "consistency"]
    if "local_material_read" in task_mode:
        return ["structure-first", "precise"]
    return ["concise"]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _task_contract_execution_mode(current_turn_context: dict[str, Any]) -> str:
    mode = str(current_turn_context.get("execution_mode") or "").strip()
    if mode == "bundle":
        return "bundle_execution"
    return "single_agent_runtime"


def _build_task_spec(
    *,
    task_id: str,
    session_id: str,
    user_goal: str,
    selected_template,
    definitions: list[Any],
    current_turn_context: dict[str, Any],
    query_understanding: dict[str, Any],
    operation_requirement_ref: str,
    active_skill: dict[str, Any],
) -> TaskSpec:
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    resolved_bindings = [
        dict(item)
        for item in list(current_turn_context.get("resolved_bindings") or [])
        if isinstance(item, dict)
    ]
    bundle_items = [
        dict(item)
        for item in list(current_turn_context.get("bundle_items") or [])
        if isinstance(item, dict)
    ]
    requested_outputs = tuple(str(key) for key in dict(selected_template.output_schema or {}).keys()) or ("final_answer",)
    selected_skill_ids = _dedupe(
        [
            *[
                str(skill or "").strip()
                for definition in definitions
                for skill in list(getattr(definition, "default_skill_refs", ()) or ())
                if str(skill or "").strip()
            ],
            str(active_skill.get("name") or "").strip(),
        ]
    )
    return TaskSpec(
        task_id=task_id,
        task_spec_ref=f"taskspec:{task_id}",
        template_id=selected_template.template_id,
        session_id=session_id,
        user_goal=user_goal,
        inputs={
            **explicit_inputs,
            **({"bundle_items": bundle_items} if bundle_items else {}),
        },
        bindings={
            "resolved_bindings": resolved_bindings,
        },
        constraints={
            "intent": str(current_turn_context.get("intent") or query_understanding.get("intent") or ""),
            "execution_mode": str(current_turn_context.get("execution_mode") or "single"),
            "confidence": float(current_turn_context.get("confidence") or query_understanding.get("confidence") or 0.0),
            "candidate_tools": [
                str(item).strip()
                for item in list(query_understanding.get("candidate_tools") or [])
                if str(item).strip()
            ],
        },
        current_turn_context_ref=str(current_turn_context.get("authority") or ""),
        requested_outputs=requested_outputs,
        selected_agent_id=str(selected_template.default_agent_id or "agent:main"),
        selected_skill_ids=tuple(selected_skill_ids),
        operation_requirement_ref=operation_requirement_ref,
    )
