from __future__ import annotations

from dataclasses import replace
from typing import Any

from orchestration.runtime_directive import RuntimeDirective
from task_system.tasks.run_models import TaskRunLedger

from .goal_contract import (
    ProfessionalTaskGoalContract,
    _dedupe_strings,
    _goal_contract_instruction,
)


def _model_only_directive(directive: RuntimeDirective, *, mode: str = "role_mode") -> RuntimeDirective:
    return replace(
        directive,
        operation_refs=("op.model_response",),
        diagnostics={
            **dict(directive.diagnostics or {}),
            "professional_task_mode": mode,
            "model_only": True,
            "delegation_disabled": True,
            "tool_execution_disabled": True,
        },
    )


def _professional_task_directive(
    directive: RuntimeDirective,
    *,
    mode: str,
    tool_execution_enabled: bool,
    delegation_enabled: bool,
    allowed_tool_operation_refs: list[str] | tuple[str, ...] | None = None,
    max_tool_rounds: int = 1,
) -> RuntimeDirective:
    if not tool_execution_enabled:
        return _model_only_directive(directive, mode=mode)
    operation_refs = tuple(
        _dedupe_strings(
            [
                "op.model_response",
                *list(allowed_tool_operation_refs or ()),
            ]
        )
    )
    return replace(
        directive,
        operation_refs=operation_refs,
        diagnostics={
            **dict(directive.diagnostics or {}),
            "professional_task_mode": mode,
            "model_only": False,
            "delegation_disabled": not delegation_enabled,
            "tool_execution_enabled": True,
            "controlled_tool_rounds": max(1, int(max_tool_rounds or 1)),
        },
    )


