from __future__ import annotations

from typing import Any

from .deliverable_progress import (
    build_deliverable_progress,
    goal_contract_targets_code_edit,
    material_review_satisfied,
    required_writes_satisfied,
)
from .goal_contract import ProfessionalTaskGoalContract
from ..memory.tool_observation_ledger import ToolObservationLedger


def build_closeout_repair_payload(
    *,
    missing_deliverables: list[str] | tuple[str, ...] = (),
    missing_evidence: list[str] | tuple[str, ...] = (),
    allowed_next_actions: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    repair_instruction: str = "请先补齐真实工具证据，再提交最终总结。",
) -> dict[str, Any]:
    return {
        "type": "closeout_repair_required",
        "missing_deliverables": [str(item) for item in list(missing_deliverables or []) if str(item).strip()],
        "missing_evidence": [str(item) for item in list(missing_evidence or []) if str(item).strip()],
        "allowed_next_actions": [dict(item) for item in list(allowed_next_actions or []) if isinstance(item, dict)],
        "repair_instruction": str(repair_instruction or ""),
    }


def suggest_evidence_repair_tools(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> tuple[str, ...]:
    if (
        goal_contract.requires_write_output
        and not required_writes_satisfied(goal_contract, tool_observation_ledger)
        and material_review_satisfied(goal_contract, tool_observation_ledger)
    ):
        if goal_contract.required_output_paths:
            return ("write_file",)
        if goal_contract_targets_code_edit(goal_contract):
            return ("edit_file",)
        return ("write_file", "edit_file")
    if (
        goal_contract.requires_verification_command
        and required_writes_satisfied(goal_contract, tool_observation_ledger)
        and not tool_observation_ledger.verification_passed()
    ):
        return ("terminal",)
    if goal_contract.requires_material_review and not material_review_satisfied(goal_contract, tool_observation_ledger):
        return ("read_file", "read_structured_file", "search_files", "search_text")
    return ()


def build_evidence_gap_guidance(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> str:
    suggested_tools = suggest_evidence_repair_tools(goal_contract, tool_observation_ledger)
    if not suggested_tools:
        return ""
    deliverable_progress = build_deliverable_progress(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    return (
        "目标契约仍缺少真实交付证据；建议工具："
        + "、".join(suggested_tools)
        + "。"
        + deliverable_progress.progress_hint()
    )
