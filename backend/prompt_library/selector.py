from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import (
    PromptAssemblyPlan,
    PromptAssemblyPlanItem,
    PromptResource,
    PromptSelectionContext,
)


_RESOURCE_SECTION_IDS = {
    "common_contract": "shared_common_contract",
    "mode_policy": "mode_policy_section",
    "understanding_policy": "understanding_policy_section",
    "flow_matching_policy": "flow_matching_policy_section",
    "role_prompt": "role_prompt_section",
    "task_goal_role": "task_goal_role_prompt_section",
    "stage_role": "node_professional_prompt_section",
    "skill_prompt": "skill_prompt_section",
    "tool_guidance": "tool_guidance_section",
    "verification": "verification_section",
    "output_boundary": "output_section",
}

_RESOURCE_ORDERS = {
    "common_contract": 8,
    "mode_policy": 12,
    "understanding_policy": 18,
    "flow_matching_policy": 19,
    "role_prompt": 15,
    "task_goal_role": 25,
    "stage_role": 35,
    "skill_prompt": 45,
    "tool_guidance": 55,
    "verification": 75,
    "output_boundary": 90,
}

_BUILTIN_SECTION_PLAN = (
    ("task_section", "builtin:task_section", "runtime_task_section", "任务契约", "task", 10),
    ("semantic_task_section", "builtin:semantic_task_section", "task_requirement_contract", "语义任务契约", "task", 20),
    ("goal_understanding_section", "builtin:goal_understanding_section", "goal_understanding_contract", "目标理解", "task", 22),
    ("workflow_section", "builtin:workflow_section", "task_workflow", "工作流", "task", 30),
    ("professional_profile_section", "builtin:professional_profile_section", "professional_prompt_profile", "专业职责", "task", 40),
    ("agent_plan_section", "builtin:agent_plan_section", "agent_plan_draft", "执行计划草案", "task", 50),
    ("plan_coverage_section", "builtin:plan_coverage_section", "plan_coverage_review", "计划覆盖审查", "task", 52),
    ("completion_judgment_section", "builtin:completion_judgment_section", "completion_judgment", "完成裁决", "task", 54),
    ("mode_policy_section", "builtin:mode_policy_section", "runtime_interaction_mode_policy", "交互模式策略", "task", 60),
    ("output_section", "builtin:output_section", "runtime_output_boundary", "输出边界", "task", 95),
)


@dataclass(frozen=True, slots=True)
class _ScoredResource:
    resource: PromptResource
    score: int
    reason: str


