from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..memory.tool_observation_ledger import ToolObservationLedger
from .deliverable_progress import (
    build_deliverable_progress,
    material_review_satisfied,
    next_missing_material_read,
    required_writes_satisfied,
)
from .goal_contract import ProfessionalTaskGoalContract


READ_TOOLS = {"read_file", "read_structured_file", "search_files", "search_text", "glob_paths", "list_dir", "path_exists", "stat_path"}
WRITE_TOOLS = {"write_file", "edit_file"}
VERIFY_TOOLS = {"terminal", "browser_control"}


@dataclass(frozen=True, slots=True)
class ActionGateDecision:
    allowed_tool_names: tuple[str, ...]
    forced: bool = False
    stage: str = "open"
    reason: str = ""
    missing_obligations: tuple[str, ...] = ()
    target_path: str = ""
    reserved_tool_calls: int = 0
    authority: str = "professional_runtime.action_gate"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_tool_names"] = list(self.allowed_tool_names)
        payload["missing_obligations"] = list(self.missing_obligations)
        return payload

    def instruction(self) -> str:
        if not self.forced:
            return ""
        tool_text = "、".join(self.allowed_tool_names)
        target_text = f"目标路径：{self.target_path}。" if self.target_path else ""
        if self.stage == "read_material":
            return (
                "运行时已确认任务存在必读材料，当前优先目标是取得缺失材料的真实观察；"
                "可以先用无副作用计划或路径恢复工具定位材料。"
                f"下一步只能从这些工具中选择：{tool_text}。{target_text}"
                "不要跳到写入、验证或只写总结；先读取这份材料。"
            )
        if self.stage == "write_output":
            return (
                "运行时已确认材料读取义务满足，当前唯一优先动作是补齐真实写入产物。"
                f"下一步只能从这些工具中选择：{tool_text}。{target_text}"
                "不要继续泛化读取、搜索或只写总结；先完成真实文件写入或编辑。"
            )
        if self.stage == "verify_output":
            return (
                "运行时已确认写入义务满足，当前唯一优先动作是真实验证。"
                f"下一步只能从这些工具中选择：{tool_text}。"
                "不要继续读取或只写总结；先运行验证命令或浏览器验证。"
            )
        return f"运行时要求下一步只能从这些工具中选择：{tool_text}。"


def decide_next_action_gate(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    allowed_tool_names: list[str] | tuple[str, ...],
) -> ActionGateDecision:
    allowed = tuple(_dedupe(str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip()))
    allowed_set = set(allowed)
    progress = build_deliverable_progress(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    missing = progress.missing_obligations()
    next_material = next_missing_material_read(goal_contract, tool_observation_ledger)
    if next_material is not None:
        preferred_read_tools = tuple(
            tool
            for tool in list(next_material.suggested_tool_names)
            if tool in allowed_set
        )
        read_tools = preferred_read_tools or tuple(tool for tool in ("read_file", "read_structured_file") if tool in allowed_set)
        planning_tools = (
            ("agent_todo",)
            if (
                "agent_todo" in allowed_set
                and goal_contract.requires_write_output
                and not any(record.tool_name == "agent_todo" for record in tool_observation_ledger.records)
            )
            else ()
        )
        command_tools = (
            ("terminal",)
            if (
                "terminal" in allowed_set
                and not goal_contract.requires_write_output
                and goal_contract.requires_verification_command
            )
            else ()
        )
        recovery_tools = tuple(
            tool
            for tool in ("path_exists", "stat_path", "list_dir", "glob_paths", "search_files", "search_text")
            if tool in allowed_set and tool not in set(read_tools) and tool not in set(command_tools)
        )
        if read_tools:
            material_missing = tuple(
                f"read_material:{next_material.path}" if next_material.path else "read_material"
                for _ in (0,)
            )
            return ActionGateDecision(
                allowed_tool_names=(*planning_tools, *command_tools, *read_tools, *recovery_tools),
                forced=True,
                stage="read_material",
                reason="required_material_missing",
                missing_obligations=(*material_missing, *missing),
                target_path=next_material.path,
                reserved_tool_calls=4,
            )
    if (
        goal_contract.requires_write_output
        and material_review_satisfied(goal_contract, tool_observation_ledger)
        and not required_writes_satisfied(goal_contract, tool_observation_ledger)
    ):
        next_missing = progress.next_missing_deliverable
        preferred_write_tools = tuple(
            tool
            for tool in list(next_missing.suggested_tool_names if next_missing is not None else ())
            if tool in allowed_set
        )
        write_tools = preferred_write_tools or tuple(tool for tool in ("write_file", "edit_file") if tool in allowed_set)
        if write_tools:
            initial_todo_tools = (
                ("agent_todo",)
                if "agent_todo" in allowed_set and not list(tool_observation_ledger.records or ())
                else ()
            )
            return ActionGateDecision(
                allowed_tool_names=(*initial_todo_tools, *write_tools),
                forced=True,
                stage="write_output",
                reason="required_write_missing_after_material_review",
                missing_obligations=missing,
                target_path=next_missing.path if next_missing is not None else "",
                reserved_tool_calls=1,
            )
    if (
        goal_contract.requires_verification_command
        and required_writes_satisfied(goal_contract, tool_observation_ledger)
        and not tool_observation_ledger.verification_passed()
    ):
        verify_tools = tuple(tool for tool in ("terminal", "browser_control") if tool in allowed_set)
        if verify_tools:
            return ActionGateDecision(
                allowed_tool_names=verify_tools,
                forced=True,
                stage="verify_output",
                reason="required_verification_missing_after_write",
                missing_obligations=missing,
                reserved_tool_calls=1,
            )
    return ActionGateDecision(
        allowed_tool_names=allowed,
        forced=False,
        stage="open",
        reason="no_forced_action",
        missing_obligations=missing,
    )


def tool_counts_against_delivery_budget(tool_name: str, gate: ActionGateDecision) -> bool:
    name = str(tool_name or "").strip()
    if not name:
        return False
    if not gate.forced:
        return True
    return name in set(gate.allowed_tool_names)


def _dedupe(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
