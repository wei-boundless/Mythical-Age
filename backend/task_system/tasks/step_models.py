from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskStepBlueprint:
    step_id: str
    title: str
    step_kind: str
    executor_type: str
    required_operations: tuple[str, ...] = ()
    optional_operations: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_contract_id: str = ""
    stop_policy: str = "on_success"
    retry_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_operations"] = list(self.required_operations)
        payload["optional_operations"] = list(self.optional_operations)
        payload["input_refs"] = list(self.input_refs)
        return payload


@dataclass(frozen=True, slots=True)
class StepInputBinding:
    step_id: str
    input_refs: tuple[str, ...] = ()
    inherited_parent_refs: tuple[str, ...] = ()
    private_state_refs: tuple[str, ...] = ()
    output_writebacks: dict[str, str] = field(default_factory=dict)
    binding_policy: str = "inherit_parent_context"
    authority: str = "task_system.step_input_binding"

    def __post_init__(self) -> None:
        if self.authority != "task_system.step_input_binding":
            raise ValueError("StepInputBinding authority must be task_system.step_input_binding")
        if not self.step_id:
            raise ValueError("StepInputBinding requires step_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_refs"] = list(self.input_refs)
        payload["inherited_parent_refs"] = list(self.inherited_parent_refs)
        payload["private_state_refs"] = list(self.private_state_refs)
        return payload


