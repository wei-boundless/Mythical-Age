from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectInstance:
    project_id: str
    environment_id: str
    title: str
    project_kind: str = "project"
    template_id: str = ""
    library_id: str = ""
    lifecycle_state: str = "active"
    schema_version: str = "project_library.v1"
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_instance"

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("ProjectInstance requires project_id")
        if not self.environment_id:
            raise ValueError("ProjectInstance requires environment_id")
        if not self.library_id:
            raise ValueError("ProjectInstance requires library_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_instance_from_dict(payload: dict[str, Any]) -> ProjectInstance:
    project_id = str(payload.get("project_id") or "").strip()
    return ProjectInstance(
        project_id=project_id,
        environment_id=str(payload.get("environment_id") or "").strip(),
        title=str(payload.get("title") or project_id).strip(),
        project_kind=str(payload.get("project_kind") or "project").strip() or "project",
        template_id=str(payload.get("template_id") or "").strip(),
        library_id=str(payload.get("library_id") or f"library.{project_id}").strip(),
        lifecycle_state=str(payload.get("lifecycle_state") or "active").strip() or "active",
        schema_version=str(payload.get("schema_version") or "project_library.v1").strip() or "project_library.v1",
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "task_system.project_instance"),
    )
