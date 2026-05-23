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
    node_prompt_resource = selected_stage_role.to_dict() if selected_stage_role is not None else {}
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
        "task_understanding_section": _task_understanding_section(
            semantic_contract=semantic_contract,
            current_turn_context=dict(current_turn_context or {}),
        ),
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
        ),
        "domain_playbook_section": _domain_playbook_section(semantic_contract),
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
            "task_workflow_id": str(task_workflow.get("workflow_id") or ""),
            "task_family": str(task_execution_assembly.get("task_family") or "").strip(),
            "task_mode": str(task_execution_assembly.get("task_mode") or "").strip(),
            "requested_outputs": list(task_execution_assembly.get("requested_outputs") or ()),
            "workflow_steps": workflow_steps,
            "visible_skill_ids": skill_ids,
            "node_professional_prompt_resource": node_prompt_resource,
            "prompt_selection_context": prompt_selection_context.to_dict(),
            "prompt_assembly_plan": prompt_assembly_plan.to_dict(),
            "semantic_task_contract": semantic_contract,
            "task_understanding_frame": dict(prompt_selection_context.task_understanding_frame or {}),
            "model_understanding_request": dict(prompt_selection_context.model_understanding_request or {}),
            "understanding_arbitration": dict(prompt_selection_context.understanding_arbitration or {}),
            "communication_frame": dict(prompt_selection_context.communication_frame or {}),
            "task_domain_binding": dict(prompt_selection_context.task_domain_binding or {}),
            "goal_hypothesis_set": dict(prompt_selection_context.goal_hypothesis_set or {}),
            "task_goal_frame": dict(prompt_selection_context.task_goal_frame or {}),
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


def _task_understanding_section(
    *,
    semantic_contract: dict[str, Any],
    current_turn_context: dict[str, Any],
) -> str:
    diagnostics = dict(semantic_contract.get("diagnostics") or {})
    frame = dict(
        current_turn_context.get("task_understanding_frame")
        or diagnostics.get("task_understanding_frame")
        or dict(diagnostics.get("task_goal_frame") or {}).get("task_understanding_frame")
        or {}
    )
    if not frame:
        return ""
    communication = dict(frame.get("communication_frame") or diagnostics.get("communication_frame") or {})
    lines = [
        "你负责先判断本轮请求应该如何被承接：用户是在提问、探讨方案、下达执行、纠偏，还是延续之前任务。",
        "你需要以用户真实目标、明确流程、约束和证据要求来确定行动边界。",
        "任务域只提供成熟工作习惯；用户明确给出的流程和禁令优先于任务域默认制式。",
    ]
    if communication:
        posture = str(communication.get("user_posture") or "").strip()
        agent_posture = str(communication.get("agent_posture") or "").strip()
        collaboration = str(communication.get("collaboration_mode") or "").strip()
        clarification = str(communication.get("clarification_policy") or "").strip()
        final_contract = str(communication.get("final_response_contract") or "").strip()
        lines.append(
            "交流承接："
            + f"用户姿态={posture or 'unspecified'}；"
            + f"agent姿态={agent_posture or 'unspecified'}；"
            + f"协作模式={collaboration or 'conversation'}；"
            + f"澄清策略={clarification or 'no_clarification_needed'}；"
            + f"最终回应契约={final_contract or 'direct_answer'}。"
        )
    interaction = str(frame.get("interaction_intent") or "").strip()
    action = str(frame.get("action_intent") or "").strip()
    mode = str(frame.get("execution_mode_hint") or "").strip()
    domain = str(frame.get("task_domain_hint") or "").strip()
    goal_type = str(frame.get("task_goal_type_hint") or "").strip()
    if interaction or action:
        lines.append(f"本轮交互意图：{interaction or 'unspecified'}；行动意图：{action or 'unspecified'}。")
    if domain or goal_type or mode:
        lines.append(f"任务域提示：{domain or 'general'}；目标类型提示：{goal_type or 'unspecified'}；执行方式提示：{mode or 'answer'}。")
    flow = [
        str(item).strip()
        for item in list(frame.get("user_provided_flow") or [])
        if str(item).strip()
    ]
    if flow:
        lines.append("用户明确流程：" + " -> ".join(flow[:8]) + "。")
    targets = [
        str(item).strip()
        for item in list(frame.get("target_objects") or [])
        if str(item).strip()
    ]
    if targets:
        lines.append("目标对象：" + "、".join(targets[:8]) + "。")
    constraints = [
        str(item).strip()
        for item in list(frame.get("explicit_constraints") or [])
        if str(item).strip()
    ]
    forbidden = [
        str(item).strip()
        for item in list(frame.get("forbidden_actions") or [])
        if str(item).strip()
    ]
    if constraints:
        lines.append("显式约束：" + "、".join(constraints[:8]) + "。")
    if forbidden:
        lines.append("禁止动作：" + "、".join(forbidden) + "。")
    evidence = [
        str(item).strip()
        for item in list(frame.get("evidence_requirements") or [])
        if str(item).strip()
    ]
    if evidence:
        lines.append("完成前需要形成或说明的证据边界：" + "、".join(evidence) + "。")
    context_binding = dict(frame.get("context_binding") or {})
    if context_binding:
        lines.append(
            "上下文绑定："
            + str(context_binding.get("kind") or "current_turn")
            + "（"
            + str(context_binding.get("source") or "user_message")
            + "）。"
        )
    arbitration = dict(frame.get("understanding_arbitration") or diagnostics.get("understanding_arbitration") or {})
    if arbitration:
        arbitration_diagnostics = dict(arbitration.get("diagnostics") or {})
        model_status = str(
            arbitration.get("model_draft_status")
            or arbitration_diagnostics.get("model_draft_status")
            or ""
        ).strip()
        if model_status:
            lines.append(
                "理解裁决："
                + ("没有真实模型理解草稿，当前理解来自确定性信号兜底。" if model_status == "absent" else f"模型理解草稿状态={model_status}。")
            )
        conflicts = [
            dict(item)
            for item in list(arbitration.get("conflict_set") or frame.get("conflict_set") or [])
            if isinstance(item, dict)
        ]
        if conflicts:
            rendered = []
            for item in conflicts[:4]:
                field_name = str(item.get("field") or "").strip()
                reason = str(item.get("reason") or "").strip()
                selected = str(item.get("selected_source") or "").strip()
                rendered.append(
                    field_name + (f"由{selected}优先" if selected else "") + (f"（{reason}）" if reason else "")
                )
            lines.append("理解冲突已记录，不能静默覆盖：" + "；".join(rendered) + "。")
        assumptions = [
            str(item).strip()
            for item in list(arbitration.get("assumption_set") or frame.get("assumption_set") or [])
            if str(item).strip()
        ]
        if assumptions:
            lines.append("当前理解中的假设：" + "；".join(assumptions[:5]) + "。")
    if bool(frame.get("clarification_needed")):
        question = str(frame.get("clarification_question") or "").strip()
        lines.append("如果不澄清会误执行：" + (question or "请先澄清关键目标或流程。"))
    return "\n".join(line for line in lines if line.strip())