def build_prompt_selection_context(
    *,
    task_id: str,
    user_goal: str,
    task_contract: dict[str, Any],
    task_execution_assembly: dict[str, Any],
    selected_recipe: dict[str, Any],
    task_workflow: dict[str, Any],
    registered_task: dict[str, Any],
    skill_runtime_views: list[dict[str, Any]],
    agent_id: str,
    current_turn_context: dict[str, Any] | None = None,
) -> PromptSelectionContext:
    contract = dict(task_contract or {})
    assembly = dict(task_execution_assembly or {})
    recipe = dict(selected_recipe or {})
    workflow = dict(task_workflow or {})
    registered = dict(registered_task or {})
    current_turn = dict(current_turn_context or dict(contract.get("bindings") or {}).get("current_turn") or {})
    assembly_metadata = dict(assembly.get("metadata") or {})
    recipe_metadata = dict(recipe.get("metadata") or {})
    workflow_metadata = dict(workflow.get("metadata") or {})
    registered_metadata = dict(registered.get("metadata") or {})
    registered_policy = dict(registered.get("task_policy") or {})
    registered_structure = dict(registered_policy.get("task_structure") or {})
    model_turn_decision = dict(
        current_turn.get("model_turn_decision")
        or dict(task_contract.get("bindings") or {}).get("model_turn_decision")
        or {}
    )
    action_permit = dict(
        current_turn.get("action_permit")
        or dict(task_contract.get("bindings") or {}).get("action_permit")
        or {}
    )
    boundary_policy = dict(
        current_turn.get("boundary_policy")
        or dict(task_contract.get("bindings") or {}).get("boundary_policy")
        or {}
    )
    request_facts = dict(
        current_turn.get("request_facts")
        or dict(task_contract.get("bindings") or {}).get("request_facts")
        or {}
    )
    context_binding = dict(
        current_turn.get("context_binding")
        or dict(model_turn_decision.get("context_binding_decision") or {})
        or {}
    )
    semantic_contract = dict(
        contract.get("task_requirement_contract")
        or recipe_metadata.get("task_requirement_contract")
        or assembly_metadata.get("task_requirement_contract")
        or {}
    )
    semantic_diagnostics = dict(semantic_contract.get("diagnostics") or {})
    task_goal_spec = dict(
        current_turn.get("task_goal_spec")
        or semantic_diagnostics.get("task_goal_spec")
        or {}
    )
    goal_hypothesis_set = dict(
        semantic_diagnostics.get("goal_hypothesis_set")
        or dict(task_goal_spec.get("evidence") or {}).get("goal_hypothesis_set")
        or {}
    )
    agent_plan_draft = dict(
        recipe_metadata.get("agent_plan_draft")
        or assembly_metadata.get("agent_plan_draft")
        or {}
    )
    agent_plan_requirement = dict(
        recipe_metadata.get("agent_plan_requirement")
        or assembly_metadata.get("agent_plan_requirement")
        or {}
    )
    plan_coverage_review = dict(
        recipe_metadata.get("plan_coverage_review")
        or assembly_metadata.get("plan_coverage_review")
        or {}
    )
    verification_review = dict(
        recipe_metadata.get("verification_review")
        or assembly_metadata.get("verification_review")
        or {}
    )
    completion_judgment = dict(
        recipe_metadata.get("completion_judgment")
        or assembly_metadata.get("completion_judgment")
        or {}
    )
    mode_policy = dict(
        contract.get("mode_policy")
        or recipe_metadata.get("mode_policy")
        or assembly_metadata.get("mode_policy")
        or {}
    )
    workflow_steps = _normalize_steps(workflow.get("steps"), source="workflow")
    recipe_steps = _normalize_steps(recipe.get("step_blueprints"), source="recipe")
    task_graph_node_runtime = bool(
        current_turn.get("task_graph_node_runtime") is True
        or current_turn.get("suppress_bundle_projection") is True
        or assembly_metadata.get("task_graph_node_runtime") is True
        or registered_metadata.get("task_graph_node_runtime") is True
        or registered_structure.get("suppress_bundle_projection") is True
        or str(registered_structure.get("execution_chain_type") or "").strip() == "coordination_node"
    )
    workflow_id = str(
        workflow.get("workflow_id")
        or assembly.get("workflow_id")
        or current_turn.get("workflow_id")
        or current_turn.get("task_workflow_id")
        or registered.get("workflow_id")
        or registered.get("default_workflow_id")
        or ""
    ).strip()
    node_id = _first_non_empty(
        current_turn.get("node_id"),
        current_turn.get("stage_id"),
        workflow_metadata.get("node_id"),
        registered_metadata.get("node_id"),
        registered_structure.get("node_id"),
        _node_id_from_workflow(workflow_id),
    )
    stage_id = _first_non_empty(
        current_turn.get("stage_id"),
        current_turn.get("continuation_stage_id"),
        workflow_metadata.get("stage_id"),
        workflow_metadata.get("node_id"),
        registered_metadata.get("stage_id"),
        registered_metadata.get("node_id"),
        node_id,
    )
    graph_id = _first_non_empty(
        current_turn.get("graph_id"),
        current_turn.get("task_graph_id"),
        assembly.get("graph_ref"),
        workflow_metadata.get("graph_id"),
        registered_metadata.get("graph_id"),
    )
    phase_id = _first_non_empty(
        current_turn.get("phase_id"),
        current_turn.get("current_phase_id"),
        workflow_metadata.get("phase_id"),
        registered_metadata.get("phase_id"),
    )
    current_step = _resolve_current_step(
        current_turn=current_turn,
        workflow_steps=workflow_steps,
        recipe_steps=recipe_steps,
        node_id=node_id,
        stage_id=stage_id,
        task_graph_node_runtime=task_graph_node_runtime,
    )
    skill_ids = [
        str(item.get("skill_id") or "").strip()
        for item in list(skill_runtime_views or [])
        if isinstance(item, dict) and str(item.get("skill_id") or "").strip()
    ]
    process_kind = _first_non_empty(
        "task_graph_node" if task_graph_node_runtime else "",
        assembly.get("execution_chain_type"),
        recipe.get("execution_kind"),
        assembly_metadata.get("execution_kind"),
        "single_agent",
    )
    return PromptSelectionContext(
        task_id=str(task_id or contract.get("task_id") or assembly.get("task_id") or "").strip(),
        user_goal=str(contract.get("user_goal") or user_goal or "").strip(),
        agent_id=str(agent_id or current_turn.get("agent_id") or "").strip(),
        interaction_mode=str(
            mode_policy.get("interaction_mode")
            or current_turn.get("interaction_mode")
            or current_turn.get("runtime_interaction_mode")
            or assembly_metadata.get("interaction_mode")
            or assembly.get("task_mode")
            or "standard_mode"
        ).strip(),
        work_mode=str(
            model_turn_decision.get("work_mode")
            or current_turn.get("work_mode")
            or ""
        ).strip(),
        interaction_intent=str(
            model_turn_decision.get("interaction_intent")
            or current_turn.get("interaction_intent")
            or ""
        ).strip(),
        action_intent=str(
            model_turn_decision.get("action_intent")
            or current_turn.get("action_intent")
            or ""
        ).strip(),
        runtime_lane=str(
            mode_policy.get("runtime_lane")
            or current_turn.get("runtime_lane")
            or assembly_metadata.get("runtime_lane_hint")
            or ""
        ).strip(),
        process_kind=process_kind,
        task_goal_type=str(
            semantic_contract.get("task_goal_type")
            or current_turn.get("task_goal_type")
            or current_turn.get("semantic_task_type")
            or assembly_metadata.get("semantic_task_type")
            or ""
        ).strip(),
        task_domain=str(
            semantic_contract.get("domain")
            or current_turn.get("domain")
            or current_turn.get("target_domain_hint")
            or workflow_metadata.get("domain_id")
            or assembly_metadata.get("domain_id")
            or ""
        ).strip(),
        task_mode=str(assembly.get("task_mode") or recipe.get("task_mode") or "").strip(),
        workflow_id=workflow_id,
        workflow_title=str(workflow.get("title") or assembly_metadata.get("workflow_title") or "").strip(),
        registered_task_id=str(registered.get("task_id") or assembly_metadata.get("registered_task_id") or "").strip(),
        graph_id=graph_id,
        node_id=node_id,
        stage_id=stage_id,
        phase_id=phase_id,
        current_step_id=str(current_step.get("step_id") or "").strip(),
        current_step_kind=str(current_step.get("step_kind") or "").strip(),
        current_step_title=str(current_step.get("title") or "").strip(),
        current_step_index=int(current_step.get("index", -1)),
        current_step_source=str(current_step.get("source") or "").strip(),
        task_graph_node_runtime=task_graph_node_runtime,
        workflow_steps=tuple(workflow_steps),
        recipe_steps=tuple(recipe_steps),
        step_sequence=tuple(_step_sequence(workflow_steps=workflow_steps, recipe_steps=recipe_steps)),
        skill_ids=tuple(skill_ids),
        visible_tool_ids=tuple(
            str(item).strip()
            for item in list(current_turn.get("visible_tool_ids") or current_turn.get("available_tool_ids") or [])
            if str(item).strip()
        ),
        model_turn_decision=model_turn_decision,
        action_permit=action_permit,
        boundary_policy=boundary_policy,
        request_facts=request_facts,
        context_binding=context_binding,
        task_requirement_contract=semantic_contract,
        goal_hypothesis_set=goal_hypothesis_set,
        task_goal_spec=task_goal_spec,
        agent_plan_requirement=agent_plan_requirement,
        agent_plan_draft=agent_plan_draft,
        plan_coverage_review=plan_coverage_review,
        verification_review=verification_review,
        completion_judgment=completion_judgment,
        metadata={
            "selector_version": "flow_aware_v1",
            "mode_policy_ref": str(mode_policy.get("authority") or ""),
            "selected_recipe_id": str(recipe.get("recipe_id") or ""),
            "selected_recipe_title": str(recipe.get("title") or ""),
            "task_requirement_contract_ref": str(semantic_contract.get("contract_id") or ""),
            "goal_hypothesis_set_ref": str(goal_hypothesis_set.get("hypothesis_set_id") or ""),
            "agent_plan_ref": str(agent_plan_draft.get("plan_id") or ""),
            "agent_plan_requirement_ref": str(agent_plan_requirement.get("requirement_id") or ""),
            "plan_coverage_ref": str(plan_coverage_review.get("review_id") or ""),
            "verification_review_ref": str(verification_review.get("review_id") or ""),
            "completion_judgment_ref": str(completion_judgment.get("judgment_id") or ""),
        },
    )


