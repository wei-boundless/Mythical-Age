from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import stable_json_hash


@dataclass(frozen=True, slots=True)
class CompactionDecision:
    status: str
    reason: str = ""
    replacement_history_ref: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.dynamic_context.compaction_decision"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "replacement_history_ref": self.replacement_history_ref,
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


def replacement_history_ref(*, session_id: str, task_run_id: str, history_projection: dict[str, Any]) -> str:
    digest = stable_json_hash(
        {
            "session_id": str(session_id or ""),
            "task_run_id": str(task_run_id or ""),
            "history_projection": history_projection,
        }
    ).removeprefix("sha256:")[:24]
    return f"replacement-history:{digest}"
