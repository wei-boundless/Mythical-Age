from __future__ import annotations

from dataclasses import dataclass

from file_management import (
    FileAccessTable,
    build_file_access_table,
    default_file_environment_registry,
    resolve_file_environment,
)

from .models import TaskEnvironmentGroup, TaskEnvironmentSpec
from .registry import TaskEnvironmentRegistry, default_task_environment_registry


@dataclass(frozen=True, slots=True)
class ResolvedTaskEnvironment:
    spec: TaskEnvironmentSpec
    group: TaskEnvironmentGroup | None
    file_access_tables: tuple[FileAccessTable, ...]
    authority: str = "task_system.resolved_task_environment"

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict(),
            "group": self.group.to_dict() if self.group is not None else {},
            "environment_prompts": [item.to_dict() for item in self.spec.environment_prompts],
            "sandbox_policy": self.spec.sandbox_policy.to_dict(),
            "storage_space": _storage_space_payload(self.spec),
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
    definition = active_registry.require(environment_id)
    spec = definition.spec
    group = active_registry.groups.get(definition.record.group_id)
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
    return ResolvedTaskEnvironment(spec=spec, group=group, file_access_tables=tuple(tables))


def _storage_space_payload(spec: TaskEnvironmentSpec) -> dict:
    resource = spec.resource_space
    namespace = str(resource.storage_namespace or spec.environment_id.replace(".", "/")).strip("/")
    return {
        "storage_namespace": namespace,
        "environment_storage_root": f"storage/task_environments/{namespace}",
        "runtime_state_root": f"storage/task_environments/{namespace}/runtime_state",
        "artifact_root": f"storage/task_environments/{namespace}/artifacts",
        "cache_root": f"storage/task_environments/{namespace}/cache",
        "task_library_root": f"storage/task_environments/{namespace}/task_library",
        "storage_root_policy": resource.storage_root_policy,
        "runtime_state_root_policy": resource.runtime_state_root_policy,
        "artifact_storage_policy": resource.artifact_storage_policy,
        "cache_storage_policy": resource.cache_storage_policy,
        "authority": "task_system.environment_storage_space",
    }