class PromptSelector:
    def __init__(self, resources: list[PromptResource] | tuple[PromptResource, ...]) -> None:
        self.resources = tuple(resources or ())

    def select(self, context: PromptSelectionContext) -> PromptAssemblyPlan:
        selected: list[PromptAssemblyPlanItem] = list(_builtin_plan_items(context))
        omitted: list[PromptAssemblyPlanItem] = []
        winners: dict[str, _ScoredResource] = {}
        for resource in self.resources:
            omitted_reason = _hard_omit_reason(resource, context)
            if omitted_reason:
                omitted.append(_plan_item_from_resource(resource, omitted_reason=omitted_reason))
                continue
            scored = _score_resource(resource, context)
            if scored.score <= 0:
                omitted.append(_plan_item_from_resource(resource, omitted_reason="no_flow_or_context_match"))
                continue
            winner_key = _winner_key(resource)
            current = winners.get(winner_key)
            if current is None or (scored.score, -resource.priority, resource.resource_id) > (
                current.score,
                -current.resource.priority,
                current.resource.resource_id,
            ):
                if current is not None:
                    omitted.append(
                        _plan_item_from_resource(
                            current.resource,
                            omitted_reason=f"replaced_by_higher_priority_{resource.resource_id}",
                        )
                    )
                winners[winner_key] = scored
            else:
                omitted.append(
                    _plan_item_from_resource(
                        resource,
                        omitted_reason=f"lower_priority_than_{current.resource.resource_id}",
                    )
                )
        for scored in winners.values():
            selected.append(
                _plan_item_from_resource(
                    scored.resource,
                    selection_reason=scored.reason,
                    score=scored.score,
                )
            )
        selected.sort(key=lambda item: (item.order, item.priority, item.section_id, item.resource_id))
        omitted.sort(key=lambda item: (item.resource_type, item.section_id, item.resource_id))
        diagnostics = {
            "selector": "prompt_library.flow_aware_v2",
            "workflow_id": context.workflow_id,
            "workflow_title": context.workflow_title,
            "graph_id": context.graph_id,
            "node_id": context.node_id,
            "stage_id": context.stage_id,
            "phase_id": context.phase_id,
            "current_step_id": context.current_step_id,
            "current_step_kind": context.current_step_kind,
            "current_step_title": context.current_step_title,
            "current_step_index": context.current_step_index,
            "current_step_source": context.current_step_source,
            "workflow_step_count": len(context.workflow_steps),
            "recipe_step_count": len(context.recipe_steps),
            "step_sequence": list(context.step_sequence),
            "task_graph_node_runtime": context.task_graph_node_runtime,
            "work_mode": context.work_mode,
            "interaction_intent": context.interaction_intent,
            "action_intent": context.action_intent,
            "model_turn_decision_ref": str(context.model_turn_decision.get("decision_id") or ""),
            "action_permit_ref": str(context.action_permit.get("permit_id") or ""),
            "goal_hypothesis_set_ref": str(context.goal_hypothesis_set.get("hypothesis_set_id") or ""),
            "task_requirement_contract_ref": str(context.task_requirement_contract.get("contract_id") or ""),
            "agent_plan_ref": str(context.agent_plan_draft.get("plan_id") or ""),
            "plan_coverage_passed": bool(context.plan_coverage_review.get("passed") is True),
            "verification_review_ref": str(context.verification_review.get("review_id") or ""),
            "completion_judgment_ref": str(context.completion_judgment.get("judgment_id") or ""),
            "selected_resource_ids": [
                item.resource_id
                for item in selected
                if item.resource_id and not item.resource_id.startswith("builtin:")
            ],
            "omitted_count": len(omitted),
        }
        return PromptAssemblyPlan(
            plan_id=f"promptplan:{context.task_id or 'runtime'}",
            task_id=context.task_id,
            interaction_mode=context.interaction_mode,
            selected=tuple(selected),
            omitted=tuple(omitted),
            diagnostics=diagnostics,
        )


