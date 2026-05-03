from __future__ import annotations

from typing import Any

from soul.projection import build_soul_runtime_view
from tasks.runtime_contracts import ProjectionRequirement, SkillRuntimeView, TaskPromptContract


def build_legacy_task_runtime_compat_surface(
    *,
    assembly_bundle: dict[str, Any],
    user_goal: str,
    fallback_task_id: str,
) -> dict[str, Any]:
    definitions = list(assembly_bundle["_definitions_obj"])
    selected_template = assembly_bundle["_selected_template_obj"]
    merged_binding = assembly_bundle["_merged_binding_obj"]
    task_workflow = dict(assembly_bundle["_task_workflow_obj"] or {})
    projection_selection = assembly_bundle["_projection_selection_obj"]
    task_contract_payload = dict(assembly_bundle["task_contract"] or {})
    registered_task = dict(assembly_bundle["registered_task"] or {})
    skill_views = [
        SkillRuntimeView(**dict(item))
        for item in list(assembly_bundle["skill_runtime_views"] or [])
        if isinstance(item, dict)
    ]
    task_id = str(task_contract_payload.get("task_id") or fallback_task_id)
    projection_requirement = _build_projection_requirement_from_selection(
        task_id=task_id,
        projection_selection=projection_selection,
        fallback_role_type=str(merged_binding.projection_selector or "task_default"),
    )
    task_prompt_contract = TaskPromptContract(
        contract_id=f"task-prompt:{task_id}:runtime",
        task_id=task_id,
        definition_id=merged_binding.definition_id,
        binding_id=merged_binding.binding_id,
        task_section=_task_section(str(task_contract_payload.get("user_goal") or user_goal), definitions),
        workflow_section=_workflow_section(task_workflow, selected_template, skill_views),
        resource_section="",
        projection_section=_projection_section(projection_requirement),
        output_section=_output_section(definitions),
        guardrail_section="",
        metadata={
            "runtime_directive_enabled": True,
            "runtime_executable": True,
            "section_sources": {
                "task_section": "TaskContract/TaskTemplate/TaskDefinition",
                "workflow_section": "TaskWorkflowBinding/TaskTemplate/SkillRuntimeView",
                "projection_section": "ProjectionSelectionResult",
                "output_section": "TaskTemplate.output_schema + TaskDefinition.output_contract",
            },
            "registered_task_id": registered_task["task_id"] if registered_task else "",
            "registered_task_type": registered_task["task_type"] if registered_task else "",
            "workflow_id": (task_workflow or {}).get("workflow_id") or "",
            "projection_id": projection_requirement.projection_id,
            "projection_source": projection_selection.selection_source or "task_binding",
        },
    )
    soul_runtime = build_soul_runtime_view(
        task_prompt_contract=task_prompt_contract,
        projection_requirement=projection_requirement,
        skill_views=skill_views,
        resource_views=[],
    )
    return {
        "projection_requirement": projection_requirement.to_dict(),
        "task_prompt_contract": task_prompt_contract.to_dict(),
        "soul_runtime_view": soul_runtime["runtime_view"],
        "soul_projection_request": soul_runtime["projection_request"],
        "prompt_manifest": soul_runtime["prompt_manifest"],
        "agent_prompt_bundle": soul_runtime["agent_prompt_bundle"],
    }


def _build_projection_requirement_from_selection(
    *,
    task_id: str,
    projection_selection: Any,
    fallback_role_type: str,
) -> ProjectionRequirement:
    selection_source = str(getattr(projection_selection, "selection_source", "") or "task_binding").strip()
    reason_by_source = {
        "current_turn_context": "selected by current turn context",
        "registered_task": "selected by registered task binding",
        "workflow": "selected by workflow compatibility",
        "task_binding": "derived from task binding role and task mode",
    }
    posture_tags = tuple(
        str(item).strip()
        for item in list(getattr(projection_selection, "posture_tags", ()) or ())
        if str(item).strip()
    ) or ("concise",)
    return ProjectionRequirement(
        task_id=task_id,
        role_type=str(getattr(projection_selection, "role_type", "") or fallback_role_type or "task_default"),
        posture_tags=posture_tags,
        attention_focus=("task_goal", "workflow", "output"),
        projection_id=str(getattr(projection_selection, "selected_projection_id", "") or "").strip(),
        reason=reason_by_source.get(selection_source, "derived from task-side projection selection"),
    )


