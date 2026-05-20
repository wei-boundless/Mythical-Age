from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from prompting.professional_profiles import get_professional_prompt_profile
from soul import SoulFacade
from soul.projection_store import get_projection_card

from .agent_registry import AgentRegistry
from .agent_identity import normalize_agent_id
from .agent_runtime_models import AgentRuntimeProfile
from .agent_runtime_registry import AgentRuntimeRegistry
from .assembly_models import AgentRuntimeSpec, TaskBodyOrchestration
from .body_registry import BodyProfileRegistry
from .resource_policy_builder import build_resource_policy_candidate
from .resource_runtime_view import build_resource_runtime_views


def build_orchestration_runtime_bundle(
    *,
    base_dir: Path,
    session_id: str,
    task_id: str,
    user_goal: str,
    task_assembly_bundle: dict[str, Any],
    memory_runtime_view: dict[str, Any] | None = None,
    context_policy_result: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    active_skill: dict[str, Any] | None = None,
    agent_runtime_profile: AgentRuntimeProfile | None = None,
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    task_contract = dict(task_assembly_bundle.get("task_contract") or {})
    task_execution_assembly = dict(task_assembly_bundle.get("task_execution_assembly") or {})
    task_spec = dict(task_assembly_bundle.get("task_spec") or {})
    selected_recipe = dict(task_assembly_bundle.get("selected_recipe") or {})
    projection_selection = dict(task_assembly_bundle.get("projection_selection") or {})
    task_workflow = dict(task_assembly_bundle.get("_task_workflow_obj") or {})
    binding = dict(task_assembly_bundle.get("binding") or {})
    operation_requirement = dict(task_assembly_bundle.get("operation_requirement") or {})
    memory_request_profile = dict(task_assembly_bundle.get("task_memory_request_profile") or {})
    skill_runtime_views = [
        dict(item)
        for item in list(task_assembly_bundle.get("skill_runtime_views") or ())
        if isinstance(item, dict)
    ]
    registered_task = dict(task_assembly_bundle.get("registered_task") or {})
    current_turn_payload = dict(current_turn_context or task_assembly_bundle.get("current_turn_context") or {})
    active_skill_payload = dict(active_skill or task_assembly_bundle.get("active_skill") or {})
    memory_view = dict(memory_runtime_view or {})
    context_policy = dict(context_policy_result or {})

    explicit_context_agent_id = normalize_agent_id(str(current_turn_payload.get("agent_id") or "").strip())
    if explicit_context_agent_id:
        current_turn_payload["agent_id"] = explicit_context_agent_id
    agent_id = normalize_agent_id(str(getattr(agent_runtime_profile, "agent_id", "") or explicit_context_agent_id or "").strip())
    if explicit_context_agent_id and not agent_id:
        raise ValueError(f"TaskGraph node agent has no runtime profile: {explicit_context_agent_id}")
    runtime_profile = agent_runtime_profile or AgentRuntimeRegistry(base_dir).get_profile(agent_id)
    if explicit_context_agent_id:
        if runtime_profile is None:
            raise ValueError(f"TaskGraph node agent has no runtime profile: {explicit_context_agent_id}")
        if normalize_agent_id(str(getattr(runtime_profile, "agent_id", "") or "").strip()) != explicit_context_agent_id:
            raise ValueError(
                "TaskGraph node agent profile mismatch: "
                f"requested {explicit_context_agent_id}, got {getattr(runtime_profile, 'agent_id', '')}"
            )
    agent_id = str(getattr(runtime_profile, "agent_id", "") or agent_id).strip() or "agent:0"
    descriptor = AgentRegistry(base_dir).get_agent(agent_id)
    profile_registry = BodyProfileRegistry(base_dir)

    body_profile = profile_registry.build_agent_body_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
    )
    prompt_profile = profile_registry.build_prompt_structure_profile(
        agent_id=agent_id,
        task_mode=str(task_execution_assembly.get("task_mode") or ""),
        output_contract_id=str(task_execution_assembly.get("output_contract_id") or ""),
    )
    memory_scope_profile = profile_registry.build_memory_scope_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        memory_request_profile=memory_request_profile,
    )
    requested_runtime_lane = _requested_runtime_lane(
        binding=binding,
        registered_task=registered_task,
        task_execution_assembly=task_execution_assembly,
    )
    runtime_lane_profile = profile_registry.build_runtime_lane_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        task_mode=str(task_execution_assembly.get("task_mode") or ""),
        requested_runtime_lane=requested_runtime_lane,
    )
    output_boundary_profile = profile_registry.build_output_boundary_profile(
        agent_id=agent_id,
        runtime_profile=runtime_profile,
        output_contract_id=str(task_execution_assembly.get("output_contract_id") or ""),
    )

    projection_requirement = _build_projection_requirement(
        base_dir=base_dir,
        task_id=task_id,
        projection_selection=projection_selection,
        agent_descriptor=descriptor,
        task_mode=str(task_execution_assembly.get("task_mode") or ""),
        task_contract=task_contract,
        task_execution_assembly=task_execution_assembly,
        selected_recipe=selected_recipe,
    )
    projection_diagnostics = _projection_resolution_diagnostics(projection_requirement)
    prompt_contract = _build_runtime_prompt_contract(
        task_id=task_id,
        user_goal=user_goal,
        task_contract=task_contract,
        task_execution_assembly=task_execution_assembly,
        task_spec=task_spec,
        selected_recipe=selected_recipe,
        task_workflow=task_workflow,
        binding=binding,
        registered_task=registered_task,
        skill_runtime_views=skill_runtime_views,
        projection_requirement=projection_requirement,
        operation_requirement=operation_requirement,
        active_skill=active_skill_payload,
        agent_id=agent_id,
    )
    operation_registry = build_default_operation_registry()
    candidate_policy = build_resource_policy_candidate(
        _operation_requirement_from_payload(operation_requirement),
        operation_registry,
    )
    resource_views = [item.to_dict() for item in build_resource_runtime_views(candidate_policy, operation_registry)]
    soul_runtime = SoulFacade(base_dir).build_runtime_view(
        task_prompt_contract=prompt_contract,
        projection_requirement=projection_requirement,
        skill_views=skill_runtime_views,
        resource_views=resource_views,
        soul_id=str(projection_requirement.get("soul_id") or getattr(descriptor, "default_soul_id", "") or "runtime"),
        agent_profile_id=str(getattr(runtime_profile, "agent_profile_id", "") or "runtime_agent"),
        use_shared_contract=bool(getattr(runtime_profile, "use_shared_contract", True)),
    )
    soul_runtime_view = dict(soul_runtime.get("runtime_view") or {})
    prompt_manifest = dict(soul_runtime.get("prompt_manifest") or {})
    projection_ref = str(soul_runtime.get("projection_id") or prompt_manifest.get("projection_id") or "")
    prompt_manifest_ref = str(prompt_manifest.get("manifest_id") or "")

    orchestration = TaskBodyOrchestration(
        orchestration_id=f"orchestration:{task_id}",
        task_id=task_id,
        agent_id=agent_id,
        task_execution_assembly_ref=str(task_execution_assembly.get("assembly_id") or ""),
        body_profile_ref=body_profile.body_profile_id,
        prompt_structure_profile_ref=prompt_profile.profile_id,
        memory_scope_profile_ref=memory_scope_profile.profile_id,
        runtime_lane_profile_ref=runtime_lane_profile.profile_id,
        output_boundary_profile_ref=output_boundary_profile.profile_id,
        stage_plan={
            "stage_owner": "orchestration",
            "section_order": list(prompt_profile.section_order),
            "projection_policy": prompt_profile.stage_projection_policy,
            "current_turn_ref": str(current_turn_payload.get("turn_id") or ""),
        },
        resource_binding_plan={
            "operation_requirement_ref": str(operation_requirement.get("requirement_id") or ""),
            "required_operations": list(operation_requirement.get("required_operations") or ()),
            "optional_operations": list(operation_requirement.get("optional_operations") or ()),
            "approval_policy": str(dict(operation_requirement.get("metadata") or {}).get("approval_policy") or "default"),
            "intent_runtime_assembly_hint": dict(current_turn_payload.get("runtime_assembly_hint") or {}),
        },
        verification_gate_plan={
            "task_constraints": dict(task_execution_assembly.get("task_constraints") or {}),
            "safety_envelope": dict(task_execution_assembly.get("safety_envelope") or {}),
        },
        fallback_plan={
            "runtime_executable_default": True,
            "fallback_policy": "fail_closed",
            "on_projection_gap": "continue_with_minimal_projection",
        },
        projection_requirement=projection_requirement,
        soul_runtime_view=soul_runtime_view,
        prompt_manifest=prompt_manifest,
        projection_ref=projection_ref,
        prompt_manifest_ref=prompt_manifest_ref,
        diagnostics={
            "builder": "orchestration.build_orchestration_runtime_bundle",
            "projection_provider": "soul.build_soul_runtime_view",
            "projection_resolution": projection_diagnostics,
            "memory_view_ref": str(memory_view.get("view_id") or ""),
            "context_policy_ref": _context_policy_ref(context_policy),
            "runtime_lane": runtime_lane_profile.lane_id,
            "requested_runtime_lane": requested_runtime_lane,
            "active_skill_name": str(active_skill_payload.get("name") or ""),
            "intent_decision": dict(current_turn_payload.get("intent_decision") or {}),
            "runtime_assembly_hint": dict(current_turn_payload.get("runtime_assembly_hint") or {}),
            "continuation_decision": dict(current_turn_payload.get("continuation_decision") or {}),
        },
    )
    runtime_spec = AgentRuntimeSpec(
        runtime_spec_id=f"rtspec:{task_id}",
        task_id=task_id,
        session_id=session_id,
        agent_id=agent_id,
        task_execution_assembly_ref=str(task_execution_assembly.get("assembly_id") or ""),
        task_body_orchestration_ref=orchestration.orchestration_id,
        context_input_refs=tuple(
            item
            for item in (
                str(memory_view.get("view_id") or ""),
                _context_policy_ref(context_policy),
                str(current_turn_payload.get("turn_id") or ""),
            )
            if item
        ),
        projection_snapshot_ref=f"stageproj:{task_id}",
        resource_policy_candidate_ref=str(operation_requirement.get("requirement_id") or ""),
        input_contract_ref=str(task_execution_assembly.get("input_contract_id") or task_contract.get("input_contract_id") or ""),
        output_contract_ref=str(task_execution_assembly.get("output_contract_id") or task_contract.get("output_contract_id") or ""),
        runtime_lane=runtime_lane_profile.lane_id,
        runtime_executable=True,
        diagnostics={
            "builder": "orchestration.build_orchestration_runtime_bundle",
            "body_profile_ref": body_profile.body_profile_id,
            "prompt_structure_profile_ref": prompt_profile.profile_id,
            "memory_scope_profile_ref": memory_scope_profile.profile_id,
            "runtime_lane_profile_ref": runtime_lane_profile.profile_id,
            "requested_runtime_lane": requested_runtime_lane,
            "output_boundary_profile_ref": output_boundary_profile.profile_id,
            "projection_resolution": projection_diagnostics,
            "intent_decision": dict(current_turn_payload.get("intent_decision") or {}),
            "runtime_assembly_hint": dict(current_turn_payload.get("runtime_assembly_hint") or {}),
            "continuation_decision": dict(current_turn_payload.get("continuation_decision") or {}),
        },
    )
    return {
        "agent_body_profile": body_profile.to_dict(),
        "prompt_structure_profile": prompt_profile.to_dict(),
        "memory_scope_profile": memory_scope_profile.to_dict(),
        "runtime_lane_profile": runtime_lane_profile.to_dict(),
        "output_boundary_profile": output_boundary_profile.to_dict(),
        "task_body_orchestration": orchestration.to_dict(),
        "agent_runtime_spec": runtime_spec.to_dict(),
        "runtime_executable": True,
    }