def selected_prompt_resource(
    *,
    plan: PromptAssemblyPlan,
    resources: list[PromptResource] | tuple[PromptResource, ...],
    resource_type: str,
) -> PromptResource | None:
    target_type = str(resource_type or "").strip()
    resource_by_id = {item.resource_id: item for item in tuple(resources or ())}
    for item in plan.selected:
        if item.resource_type == target_type and item.resource_id in resource_by_id:
            return resource_by_id[item.resource_id]
    return None


def _builtin_plan_items(context: PromptSelectionContext) -> tuple[PromptAssemblyPlanItem, ...]:
    return tuple(
        PromptAssemblyPlanItem(
            section_id=section_id,
            resource_id=resource_id,
            resource_type=resource_type,
            title=title,
            owner_layer=owner_layer,
            cache_scope="dynamic",
            model_visible=True,
            source_ref=context.task_id,
            source_refs=tuple(item for item in (context.task_id, context.workflow_id, context.current_step_id) if item),
            renderer_id=f"prompt_library.runtime_sections.{section_id}",
            order=order,
            priority=100,
            selection_reason="builtin_runtime_section",
            metadata={"flow_aware": True},
        )
        for section_id, resource_id, resource_type, title, owner_layer, order in _BUILTIN_SECTION_PLAN
    )


