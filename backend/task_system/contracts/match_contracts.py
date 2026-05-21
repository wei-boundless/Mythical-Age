from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskIntentContract:
    task_intent_id: str
    session_id: str
    task_id: str
    user_goal: str
    intent_kind: str = ""
    execution_intent: str = "single_task"
    requested_outputs: tuple[str, ...] = ()
    explicit_inputs: dict[str, Any] = field(default_factory=dict)
    source_binding_refs: tuple[str, ...] = ()
    followup_target_refs: tuple[str, ...] = ()
    capability_requests: tuple[str, ...] = ()
    execution_obligation: dict[str, Any] = field(default_factory=dict)
    semantic_task_contract: dict[str, Any] = field(default_factory=dict)
    mode_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_intent_contract"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_intent_contract":
            raise ValueError("TaskIntentContract authority must be task_system.task_intent_contract")
        if not self.task_intent_id:
            raise ValueError("TaskIntentContract requires task_intent_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["source_binding_refs"] = list(self.source_binding_refs)
        payload["followup_target_refs"] = list(self.followup_target_refs)
        payload["capability_requests"] = list(self.capability_requests)
        payload["execution_obligation"] = dict(self.execution_obligation or {})
        payload["semantic_task_contract"] = dict(self.semantic_task_contract or {})
        payload["mode_policy"] = dict(self.mode_policy or {})
        return payload