def _with_professional_task_instruction(
    model_messages: list[Any],
    *,
    mode: str,
    plan_items: list[dict[str, Any]],
    plan_coverage_review: dict[str, Any] | None = None,
    tool_execution_enabled: bool,
    delegation_enabled: bool,
    allowed_tool_names: list[str] | tuple[str, ...] | None = None,
    max_tool_calls: int = 0,
    max_tool_calls_per_task_run: int = 0,
    max_tool_rounds: int = 0,
    max_delegate_calls: int = 0,
    goal_contract: ProfessionalTaskGoalContract | None = None,
    semantic_contract: dict[str, Any] | None = None,
    mode_policy: dict[str, Any] | None = None,
    sandbox_policy: dict[str, Any] | None = None,
) -> list[Any]:
    plan_lines = "\n".join(
        f"- {item['title']}: {item['summary']}"
        for item in plan_items
        if str(item.get("title") or "").strip()
    )
    allowed_tools = [str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip()]
    contract_line = _goal_contract_instruction(goal_contract)
    semantic_line = _semantic_contract_instruction(dict(semantic_contract or {}))
    policy_line = _interaction_policy_instruction(dict(mode_policy or {}))
    material_mount_line = _material_mount_instruction(dict(sandbox_policy or {}))
    review = dict(plan_coverage_review or {})
    plan_passed = bool(review.get("passed") is True) if review else True
    if tool_execution_enabled:
        write_guidance = ""
        if "agent_todo" in set(allowed_tools):
            write_guidance += (
                "如果任务是多文件开发、长任务、复杂调试或用户要求连续验收，"
                "可以使用 agent_todo 建立和维护自己的可执行待办，并在真实动作后按需更新状态。"
                "todo 要拆到可执行小步，尤其是大型源码文件应拆成骨架写入、分段 edit_file、验证和收口；"
                "todo 不能替代真实文件写入、命令验证或最终证据。"
            )
        if "write_file" in set(allowed_tools) and goal_contract is not None and goal_contract.requires_write_output:
            target_paths = [
                str(path).strip()
                for path in list(goal_contract.required_output_paths or [])
                if str(path).strip()
            ]
            target_line = (
                "目标契约列出的缺失产物路径是：" + "、".join(target_paths[:6]) + "。"
                if target_paths
                else "目标契约要求真实写入产物，但没有绑定具体路径；你需要在允许写入范围内产出真实文件。"
            )
            write_guidance = (
                f"{write_guidance}"
                "目标契约要求真实文件写入；在读到核心材料后应尽快调用 write_file 或 edit_file 产出文件，"
                "不要把工具预算耗尽在泛化搜索上。"
                f"{target_line}"
                "如果目标契约列出多个文件，你需要逐个文件真实写入或增量编辑，直到缺失路径全部补齐。"
                "大型源码文件不要强行一次写完整；先写可运行骨架，再用 edit_file 分段补齐系统。"
            )
        tool_line = (
            "当前模式已开放预算受控的真实工具观察；只能基于真实工具结果写结论。"
            f"可用工具：{', '.join(allowed_tools) or '无'}。"
            f"每轮最多请求 {max(1, int(max_tool_calls or 1))} 个工具调用，"
            f"整个任务最多请求 {max(1, int(max_tool_calls_per_task_run or max_tool_calls or 1))} 个工具调用，"
            f"最多推进 {max(1, int(max_tool_rounds or 1))} 轮。"
            "如果还没有完成用户目标，可以在下一轮继续使用真实工具；如果已经完成，请直接收口。"
            f"{write_guidance}"
            "不要把工具调用、DSML、JSON schema 或内部协议写进可见回答。"
        )
    else:
        tool_line = "当前模式不会向你开放工具执行；不要声称执行了未发生的检索、测试、文件读取、写入或验证。"
    if not plan_passed:
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
        blocked_parts = []
        if missing_actions:
            blocked_parts.append("缺少动作覆盖：" + "、".join(missing_actions))
        if missing_deliverables:
            blocked_parts.append("缺少交付物覆盖：" + "、".join(missing_deliverables))
        tool_line = (
            "当前执行计划尚未通过系统覆盖审查，你不能请求写入、命令、浏览器或委派等执行类工具。"
            "请先提交或修正自己的执行计划，覆盖语义任务契约中的动作、交付物和证据要求。"
            + (("原因：" + "；".join(blocked_parts) + "。") if blocked_parts else "")
        )
    delegation_line = (
        (
            "当前模式允许受控委派子 Agent；只能基于真实委派回传写结论。"
            f"委派必须通过 delegate_to_agent 工具发起，最多 {max(1, int(max_delegate_calls or 1))} 次。"
            "委派指令要写成给专业同事派活：说明目标、范围、禁止扩大范围、期望返回 summary/answer_candidate/evidence_refs/limitations。"
            "子 Agent 回传只是 evidence packet，最终用户回答必须由你综合收口。"
        )
        if delegation_enabled
        else "当前模式不会向你开放子 Agent 委派；不要声称有子 Agent 已完成工作。"
    )
    instruction = (
        f"你是当前任务的主执行 Agent，正在使用 {mode}。\n"
        "请先锁定用户目标和边界，再由你生成或修正执行计划；系统只负责校验计划覆盖和工具权限。\n"
        f"{semantic_line}"
        f"{policy_line}"
        f"{material_mount_line}"
        f"{tool_line}\n"
        f"{delegation_line}\n"
        "如果当前可见上下文不足，请明确说明限制，并给出下一步建议。\n"
        "请在最终回答中覆盖：目标理解、你的计划、当前结论、限制或下一步。\n"
        f"{contract_line}"
        f"运行时计划：\n{plan_lines}"
    )
    if not model_messages:
        return [{"role": "system", "content": instruction}]
    messages = list(model_messages)
    insert_at = len(messages)
    last_role = ""
    if isinstance(messages[-1], dict):
        last_role = str(messages[-1].get("role") or "")
    else:
        last_role = str(getattr(messages[-1], "type", "") or getattr(messages[-1], "role", "") or "")
    if last_role == "user" or last_role == "human":
        insert_at = max(0, len(messages) - 1)
    messages.insert(insert_at, {"role": "system", "content": instruction})
    return messages


def _material_mount_instruction(sandbox_policy: dict[str, Any]) -> str:
    mounts = [
        dict(item)
        for item in list(sandbox_policy.get("material_mounts") or [])
        if isinstance(item, dict) and str(item.get("mount_path") or "").strip()
    ]
    if not mounts:
        return ""
    entries = [
        f"{item.get('mount_id')}: {item.get('mount_path')} ({item.get('status') or 'unknown'})"
        for item in mounts
    ]
    return (
        "外部源材料已由运行时导入 sandbox 内，只能通过这些相对材料入口读取："
        + "；".join(entries)
        + "。不要读取外部绝对源路径；目标产物仍写入用户指定的输出目录。\n"
    )


def _semantic_contract_instruction(semantic_contract: dict[str, Any]) -> str:
    if not semantic_contract:
        return ""
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    forbidden = [
        str(item).strip()
        for item in list(semantic_contract.get("forbidden_actions") or [])
        if str(item).strip()
    ]
    lines = [f"语义任务契约：{task_goal_type}。\n"]
    if deliverables:
        lines.append("最终必须交付：" + "、".join(deliverables) + "。\n")
    if forbidden:
        lines.append("禁止：" + "、".join(forbidden) + "。\n")
    return "".join(lines)