def _plan_item_from_resource(
    resource: PromptResource,
    *,
    selection_reason: str = "",
    omitted_reason: str = "",
    score: int = 0,
) -> PromptAssemblyPlanItem:
    return PromptAssemblyPlanItem(
        section_id=_RESOURCE_SECTION_IDS.get(resource.resource_type, f"{resource.resource_type}_section"),
        resource_id=resource.resource_id,
        resource_type=resource.resource_type,
        title=resource.title,
        owner_layer="role_prompt" if resource.resource_type == "role_prompt" else "task",
        cache_scope=resource.cache_scope,
        model_visible=resource.model_visible,
        source_ref=resource.source_ref,
        source_refs=tuple(
            item
            for item in (
                resource.source_ref,
                resource.workflow_id,
                resource.task_id,
                resource.graph_id,
                resource.node_id,
                resource.stage_id,
                resource.step_id,
            )
            if item
        ),
        renderer_id=f"prompt_library.resource.{resource.resource_type}",
        order=_RESOURCE_ORDERS.get(resource.resource_type, 80),
        priority=resource.priority,
        selection_reason=selection_reason,
        omitted_reason=omitted_reason,
        metadata={
            "score": score,
            "phase_id": resource.phase_id,
            "step_kind": resource.step_kind,
            "tags": list(resource.tags),
        },
    )


