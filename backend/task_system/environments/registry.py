from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .default_environments import default_task_environment_groups, default_task_environments
from .models import TaskEnvironmentDefinition, TaskEnvironmentGroup, TaskEnvironmentRecord, TaskEnvironmentSpec
from .repository import load_configured_task_environments


@dataclass(slots=True)
class TaskEnvironmentRegistry:
    definitions: dict[str, TaskEnvironmentDefinition]
    groups: dict[str, TaskEnvironmentGroup]

    @classmethod
    def with_defaults(cls) -> "TaskEnvironmentRegistry":
        definitions = {definition.record.environment_id: definition for definition in default_task_environments()}
        return cls(
            definitions=definitions,
            groups={group.group_id: group for group in default_task_environment_groups()},
        )

    @classmethod
    def from_backend_dir(cls, backend_dir: Path | str) -> "TaskEnvironmentRegistry":
        registry = cls.with_defaults()
        groups, definitions = load_configured_task_environments(backend_dir)
        merged_groups = dict(registry.groups)
        for group in groups:
            merged_groups[group.group_id] = group
        merged_definitions = dict(registry.definitions)
        for definition in definitions:
            if definition.record.group_id not in merged_groups:
                raise KeyError(f"unknown task environment group: {definition.record.group_id}")
            merged_definitions[definition.record.environment_id] = definition
        return cls(definitions=merged_definitions, groups=merged_groups)

    def get(self, environment_id: str) -> TaskEnvironmentDefinition | None:
        key = str(environment_id or "").strip()
        return self.definitions.get(key)

    def require(self, environment_id: str) -> TaskEnvironmentDefinition:
        definition = self.get(environment_id)
        if definition is None:
            raise KeyError(f"unknown task environment: {environment_id}")
        return definition

    def get_record(self, environment_id: str) -> TaskEnvironmentRecord | None:
        definition = self.get(environment_id)
        return definition.record if definition is not None else None

    def get_spec(self, environment_id: str) -> TaskEnvironmentSpec | None:
        definition = self.get(environment_id)
        return definition.spec if definition is not None else None

    def list(self) -> tuple[TaskEnvironmentDefinition, ...]:
        return tuple(self.definitions[key] for key in sorted(self.definitions))

    def list_groups(self) -> tuple[TaskEnvironmentGroup, ...]:
        return tuple(self.groups[key] for key in sorted(self.groups))


def default_task_environment_registry() -> TaskEnvironmentRegistry:
    return TaskEnvironmentRegistry.with_defaults()


def task_environment_registry_from_backend_dir(backend_dir: Path | str) -> TaskEnvironmentRegistry:
    return TaskEnvironmentRegistry.from_backend_dir(backend_dir)


