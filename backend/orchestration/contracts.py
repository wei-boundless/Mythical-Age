from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


UnitType = Literal["tool", "skill", "agent", "worker", "memory", "retrieval", "artifact", "session", "task"]
PortName = Literal["candidate", "policy", "execution", "artifact", "commit", "trace"]


@dataclass(slots=True, frozen=True)
class UnitDescriptor:
    """Passive description of a modular unit; it never grants execution authority."""

    unit_id: str
    unit_type: UnitType
    owner_module: str
    version: str = "v1"
    ports: tuple[PortName, ...] = ("candidate", "trace")
    capability_tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    decision_authority: bool = False

    def __post_init__(self) -> None:
        if self.decision_authority:
            raise ValueError("UnitDescriptor is passive and cannot carry decision authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ports"] = list(self.ports)
        payload["capability_tags"] = list(self.capability_tags)
        return payload


@dataclass(slots=True, frozen=True)
class TaskContract:
    """Canonical current-turn task owned by the control kernel."""

    task_id: str
    user_goal: str
    session_id: str = ""
    task_kind: str = "general_query"
    modality: str = "general"
    source: str = "user_request"
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    canonical_owner: str = "orchestration.control_kernel"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class PolicyHint:
    """Non-authoritative policy material submitted through PolicyPort."""

    hint_id: str
    producer: str
    policy_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    authority: str = "hint_only"
    refs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "hint_only":
            raise ValueError("PolicyHint must remain hint_only")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
