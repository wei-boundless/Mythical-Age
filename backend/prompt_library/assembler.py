from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration.artifact_policy_view import render_artifact_policy_instructions
from prompting.professional_profiles import get_professional_prompt_profile

from .registry import PromptLibraryRegistry
from .selector import (
    PromptSelector,
    build_prompt_selection_context,
    selected_prompt_resource,
)


def assemble_runtime_prompt_contract(
    *,
    base_dir: Path,
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
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_metadata = dict(selected_recipe.get("metadata") or {})
    semantic_contract = dict(
        task_contract.get("task_requirement_contract")
        or selected_metadata.get("task_requirement_contract")
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
    workflow_steps = _workflow_steps(task_workflow=task_workflow, selected_recipe=selected_recipe)
    skill_ids = [
        str(item.get("skill_id") or "").strip()
        for item in skill_runtime_views
        if str(item.get("skill_id") or "").strip()
    ]
    if not skill_ids and active_skill:
        skill_ids.append(str(active_skill.get("name") or "").strip())
    prompt_registry = PromptLibraryRegistry(base_dir)
    prompt_resources = prompt_registry.list_resources()
    prompt_selection_context = build_prompt_selection_context(
        task_id=task_id,
        user_goal=user_goal,
        task_contract=task_contract,
        task_execution_assembly=task_execution_assembly,
        selected_recipe=selected_recipe,
        task_workflow=task_workflow,
        registered_task=registered_task,
        skill_runtime_views=skill_runtime_views,
        active_skill=active_skill,
        agent_id=agent_id,
        current_turn_context=current_turn_context,
    )
    prompt_assembly_plan = PromptSelector(prompt_resources).select(prompt_selection_context)
    selected_stage_role = selected_prompt_resource(
        plan=prompt_assembly_plan,
        resources=prompt_resources,
        resource_type="stage_role",
    )
    selected_domain_role = selected_prompt_resource(
        plan=prompt_assembly_plan,
        resources=prompt_resources,
        resource_type="domain_role",
    )
    node_prompt_resource = selected_stage_role.to_dict() if selected_stage_role is not None else {}
    model_turn_decision = dict(prompt_selection_context.model_turn_decision or {})
    interaction_mode = str(prompt_selection_context.interaction_mode or mode_policy.get("interaction_mode") or "").strip()
    return {
        "contract_id": f"orchprompt:{task_id}",
        "task_id": task_id,
        "definition_id": str(binding.get("definition_id") or task_execution_assembly.get("task_family") or "runtime"),
        "binding_id": str(binding.get("binding_id") or ""),
        "task_section": "\n".join(
            [
                f"你本轮需要完成用户目标：{str(task_contract.get('user_goal') or user_goal).strip()}",
                "请围绕这个目标组织判断、行动和最终交付，不要把内部任务编号或编排字段暴露给用户。",
            ]
        ).strip(),
        "workflow_section": _workflow_section(
            task_workflow=task_workflow,
            selected_recipe=selected_recipe,
            workflow_steps=workflow_steps,
            skill_ids=skill_ids,
        ),
        "node_professional_prompt_section": _node_professional_prompt_section(
            task_workflow=task_workflow,
            registered_task=registered_task,
            prompt_resource=node_prompt_resource,
        ),
        "semantic_task_section": _semantic_task_section(semantic_contract),
        "goal_understanding_section": _goal_understanding_section(
            semantic_contract=semantic_contract,
            current_turn_context=dict(current_turn_context or {}),
            current_step_kind=str(prompt_selection_context.current_step_kind or ""),
        ),
        "domain_playbook_section": _domain_playbook_section(
            semantic_contract,
            selected_domain_role=selected_domain_role.to_dict() if selected_domain_role is not None else {},
        ),
        "professional_profile_section": professional_profile.prompt if professional_profile is not None else "",
        "agent_plan_section": _agent_plan_section(
            dict(selected_metadata.get("agent_plan_draft") or {}),
            operation_requirement=operation_requirement,
        ),
        "plan_coverage_section": _plan_coverage_section(dict(selected_metadata.get("plan_coverage_review") or {})),
        "completion_judgment_section": _completion_judgment_section(
            dict(selected_metadata.get("completion_judgment") or {}),
            verification_review=dict(selected_metadata.get("verification_review") or {}),
        ),
        "mode_policy_section": _mode_policy_section(
            mode_policy,
            model_turn_decision=model_turn_decision,
        ),
        "resource_section": "",
        "projection_section": _projection_section(
            projection_requirement,
            interaction_mode=interaction_mode,
        ),
        "output_section": _output_section(task_execution_assembly=task_execution_assembly, task_spec=task_spec),
        "guardrail_section": _communication_guardrail_section(task_spec),
        "metadata": {
            "agent_id": agent_id,
            "resource_policy_ref": str(operation_requirement.get("requirement_id") or ""),
            "registered_task_id": str(registered_task.get("task_id") or ""),
            "selected_recipe_id": str(selected_recipe.get("recipe_id") or ""),
            "task_workflow_id": str(task_workflow.get("workflow_id") or ""),
            "task_family": str(task_execution_assembly.get("task_family") or "").strip(),
            "task_mode": str(task_execution_assembly.get("task_mode") or "").strip(),
            "requested_outputs": list(task_execution_assembly.get("requested_outputs") or ()),
            "workflow_steps": workflow_steps,
            "visible_skill_ids": skill_ids,
            "node_professional_prompt_resource": node_prompt_resource,
            "prompt_selection_context": prompt_selection_context.to_dict(),
            "prompt_assembly_plan": prompt_assembly_plan.to_dict(),
            "task_requirement_contract": semantic_contract,
            "task_domain_binding": dict(prompt_selection_context.task_domain_binding or {}),
            "goal_hypothesis_set": dict(prompt_selection_context.goal_hypothesis_set or {}),
            "task_goal_spec": dict(prompt_selection_context.task_goal_spec or {}),
            "agent_plan_draft": dict(prompt_selection_context.agent_plan_draft or {}),
            "plan_coverage_review": dict(prompt_selection_context.plan_coverage_review or {}),
            "verification_review": dict(prompt_selection_context.verification_review or {}),
            "completion_judgment": dict(prompt_selection_context.completion_judgment or {}),
            "mode_policy": mode_policy,
            "professional_profile": professional_profile.to_dict() if professional_profile is not None else {},
        },
    }


def _workflow_steps(*, task_workflow: dict[str, Any], selected_recipe: dict[str, Any]) -> list[str]:
    workflow_steps = [
        str(item.get("title") or item.get("step_id") or "").strip()
        for item in list(task_workflow.get("steps") or ())
        if isinstance(item, dict) and str(item.get("title") or item.get("step_id") or "").strip()
    ]
    if workflow_steps:
        return workflow_steps
    return [
        str(item.get("title") or item.get("step_id") or "").strip()
        for item in list(selected_recipe.get("step_blueprints") or ())
        if isinstance(item, dict) and str(item.get("title") or item.get("step_id") or "").strip()
    ]


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


def _goal_understanding_section(
    *,
    semantic_contract: dict[str, Any],
    current_turn_context: dict[str, Any],
    current_step_kind: str = "",
) -> str:
    if str(current_step_kind or "").strip() != "task_goal_understanding":
        return ""
    diagnostics = dict(semantic_contract.get("diagnostics") or {})
    frame = dict(current_turn_context.get("task_goal_spec") or diagnostics.get("task_goal_spec") or {})
    contract_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    frame_goal_type = str(frame.get("task_goal_type") or "").strip()
    if contract_goal_type and frame_goal_type and frame_goal_type != contract_goal_type:
        return ""
    hypothesis_set = dict(
        diagnostics.get("goal_hypothesis_set")
        or dict(frame.get("evidence") or {}).get("goal_hypothesis_set")
        or {}
    )
    chosen = dict(hypothesis_set.get("chosen") or {})
    chosen_goal_type = str(chosen.get("task_goal_type") or "").strip()
    if contract_goal_type and chosen_goal_type and chosen_goal_type != contract_goal_type:
        hypothesis_set = {}
        chosen = {}
    rejected = [
        dict(item)
        for item in list(frame.get("rejected_goal_candidates") or diagnostics.get("rejected_goal_candidates") or [])
        if isinstance(item, dict)
    ]
    unacceptable = [
        str(item).strip()
        for item in list(frame.get("unacceptable_outcomes") or diagnostics.get("unacceptable_outcomes") or [])
        if str(item).strip()
    ]
    if not frame and not hypothesis_set and not rejected and not unacceptable:
        return ""
    lines = [
        "你需要以目标理解结果作为任务边界，不要让路径、报告名或旧路由覆盖用户真实目标。",
    ]
    if chosen:
        lines.append(
            "当前选定目标："
            + str(chosen.get("task_goal_type") or frame.get("task_goal_type") or "").strip()
            + "；领域："
            + str(chosen.get("task_domain") or frame.get("task_domain") or "").strip()
            + "。"
        )
    if rejected:
        rendered = []
        for item in rejected[:5]:
            goal_type = str(item.get("task_goal_type") or "").strip()
            reason = str(item.get("rejection_reason") or "").strip()
            if goal_type:
                rendered.append(goal_type + (f"（{reason}）" if reason else ""))
        if rendered:
            lines.append("已拒绝的候选目标：" + "；".join(rendered) + "。")
    if unacceptable:
        lines.append("不可接受的收口状态：" + "、".join(unacceptable) + "。")
    ambiguity = [
        str(item).strip()
        for item in list(frame.get("ambiguity_points") or hypothesis_set.get("ambiguity_points") or [])
        if str(item).strip()
    ]
    if ambiguity:
        lines.append("仍需警惕的歧义：" + "、".join(ambiguity) + "。")
    return "\n".join(line for line in lines if line.strip())


def _domain_playbook_section(semantic_contract: dict[str, Any], *, selected_domain_role: dict[str, Any] | None = None) -> str:
    role_prompt = str(dict(selected_domain_role or {}).get("content") or "").strip()
    if role_prompt:
        return role_prompt
    playbook = dict(semantic_contract.get("domain_playbook") or {})
    if not playbook:
        return ""
    role = str(playbook.get("role") or "").strip()
    responsibilities = [
        str(item).strip()
        for item in list(playbook.get("responsibilities") or [])
        if str(item).strip()
    ]
    forbidden = [
        str(item).strip()
        for item in list(playbook.get("forbidden_actions") or [])
        if str(item).strip()
    ]
    lines = []
    if role:
        lines.append(f"你在该任务领域中的职责是：{role}。")
    if responsibilities:
        lines.append("你需要负责：" + "、".join(responsibilities[:8]) + "。")
    if forbidden:
        lines.append("你不负责：" + "、".join(forbidden[:8]) + "。")
    return "\n".join(lines)


def _agent_plan_section(agent_plan: dict[str, Any], *, operation_requirement: dict[str, Any] | None = None) -> str:
    if not agent_plan:
        return ""
    steps = [dict(item) for item in list(agent_plan.get("steps") or []) if isinstance(item, dict)]
    if not steps:
        return ""
    diagnostics = dict(agent_plan.get("diagnostics") or {})
    source = str(agent_plan.get("source") or diagnostics.get("source") or "").strip()
    model_absent = diagnostics.get("model_plan_absent") is True
    operations = set(_operation_refs(dict(operation_requirement or {})))
    lines = [
        "你是一名任务执行规划员。你需要按计划推进，但如果真实代码或环境发现计划不完整，必须先修正计划再继续。",
        "每个步骤都必须产生对应的真实观察或明确阻断原因。",
    ]
    if model_absent or source == "deterministic_scaffold":
        lines.append("当前没有真实模型生成的执行计划草稿；这里的计划是系统脚手架兜底，执行前仍需按真实上下文修正。")
    elif source:
        lines.append(f"当前计划来源：{source}。")
    if "op.agent_todo" in operations:
        lines.append(
            "进入多步执行时，你需要维护当前任务的执行状态；如果可用工具中包含 agent_todo，请用它记录和更新待处理、进行中和已完成步骤。"
        )
        lines.append("todo 只是执行状态，不能替代用户目标、语义任务合同或完成证据。")
    for index, step in enumerate(steps[:12], start=1):
        title = str(step.get("title") or step.get("step_id") or "").strip()
        purpose = str(step.get("purpose") or "").strip()
        evidence = [
            str(item).strip()
            for item in list(step.get("evidence_expectations") or [])
            if str(item).strip()
        ]
        suffix = f"；证据期望：{', '.join(evidence)}" if evidence else ""
        lines.append(f"{index}. {title}：{purpose}{suffix}")
    return "\n".join(lines)


def _operation_refs(operation_requirement: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("required_operations", "optional_operations", "skill_required_operations"):
        refs.extend(str(item).strip() for item in list(operation_requirement.get(key) or []) if str(item).strip())
    return _dedupe(refs)


def _plan_coverage_section(review: dict[str, Any]) -> str:
    if not review:
        return ""
    passed = review.get("passed") is True
    gate_status = str(review.get("gate_status") or ("passed" if passed else "blocked_replan_required")).strip()
    missing_actions = [
        str(item).strip()
        for item in list(review.get("missing_actions") or [])
        if str(item).strip()
    ]
    missing_deliverables = [
        str(item).strip()
        for item in list(review.get("missing_deliverables") or [])
        if str(item).strip()
    ]
    lines = [
        "你需要先确认执行计划覆盖语义合同。计划未覆盖核心义务时，不能直接进入最终完成声明。",
        f"计划覆盖审查：{'通过' if passed else '未通过'}；硬门状态={gate_status}。",
    ]
    if missing_actions:
        lines.append("缺少动作覆盖：" + "、".join(missing_actions) + "。")
    if missing_deliverables:
        lines.append("缺少交付物覆盖：" + "、".join(missing_deliverables) + "。")
    if not passed:
        lines.append("计划覆盖未通过时不能进入执行步骤；你必须先补齐或修正计划，若因环境阻断无法覆盖，必须把阻断原因写入证据边界。")
    return "\n".join(lines)


def _completion_judgment_section(judgment: dict[str, Any], *, verification_review: dict[str, Any] | None = None) -> str:
    if not judgment:
        return ""
    review = dict(verification_review or {})
    status = str(judgment.get("status") or "unverified").strip()
    allowed = bool(judgment.get("completion_allowed") is True)
    lines = [
        "你需要以完成裁决作为收口边界；最终回答不能用语气替代证据状态。",
        f"完成裁决：状态={status}；允许完成声明={'是' if allowed else '否'}。",
    ]
    missing = [str(item).strip() for item in list(judgment.get("missing_deliverables") or []) if str(item).strip()]
    unsatisfied = [str(item).strip() for item in list(judgment.get("unsatisfied_obligations") or []) if str(item).strip()]
    unsupported = [str(item).strip() for item in list(judgment.get("unsupported_claims") or []) if str(item).strip()]
    limitations = [str(item).strip() for item in list(judgment.get("limitations") or []) if str(item).strip()]
    if missing:
        lines.append("缺失交付物：" + "、".join(missing[:8]) + "。")
    if unsatisfied:
        lines.append("未满足义务：" + "、".join(unsatisfied[:8]) + "。")
    if unsupported:
        lines.append("无证据支撑的声明：" + "、".join(unsupported[:8]) + "。")
    if limitations:
        lines.append("证据限制：" + "；".join(limitations[:5]) + "。")
    if review:
        mode = str(review.get("verifier_mode") or "readonly_structured_review").strip()
        lines.append(f"验证评审模式：{mode}；只读评审结果不能被最终回答覆盖。")
    return "\n".join(lines)


def _mode_policy_section(
    mode_policy: dict[str, Any],
    *,
    model_turn_decision: dict[str, Any] | None = None,
) -> str:
    if not mode_policy:
        return ""
    decision = dict(model_turn_decision or {})
    interaction_mode = str(mode_policy.get("interaction_mode") or "").strip()
    projection_strength = str(mode_policy.get("projection_strength") or "").strip()
    work_mode = str(decision.get("work_mode") or "").strip()
    action_intent = str(decision.get("action_intent") or "").strip()
    verification_policy = dict(mode_policy.get("verification_policy") or {})
    tool_policy = dict(mode_policy.get("tool_policy") or {})
    lines = [
        f"当前交互模式：{interaction_mode or 'role_mode'}。",
    ]
    if work_mode:
        lines.append(f"当前工作模式：{work_mode}。")
    if action_intent:
        lines.append(f"当前行动意图：{action_intent}。")
    if interaction_mode == "role_mode":
        lines.append(f"角色参与强度：{projection_strength or 'primary'}。")
    if interaction_mode == "role_mode":
        lines.append("请优先保持角色与灵魂投影的自然表达，只在真实可用的只读能力范围内辅助回答。")
    elif interaction_mode == "standard_mode":
        lines.append("请在当前回合内用有限工具解决明确问题，结论必须说明真实依据和限制。")
    elif interaction_mode == "professional_mode":
        lines.append("请以专业任务职责和语义契约为最高优先级推进，不要引入角色投影、灵魂设定或人格包袱来覆盖交付物和验证要求。")
    elif interaction_mode == "vibe_coding":
        lines.append(
            "你是一名代码任务执行 Agent。请先理解项目结构和相关文件职责，再做必要、可维护的真实修改；"
            "修改后需要运行测试、构建、浏览器检查或给出无法验证的真实限制。"
        )
        lines.append("最终回答必须基于真实变更、差异、命令或浏览器证据收口，不要把实现计划写成已完成结果。")
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
    lines = [
        f"当前工作方式：{title}。",
    ]
    if workflow_steps:
        lines.append("建议按这些阶段推进：" + " -> ".join(workflow_steps) + "。")
    if skill_ids:
        lines.append("当前可参考的能力边界：" + "、".join(skill_ids) + "。")
    stop_conditions = [str(item).strip() for item in list(task_workflow.get("stop_conditions") or ()) if str(item).strip()]
    if stop_conditions:
        lines.append("当满足这些条件时停止继续扩展：" + "；".join(stop_conditions) + "。")
    output_boundary = str(
        task_workflow.get("output_boundary")
        or task_workflow.get("output_contract_id")
        or selected_recipe.get("output_schema")
        or ""
    ).strip()
    if output_boundary:
        lines.append("最终交付必须遵守当前任务的输出边界。")
    return "\n".join(lines)


def _node_professional_prompt_section(
    *,
    task_workflow: dict[str, Any],
    registered_task: dict[str, Any],
    prompt_resource: dict[str, Any] | None = None,
) -> str:
    resource = dict(prompt_resource or {})
    resource_prompt = str(resource.get("content") or "").strip()
    if resource_prompt:
        return resource_prompt
    prompt = str(task_workflow.get("prompt") or "").strip()
    if prompt:
        return prompt
    metadata = dict((registered_task or {}).get("metadata") or {})
    return str(metadata.get("role_prompt") or metadata.get("prompt") or "").strip()


def _projection_section(
    projection_requirement: dict[str, Any],
    *,
    interaction_mode: str = "",
) -> str:
    if str(interaction_mode or "").strip() != "role_mode":
        return ""
    posture_tags = [str(item).strip() for item in list(projection_requirement.get("posture_tags") or ()) if str(item).strip()]
    attention_focus = [str(item).strip() for item in list(projection_requirement.get("attention_focus") or ()) if str(item).strip()]
    projection_strength = str(projection_requirement.get("projection_strength") or "").strip()
    lines = [
        f"当前表达姿态：{str(projection_requirement.get('role_type') or 'task_default')}。",
    ]
    if projection_strength == "style_only":
        lines.append("表达姿态只影响语气和协作温度，不能覆盖事实边界。")
    elif posture_tags:
        lines.append("表达侧重：" + "、".join(posture_tags) + "。")
    identity_anchor = str(projection_requirement.get("identity_anchor") or "").strip()
    if identity_anchor:
        lines.append(identity_anchor)
    if attention_focus:
        lines.append("请把注意力放在：" + "、".join(attention_focus) + "。")
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
            "如果所需输入已经齐备，请直接执行能力并返回结果；如果缺少关键输入，请明确指出缺什么。"
        )
    output_contract = str(task_execution_assembly.get("output_contract_id") or "").strip()
    template_metadata = dict(task_execution_assembly.get("metadata") or {})
    artifact_policy = dict(
        task_execution_assembly.get("artifact_policy")
        or template_metadata.get("artifact_policy")
        or {}
    )
    artifact_policy_section = render_artifact_policy_instructions(
        artifact_policy,
        heading="产物政策",
    )
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
            "最终回答必须交付：" + ("、".join(requested_outputs) if requested_outputs else "可被用户直接使用的答案") + "。",
            "最终交付必须满足已绑定的输出契约。" if output_contract else "",
            artifact_policy_section,
            f"交付摘要：{str(task_spec.get('summary') or '').strip()}" if str(task_spec.get("summary") or "").strip() else "",
            (
                "最终回答必须满足："
                + "；".join(final_answer_requirements)
                + "。"
            ) if final_answer_requirements else "",
            (
                "禁止以下收口状态："
                + "；".join(forbidden_final_states)
                + "。"
            ) if forbidden_final_states else "",
        )
        if line
    )


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
