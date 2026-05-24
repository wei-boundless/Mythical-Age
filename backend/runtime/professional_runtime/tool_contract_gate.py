from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.tool_runtime.tool_call_policy import ToolCallBindingOptions, build_required_tool_call_options

from .goal_contract import (
    ProfessionalTaskGoalContract,
    _dedupe_strings,
    _normalize_path_for_match,
)
from .required_action_queue import RequiredActionQueue, build_required_action_queue
from ..memory.tool_observation_ledger import ToolObservationLedger


@dataclass(frozen=True, slots=True)
class ProfessionalTaskContractGateDecision:
    allowed: bool
    error: str = ""
    message: str = ""
    repair_instruction: str = ""
    next_required_tool_names: tuple[str, ...] = ()
    next_required_path: str = ""


def _contract_gate_tool_request(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    requested_tool_name: str,
    requested_tool_args: dict[str, Any] | None = None,
    allowed_tool_names: list[str] | tuple[str, ...],
) -> ProfessionalTaskContractGateDecision:
    tool_name = str(requested_tool_name or "").strip()
    tool_args = dict(requested_tool_args or {})
    allowed = set(str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip())
    read_tools = {"read_file", "read_structured_file", "search_files", "search_text", "glob_paths"}
    required_queue = build_required_action_queue(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    current_action = required_queue.current_action
    if current_action is not None and current_action.kind in {"write_output", "ensure_dir"}:
        if _material_review_satisfied(goal_contract, tool_observation_ledger):
            write_tools = tuple(name for name in current_action.tool_names if name in allowed)
            if tool_name == "agent_todo":
                return ProfessionalTaskContractGateDecision(allowed=True)
            if tool_name in read_tools or tool_name == "delegate_to_agent":
                return ProfessionalTaskContractGateDecision(
                    allowed=False,
                    error="professional_task_goal_contract_requires_write",
                    message="目标契约要求产出真实文件或修改；材料观察已经足够，继续读搜或委派会偏离目标。",
                    repair_instruction=_contract_repair_instruction(
                        goal_contract=goal_contract,
                        tool_observation_ledger=tool_observation_ledger,
                        next_required_tool_names=write_tools,
                    ),
                    next_required_tool_names=_write_tool_priority(goal_contract, write_tools, tool_observation_ledger),
                    next_required_path=current_action.path,
                )
            if write_tools and tool_name not in write_tools and tool_name != "agent_todo":
                return ProfessionalTaskContractGateDecision(
                    allowed=False,
                    error="professional_task_goal_contract_requires_write",
                    message="目标契约要求下一步使用当前动作指定工具形成真实产物；写入完成前不能改用命令验证或继续泛化操作。",
                    repair_instruction=_contract_repair_instruction(
                        goal_contract=goal_contract,
                        tool_observation_ledger=tool_observation_ledger,
                        next_required_tool_names=write_tools,
                    ),
                    next_required_tool_names=_write_tool_priority(goal_contract, write_tools, tool_observation_ledger),
                    next_required_path=current_action.path,
                )
            if current_action.path and tool_name in write_tools:
                requested_path = str(tool_args.get("path") or "").strip()
                if not requested_path or not _path_matches(current_action.path, requested_path):
                    return ProfessionalTaskContractGateDecision(
                        allowed=False,
                        error="professional_task_goal_contract_requires_specific_write_path",
                        message=(
                            "目标契约要求当前动作写入指定路径；不能跳过、改写其他路径或省略 path。"
                            f"当前必须写入：{current_action.path}"
                        ),
                        repair_instruction=_contract_repair_instruction(
                            goal_contract=goal_contract,
                            tool_observation_ledger=tool_observation_ledger,
                            next_required_tool_names=("write_file",),
                        ),
                        next_required_tool_names=("write_file",),
                        next_required_path=current_action.path,
                    )
                return ProfessionalTaskContractGateDecision(allowed=True, next_required_path=current_action.path)
    if (
        current_action is not None
        and current_action.kind == "verify_command"
        and "terminal" in allowed
        and tool_name in read_tools.union({"write_file", "edit_file", "delegate_to_agent"})
    ):
        return ProfessionalTaskContractGateDecision(
            allowed=False,
            error="professional_task_goal_contract_requires_verification",
            message="目标契约要求写入或修改后运行命令验证；下一步必须使用 terminal 返回真实验证结果。",
            repair_instruction=_contract_repair_instruction(
                goal_contract=goal_contract,
                tool_observation_ledger=tool_observation_ledger,
                next_required_tool_names=("terminal",),
            ),
            next_required_tool_names=("terminal",),
        )
    return ProfessionalTaskContractGateDecision(allowed=True)


def _write_tool_priority(
    goal_contract: ProfessionalTaskGoalContract,
    available_write_tools: tuple[str, ...],
    tool_observation_ledger: ToolObservationLedger | None = None,
) -> tuple[str, ...]:
    available = tuple(name for name in available_write_tools if name)
    if "write_file" in available and goal_contract.required_output_paths:
        return _with_agent_todo_if_available(("write_file",), tool_observation_ledger) if tool_observation_ledger is not None else ("write_file",)
    if "edit_file" in available and _goal_contract_targets_code_edit(goal_contract):
        return _with_agent_todo_if_available(("edit_file",), tool_observation_ledger) if tool_observation_ledger is not None else ("edit_file",)
    return _with_agent_todo_if_available(available, tool_observation_ledger) if tool_observation_ledger is not None else available


def _goal_contract_targets_code_edit(goal_contract: ProfessionalTaskGoalContract) -> bool:
    code_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
    candidate_paths = [
        *list(goal_contract.required_material_paths or []),
        *list(goal_contract.required_output_paths or []),
    ]
    if any(_normalize_path_for_match(path).endswith(code_suffixes) for path in candidate_paths):
        return True
    return any(
        str(kind or "").strip().lower() in {"code", "python", "typescript", "javascript"}
        for kind in goal_contract.material_types
    )


def _contract_repair_instruction(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    gate_decision: ProfessionalTaskContractGateDecision | None = None,
    next_required_tool_names: tuple[str, ...] = (),
) -> str:
    if gate_decision is not None and gate_decision.repair_instruction:
        return gate_decision.repair_instruction
    required_tools = tuple(next_required_tool_names or _next_required_tools(goal_contract, tool_observation_ledger))
    if "write_file" in required_tools or "edit_file" in required_tools:
        required_queue = build_required_action_queue(
            goal_contract=goal_contract,
            tool_observation_ledger=tool_observation_ledger,
        )
        missing_paths = [
            action.path
            for action in required_queue.actions
            if action.kind in {"write_output", "ensure_dir"} and action.path and not action.satisfied
        ]
        next_missing_path = required_queue.current_path() or (missing_paths[0] if missing_paths else "")
        output_hint = (
            "缺失目标路径：" + "、".join(missing_paths)
            if missing_paths
            else "目标路径：" + "、".join(goal_contract.required_output_paths)
            if goal_contract.required_output_paths
            else "请在 sandbox overlay 中选择清晰的输出路径。"
        )
        next_path_hint = f"本轮优先写入：{next_missing_path}。" if next_missing_path else ""
        return (
            "上一轮请求已被目标契约拦截。用户目标要求真实产出文件或修改。"
            f"{output_hint}"
            f"{next_path_hint}"
            f"下一步只能使用 {' 或 '.join(required_tools)}；不要再请求 read_file、search_files、search_text、terminal 或委派。"
            "当前动作完成前不要切换到其他路径。"
            "文件内容必须完整可验收，不能写占位说明。"
            "如果确实无法写入，请只用普通中文说明阻塞原因，不要伪造工具调用。"
        )
    if "terminal" in required_tools:
        return (
            "上一轮请求已被目标契约拦截。用户目标要求命令验证。"
            "下一步只能使用 terminal 运行验证命令，并基于真实输出收口；不要继续读搜或改写。"
        )
    return (
        "上一轮请求已被目标契约拦截。请回到用户目标，只使用真实工具完成缺失动作；"
        "如果无法继续，直接说明缺失证据和阻塞原因。"
    )


def _contract_followup_guidance(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> str:
    required_tools = _next_required_tools(goal_contract, tool_observation_ledger)
    if not required_tools:
        return ""
    required_queue = build_required_action_queue(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    queue_guidance = required_queue.prompt_guidance()
    return "目标契约下一步仍缺少：" + "、".join(required_tools) + "。" + queue_guidance


def _next_required_tools(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> tuple[str, ...]:
    if (
        goal_contract.requires_write_output
        and not _required_writes_satisfied(goal_contract, tool_observation_ledger)
        and _material_review_satisfied(goal_contract, tool_observation_ledger)
    ):
        if goal_contract.required_output_paths:
            return _with_agent_todo_if_available(("write_file",), tool_observation_ledger)
        if _goal_contract_targets_code_edit(goal_contract):
            return _with_agent_todo_if_available(("edit_file",), tool_observation_ledger)
        return _with_agent_todo_if_available(("write_file", "edit_file"), tool_observation_ledger)
    if (
        goal_contract.requires_verification_command
        and _required_writes_satisfied(goal_contract, tool_observation_ledger)
        and not tool_observation_ledger.verification_passed()
    ):
        return ("terminal",)
    if goal_contract.requires_material_review and not _material_review_satisfied(goal_contract, tool_observation_ledger):
        return ("read_file", "read_structured_file", "search_files", "search_text")
    return ()


def _with_agent_todo_if_available(
    required_tools: tuple[str, ...],
    tool_observation_ledger: ToolObservationLedger,
) -> tuple[str, ...]:
    if tuple(required_tools or ()) == ("edit_file",):
        return required_tools
    if any(record.tool_name == "agent_todo" for record in tool_observation_ledger.records):
        return required_tools
    return ("agent_todo", *required_tools)


def _required_writes_satisfied(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> bool:
    if not goal_contract.requires_write_output:
        return True
    if not goal_contract.required_output_paths:
        return tool_observation_ledger.has_write()
    required_queue = build_required_action_queue(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    return all(action.satisfied for action in required_queue.actions if action.kind in {"write_output", "ensure_dir"})


def _missing_required_output_paths(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> list[str]:
    required_queue = build_required_action_queue(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    return [
        action.path
        for action in required_queue.actions
        if action.kind in {"write_output", "ensure_dir"} and action.path and not action.satisfied
    ]


def _model_tools_for_required_next_step(
    *,
    model_tool_instances: list[Any] | tuple[Any, ...],
    required_next_tools: tuple[str, ...],
) -> list[Any]:
    required = {str(item or "").strip() for item in list(required_next_tools or ()) if str(item or "").strip()}
    if not required:
        return list(model_tool_instances or [])
    selected = [
        tool
        for tool in list(model_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip() in required
    ]
    if any(name in required for name in ("read_file", "read_structured_file", "search_files", "search_text")):
        selected_names = {str(getattr(tool, "name", "") or "").strip() for tool in selected}
        for tool in list(model_tool_instances or []):
            if str(getattr(tool, "name", "") or "").strip() == "terminal" and "terminal" not in selected_names:
                selected.append(tool)
                break
    return selected


def _compact_professional_recovery_messages(
    *,
    user_message: str,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    structured_observations: list[dict[str, Any]],
    next_required_tools: tuple[str, ...],
    required_action_queue: RequiredActionQueue | None = None,
) -> list[Any]:
    required_queue = required_action_queue or build_required_action_queue(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    written_paths = _observation_paths_for_satisfaction(tool_observation_ledger, "write_output")
    missing_paths = [
        action.path
        for action in required_queue.actions
        if action.kind in {"write_output", "ensure_dir"} and action.path and not action.satisfied
    ]
    next_missing_path = required_queue.current_path() or (missing_paths[0] if missing_paths else "")
    latest_observations = [
        {
            "tool_name": str(item.get("tool_name") or ""),
            "path": str(dict(item.get("tool_args") or {}).get("path") or ""),
            "result": str(item.get("result") or "")[:240],
        }
        for item in list(structured_observations or [])[-6:]
        if isinstance(item, dict)
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是当前专业任务的主执行 Agent。本轮从模型超时处恢复，必须继续完成未满足的目标契约。"
                "不要重复已经成功写入的文件；不要输出解释、DSML、工具参数文本或最终总结。"
                f"下一步只能使用这些真实工具：{'、'.join(next_required_tools) or '按目标契约继续'}。"
                f"必须补齐的输出路径：{'、'.join(missing_paths) if missing_paths else '无'}。"
                f"本轮优先补齐路径：{next_missing_path or '无'}。"
                f"已经写入的路径：{'、'.join(written_paths) if written_paths else '无'}。"
                f"{required_queue.prompt_guidance()}"
                "文件内容必须是可运行或可验收的完整内容，不能写占位说明。"
            ),
        },
        {"role": "user", "content": str(user_message or "")},
        {
            "role": "system",
            "content": "最近真实观察摘要：" + repr(latest_observations),
        },
    ]


def _tool_call_options_for_round(
    *,
    round_model_tool_instances: list[Any] | tuple[Any, ...],
    required_next_tools: tuple[str, ...],
    max_tool_calls: int,
) -> ToolCallBindingOptions | None:
    tool_names = [
        str(getattr(tool, "name", "") or "").strip()
        for tool in list(round_model_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip()
    ]
    if not tool_names:
        return None
    if "terminal" in tool_names and any(
        name in set(required_next_tools or ()) for name in ("read_file", "read_structured_file", "search_files", "search_text")
    ):
        return None
    if required_next_tools:
        return build_required_tool_call_options(
            tool_names,
            strict=None,
            parallel_tool_calls=False,
        )
    if max(1, int(max_tool_calls or 1)) <= 1:
        return ToolCallBindingOptions(parallel_tool_calls=False)
    return None


def _material_review_satisfied(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> bool:
    if not goal_contract.requires_material_review:
        return True
    if not goal_contract.required_material_paths:
        return tool_observation_ledger.has_read()
    return all(tool_observation_ledger.has_read(path) for path in goal_contract.required_material_paths)


def _observation_paths_for_satisfaction(
    tool_observation_ledger: ToolObservationLedger,
    satisfaction: str,
) -> list[str]:
    paths: list[str] = []
    for record in tool_observation_ledger.records:
        if satisfaction not in record.satisfies:
            continue
        paths.extend([str(path).strip() for path in list(record.observed_paths or []) if str(path).strip()])
        paths.extend([str(path).strip() for path in list(record.matched_paths or []) if str(path).strip()])
    return _dedupe_strings(paths)


def _path_matches(target: str, candidate: str) -> bool:
    normalized_target = _normalize_path_for_match(target)
    normalized_candidate = _normalize_path_for_match(candidate)
    if not normalized_target or not normalized_candidate:
        return False
    return (
        normalized_candidate == normalized_target
        or normalized_candidate.endswith("/" + normalized_target)
        or normalized_target.endswith("/" + normalized_candidate)
    )
