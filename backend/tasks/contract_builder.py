from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import AgentRegistry, RuntimeApprovalContext, build_operation_requirement
from soul.projection import build_soul_runtime_view
from soul.projection_store import get_projection_card
from understanding.candidate_layer import build_understanding_candidates

from .bindings import default_task_binding, merge_task_bindings
from .bundle_models import BundleItemSpec, BundleSpec
from .contracts import build_task_contract
from .definitions import select_runtime_task_definitions, select_task_definitions
from .flow_registry import TaskFlowRegistry
from .runtime_contracts import (
    ProjectionRequirement,
    SkillRuntimeView,
    TaskPromptContract,
    skill_runtime_views_for_refs,
)
from .spec_models import TaskSpec
from .step_models import StepInputBinding, TaskStepBlueprint
from .template_registry import TaskTemplateRegistry
from .workflow_registry import TaskWorkflowRegistry


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
    registry_base_dir = Path(__file__).resolve().parents[1]
    template_registry = TaskTemplateRegistry(registry_base_dir)
    flow_registry = TaskFlowRegistry(registry_base_dir)
    workflow_registry = TaskWorkflowRegistry(registry_base_dir)
    registered_task = _resolve_registered_task(
        flow_registry=flow_registry,
        current_turn_context=current_turn_payload,
    )
    task_intent_contract = template_registry.build_task_intent_contract(
        session_id=session_id,
        task_id=task_id,
        user_goal=user_goal,
        query_understanding=query_understanding,
        current_turn_context=current_turn_payload,
    )
    template_match = template_registry.match_template(
        task_intent_contract=task_intent_contract,
        query_understanding=query_understanding,
        current_turn_context=current_turn_payload,
        definitions=definitions,
    )
    selected_template = template_registry.get_template(template_match.template_id)
    if selected_template is None:
        raise ValueError(f"Unknown template selected: {template_match.template_id}")
    bundle_spec = _build_bundle_spec(
        task_id=task_id,
        current_turn_context=current_turn_payload,
    )
    bindings = [default_task_binding(definition) for definition in definitions]
    merged_binding = merge_task_bindings(bindings)
    task_family = _resolve_task_family(
        registered_task=registered_task,
        selected_template=selected_template,
        definitions=definitions,
    )
    task_mode = _resolve_task_mode(
        registered_task=registered_task,
        selected_template=selected_template,
        definitions=definitions,
    )
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
        registered_task=registered_task,
        task_intent_contract=task_intent_contract,
        template_match=template_match,
        bundle_spec=bundle_spec,
        definitions=definitions,
        current_turn_context=current_turn_payload,
        query_understanding=dict(query_understanding or {}),
        operation_requirement_ref=operation_requirement.requirement_id,
        active_skill=active_skill_payload,
    )
    selected_agent_id = str(task_spec.selected_agent_id or "agent:0").strip() or "agent:0"
    task_workflow = _resolve_task_workflow(
        flow_registry=flow_registry,
        workflow_registry=workflow_registry,
        registered_task=registered_task,
        selected_template=selected_template,
        definitions=definitions,
        current_turn_context=current_turn_payload,
        task_mode=task_mode,
    )
    projection_card = _resolve_projection_card(
        registry_base_dir=registry_base_dir,
        flow_registry=flow_registry,
        workflow_registry=workflow_registry,
        selected_agent_id=selected_agent_id,
        registered_task=registered_task,
        task_workflow=task_workflow,
        selected_template=selected_template,
        current_turn_context=current_turn_payload,
        task_mode=task_mode,
    )
    projection_requirement = _build_projection_requirement(
        contract.task_id,
        fallback_role_type=merged_binding.projection_selector,
        fallback_tags=tuple(_projection_tags(task_mode)),
        projection_card=projection_card,
    )
    task_prompt_contract = TaskPromptContract(
        contract_id=f"task-prompt:{contract.task_id}:runtime",
        task_id=contract.task_id,
        definition_id=merged_binding.definition_id,
        binding_id=merged_binding.binding_id,
        task_section=_task_section(contract.user_goal, definitions),
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
                "projection_section": "ProjectionRequirement",
                "output_section": "TaskTemplate.output_schema + TaskDefinition.output_contract",
            },
            "registered_task_id": registered_task["task_id"] if registered_task else "",
            "registered_task_type": registered_task["task_type"] if registered_task else "",
            "workflow_id": (task_workflow or {}).get("workflow_id") or "",
            "projection_id": projection_requirement.projection_id,
            "projection_source": "projection_card" if projection_card else "task_binding",
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
    task_contract_payload["task_intent_ref"] = task_intent_contract.task_intent_id
    task_contract_payload["template_match_ref"] = template_match.match_id
    task_contract_payload["bundle_spec_ref"] = bundle_spec.bundle_id if bundle_spec is not None else ""
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
        "task_intent_contract": task_intent_contract.to_dict(),
        "template_match": template_match.to_dict(),
        "selected_template": selected_template.to_dict(),
        "bundle_spec": bundle_spec.to_dict() if bundle_spec is not None else {},
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
        "registered_task": dict(registered_task or {}),
        "runtime_executable": True,
        "status": "runtime",
    }


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


