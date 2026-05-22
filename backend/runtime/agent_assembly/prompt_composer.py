from __future__ import annotations

from typing import Any

from .models import AgentAssemblyContract


def compose_prompt(assembly: AgentAssemblyContract) -> str:
    prompt = assembly.prompt_assembly
    role_name = str(prompt.role_name if prompt is not None else "agent").strip() or "agent"
    role_summary = str(prompt.role_summary if prompt is not None else "执行代理").strip() or "执行代理"
    instruction_text = str(prompt.instruction_text if prompt is not None else "").strip()
    lines = [
        f"你是一名{role_name}。",
        role_summary,
    ]
    if instruction_text:
        lines.append(instruction_text)
    if assembly.output_boundary.selected_channel:
        lines.append(f"你的最终交付应是：{_delivery_label(assembly.output_boundary.selected_channel)}。")
    if assembly.capability_binding.allowed_operations:
        lines.append("你可以执行的操作已被封装，不要自行扩展。")
    if assembly.prompt_assembly and assembly.prompt_assembly.forbidden_actions:
        lines.append("禁止事项：" + "，".join(assembly.prompt_assembly.forbidden_actions))
    if assembly.prompt_assembly and assembly.prompt_assembly.required_outputs:
        lines.append("必须交付：" + "，".join(assembly.prompt_assembly.required_outputs))
    return "\n".join(line for line in lines if str(line).strip())


def compose_prompt_snapshot(assembly: AgentAssemblyContract) -> dict[str, Any]:
    return {
        "prompt_id": assembly.prompt_assembly.prompt_id if assembly.prompt_assembly is not None else "",
        "role_name": assembly.prompt_assembly.role_name if assembly.prompt_assembly is not None else "",
        "instruction_text": compose_prompt(assembly),
    }


def _delivery_label(channel: str) -> str:
    return {
        "assistant_message": "面向用户的最终回答",
        "graph_node_result": "当前阶段任务结果",
        "human_review": "人工审核反馈",
        "subruntime_result": "子任务结果",
    }.get(str(channel or "").strip(), "当前任务结果")
