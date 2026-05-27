from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ExecutionMode = Literal["single", "bundle"]
BindingKind = Literal["source_file", "result", "subset", "task_ref"]
BindingSource = Literal["explicit_user_input", "task_ref"]


@dataclass(frozen=True, slots=True)
class ResolvedBinding:
    binding_id: str
    binding_kind: BindingKind
    identity: str = ""
    file_kind: str = ""
    source_handle_id: str = ""
    result_handle_id: str = ""
    subset_handle_id: str = ""
    owner_task_id: str = ""
    confidence: float = 0.0
    source: BindingSource = "explicit_user_input"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BundleItem:
    item_id: str
    ordinal: int
    user_text: str
    bundle_id: str = ""
    recipe_id: str = ""
    capability_kind: str = ""
    required_tool: str = ""
    requested_outputs: tuple[str, ...] = ()
    inherited_binding_refs: tuple[str, ...] = ()
    followup_target_ref: str = ""
    target_ref: str = ""
    target_binding: ResolvedBinding | None = None
    output_requirement: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["inherited_binding_refs"] = list(self.inherited_binding_refs)
        payload["target_binding"] = self.target_binding.to_dict() if self.target_binding is not None else None
        return payload


@dataclass(frozen=True, slots=True)
class TurnBinding:
    session_id: str
    task_id: str
    user_message: str
    intent: str = ""
    execution_mode: ExecutionMode = "single"
    bundle_id: str = ""
    explicit_inputs: dict[str, Any] = field(default_factory=dict)
    resolved_bindings: tuple[ResolvedBinding, ...] = ()
    bundle_items: tuple[BundleItem, ...] = ()
    followup_target_refs: tuple[str, ...] = ()
    restore_candidates_used: tuple[str, ...] = ()
    unresolved_ambiguities: tuple[str, ...] = ()
    task_goal_spec: dict[str, Any] = field(default_factory=dict)
    continuation_candidates: tuple[dict[str, Any], ...] = ()
    continuation_decision: dict[str, Any] = field(default_factory=dict)
    context_recall_candidates: tuple[dict[str, Any], ...] = ()
    structural_signals: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    authority: str = "context.current_turn"

    def __post_init__(self) -> None:
        if self.authority != "context.current_turn":
            raise ValueError("TurnBinding authority must be context.current_turn")

    @property
    def bundle_item_count(self) -> int:
        return len(self.bundle_items)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resolved_bindings"] = [item.to_dict() for item in self.resolved_bindings]
        payload["bundle_items"] = [item.to_dict() for item in self.bundle_items]
        payload["followup_target_refs"] = list(self.followup_target_refs)
        payload["restore_candidates_used"] = list(self.restore_candidates_used)
        payload["unresolved_ambiguities"] = list(self.unresolved_ambiguities)
        payload["continuation_candidates"] = [dict(item) for item in self.continuation_candidates]
        payload["context_recall_candidates"] = [dict(item) for item in self.context_recall_candidates]
        return payload


