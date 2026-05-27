from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class BundleItemSpec:
    item_id: str
    ordinal: int
    user_text: str
    recipe_id: str = ""
    capability_kind: str = ""
    required_tool: str = ""
    requested_outputs: tuple[str, ...] = ()
    inherited_binding_refs: tuple[str, ...] = ()
    target_binding_ref: str = ""
    followup_target_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.bundle_item_spec"

    def __post_init__(self) -> None:
        if self.authority != "task_system.bundle_item_spec":
            raise ValueError("BundleItemSpec authority must be task_system.bundle_item_spec")
        if not self.item_id:
            raise ValueError("BundleItemSpec requires item_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_outputs"] = list(self.requested_outputs)
        payload["inherited_binding_refs"] = list(self.inherited_binding_refs)
        return payload


@dataclass(frozen=True, slots=True)
class BundleSpec:
    bundle_id: str
    parent_task_spec_ref: str = ""
    parent_task_id: str = ""
    aggregation_policy: str = "ordered_sections"
    items: tuple[BundleItemSpec, ...] = ()
    followup_resolution_mode: str = "stable_item_ref"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.bundle_spec"

    def __post_init__(self) -> None:
        if self.authority != "task_system.bundle_spec":
            raise ValueError("BundleSpec authority must be task_system.bundle_spec")
        if not self.bundle_id:
            raise ValueError("BundleSpec requires bundle_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload


