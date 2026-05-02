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

