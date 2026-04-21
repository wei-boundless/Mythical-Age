from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class TaskSummaryRef:
    task_id: str
    query: str
    summary: str = ""
    task_kind: str = ""
    response_style: str = ""
    key_points: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidenceSummary:
    task_id: str = ""
    kind: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class MainContextState:
    active_goal: str = ""
    active_work_item: str = ""
    followup_target_task_id: str | None = None
    followup_target_task_ids: list[str] = field(default_factory=list)
    active_constraints: dict[str, Any] = field(default_factory=dict)
    latest_correction: str = ""
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt_block(self) -> str:
        lines = ["## Main Working Context"]
        if self.active_goal:
            lines.append(f"- Active Goal: {self.active_goal}")
        if self.active_work_item:
            lines.append(f"- Active Work Item: {self.active_work_item}")
        if self.followup_target_task_id:
            lines.append(f"- Follow-up Target Task: {self.followup_target_task_id}")
        if self.followup_target_task_ids:
            lines.append(
                f"- Follow-up Target Tasks: {', '.join(task_id for task_id in self.followup_target_task_ids if task_id)}"
            )
        if self.active_constraints:
            parts = [
                f"{key}={value}"
                for key, value in self.active_constraints.items()
                if value not in ("", None, [], {})
            ]
            if parts:
                lines.append(f"- Active Constraints: {', '.join(parts)}")
        if self.latest_correction:
            lines.append(f"- Latest Correction: {self.latest_correction}")
        if self.next_step:
            lines.append(f"- Next Step: {self.next_step}")
        return "\n".join(lines)
