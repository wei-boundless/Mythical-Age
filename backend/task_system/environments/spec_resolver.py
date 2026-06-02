from __future__ import annotations

from dataclasses import dataclass

from file_management import (
    FileAccessTable,
    build_file_access_table,
    default_file_environment_registry,
    resolve_file_environment,
)

from .models import TaskEnvironmentGroup, TaskEnvironmentSpec
from .prompt_resources import environment_resource_prompt_refs
from .registry import TaskEnvironmentRegistry, default_task_environment_registry


@dataclass(frozen=True, slots=True)
class ResolvedTaskEnvironment:
    spec: TaskEnvironmentSpec
    group: TaskEnvironmentGroup | None
    file_access_tables: tuple[FileAccessTable, ...]
    authority: str = "task_system.resolved_task_environment"

    def to_dict(self) -> dict:
        boundary = _environment_boundary_payload(self)
        return {
            "spec": self.spec.to_dict(),
            "group": self.group.to_dict() if self.group is not None else {},
            "environment_prompts": [item.to_dict() for item in self.spec.environment_prompts],
            "environment_boundary": boundary,
            "sandbox_policy": self.spec.sandbox_policy.to_dict(),
            "storage_space": boundary["storage_space"],
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


def _environment_boundary_payload(resolved: ResolvedTaskEnvironment) -> dict:
    spec = resolved.spec
    storage_space = _storage_space_payload(spec)
    file_access_tables = [table.to_dict() for table in resolved.file_access_tables]
    prompt_refs = _environment_prompt_refs(spec)
    return {
        "environment_id": spec.environment_id,
        "group_id": resolved.group.group_id if resolved.group is not None else "",
        "prompt_refs": list(prompt_refs),
        "resource_prompt_refs": list(environment_resource_prompt_refs(spec)),
        "environment_specific_prompt_refs": [
            item.prompt_id for item in spec.environment_prompts if str(item.prompt_id or "").strip()
        ],
        "prompt_count": len(prompt_refs),
        "storage_space": storage_space,
        "sandbox_policy": spec.sandbox_policy.to_dict(),
        "file_management": spec.file_management.to_dict(),
        "file_access_table_ids": [
            str(item.get("table_id") or "")
            for item in file_access_tables
            if str(item.get("table_id") or "").strip()
        ],
        "artifact_policy": spec.artifact_policy.to_dict(),
        "execution_policy": spec.execution_policy.to_dict(),
        "risk_policy": spec.risk_policy.to_dict(),
        "boundary_contract": {
            "environment_prompts_source": _environment_prompts_source(spec),
            "environment_prompt_role": "outer_environment_orientation",
            "tool_authority": "agent_profile_only",
            "skill_authority": "agent_profile_only",
            "mode_authority": "runtime_profile_only",
            "file_boundary_authority": "file_access_table",
            "storage_boundary_authority": "task_environment",
            "sandbox_boundary_authority": "task_environment",
        },
        "authority": "task_system.resolved_environment_boundary",
    }


def _environment_prompt_refs(spec: TaskEnvironmentSpec) -> tuple[str, ...]:
    refs = [
        *environment_resource_prompt_refs(spec),
        *[
            str(item.prompt_id or "").strip()
            for item in spec.environment_prompts
            if str(item.prompt_id or "").strip()
        ],
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return tuple(ordered)


def _environment_prompts_source(spec: TaskEnvironmentSpec) -> str:
    has_resource_refs = bool(environment_resource_prompt_refs(spec))
    prompt_items = tuple(spec.environment_prompts or ())
    has_inline = any(str(item.content or "").strip() for item in prompt_items)
    has_ref_only = any(str(item.prompt_id or "").strip() and not str(item.content or "").strip() for item in prompt_items)
    if has_resource_refs and has_inline:
        return "resource_prompt_library_and_task_environment_config"
    if has_inline and has_ref_only:
        return "prompt_library_and_task_environment_config"
    if has_inline:
        return "task_environment_config"
    return "prompt_library"


