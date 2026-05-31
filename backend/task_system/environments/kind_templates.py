from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from task_system.storage import TaskSystemStorage


@dataclass(frozen=True, slots=True)
class TaskEnvironmentKindTemplate:
    kind_id: str
    title: str
    description: str = ""
    group_id: str = ""
    allowed_resource_refs: tuple[str, ...] = ()
    default_sandbox_policy: dict[str, Any] = field(default_factory=dict)
    default_execution_policy: dict[str, Any] = field(default_factory=dict)
    default_risk_policy: dict[str, Any] = field(default_factory=dict)
    default_prompt_cache_scope: str = "static_environment"
    allowed_task_graph_kinds: tuple[str, ...] = ()
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_environment_kind_template"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskEnvironmentKindTemplate":
        return cls(
            kind_id=str(payload.get("kind_id") or payload.get("environment_kind") or "").strip(),
            title=str(payload.get("title") or payload.get("kind_id") or "").strip(),
            description=str(payload.get("description") or ""),
            group_id=str(payload.get("group_id") or ""),
            allowed_resource_refs=_tuple_of_strings(payload.get("allowed_resource_refs")),
            default_sandbox_policy=dict(payload.get("default_sandbox_policy") or {}),
            default_execution_policy=dict(payload.get("default_execution_policy") or {}),
            default_risk_policy=dict(payload.get("default_risk_policy") or {}),
            default_prompt_cache_scope=str(payload.get("default_prompt_cache_scope") or "static_environment"),
            allowed_task_graph_kinds=_tuple_of_strings(payload.get("allowed_task_graph_kinds")),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_resource_refs"] = list(self.allowed_resource_refs)
        payload["allowed_task_graph_kinds"] = list(self.allowed_task_graph_kinds)
        return payload


class TaskEnvironmentKindTemplateRepository:
    def __init__(self, base_dir: Path) -> None:
        self.storage = TaskSystemStorage(base_dir)

    def list(self) -> list[TaskEnvironmentKindTemplate]:
        stored = self.storage.read_object(
            "task_environment_kind_templates.json",
            {"kind_templates": [item.to_dict() for item in default_task_environment_kind_templates()]},
        )
        templates = [
            TaskEnvironmentKindTemplate.from_dict(item)
            for item in list(stored.get("kind_templates") or [])
            if isinstance(item, dict)
        ]
        normalized = [item.to_dict() for item in templates]
        if stored.get("kind_templates") != normalized:
            self.storage.write_object("task_environment_kind_templates.json", {"kind_templates": normalized})
        return sorted(templates, key=lambda item: (item.group_id, item.kind_id))

    def get(self, kind_id: str) -> TaskEnvironmentKindTemplate | None:
        target = str(kind_id or "").strip()
        return next((item for item in self.list() if item.kind_id == target), None)

    def upsert(self, payload: dict[str, Any]) -> TaskEnvironmentKindTemplate:
        template = TaskEnvironmentKindTemplate.from_dict(payload)
        _validate_template(template)
        templates = [item for item in self.list() if item.kind_id != template.kind_id]
        templates.append(template)
        self.storage.write_object("task_environment_kind_templates.json", {"kind_templates": [item.to_dict() for item in sorted(templates, key=lambda item: item.kind_id)]})
        return template

    def delete(self, kind_id: str) -> str:
        target = str(kind_id or "").strip()
        templates = [item for item in self.list() if item.kind_id != target]
        if len(templates) == len(self.list()):
            raise KeyError(f"unknown environment kind template: {kind_id}")
        self.storage.write_object("task_environment_kind_templates.json", {"kind_templates": [item.to_dict() for item in templates]})
        return target


def default_task_environment_kind_templates() -> tuple[TaskEnvironmentKindTemplate, ...]:
    return (
        TaskEnvironmentKindTemplate(
            kind_id="creation",
            title="Creation",
            description="Creative task environments with manuscript, memory, artifact, and review-gated write boundaries.",
            group_id="environment_group.creation",
            allowed_resource_refs=("file_profile.writing_manuscript", "writing.memory_index"),
            allowed_task_graph_kinds=("coordination", "multi_agent"),
        ),
        TaskEnvironmentKindTemplate(
            kind_id="development",
            title="Development",
            description="Project workspace environments with read-only or sandbox-write execution boundaries.",
            group_id="environment_group.development",
            allowed_resource_refs=("file_profile.project_workspace",),
            allowed_task_graph_kinds=("coordination", "single_agent", "multi_agent"),
        ),
        TaskEnvironmentKindTemplate(
            kind_id="general",
            title="General",
            description="General workspace environments for lightweight context, documents, research, and bounded artifacts.",
            group_id="environment_group.general",
            allowed_resource_refs=("file_profile.general_workspace",),
            allowed_task_graph_kinds=("single_agent", "coordination"),
        ),
        TaskEnvironmentKindTemplate(
            kind_id="custom",
            title="Custom",
            description="User-defined environment kind. Custom templates should declare resource and policy defaults before production use.",
            group_id="environment_group.general",
            allowed_task_graph_kinds=("single_agent", "multi_agent", "coordination"),
        ),
    )


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _validate_template(template: TaskEnvironmentKindTemplate) -> None:
    if not template.kind_id:
        raise ValueError("environment kind template requires kind_id")
    if not template.title:
        raise ValueError("environment kind template requires title")