def _score_resource(resource: PromptResource, context: PromptSelectionContext) -> _ScoredResource:
    score = 0
    reasons: list[str] = []
    identity_score, identity_reason = _identity_score(resource, context)
    if resource.resource_type == "stage_role" and _has_explicit_flow_binding(resource) and not identity_score:
        return _ScoredResource(resource=resource, score=0, reason="")
    if identity_score:
        score += identity_score
        reasons.append(identity_reason)
    compatibility_score, compatibility_reason = _compatibility_score(resource, context, identity_match=identity_score > 0)
    if compatibility_score:
        score += compatibility_score
        reasons.extend(compatibility_reason)
    if resource.resource_type == "common_contract":
        score += 50
        reasons.append("common_contract")
    if resource.resource_type == "mode_policy" and context.interaction_mode:
        score += 45
        reasons.append("mode_policy")
    if resource.resource_type == "understanding_policy" and context.current_step_kind == "task_goal_understanding":
        score += 140
        reasons.append("task_goal_understanding_stage")
    if resource.resource_type == "flow_matching_policy" and context.current_step_kind == "domain_flow_matching":
        score += 140
        reasons.append("domain_flow_matching_stage")
    if resource.resource_type == "stage_role" and _is_planning_context(context):
        score += 90
        reasons.append("planning_stage_context")
    if resource.resource_type == "stage_role" and _is_execution_context(context):
        score += 90
        reasons.append("execution_stage_context")
    if resource.resource_type == "output_boundary":
        score += 40
        reasons.append("output_boundary")
    if resource.resource_type == "verification" and _is_verification_context(context):
        score += 120
        reasons.append("verification_stage")
    if resource.resource_type == "skill_prompt" and _matches_any(resource.tags, context.skill_ids):
        score += 160
        reasons.append("skill_match")
    if resource.resource_type in {"stage_role", "task_goal_role", "role_prompt"} and score <= 0:
        return _ScoredResource(resource=resource, score=0, reason="")
    if score <= 0 and not _resource_is_generic(resource):
        return _ScoredResource(resource=resource, score=0, reason="")
    return _ScoredResource(
        resource=resource,
        score=score,
        reason=", ".join(dict.fromkeys(item for item in reasons if item)) or "generic_prompt_resource",
    )


def _identity_score(resource: PromptResource, context: PromptSelectionContext) -> tuple[int, str]:
    if resource.workflow_id and resource.workflow_id == context.workflow_id:
        return 10000, "workflow_id_exact"
    if resource.task_id and resource.task_id in {context.task_id, context.registered_task_id}:
        return 9000, "task_id_exact"
    if resource.graph_id and resource.node_id and resource.graph_id == context.graph_id and resource.node_id == context.node_id:
        return 8200, "graph_node_exact"
    if resource.node_id and resource.node_id in {context.node_id, context.stage_id, context.current_step_id}:
        return 7600, "node_or_stage_exact"
    if resource.stage_id and resource.stage_id in {context.stage_id, context.node_id, context.current_step_id}:
        return 7300, "stage_exact"
    if resource.step_id and resource.step_id == context.current_step_id:
        return 6900, "step_id_exact"
    if resource.phase_id and resource.phase_id == context.phase_id:
        return 6400, "phase_exact"
    if resource.step_kind and resource.step_kind == context.current_step_kind:
        return 5200, "step_kind_exact"
    return 0, ""


