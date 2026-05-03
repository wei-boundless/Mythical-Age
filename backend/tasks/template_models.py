from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .step_models import TaskStepBlueprint


@dataclass(frozen=True, slots=True)
class TaskValidationRule:
    rule_id: str
    title: str
    validation_kind: str
    severity: str = "warning"
    parameters: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskTemplate:
    template_id: str
    title: str
    description: str
    task_family: str
    task_mode: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    default_agent_id: str = "agent:0"
    allowed_agent_ids: tuple[str, ...] = ("agent:0",)
    required_capability_tags: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()
    optional_operations: tuple[str, ...] = ()
    step_blueprints: tuple[TaskStepBlueprint, ...] = ()
    validation_rules: tuple[TaskValidationRule, ...] = ()
    ui_manifest: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_agent_ids"] = list(self.allowed_agent_ids)
        payload["required_capability_tags"] = list(self.required_capability_tags)
        payload["required_operations"] = list(self.required_operations)
        payload["optional_operations"] = list(self.optional_operations)
        payload["step_blueprints"] = [item.to_dict() for item in self.step_blueprints]
        payload["validation_rules"] = [item.to_dict() for item in self.validation_rules]
        return payload
