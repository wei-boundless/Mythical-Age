from __future__ import annotations

from dataclasses import dataclass

from file_management import (
    FileAccessTable,
    build_file_access_table,
    default_file_environment_registry,
    resolve_file_environment,
)

from .models import TaskEnvironmentSpec
from .registry import TaskEnvironmentRegistry, default_task_environment_registry


@dataclass(frozen=True, slots=True)
class ResolvedTaskEnvironment:
    spec: TaskEnvironmentSpec
    file_access_tables: tuple[FileAccessTable, ...]
    authority: str = "task_system.resolved_task_environment"

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict(),
            "file_access_tables": [table.to_dict() for table in self.file_access_tables],
            "authority": self.authority,
        }


def resolve_task_environment(
    environment_id: str,
    *,
    registry: TaskEnvironmentRegistry | None = None,
    task_file_requirements: dict[str, dict] | None = None,
    agent_allowed_file_actions: tuple[str, ...] | list[str] = (),
) -> ResolvedTaskEnvironment:
    active_registry = registry or default_task_environment_registry()
    spec = active_registry.require(environment_id).spec
    file_registry = default_file_environment_registry()
    tables: list[FileAccessTable] = []
    for profile_ref in spec.file_management.file_profile_refs:
        file_environment = resolve_file_environment(
            profile_ref,
            registry=file_registry,
            repository_requirements=dict(task_file_requirements or {}),
        )
        tables.append(
            build_file_access_table(
                file_environment,
                task_file_requirements=dict(task_file_requirements or {}),
                agent_allowed_actions=agent_allowed_file_actions,
                table_id=f"file-access:{spec.environment_id}:{profile_ref}",
            )
        )
    return ResolvedTaskEnvironment(spec=spec, file_access_tables=tuple(tables))
