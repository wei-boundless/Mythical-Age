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
    candidate_template_ids: tuple[str, ...] = ()
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
        payload["candidate_template_ids"] = list(self.candidate_template_ids)
        return payload


@dataclass(frozen=True, slots=True)
class TemplateMatchResult:
    match_id: str
    task_intent_ref: str
    template_id: str
    match_source: str
    match_reasons: tuple[str, ...] = ()
    fallback_used: bool = False
    capability_contract: tuple[str, ...] = ()
    output_contract: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.template_match"

    def __post_init__(self) -> None:
        if self.authority != "task_system.template_match":
            raise ValueError("TemplateMatchResult authority must be task_system.template_match")
        if not self.match_id:
            raise ValueError("TemplateMatchResult requires match_id")
        if not self.task_intent_ref:
            raise ValueError("TemplateMatchResult requires task_intent_ref")
        if not self.template_id:
            raise ValueError("TemplateMatchResult requires template_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["match_reasons"] = list(self.match_reasons)
        payload["capability_contract"] = list(self.capability_contract)
        payload["output_contract"] = list(self.output_contract)
        return payload