def _build_projection_requirement(
    task_id: str,
    *,
    fallback_role_type: str,
    fallback_tags: tuple[str, ...],
    projection_card: dict[str, Any] | None,
) -> ProjectionRequirement:
    if projection_card:
        posture_tags = tuple(str(item) for item in list(projection_card.get("posture_tags") or []) if str(item))
        attention_focus = tuple(str(item) for item in list(projection_card.get("attention_focus") or []) if str(item))
        return ProjectionRequirement(
            task_id=task_id,
            role_type=str(projection_card.get("role_type") or fallback_role_type or "runtime"),
            posture_tags=posture_tags or fallback_tags,
            expression_density=str(projection_card.get("expression_density") or "normal"),
            attention_focus=attention_focus or ("task_goal", "workflow", "output"),
            projection_id=str(projection_card.get("projection_id") or ""),
            soul_id=str(projection_card.get("soul_id") or ""),
            projection_title=str(projection_card.get("title") or ""),
            projection_prompt=str(projection_card.get("projection_prompt") or ""),
            reason="selected by task projection assignment",
        )
    return ProjectionRequirement(
        task_id=task_id,
        role_type=fallback_role_type,
        posture_tags=fallback_tags,
        attention_focus=("task_goal", "workflow", "output"),
        reason="derived from task binding and selected definitions",
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


def _resolve_task_workflow(
    *,
    flow_registry: TaskFlowRegistry,
    workflow_registry: TaskWorkflowRegistry,
    registered_task: dict[str, Any] | None,
    selected_template,
    definitions: list[Any],
    current_turn_context: dict[str, Any],
    task_mode: str,
) -> dict[str, Any] | None:
    if registered_task:
        registered_workflow_id = str(registered_task.get("workflow_id") or "").strip()
        if registered_workflow_id:
            workflow = workflow_registry.get_workflow(registered_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    explicit_workflow_id = str(
        current_turn_context.get("workflow_id")
        or current_turn_context.get("task_workflow_id")
        or ""
    ).strip()
    if explicit_workflow_id:
        workflow = workflow_registry.get_workflow(explicit_workflow_id)
        if workflow is not None:
            return workflow.to_dict()

    linked_flow_id = str(getattr(selected_template, "metadata", {}).get("linked_flow_id") or "").strip()
    if linked_flow_id:
        flow = flow_registry.get_flow(linked_flow_id)
        if flow is not None and flow.default_workflow_id:
            workflow = workflow_registry.get_workflow(flow.default_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    for definition in definitions:
        definition_mode = str(getattr(definition, "task_mode", "") or "").strip()
        matched_flow = next(
            (flow for flow in flow_registry.list_flows() if flow.task_mode == definition_mode and flow.default_workflow_id),
            None,
        )
        if matched_flow is not None:
            workflow = workflow_registry.get_workflow(matched_flow.default_workflow_id)
            if workflow is not None:
                return workflow.to_dict()

    matched_flow = next(
        (flow for flow in flow_registry.list_flows() if flow.task_mode == task_mode and flow.default_workflow_id),
        None,
    )
    if matched_flow is not None:
        workflow = workflow_registry.get_workflow(matched_flow.default_workflow_id)
        if workflow is not None:
            return workflow.to_dict()
    return None


def _resolve_projection_card(
    *,
    registry_base_dir: Path,
    flow_registry: TaskFlowRegistry,
    workflow_registry: TaskWorkflowRegistry,
    selected_agent_id: str,
    registered_task: dict[str, Any] | None,
    task_workflow: dict[str, Any] | None,
    selected_template,
    current_turn_context: dict[str, Any],
    task_mode: str,
) -> dict[str, Any] | None:
    if registered_task:
        registered_projection_id = str(registered_task.get("projection_id") or "").strip()
        if registered_projection_id:
            card = get_projection_card(registry_base_dir, registered_projection_id)
            if card is not None:
                return card

    explicit_projection_id = str(
        current_turn_context.get("projection_id")
        or current_turn_context.get("projection_card_id")
        or current_turn_context.get("selected_projection_id")
        or ""
    ).strip()
    if explicit_projection_id:
        card = get_projection_card(registry_base_dir, explicit_projection_id)
        if card is not None:
            return card

    agent_projection_id = _resolve_agent_default_projection_id(
        registry_base_dir=registry_base_dir,
        agent_id=selected_agent_id,
    )
    if agent_projection_id:
        card = get_projection_card(registry_base_dir, agent_projection_id)
        if card is not None:
            return card

    return None


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
    registered_task: dict[str, Any] | None,
    task_intent_contract,
    template_match,
    bundle_spec,
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
    step_input_bindings = _build_step_input_bindings(
        selected_template=selected_template,
        current_turn_context=current_turn_context,
        bundle_spec=bundle_spec,
    )
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
            **({"bundle_spec": bundle_spec.to_dict()} if bundle_spec is not None else {}),
        },
        bindings={
            "resolved_bindings": resolved_bindings,
        },
        constraints={
            "intent": str(current_turn_context.get("intent") or query_understanding.get("intent") or ""),
            "execution_mode": str(current_turn_context.get("execution_mode") or "single"),
            "confidence": float(current_turn_context.get("confidence") or query_understanding.get("confidence") or 0.0),
            "template_match_source": str(template_match.match_source or ""),
            "template_match_reasons": list(template_match.match_reasons),
            "candidate_tools": [
                str(item).strip()
                for item in list(query_understanding.get("candidate_tools") or [])
                if str(item).strip()
            ],
        },
        current_turn_context_ref=str(current_turn_context.get("authority") or ""),
        task_intent_ref=str(task_intent_contract.task_intent_id or ""),
        template_match_ref=str(template_match.match_id or ""),
        bundle_spec_ref=bundle_spec.bundle_id if bundle_spec is not None else "",
        bundle_item_ref=_single_bundle_item_ref(bundle_spec),
        requested_outputs=requested_outputs,
        step_input_bindings=step_input_bindings,
        selected_agent_id=_resolve_selected_agent_id(
            registered_task=registered_task,
            current_turn_context=current_turn_context,
            selected_template=selected_template,
        ),
        selected_skill_ids=tuple(selected_skill_ids),
        operation_requirement_ref=operation_requirement_ref,
    )


def _resolve_registered_task(
    *,
    flow_registry: TaskFlowRegistry,
    current_turn_context: dict[str, Any],
) -> dict[str, Any] | None:
    specific_task_id = str(
        current_turn_context.get("selected_task_id")
        or current_turn_context.get("specific_task_id")
        or current_turn_context.get("task_assignment_id")
        or ""
    ).strip()
    if specific_task_id:
        assignment = flow_registry.get_task_assignment(specific_task_id)
        if assignment is not None:
            return {
                "task_type": "specific_task",
                "task_id": assignment.task_id,
                "task_title": assignment.task_title,
                "task_family": assignment.task_family,
                "task_mode": assignment.task_mode,
                "default_agent_id": assignment.default_agent_id,
                "workflow_id": assignment.workflow_id,
                "projection_id": assignment.projection_id,
                "input_contract_id": assignment.input_contract_id,
                "output_contract_id": assignment.output_contract_id,
                "metadata": dict(assignment.metadata or {}),
            }
    default_general_profile = next(
        (profile for profile in flow_registry.list_general_task_profiles() if profile.enabled),
        None,
    )
    if default_general_profile is None:
        return None
    return {
        "task_type": "general_task",
        "task_id": default_general_profile.profile_id,
        "task_title": default_general_profile.title,
        "task_family": "general",
        "task_mode": "general_task",
        "default_agent_id": default_general_profile.default_agent_id,
        "workflow_id": default_general_profile.default_workflow_id,
        "projection_id": default_general_profile.default_projection_id,
        "input_contract_id": default_general_profile.input_contract_id,
        "output_contract_id": default_general_profile.output_contract_id,
        "metadata": dict(default_general_profile.metadata or {}),
    }


def _resolve_selected_agent_id(
    *,
    registered_task: dict[str, Any] | None,
    current_turn_context: dict[str, Any],
    selected_template,
) -> str:
    explicit_agent_id = str(
        current_turn_context.get("selected_agent_id")
        or current_turn_context.get("agent_id")
        or ""
    ).strip()
    if explicit_agent_id:
        return explicit_agent_id
    registered_agent_id = str((registered_task or {}).get("default_agent_id") or "").strip()
    if registered_agent_id:
        return registered_agent_id
    return str(selected_template.default_agent_id or "agent:0")


def _resolve_agent_default_projection_id(
    *,
    registry_base_dir: Path,
    agent_id: str,
) -> str:
    if str(agent_id or "").strip() == "agent:0":
        return ""
    agent = AgentRegistry(registry_base_dir).get_agent(agent_id)
    if agent is None:
        return ""
    return str(agent.default_projection_id or "").strip()


def _resolve_task_family(
    *,
    registered_task: dict[str, Any] | None,
    selected_template,
    definitions: list[Any],
) -> str:
    registered_family = str((registered_task or {}).get("task_family") or "").strip()
    if registered_family:
        return registered_family
    return str(selected_template.task_family or "") or "+".join(
        _dedupe([definition.task_family for definition in definitions])
    )


def _resolve_task_mode(
    *,
    registered_task: dict[str, Any] | None,
    selected_template,
    definitions: list[Any],
) -> str:
    registered_mode = str((registered_task or {}).get("task_mode") or "").strip()
    if registered_mode:
        return registered_mode
    return str(selected_template.task_mode or "") or "+".join(
        definition.task_mode for definition in definitions
    )


def _build_bundle_spec(
    *,
    task_id: str,
    current_turn_context: dict[str, Any],
) -> BundleSpec | None:
    bundle_items = [
        dict(item)
        for item in list(current_turn_context.get("bundle_items") or [])
        if isinstance(item, dict)
    ]
    if not bundle_items:
        return None
    bundle_id = str(current_turn_context.get("bundle_id") or f"bundle:{task_id}").strip()
    item_specs: list[BundleItemSpec] = []
    for item in bundle_items:
        ordinal = int(item.get("ordinal") or 0)
        capability_kind = str(item.get("capability_kind") or "")
        bundle_id = str(current_turn_context.get("bundle_id") or f"bundle:{task_id}")
        item_specs.append(
            BundleItemSpec(
                item_id=str(item.get("item_id") or f"{bundle_id}:item:{ordinal or len(item_specs) + 1}"),
                ordinal=ordinal,
                user_text=str(item.get("user_text") or ""),
                template_id=str(item.get("template_id") or _template_id_for_capability(capability_kind)),
                capability_kind=capability_kind,
                required_tool=str(item.get("required_tool") or ""),
                requested_outputs=tuple(
                    str(value).strip()
                    for value in list(item.get("requested_outputs") or [])
                    if str(value).strip()
                ),
                inherited_binding_refs=tuple(
                    str(value).strip()
                    for value in list(item.get("inherited_binding_refs") or [])
                    if str(value).strip()
                ),
                target_binding_ref=str(
                    item.get("target_binding_ref")
                    or (
                        dict(item.get("target_binding") or {}).get("binding_id")
                        if isinstance(item.get("target_binding"), dict)
                        else ""
                    )
                    or ""
                ),
                followup_target_ref=str(item.get("followup_target_ref") or item.get("target_ref") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return BundleSpec(
        bundle_id=bundle_id,
        parent_task_id=task_id,
        aggregation_policy="ordered_sections",
        items=tuple(item_specs),
        diagnostics={
            "item_count": len(item_specs),
            "execution_mode": str(current_turn_context.get("execution_mode") or "single"),
        },
    )


def _build_step_input_bindings(
    *,
    selected_template,
    current_turn_context: dict[str, Any],
    bundle_spec: BundleSpec | None,
) -> tuple[StepInputBinding, ...]:
    explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
    resolved_bindings = [
        dict(item)
        for item in list(current_turn_context.get("resolved_bindings") or [])
        if isinstance(item, dict)
    ]
    inherited_binding_refs = tuple(
        _dedupe(
            [
                str(item.get("binding_id") or "").strip()
                for item in resolved_bindings
                if str(item.get("binding_id") or "").strip()
            ]
        )
    )
    explicit_input_refs = tuple(
        _dedupe(
            [f"input.{key}" for key, value in explicit_inputs.items() if value not in ("", None, [], {})]
        )
    )
    step_bindings: list[StepInputBinding] = []
    previous_step_id = ""
    for blueprint in list(getattr(selected_template, "step_blueprints", ()) or ()):
        blueprint_input_refs = tuple(str(item).strip() for item in list(blueprint.input_refs or ()) if str(item).strip())
        computed_input_refs = list(blueprint_input_refs)
        if bundle_spec is not None:
            computed_input_refs.append("input.bundle_spec")
        elif explicit_input_refs:
            computed_input_refs.extend(list(explicit_input_refs))
        private_state_refs: list[str] = []
        if previous_step_id:
            private_state_refs.append(f"step_output:{previous_step_id}")
        binding_policy = "inherit_parent_context"
        if bundle_spec is not None and str(selected_template.template_id or "") != "template.bundle.multi_capability":
            binding_policy = "bundle_item_private_context"
        output_writebacks = _step_output_writebacks(
            template_id=str(selected_template.template_id or ""),
            blueprint=blueprint,
            bundle_spec=bundle_spec,
        )
        step_bindings.append(
            StepInputBinding(
                step_id=str(blueprint.step_id or ""),
                input_refs=tuple(_dedupe(computed_input_refs)),
                inherited_parent_refs=inherited_binding_refs,
                private_state_refs=tuple(_dedupe(private_state_refs)),
                output_writebacks=output_writebacks,
                binding_policy=binding_policy,
            )
        )
        previous_step_id = str(blueprint.step_id or "")
    return tuple(step_bindings)


def _step_output_writebacks(
    *,
    template_id: str,
    blueprint: TaskStepBlueprint,
    bundle_spec: BundleSpec | None,
) -> dict[str, str]:
    step_kind = str(blueprint.step_kind or "")
    if template_id == "template.bundle.multi_capability":
        if step_kind == "understand":
            return {"bundle_plan": "runtime.bundle_plan"}
        if step_kind == "finalize":
            return {"final_answer": "task_result.final_answer", "bundle_result_refs": "state.bundle_result_refs"}
    if template_id in {"template.pdf.document_analysis", "template.data.structured_analysis"}:
        if step_kind == "analyze":
            return {"task_summary_refs": "state.current_result_refs"}
        if step_kind == "finalize":
            return {"final_answer": "task_result.final_answer", "task_summary_refs": "state.current_result_refs"}
    if step_kind == "finalize":
        return {"final_answer": "task_result.final_answer"}
    if step_kind in {"write", "verify"}:
        return {"artifact_refs": "task_result.artifact_refs"}
    return {"step_result": f"runtime.step:{blueprint.step_id}:output"}


def _single_bundle_item_ref(bundle_spec: BundleSpec | None) -> str:
    if bundle_spec is None or len(bundle_spec.items) != 1:
        return ""
    return str(bundle_spec.items[0].item_id or "")


def _template_id_for_capability(capability: str) -> str:
    mapping = {
        "pdf": "template.pdf.document_analysis",
        "structured_data": "template.data.structured_analysis",
        "weather": "template.capability.direct_tool",
        "gold_price": "template.capability.direct_tool",
    }
    return mapping.get(str(capability or "").strip(), "template.chat.general_response")
