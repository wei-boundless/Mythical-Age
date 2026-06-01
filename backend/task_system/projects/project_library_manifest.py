from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectRepositoryBinding:
    repository_id: str
    role: str
    root_ref: str
    lifecycle: str = "active"
    readable: bool = True
    writable: bool = False
    searchable: bool = True
    commit_gate: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.repository_id:
            raise ValueError("ProjectRepositoryBinding requires repository_id")
        if not self.root_ref:
            raise ValueError("ProjectRepositoryBinding requires root_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectLifecycleActionSpec:
    action_id: str
    title: str
    operation: str
    description: str = ""
    enabled: bool = True
    requires_confirmation: bool = True
    selectors: dict[str, Any] = field(default_factory=dict)
    safeguards: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_lifecycle_action_spec"

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ValueError("ProjectLifecycleActionSpec requires action_id")
        if not self.operation:
            raise ValueError("ProjectLifecycleActionSpec requires operation")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectLibraryManifest:
    library_id: str
    project_id: str
    environment_id: str
    file_profile_id: str
    schema_version: str
    template_id: str = ""
    repositories: tuple[ProjectRepositoryBinding, ...] = ()
    lifecycle_actions: tuple[ProjectLifecycleActionSpec, ...] = ()
    indexes: dict[str, str] = field(default_factory=dict)
    migration_log: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_library_manifest"

    def __post_init__(self) -> None:
        if not self.library_id:
            raise ValueError("ProjectLibraryManifest requires library_id")
        if not self.project_id:
            raise ValueError("ProjectLibraryManifest requires project_id")
        if not self.environment_id:
            raise ValueError("ProjectLibraryManifest requires environment_id")
        if not self.file_profile_id:
            raise ValueError("ProjectLibraryManifest requires file_profile_id")
        repository_ids = [item.repository_id for item in self.repositories]
        if len(repository_ids) != len(set(repository_ids)):
            raise ValueError("ProjectLibraryManifest has duplicate repository_id")
        action_ids = [item.action_id for item in self.lifecycle_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("ProjectLibraryManifest has duplicate lifecycle action_id")

    def repository(self, repository_id: str) -> ProjectRepositoryBinding | None:
        target = str(repository_id or "").strip()
        return next((item for item in self.repositories if item.repository_id == target), None)

    def lifecycle_action(self, action_id: str) -> ProjectLifecycleActionSpec | None:
        target = str(action_id or "").strip()
        return next((item for item in self.lifecycle_actions if item.action_id == target), None)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["repositories"] = [item.to_dict() for item in self.repositories]
        payload["lifecycle_actions"] = [item.to_dict() for item in self.lifecycle_actions]
        payload["migration_log"] = [dict(item) for item in self.migration_log]
        return payload


def project_repository_binding_from_dict(payload: dict[str, Any]) -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding(
        repository_id=str(payload.get("repository_id") or "").strip(),
        role=str(payload.get("role") or payload.get("repository_id") or "").strip(),
        root_ref=str(payload.get("root_ref") or "").strip(),
        lifecycle=str(payload.get("lifecycle") or "active").strip() or "active",
        readable=bool(payload.get("readable", True)),
        writable=bool(payload.get("writable", False)),
        searchable=bool(payload.get("searchable", True)),
        commit_gate=str(payload.get("commit_gate") or "").strip(),
        metadata=dict(payload.get("metadata") or {}),
    )


def project_lifecycle_action_spec_from_dict(payload: dict[str, Any]) -> ProjectLifecycleActionSpec:
    return ProjectLifecycleActionSpec(
        action_id=str(payload.get("action_id") or payload.get("action") or "").strip(),
        title=str(payload.get("title") or payload.get("action_id") or payload.get("action") or "").strip(),
        operation=str(payload.get("operation") or "").strip(),
        description=str(payload.get("description") or "").strip(),
        enabled=bool(payload.get("enabled", True)),
        requires_confirmation=bool(payload.get("requires_confirmation", True)),
        selectors=dict(payload.get("selectors") or {}),
        safeguards=dict(payload.get("safeguards") or {}),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "task_system.project_lifecycle_action_spec"),
    )


def project_library_manifest_from_dict(payload: dict[str, Any]) -> ProjectLibraryManifest:
    return ProjectLibraryManifest(
        library_id=str(payload.get("library_id") or "").strip(),
        project_id=str(payload.get("project_id") or "").strip(),
        environment_id=str(payload.get("environment_id") or "").strip(),
        file_profile_id=str(payload.get("file_profile_id") or "").strip(),
        schema_version=str(payload.get("schema_version") or "project_library.v1").strip() or "project_library.v1",
        template_id=str(payload.get("template_id") or "").strip(),
        repositories=tuple(
            project_repository_binding_from_dict(item)
            for item in list(payload.get("repositories") or [])
            if isinstance(item, dict)
        ),
        lifecycle_actions=tuple(
            project_lifecycle_action_spec_from_dict(item)
            for item in list(payload.get("lifecycle_actions") or [])
            if isinstance(item, dict)
        ),
        indexes=dict(payload.get("indexes") or {}),
        migration_log=tuple(dict(item) for item in list(payload.get("migration_log") or []) if isinstance(item, dict)),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "task_system.project_library_manifest"),
    )
