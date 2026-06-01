from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectLifecycleRun:
    run_id: str
    project_id: str
    action: str
    status: str = "previewed"
    preview: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_lifecycle_run"

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("ProjectLifecycleRun requires run_id")
        if not self.project_id:
            raise ValueError("ProjectLifecycleRun requires project_id")
        if not self.action:
            raise ValueError("ProjectLifecycleRun requires action")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_lifecycle_run_from_dict(payload: dict[str, Any]) -> ProjectLifecycleRun:
    return ProjectLifecycleRun(
        run_id=str(payload.get("run_id") or "").strip(),
        project_id=str(payload.get("project_id") or "").strip(),
        action=str(payload.get("action") or "").strip(),
        status=str(payload.get("status") or "previewed").strip() or "previewed",
        preview=dict(payload.get("preview") or {}),
        result=dict(payload.get("result") or {}),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "task_system.project_lifecycle_run"),
    )