def _compatibility_score(
    resource: PromptResource,
    context: PromptSelectionContext,
    *,
    identity_match: bool,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if resource.applies_to_modes and context.interaction_mode in resource.applies_to_modes:
        score += 250
        reasons.append("mode_match")
    if resource.applies_to_modes and context.work_mode and context.work_mode in resource.applies_to_modes:
        score += 90
        reasons.append("work_mode_match")
    if resource.applies_to_agents and context.agent_id in resource.applies_to_agents:
        score += 220
        reasons.append("agent_match")
    domain_values = {
        context.task_domain,
        context.task_mode,
        context.process_kind,
        context.work_mode,
        context.action_intent,
        context.interaction_intent,
    }
    if resource.applies_to_domains and _matches_any(resource.applies_to_domains, domain_values):
        score += 180
        reasons.append("domain_or_process_match")
    if resource.applies_to_task_goal_types and context.task_goal_type in resource.applies_to_task_goal_types:
        score += 180
        reasons.append("task_goal_type_match")
    if _matches_any(resource.tags, domain_values | {context.current_step_kind, context.current_step_id, context.node_id}):
        score += 80
        reasons.append("tag_match")
    if identity_match:
        score += 100
        reasons.append("identity_match_overrides_generic_prompt")
    return score, reasons


def _hard_omit_reason(resource: PromptResource, context: PromptSelectionContext) -> str:
    if not resource.enabled:
        return "resource_disabled"
    if not resource.model_visible:
        return "resource_not_model_visible"
    if resource.resource_type == "role_prompt" and context.interaction_mode != "role_mode":
        return "role_prompt_only_allowed_in_role_mode"
    if resource.applies_to_modes and context.interaction_mode and context.interaction_mode not in resource.applies_to_modes:
        return "interaction_mode_mismatch"
    if resource.applies_to_agents and context.agent_id and context.agent_id not in resource.applies_to_agents:
        return "agent_mismatch"
    identity_conflict = _identity_conflict_reason(resource, context)
    if identity_conflict:
        return identity_conflict
    if not _has_identity_match(resource, context):
        if (
            resource.applies_to_domains
            and context.task_domain
            and not _matches_any(resource.applies_to_domains, {context.task_domain, context.task_mode, context.process_kind})
        ):
            return "domain_mismatch"
        if (
            resource.applies_to_task_goal_types
            and context.task_goal_type
            and context.task_goal_type not in resource.applies_to_task_goal_types
        ):
            return "task_goal_type_mismatch"
    return ""


def _identity_conflict_reason(resource: PromptResource, context: PromptSelectionContext) -> str:
    if resource.workflow_id and context.workflow_id and resource.workflow_id != context.workflow_id:
        return "workflow_mismatch"
    if resource.graph_id and context.graph_id and resource.graph_id != context.graph_id:
        return "graph_mismatch"
    if resource.node_id and context.node_id and resource.node_id not in {context.node_id, context.stage_id, context.current_step_id}:
        return "node_mismatch"
    if resource.stage_id and context.stage_id and resource.stage_id not in {context.stage_id, context.node_id, context.current_step_id}:
        return "stage_mismatch"
    if resource.phase_id and context.phase_id and resource.phase_id != context.phase_id:
        return "phase_mismatch"
    if resource.step_id and context.current_step_id and resource.step_id != context.current_step_id:
        return "step_mismatch"
    return ""


def _has_identity_match(resource: PromptResource, context: PromptSelectionContext) -> bool:
    return _identity_score(resource, context)[0] > 0


def _winner_key(resource: PromptResource) -> str:
    if resource.resource_type == "stage_role":
        return "stage_role"
    if resource.resource_type == "task_goal_role":
        return "task_goal_role"
    if resource.resource_type == "role_prompt":
        return "role_prompt"
    if resource.resource_type == "verification":
        return "verification"
    if resource.resource_type == "output_boundary":
        return "output_boundary"
    if resource.resource_type == "mode_policy":
        return "mode_policy"
    if resource.resource_type == "understanding_policy":
        return "understanding_policy"
    if resource.resource_type == "flow_matching_policy":
        return "flow_matching_policy"
    if resource.resource_type == "common_contract":
        return resource.resource_id
    if resource.resource_type in {"skill_prompt", "tool_guidance"}:
        return f"{resource.resource_type}:{resource.resource_id}"
    return resource.resource_type


def _resource_is_generic(resource: PromptResource) -> bool:
    return not any(
        (
            resource.workflow_id,
            resource.task_id,
            resource.graph_id,
            resource.node_id,
            resource.stage_id,
            resource.phase_id,
            resource.step_id,
            resource.step_kind,
            resource.applies_to_task_goal_types,
            resource.applies_to_domains,
            resource.applies_to_modes,
            resource.applies_to_agents,
        )
    )


def _has_explicit_flow_binding(resource: PromptResource) -> bool:
    return bool(
        resource.workflow_id
        or resource.task_id
        or resource.graph_id
        or resource.node_id
        or resource.stage_id
        or resource.phase_id
        or resource.step_id
        or resource.step_kind
    )


def _is_verification_context(context: PromptSelectionContext) -> bool:
    values = {
        context.current_step_kind,
        context.current_step_id,
        context.stage_id,
        context.node_id,
        context.task_goal_type,
        context.work_mode,
        context.action_intent,
        context.interaction_intent,
    }
    if context.work_mode == "verification":
        return True
    if context.action_intent == "run_command":
        return True
    return any("verify" in item or "review" in item or "validation" in item for item in values if item)


def _is_planning_context(context: PromptSelectionContext) -> bool:
    if context.current_step_kind in {"execution_planning", "plan_coverage_review"}:
        return True
    if context.work_mode == "planning":
        return True
    if context.model_turn_decision.get("planning_required") is True:
        return True
    return False


def _is_execution_context(context: PromptSelectionContext) -> bool:
    if context.current_step_kind == "step_execution":
        return True
    if context.current_step_id.startswith("step_execution."):
        return True
    if context.work_mode == "implementation":
        return True
    if context.action_intent in {"edit_workspace", "start_service", "use_browser"}:
        return True
    return False


def _normalize_steps(raw_steps: Any, *, source: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, raw in enumerate(list(raw_steps or [])):
        if not isinstance(raw, dict):
            continue
        step_id = str(raw.get("step_id") or raw.get("id") or raw.get("node_id") or f"{source}_{index + 1}").strip()
        if not step_id:
            continue
        steps.append(
            {
                "step_id": step_id,
                "title": str(raw.get("title") or raw.get("name") or step_id).strip(),
                "step_kind": str(raw.get("step_kind") or raw.get("kind") or raw.get("type") or "").strip(),
                "executor_type": str(raw.get("executor_type") or "").strip(),
                "output_contract_id": str(raw.get("output_contract_id") or raw.get("contract_id") or "").strip(),
                "index": index,
                "source": source,
            }
        )
    return steps


def _resolve_current_step(
    *,
    current_turn: dict[str, Any],
    workflow_steps: list[dict[str, Any]],
    recipe_steps: list[dict[str, Any]],
    node_id: str,
    stage_id: str,
    task_graph_node_runtime: bool,
) -> dict[str, Any]:
    explicit_step_id = _first_non_empty(
        current_turn.get("current_step_id"),
        current_turn.get("task_step_id"),
        current_turn.get("step_id"),
        current_turn.get("continuation_step_id"),
    )
    all_steps = [*workflow_steps, *recipe_steps]
    if explicit_step_id:
        return _step_by_id(all_steps, explicit_step_id) or {
            "step_id": explicit_step_id,
            "title": str(current_turn.get("current_step_title") or explicit_step_id),
            "step_kind": str(current_turn.get("current_step_kind") or ""),
            "index": -1,
            "source": "current_turn_context",
        }
    if task_graph_node_runtime and (stage_id or node_id):
        current_id = stage_id or node_id
        return _step_by_id(all_steps, current_id) or {
            "step_id": current_id,
            "title": str(current_turn.get("stage_title") or current_id),
            "step_kind": "task_graph_node",
            "index": -1,
            "source": "task_graph_node",
        }
    if workflow_steps:
        return workflow_steps[0]
    if recipe_steps:
        return recipe_steps[0]
    return {"step_id": "", "title": "", "step_kind": "", "index": -1, "source": ""}


def _step_by_id(steps: list[dict[str, Any]], step_id: str) -> dict[str, Any] | None:
    target = str(step_id or "").strip()
    if not target:
        return None
    return next((item for item in steps if str(item.get("step_id") or "") == target), None)


def _step_sequence(*, workflow_steps: list[dict[str, Any]], recipe_steps: list[dict[str, Any]]) -> list[str]:
    source = workflow_steps or recipe_steps
    return [str(item.get("step_id") or "").strip() for item in source if str(item.get("step_id") or "").strip()]


def _node_id_from_workflow(workflow_id: str) -> str:
    value = str(workflow_id or "").strip()
    marker = ".node."
    if marker in value:
        return value.split(marker, 1)[1]
    return ""


def _first_non_empty(*values: Any) -> str:
    for value in values:
        item = str(value or "").strip()
        if item:
            return item
    return ""


def _matches_any(values: tuple[str, ...] | set[str] | list[str], targets: tuple[str, ...] | set[str] | list[str]) -> bool:
    normalized_values = {str(item or "").strip() for item in values if str(item or "").strip()}
    normalized_targets = {str(item or "").strip() for item in targets if str(item or "").strip()}
    return bool(normalized_values.intersection(normalized_targets))