def _interaction_policy_instruction(mode_policy: dict[str, Any]) -> str:
    if not mode_policy:
        return ""
    interaction_mode = str(mode_policy.get("interaction_mode") or "").strip()
    projection_strength = str(mode_policy.get("projection_strength") or "").strip()
    if interaction_mode == "professional_mode":
        return (
            f"当前模式策略：professional_mode，投影强度 {projection_strength or 'style_only'}。"
            "专业职责和语义契约优先，灵魂投影只影响表达温度。\n"
        )
    if interaction_mode == "standard_mode":
        return (
            f"当前模式策略：standard_mode，投影强度 {projection_strength or 'companion'}。"
            "请在有限工具预算内解决当前回合问题，并说明真实依据和限制。\n"
        )
    if interaction_mode == "role_mode":
        return (
            f"当前模式策略：role_mode，投影强度 {projection_strength or 'primary'}。"
            "请保持灵魂/角色体验主导，只使用只读轻能力，不制造副作用。\n"
        )
    return ""


def _professional_runtime_policy(selected_recipe_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    mode_policy = dict(metadata.get("mode_policy") or {})
    return {
        "runtime_limits": dict(metadata.get("runtime_limits") or {}),
        "checkpoint_policy": dict(metadata.get("checkpoint_policy") or mode_policy.get("checkpoint_policy") or {}),
        "delegation_policy": dict(metadata.get("delegation_policy") or mode_policy.get("delegation_policy") or {}),
        "tool_execution_policy": dict(metadata.get("tool_execution_policy") or mode_policy.get("tool_policy") or {}),
        "verification_policy": dict(metadata.get("verification_policy") or mode_policy.get("verification_policy") or {}),
        "sandbox_policy": dict(metadata.get("sandbox_policy") or mode_policy.get("sandbox_policy") or {}),
        "mode_policy": mode_policy,
        "task_requirement_contract": dict(metadata.get("task_requirement_contract") or {}),
        "execution_obligation": dict(metadata.get("execution_obligation") or dict(metadata.get("task_requirement_contract") or {}).get("execution_obligation") or {}),
        "interaction_mode": str(metadata.get("interaction_mode") or mode_policy.get("interaction_mode") or ""),
    }


def _first_finalize_step_id(ledger: TaskRunLedger | None) -> str:
    if ledger is None:
        return ""
    for step in ledger.step_runs:
        if str(step.step_kind or "") == "finalize":
            return step.step_id
    return ""


def _standard_action_step_id(plan: list[dict[str, Any]]) -> str:
    items = [dict(item) for item in list(plan or []) if isinstance(item, dict)]
    for item in items:
        step_id = str(item.get("plan_item_id") or item.get("step_id") or "").strip()
        if step_id and any(
            token in step_id
            for token in (
                "material_review",
                "context_review",
                "produce_output",
                "verify_output",
                "delegation_review",
                "execute",
                "inspect",
                "analysis",
            )
        ):
            return step_id
    for item in items:
        step_id = str(item.get("plan_item_id") or item.get("step_id") or "").strip()
        if step_id and "goal" not in step_id:
            return step_id
    return str(dict(items[0]).get("plan_item_id") or dict(items[0]).get("step_id") or "").strip() if items else ""


def _allowed_tool_names_from_policy(
    tool_policy: dict[str, Any],
    *,
    runtime_tool_instances: list[Any] | None,
    delegation_enabled: bool = False,
) -> list[str]:
    configured = [
        str(item or "").strip()
        for item in list(tool_policy.get("allowed_tool_names") or [])
        if str(item or "").strip()
    ]
    if not configured:
        configured = [
            str(getattr(tool, "name", "") or "").strip()
            for tool in list(runtime_tool_instances or [])
            if str(getattr(tool, "name", "") or "").strip()
        ]
    denied = {
        str(item or "").strip()
        for item in list(tool_policy.get("denied_tool_names") or ([] if delegation_enabled else ["delegate_to_agent"]))
        if str(item or "").strip()
    }
    available = {
        str(getattr(tool, "name", "") or "").strip()
        for tool in list(runtime_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip()
    }
    result: list[str] = []
    seen: set[str] = set()
    for name in configured:
        if name in denied or name not in available or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result