def _requested_runtime_lane(
    *,
    binding: dict[str, Any],
    registered_task: dict[str, Any],
    task_execution_assembly: dict[str, Any],
) -> str:
    binding_lane = str(binding.get("runtime_lane") or "").strip()
    if binding_lane:
        return binding_lane
    task_policy = dict(registered_task.get("task_policy") or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    policy_lane = str(task_structure.get("runtime_lane_hint") or "").strip()
    if policy_lane:
        return policy_lane
    metadata = dict(task_execution_assembly.get("metadata") or {})
    metadata_lane = str(metadata.get("runtime_lane_hint") or metadata.get("default_runtime_lane") or "").strip()
    if metadata_lane:
        return metadata_lane
    return str(task_execution_assembly.get("runtime_lane") or "").strip()


def _build_projection_requirement(
    *,
    base_dir: Path,
    task_id: str,
    projection_selection: dict[str, Any],
    agent_descriptor: Any | None,
    task_mode: str,
    task_contract: dict[str, Any] | None = None,
    task_execution_assembly: dict[str, Any] | None = None,
    selected_recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(task_contract or {})
    assembly = dict(task_execution_assembly or {})
    recipe = dict(selected_recipe or {})
    metadata = {
        **dict(recipe.get("metadata") or {}),
        **dict(assembly.get("metadata") or {}),
    }
    mode_policy = dict(
        contract.get("mode_policy")
        or metadata.get("mode_policy")
        or {}
    )
    semantic_contract = dict(
        contract.get("semantic_task_contract")
        or metadata.get("semantic_task_contract")
        or {}
    )
    selected_projection_id = str(projection_selection.get("selected_projection_id") or "").strip()
    default_projection_id = str(getattr(agent_descriptor, "default_projection_id", "") or "").strip()
    default_soul_id = str(getattr(agent_descriptor, "default_soul_id", "") or "").strip()
    selection_source = str(projection_selection.get("selection_source") or "task_binding").strip() or "task_binding"
    reason = str(projection_selection.get("selection_reason") or "").strip() or "derived from task-side projection selection"
    resolved_projection_id = selected_projection_id or default_projection_id
    issue = ""
    if selected_projection_id:
        resolution_source = "task_requirement"
        if default_projection_id and default_projection_id != selected_projection_id:
            issue = "task_projection_overrides_agent_default"
    elif default_projection_id:
        resolution_source = "agent_default"
    else:
        resolution_source = "no_projection"
    projection_card = get_projection_card(base_dir, resolved_projection_id) if resolved_projection_id else None
    return {
        "task_id": task_id,
        "role_type": str((projection_card or {}).get("role_type") or projection_selection.get("role_type") or "task_default"),
        "posture_tags": list((projection_card or {}).get("posture_tags") or projection_selection.get("posture_tags") or ("concise",)),
        "expression_density": str((projection_card or {}).get("expression_density") or "normal"),
        "attention_focus": list((projection_card or {}).get("attention_focus") or ["task_goal", "workflow", "output"]),
        "projection_id": resolved_projection_id,
        "selected_projection_id": selected_projection_id,
        "agent_default_projection_id": default_projection_id,
        "resolution_source": resolution_source,
        "issue": issue,
        "projection_optional": True,
        "soul_id": str((projection_card or {}).get("soul_id") or default_soul_id),
        "projection_title": str((projection_card or {}).get("title") or ""),
        "identity_anchor": str((projection_card or {}).get("identity_anchor") or ""),
        "projection_prompt": str((projection_card or {}).get("projection_prompt") or ""),
        "reason": reason,
        "selection_source": selection_source,
        "task_mode": task_mode,
        "interaction_mode": str(mode_policy.get("interaction_mode") or metadata.get("interaction_mode") or ""),
        "projection_strength": str(mode_policy.get("projection_strength") or metadata.get("projection_strength") or ""),
        "runtime_lane": str(mode_policy.get("runtime_lane") or metadata.get("runtime_lane_hint") or ""),
        "professional_profile_id": str(
            semantic_contract.get("professional_profile_id")
            or metadata.get("professional_profile_id")
            or ""
        ),
        "semantic_task_type": str(semantic_contract.get("task_goal_type") or metadata.get("semantic_task_type") or ""),
        "mode_policy_ref": str(mode_policy.get("authority") or ""),
    }


def _projection_resolution_diagnostics(projection_requirement: dict[str, Any]) -> dict[str, Any]:
    issue = str(projection_requirement.get("issue") or "").strip()
    return {
        "authority": "orchestration.projection_resolution",
        "status": "warning" if issue else "ok",
        "projection_optional": True,
        "resolution_source": str(projection_requirement.get("resolution_source") or "no_projection"),
        "selected_projection_id": str(projection_requirement.get("selected_projection_id") or ""),
        "agent_default_projection_id": str(projection_requirement.get("agent_default_projection_id") or ""),
        "resolved_projection_id": str(projection_requirement.get("projection_id") or ""),
        "issue": issue,
    }


def _build_runtime_prompt_contract(
    *,
    task_id: str,
    user_goal: str,
    task_contract: dict[str, Any],
    task_execution_assembly: dict[str, Any],
    task_spec: dict[str, Any],
    selected_recipe: dict[str, Any],
    task_workflow: dict[str, Any],
    binding: dict[str, Any],
    registered_task: dict[str, Any],
    skill_runtime_views: list[dict[str, Any]],
    projection_requirement: dict[str, Any],
    operation_requirement: dict[str, Any],
    active_skill: dict[str, Any],
    agent_id: str,
) -> dict[str, Any]:
    selected_metadata = dict(selected_recipe.get("metadata") or {})
    semantic_contract = dict(
        task_contract.get("semantic_task_contract")
        or selected_metadata.get("semantic_task_contract")
        or {}
    )
    mode_policy = dict(
        task_contract.get("mode_policy")
        or selected_metadata.get("mode_policy")
        or {}
    )
    professional_profile_id = str(
        semantic_contract.get("professional_profile_id")
        or selected_metadata.get("professional_profile_id")
        or ""
    ).strip()
    professional_profile = get_professional_prompt_profile(professional_profile_id)
    workflow_steps = [
        str(item.get("title") or item.get("step_id") or "").strip()
        for item in list(task_workflow.get("steps") or ())
        if isinstance(item, dict) and str(item.get("title") or item.get("step_id") or "").strip()
    ]
    if not workflow_steps:
        workflow_steps = [
            str(item.get("title") or item.get("step_id") or "").strip()
            for item in list(selected_recipe.get("step_blueprints") or ())
            if isinstance(item, dict) and str(item.get("title") or item.get("step_id") or "").strip()
        ]
    skill_ids = [
        str(item.get("skill_id") or "").strip()
        for item in skill_runtime_views
        if str(item.get("skill_id") or "").strip()
    ]
    if not skill_ids and active_skill:
        skill_ids.append(str(active_skill.get("name") or "").strip())
    return {
        "contract_id": f"orchprompt:{task_id}",
        "task_id": task_id,
        "definition_id": str(binding.get("definition_id") or task_execution_assembly.get("task_family") or "runtime"),
        "binding_id": str(binding.get("binding_id") or ""),
        "task_section": "\n".join(
            [
                f"Goal: {str(task_contract.get('user_goal') or user_goal).strip()}",
                f"Task family: {str(task_execution_assembly.get('task_family') or '').strip() or 'general'}",
                f"Task mode: {str(task_execution_assembly.get('task_mode') or '').strip() or 'general_qa'}",
                f"Requested outputs: {', '.join(list(task_execution_assembly.get('requested_outputs') or ()) or ['AssistantFinalAnswer'])}",
            ]
        ).strip(),
        "workflow_section": _workflow_section(
            task_workflow=task_workflow,
            selected_recipe=selected_recipe,
            workflow_steps=workflow_steps,
            skill_ids=skill_ids,
        ),
        "semantic_task_section": _semantic_task_section(semantic_contract),
        "professional_profile_section": professional_profile.prompt if professional_profile is not None else "",
        "mode_policy_section": _mode_policy_section(mode_policy),
        "resource_section": "",
        "projection_section": _projection_section(projection_requirement),
        "output_section": _output_section(task_execution_assembly=task_execution_assembly, task_spec=task_spec),
        "guardrail_section": _communication_guardrail_section(task_spec),
        "metadata": {
            "agent_id": agent_id,
            "resource_policy_ref": str(operation_requirement.get("requirement_id") or ""),
            "registered_task_id": str(registered_task.get("task_id") or ""),
            "selected_recipe_id": str(selected_recipe.get("recipe_id") or ""),
            "semantic_task_contract": semantic_contract,
            "mode_policy": mode_policy,
            "professional_profile": professional_profile.to_dict() if professional_profile is not None else {},
        },
    }


def _semantic_task_section(semantic_contract: dict[str, Any]) -> str:
    if not semantic_contract:
        return ""
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    reasoning_steps = [
        str(item).strip()
        for item in list(semantic_contract.get("required_reasoning_steps") or [])
        if str(item).strip()
    ]
    required_actions = [
        str(item).strip()
        for item in list(semantic_contract.get("required_actions") or [])
        if str(item).strip()
    ]
    forbidden_actions = [
        str(item).strip()
        for item in list(semantic_contract.get("forbidden_actions") or [])
        if str(item).strip()
    ]
    materials = [
        str(dict(item).get("path") or "").strip()
        for item in list(semantic_contract.get("materials") or [])
        if isinstance(item, dict) and str(dict(item).get("path") or "").strip()
    ]
    lines = [
        f"你本轮要完成的任务类型是：{str(semantic_contract.get('task_goal_type') or 'general').strip()}。",
        f"任务领域：{str(semantic_contract.get('domain') or 'general').strip()}。",
    ]
    if materials:
        lines.append("需要优先处理的材料：" + "、".join(materials[:8]) + "。")
    if reasoning_steps:
        lines.append("你需要按这些思考步骤推进：" + " -> ".join(reasoning_steps) + "。")
    if required_actions:
        lines.append("必须真实完成或明确说明无法完成的动作：" + "、".join(required_actions) + "。")
    if deliverables:
        lines.append("最终回答必须交付：" + "、".join(deliverables) + "。")
    if forbidden_actions:
        lines.append("禁止：" + "、".join(forbidden_actions) + "。")
    return "\n".join(lines)


def _mode_policy_section(mode_policy: dict[str, Any]) -> str:
    if not mode_policy:
        return ""
    interaction_mode = str(mode_policy.get("interaction_mode") or "").strip()
    projection_strength = str(mode_policy.get("projection_strength") or "").strip()
    verification_policy = dict(mode_policy.get("verification_policy") or {})
    tool_policy = dict(mode_policy.get("tool_policy") or {})
    lines = [
        f"当前交互模式：{interaction_mode or 'role_mode'}。",
        f"投影参与强度：{projection_strength or 'primary'}。",
    ]
    if interaction_mode == "role_mode":
        lines.append("请优先保持角色与灵魂投影的自然表达，只在真实可用的只读能力范围内辅助回答。")
    elif interaction_mode == "standard_mode":
        lines.append("请在当前回合内用有限工具解决明确问题，结论必须说明真实依据和限制。")
    elif interaction_mode == "professional_mode":
        lines.append("请以专业任务职责和语义契约为最高优先级，灵魂投影只影响表达温度，不能覆盖交付物和验证要求。")
    if bool(tool_policy.get("requires_evidence_packet")):
        lines.append("工具或委派观察必须先沉淀为证据包，再进入最终结论。")
    if bool(verification_policy.get("deliverable_validator")):
        lines.append("最终回答需要接受交付物验证；缺少必要交付物时不能宣称完成。")
    return "\n".join(lines)


def _communication_guardrail_section(task_spec: dict[str, Any]) -> str:
    inputs = dict(task_spec.get("inputs") or {})
    protocol = dict(inputs.get("agent_communication_protocol") or {})
    if not protocol:
        return ""
    main_contract = dict(protocol.get("main_agent_contract") or {})
    child_contract = dict(protocol.get("child_agent_contract") or {})
    parent_contract = dict(protocol.get("parent_closeout_contract") or {})
    lines = [
        "Agent communication protocol:",
        f"- Transport: {str(protocol.get('transport') or 'runtime_tool:delegate_to_agent')}.",
        f"- Delegate when: {str(main_contract.get('delegate_when') or '').strip()}",
        f"- Main instruction style: {str(main_contract.get('instruction_style') or '').strip()}",
        f"- Scope rule: {str(main_contract.get('scope_rule') or '').strip()}",
        f"- Child must return: {', '.join(list(child_contract.get('must_return') or [])) or 'summary, answer_candidate'}.",
        f"- Parent closeout: {str(parent_contract.get('closeout_rule') or '').strip()}",
    ]
    return "\n".join(line for line in lines if line.strip() and not line.endswith(": "))


def _workflow_section(
    *,
    task_workflow: dict[str, Any],
    selected_recipe: dict[str, Any],
    workflow_steps: list[str],
    skill_ids: list[str],
) -> str:
    title = str(task_workflow.get("title") or selected_recipe.get("title") or "未命名工作流").strip()
    workflow_id = str(task_workflow.get("workflow_id") or selected_recipe.get("recipe_id") or "").strip() or "runtime_recipe"
    task_mode = str(task_workflow.get("task_mode") or selected_recipe.get("task_mode") or "").strip() or "runtime"
    lines = [
        f"Workflow: {title}",
        f"Workflow ID: {workflow_id}",
        f"Task mode: {task_mode}",
    ]
    if workflow_steps:
        lines.append(f"Steps: {' -> '.join(workflow_steps)}")
    if skill_ids:
        lines.append(f"Visible skills: {', '.join(skill_ids)}")
    stop_conditions = [str(item).strip() for item in list(task_workflow.get("stop_conditions") or ()) if str(item).strip()]
    if stop_conditions:
        lines.append(f"Stop conditions: {'; '.join(stop_conditions)}")
    output_boundary = str(
        task_workflow.get("output_boundary")
        or task_workflow.get("output_contract_id")
        or selected_recipe.get("output_schema")
        or ""
    ).strip()
    if output_boundary:
        lines.append(f"Output boundary: {output_boundary}")
    return "\n".join(lines)


def _projection_section(projection_requirement: dict[str, Any]) -> str:
    posture_tags = [str(item).strip() for item in list(projection_requirement.get("posture_tags") or ()) if str(item).strip()]
    attention_focus = [str(item).strip() for item in list(projection_requirement.get("attention_focus") or ()) if str(item).strip()]
    lines = [
        f"Projection role: {str(projection_requirement.get('role_type') or 'task_default')}.",
        f"Posture tags: {', '.join(posture_tags) or 'none'}.",
    ]
    identity_anchor = str(projection_requirement.get("identity_anchor") or "").strip()
    if identity_anchor:
        lines.append(f"Projection identity anchor: {identity_anchor}")
    projection_id = str(projection_requirement.get("projection_id") or "").strip()
    if projection_id:
        lines.append(f"Projection ID: {projection_id}.")
    soul_id = str(projection_requirement.get("soul_id") or "").strip()
    if soul_id:
        lines.append(f"Soul: {soul_id}.")
    if attention_focus:
        lines.append(f"Attention focus: {', '.join(attention_focus)}.")
    reason = str(projection_requirement.get("reason") or "").strip()
    if reason:
        lines.append(f"Projection reason: {reason}.")
    return "\n".join(lines)


def _output_section(
    *,
    task_execution_assembly: dict[str, Any],
    task_spec: dict[str, Any],
) -> str:
    requested_outputs = [str(item).strip() for item in list(task_execution_assembly.get("requested_outputs") or ()) if str(item).strip()]
    task_mode = str(task_execution_assembly.get("task_mode") or "").strip()
    if task_mode == "capability_execution":
        return (
            f"Output should satisfy task mode {task_mode}. "
            "If required inputs are already present, execute the capability directly and return the result."
        )
    output_contract = str(task_execution_assembly.get("output_contract_id") or "").strip()
    template_metadata = dict(task_execution_assembly.get("metadata") or {})
    final_answer_requirements = [
        str(item).strip()
        for item in list(template_metadata.get("final_answer_requirements") or [])
        if str(item).strip()
    ]
    forbidden_final_states = [
        str(item).strip()
        for item in list(template_metadata.get("forbidden_final_states") or [])
        if str(item).strip()
    ]
    return "\n".join(
        line
        for line in (
            f"Output should satisfy task mode: {task_mode or 'general_qa'}.",
            f"Requested outputs: {', '.join(requested_outputs) if requested_outputs else 'AssistantFinalAnswer'}.",
            f"Output contract: {output_contract}." if output_contract else "",
            f"Deliverable summary: {str(task_spec.get('summary') or '').strip()}" if str(task_spec.get("summary") or "").strip() else "",
            (
                "Mandatory final answer requirements: "
                + "; ".join(final_answer_requirements)
                + "."
            ) if final_answer_requirements else "",
            (
                "Forbidden terminal states: "
                + "; ".join(forbidden_final_states)
                + "."
            ) if forbidden_final_states else "",
        )
        if line
    )


def _context_policy_ref(context_policy_result: dict[str, Any]) -> str:
    package = dict(context_policy_result.get("package") or {})
    return str(
        context_policy_result.get("result_id")
        or package.get("package_id")
        or package.get("id")
        or package.get("rebuild_reason")
        or ""
    )


def _operation_requirement_from_payload(payload: dict[str, Any]):
    from tasks.capability_requirements import OperationRequirement

    return OperationRequirement(
        requirement_id=str(payload.get("requirement_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        source=str(payload.get("source") or ""),
        required_operations=tuple(str(item) for item in list(payload.get("required_operations") or []) if str(item)),
        optional_operations=tuple(str(item) for item in list(payload.get("optional_operations") or []) if str(item)),
        denied_operations=tuple(str(item) for item in list(payload.get("denied_operations") or []) if str(item)),
        reason=str(payload.get("reason") or ""),
        authority=str(payload.get("authority") or "candidate_only"),
        metadata=dict(payload.get("metadata") or {}),
    )
