from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskWorkflowBinding:
    workflow_id: str
    title: str
    visible_skill_ids: tuple[str, ...] = ()
    steps: tuple[dict[str, Any], ...] = ()
    input_boundary: str = ""
    output_boundary: str = ""
    stop_conditions: tuple[str, ...] = ()
    required_evidence_refs: tuple[str, ...] = ()
    output_contract_id: str = ""
    prompt: str = ""
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["visible_skill_ids"] = list(self.visible_skill_ids)
        payload["steps"] = [dict(item) for item in self.steps]
        payload["stop_conditions"] = list(self.stop_conditions)
        payload["required_evidence_refs"] = list(self.required_evidence_refs)
        return payload