def _task_section(user_goal: str, definitions: list[Any]) -> str:
    definition_ids = ", ".join(definition.definition_id for definition in definitions)
    criteria = "; ".join(
        criterion for definition in definitions for criterion in definition.completion_criteria
    )
    return f"Goal: {user_goal}\nTask definitions: {definition_ids}\nCompletion criteria: {criteria}"


def _workflow_section(
    workflow: dict[str, Any] | None,
    selected_template,
    skill_views: list[Any],
) -> str:
    workflow = dict(workflow or {})
    title = str(workflow.get("title") or workflow.get("workflow_id") or selected_template.title or "未命名工作流").strip()
    workflow_id = str(workflow.get("workflow_id") or "").strip()
    task_mode = str(workflow.get("task_mode") or selected_template.task_mode or "").strip()
    raw_steps = workflow.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    step_titles = [
        str(item.get("title") or item.get("step_id") or "").strip()
        for item in steps
        if isinstance(item, dict) and str(item.get("title") or item.get("step_id") or "").strip()
    ]
    if not step_titles:
        step_titles = [
            str(step.title or step.step_id or "").strip()
            for step in list(getattr(selected_template, "step_blueprints", ()) or ())
            if str(step.title or step.step_id or "").strip()
        ]
    visible_skill_ids = workflow.get("visible_skill_ids")
    workflow_skills = [
        str(item).strip()
        for item in (visible_skill_ids if isinstance(visible_skill_ids, list) else [])
        if str(item).strip()
    ]
    if not workflow_skills:
        workflow_skills = [view.skill_id for view in skill_views if str(view.skill_id or "").strip()]
    stop_conditions = [
        str(item).strip()
        for item in list(workflow.get("stop_conditions") or [])
        if str(item).strip()
    ]
    evidence_refs = [
        str(item).strip()
        for item in list(workflow.get("required_evidence_refs") or [])
        if str(item).strip()
    ]
    output_boundary = str(
        workflow.get("output_boundary")
        or workflow.get("output_contract_id")
        or selected_template.output_schema
        or ""
    ).strip()
    lines = [
        f"Workflow: {title}",
        f"Workflow ID: {workflow_id or 'template_runtime'}",
        f"Task mode: {task_mode or 'runtime'}",
    ]
    if step_titles:
        lines.append(f"Steps: {' -> '.join(step_titles)}")
    if workflow_skills:
        lines.append(f"Visible skills: {', '.join(workflow_skills)}")
    if stop_conditions:
        lines.append(f"Stop conditions: {'; '.join(stop_conditions)}")
    if evidence_refs:
        lines.append(f"Required evidence refs: {', '.join(evidence_refs)}")
    if output_boundary:
        lines.append(f"Output boundary: {output_boundary}")
    return "\n".join(lines)


def _projection_section(requirement: ProjectionRequirement) -> str:
    lines = [
        f"Projection role: {requirement.role_type}.",
        f"Posture tags: {', '.join(requirement.posture_tags) or 'none'}.",
    ]
    if requirement.projection_id:
        lines.append(f"Projection ID: {requirement.projection_id}.")
    if requirement.soul_id:
        lines.append(f"Soul: {requirement.soul_id}.")
    if requirement.projection_title:
        lines.append(f"Projection title: {requirement.projection_title}.")
    if requirement.expression_density:
        lines.append(f"Expression density: {requirement.expression_density}.")
    if requirement.attention_focus:
        lines.append(f"Attention focus: {', '.join(requirement.attention_focus)}.")
    if requirement.projection_prompt:
        lines.append("Projection prompt:")
        lines.append(requirement.projection_prompt)
    return "\n".join(lines)


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
