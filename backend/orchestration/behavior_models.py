from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

NodeStatus = Literal["idle", "visited", "warning", "failed", "success", "blocked", "skipped"]


@dataclass(slots=True)
class BehaviorDecisionNode:
    id: str
    index: int
    label: str
    description: str
    status: NodeStatus = "idle"
    summary: str = ""
    source_event: str = ""
    source_module: str = ""
    reasons: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BehaviorDecisionEdge:
    id: str
    from_node: str
    to: str
    label: str
    status: NodeStatus = "success"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["from"] = payload.pop("from_node")
        return payload


@dataclass(slots=True)
class ContractPreview:
    tool_name: str
    scope_allowed: bool
    contract_action: str
    contract_reason: str
    permission_allowed: bool
    permission_reason: str
    missing_inputs: list[str] = field(default_factory=list)
    missing_bindings: list[str] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
