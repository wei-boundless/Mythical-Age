from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.tasks.step_models import StepInputBinding


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    task_spec_ref: str
    recipe_id: str
    session_id: str
    user_goal: str
    inputs: dict[str, Any] = field(default_factory=dict)
    bindings: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    current_turn_context_ref: str = ""
    task_intent_ref: str = ""
    bundle_spec_ref: str = ""
    bundle_item_ref: str = ""
    requested_outputs: tuple[str, ...] = ()
    step_input_bindings: tuple[StepInputBinding, ...] = ()
    selected_skill_ids: tuple[str, ...] = ()
    operation_requirement_ref: str = ""
    safety_envelope: dict[str, Any] = field(default_factory=dict)
    status: str = "selected"
    authority: str = "task_system.task_spec"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_spec":
            raise ValueError("TaskSpec authority must be task_system.task_spec")
        if not self.task_spec_ref:
            raise ValueError("TaskSpec requires task_spec_ref")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["step_input_bindings"] = [item.to_dict() for item in self.step_input_bindings]
        payload["selected_skill_ids"] = list(self.selected_skill_ids)
        return payload


