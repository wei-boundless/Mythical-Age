from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .step_models import TaskStepBlueprint
from .template_models import TaskTemplate, TaskValidationRule


@dataclass(frozen=True, slots=True)
class ExecutionRecipe:
    recipe_id: str
    title: str
    description: str
    execution_kind: str
    task_family: str
    task_mode: str
    source_kind: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    default_agent_id: str = "agent:0"
    allowed_agent_ids: tuple[str, ...] = ("agent:0",)
    required_capability_tags: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()
    optional_operations: tuple[str, ...] = ()
    step_blueprints: tuple[TaskStepBlueprint, ...] = ()
    validation_rules: tuple[TaskValidationRule, ...] = ()
    safety_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    finalization_policy: dict[str, Any] = field(default_factory=dict)
    ui_manifest: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    legacy_template_id: str = ""

    @property
    def template_id(self) -> str:
        return str(self.legacy_template_id or self.recipe_id).strip()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["template_id"] = self.template_id
        payload["allowed_agent_ids"] = list(self.allowed_agent_ids)
        payload["required_capability_tags"] = list(self.required_capability_tags)
        payload["required_operations"] = list(self.required_operations)
        payload["optional_operations"] = list(self.optional_operations)
        payload["step_blueprints"] = [item.to_dict() for item in self.step_blueprints]
        payload["validation_rules"] = [item.to_dict() for item in self.validation_rules]
        return payload

    def to_legacy_template_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "title": self.title,
            "description": self.description,
            "task_family": self.task_family,
            "task_mode": self.task_mode,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "default_agent_id": self.default_agent_id,
            "allowed_agent_ids": list(self.allowed_agent_ids),
            "required_capability_tags": list(self.required_capability_tags),
            "required_operations": list(self.required_operations),
            "optional_operations": list(self.optional_operations),
            "step_blueprints": [item.to_dict() for item in self.step_blueprints],
            "validation_rules": [item.to_dict() for item in self.validation_rules],
            "safety_policy": dict(self.safety_policy),
            "ui_manifest": dict(self.ui_manifest),
            "enabled": bool(self.enabled),
            "metadata": dict(self.metadata),
        }


def execution_recipe_from_template(
    template: TaskTemplate,
    *,
    execution_kind: str = "",
    source_kind: str = "",
    artifact_policy: dict[str, Any] | None = None,
    finalization_policy: dict[str, Any] | None = None,
) -> ExecutionRecipe:
    metadata = dict(template.metadata or {})
    inferred_source_kind = str(source_kind or metadata.get("source_kind") or "").strip()
    inferred_execution_kind = str(execution_kind or metadata.get("execution_kind") or template.task_family or "conversation").strip()
    return ExecutionRecipe(
        recipe_id=str(template.template_id or "").strip(),
        title=str(template.title or "").strip(),
        description=str(template.description or "").strip(),
        execution_kind=inferred_execution_kind or "conversation",
        task_family=str(template.task_family or "").strip(),
        task_mode=str(template.task_mode or "").strip(),
        source_kind=inferred_source_kind,
        input_schema=dict(template.input_schema or {}),
        output_schema=dict(template.output_schema or {}),
        default_agent_id=str(template.default_agent_id or "agent:0"),
        allowed_agent_ids=tuple(str(item) for item in tuple(template.allowed_agent_ids or ("agent:0",))),
        required_capability_tags=tuple(str(item) for item in tuple(template.required_capability_tags or ())),
        required_operations=tuple(str(item) for item in tuple(template.required_operations or ())),
        optional_operations=tuple(str(item) for item in tuple(template.optional_operations or ())),
        step_blueprints=tuple(template.step_blueprints or ()),
        validation_rules=tuple(template.validation_rules or ()),
        safety_policy=dict(template.safety_policy or {}),
        artifact_policy=dict(artifact_policy or {}),
        finalization_policy=dict(finalization_policy or {}),
        ui_manifest=dict(template.ui_manifest or {}),
        enabled=bool(template.enabled),
        metadata=metadata,
        legacy_template_id=str(template.template_id or "").strip(),
    )
