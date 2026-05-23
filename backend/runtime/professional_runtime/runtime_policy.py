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
            "auto_delegate_model_answer": False,
        },
    )


def _with_professional_task_instruction(
    model_messages: list[Any],
    *,
    mode: str,
    plan_items: list[dict[str, Any]],
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
    if tool_execution_enabled:
        write_guidance = ""
        if "write_file" in set(allowed_tools):
            write_guidance = (
                "如果用户明确要求写入、保存、产出草案文件或在 sandbox overlay 中交付文件，"
                "在读到核心材料后应尽快调用 write_file 产出文件；不要把工具预算耗尽在泛化搜索上。"
                "如果目标列出多个文件，你需要逐个文件真实写入，每次工具调用写一个完整文件，直到缺失路径全部补齐。"
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
        "请先锁定用户目标和边界，再按运行时计划完成收口。\n"
        f"{semantic_line}"
        f"{policy_line}"
        f"{tool_line}\n"
        f"{delegation_line}\n"
        "如果当前可见上下文不足，请明确说明限制，并给出下一步建议。\n"
        "请在最终回答中覆盖：目标理解、运行计划、当前结论、限制或下一步。\n"
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
    if interaction_mode == "vibe_coding":
        return (
            f"当前模式策略：vibe_coding，投影强度 {projection_strength or 'style_only'}。"
            "你是一名代码任务执行 Agent。请先理解项目结构和相关文件职责，再做必要、可维护的真实修改。"
            "修改后需要运行测试、构建、浏览器检查或给出无法验证的真实限制；最终回答只能基于真实变更、差异、命令或浏览器证据收口。"
            "不要把角色投影、灵魂设定或实现计划当作已完成证据。\n"
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
