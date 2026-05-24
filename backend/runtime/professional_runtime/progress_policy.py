from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..memory.tool_observation_ledger import ToolObservationLedger
from .deliverable_progress import build_deliverable_progress
from .goal_contract import ProfessionalTaskGoalContract


NON_PROGRESS_TOOLS = {"read_file", "read_structured_file", "search_files", "search_text", "glob_paths", "list_dir", "path_exists", "stat_path", "terminal"}


@dataclass(frozen=True, slots=True)
class ProgressPolicyDecision:
    allowed: bool
    reason: str = ""
    repair_observation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_progress_policy(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    ledger: ToolObservationLedger,
    requested_tool_name: str,
    requested_tool_args: dict[str, Any] | None = None,
    recent_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    max_non_progress_observations: int = 3,
) -> ProgressPolicyDecision:
    tool_name = str(requested_tool_name or "").strip()
    if tool_name in {"write_file", "edit_file", "agent_todo"}:
        return ProgressPolicyDecision(allowed=True, reason="progress_capable_tool")
    progress = build_deliverable_progress(goal_contract=goal_contract, tool_observation_ledger=ledger)
    missing = progress.missing_obligations()
    if not missing:
        return ProgressPolicyDecision(allowed=True, reason="no_missing_deliverables")
    if tool_name not in NON_PROGRESS_TOOLS:
        return ProgressPolicyDecision(allowed=True, reason="tool_not_classified_non_progress")
    recent = list(recent_observations or [])[-max(1, int(max_non_progress_observations or 3)) :]
    non_progress_count = sum(1 for item in recent if _observation_is_non_progress(item))
    if non_progress_count < max(1, int(max_non_progress_observations or 3)):
        return ProgressPolicyDecision(allowed=True, reason="non_progress_budget_available")
    return ProgressPolicyDecision(
        allowed=False,
        reason="recent_tool_calls_did_not_advance_missing_deliverables",
        repair_observation={
            "type": "tool_policy_rejection",
            "policy": "non_progress",
            "requested_tool": tool_name,
            "requested_args": dict(requested_tool_args or {}),
            "missing_deliverables": list(missing),
            "repair_instruction": (
                "请补齐真实缺失产物或验证证据；如果必须继续读取，请说明唯一缺失信息并读取唯一必要文件。"
            ),
        },
    )


def _observation_is_non_progress(observation: dict[str, Any]) -> bool:
    payload = dict(observation.get("payload") or observation)
    tool_name = str(payload.get("tool_name") or "").strip()
    if tool_name not in NON_PROGRESS_TOOLS:
        return False
    if payload.get("artifact_refs") or payload.get("observed_paths") and tool_name in {"write_file", "edit_file"}:
        return False
    structured = dict(payload.get("structured_payload") or {})
    if structured.get("artifact_refs") or structured.get("command_receipt", {}).get("passed") is True:
        return False
    return True
