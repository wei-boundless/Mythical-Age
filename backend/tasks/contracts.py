from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskContract:
    task_id: str
    session_id: str
    user_goal: str
    source: str = "user_request"
    task_family: str = "unknown"
    task_mode: str = "unknown"
    parent_task_id: str = ""
    bindings: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    requested_outputs: tuple[str, ...] = ()
    candidate_refs: tuple[str, ...] = ()
    refs: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    authority: str = "task_contract"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_task_contract(
    *,
    task_id: str,
    session_id: str,
    user_goal: str,
    source: str = "manual_preview",
    task_family: str = "unknown",
    task_mode: str = "unknown",
) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        session_id=session_id,
        user_goal=user_goal,
        source=source,
        task_family=task_family,
        task_mode=task_mode,
    )