def _domain_playbook_section(semantic_contract: dict[str, Any]) -> str:
    diagnostics = dict(semantic_contract.get("diagnostics") or {})
    binding = dict(diagnostics.get("task_domain_binding") or {})
    if not binding:
        return ""
    lines = [
        "你需要把任务域当作成熟工作制式，而不是用户目标裁判。",
        "任务域可以补充默认工作习惯、风险控制和验证习惯；用户明确流程、用户禁令和语义任务合同优先。",
    ]
    title = str(binding.get("title") or binding.get("bound_domain_id") or "").strip()
    family = str(binding.get("task_family") or "").strip()
    source = str(binding.get("binding_source") or "").strip()
    if title or family:
        lines.append(f"当前任务域制式：{title or family}；任务族：{family or 'general'}；绑定来源：{source or 'unknown'}。")
    default_practices = [str(item).strip() for item in list(binding.get("default_practices") or []) if str(item).strip()]
    validation = [str(item).strip() for item in list(binding.get("validation_practices") or []) if str(item).strip()]
    risks = [str(item).strip() for item in list(binding.get("risk_controls") or []) if str(item).strip()]
    if default_practices:
        lines.append("默认工作习惯：" + "；".join(default_practices[:6]) + "。")
    if validation:
        lines.append("默认验证习惯：" + "；".join(validation[:6]) + "。")
    if risks:
        lines.append("风险控制：" + "；".join(risks[:6]) + "。")
    return "\n".join(lines)


def _goal_understanding_section(
    *,
    semantic_contract: dict[str, Any],
    current_turn_context: dict[str, Any],
) -> str:
    diagnostics = dict(semantic_contract.get("diagnostics") or {})
    frame = dict(current_turn_context.get("task_goal_frame") or diagnostics.get("task_goal_frame") or {})
    hypothesis_set = dict(
        diagnostics.get("goal_hypothesis_set")
        or dict(frame.get("evidence") or {}).get("goal_hypothesis_set")
        or {}
    )
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
    chosen = dict(hypothesis_set.get("chosen") or {})
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


def _projection_section(projection_requirement: dict[str, Any]) -> str:
    posture_tags = [str(item).strip() for item in list(projection_requirement.get("posture_tags") or ()) if str(item).strip()]
    attention_focus = [str(item).strip() for item in list(projection_requirement.get("attention_focus") or ()) if str(item).strip()]
    interaction_mode = str(projection_requirement.get("interaction_mode") or "").strip()
    projection_strength = str(projection_requirement.get("projection_strength") or "").strip()
    lines = [
        f"当前表达姿态：{str(projection_requirement.get('role_type') or 'task_default')}。",
    ]
    if interaction_mode == "professional_mode" or projection_strength == "style_only":
        lines.append("表达姿态只影响语气和协作温度，不能覆盖任务职责、语义契约、证据要求或交付边界。")
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
