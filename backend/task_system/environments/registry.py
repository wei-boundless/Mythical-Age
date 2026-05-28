from __future__ import annotations

from dataclasses import dataclass

from .default_environments import default_task_environment_groups, default_task_environments
from .models import TaskEnvironmentDefinition, TaskEnvironmentGroup, TaskEnvironmentRecord, TaskEnvironmentSpec


@dataclass(slots=True)
class TaskEnvironmentRegistry:
    definitions: dict[str, TaskEnvironmentDefinition]
    groups: dict[str, TaskEnvironmentGroup]
    aliases: dict[str, str]

    @classmethod
    def with_defaults(cls) -> "TaskEnvironmentRegistry":
        definitions = {definition.record.environment_id: definition for definition in default_task_environments()}
        aliases: dict[str, str] = {}
        for definition in definitions.values():
            for alias in list(dict(definition.record.metadata or {}).get("legacy_aliases") or []):
                value = str(alias or "").strip()
                if value:
                    aliases[value] = definition.record.environment_id
        return cls(
            definitions=definitions,
            groups={group.group_id: group for group in default_task_environment_groups()},
            aliases=aliases,
        )

    def get(self, environment_id: str) -> TaskEnvironmentDefinition | None:
        key = self.resolve_environment_id(environment_id)
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

    def resolve_environment_id(self, environment_id: str) -> str:
        key = str(environment_id or "").strip()
        return self.aliases.get(key, key)


def default_task_environment_registry() -> TaskEnvironmentRegistry:
    return TaskEnvironmentRegistry.with_defaults()


