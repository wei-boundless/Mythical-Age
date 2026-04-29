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


@dataclass(slots=True, frozen=True)
class ControlKernelPreviewContext:
    """Preview-only references submitted to the control kernel.

    This object is intentionally diagnostic. It can point at the task/resource
    preview chain, but it cannot carry runtime execution authority.
    """

    task_prompt_contract_ref: str = ""
    resource_policy_ref: str = ""
    prompt_manifest_ref: str = ""
    operation_requirement_ref: str = ""
    resource_policy_state: str = "preview"
    resource_policy_adopted: bool = False
    preview_only: bool = True
    runtime_directive_enabled: bool = False
    runtime_executable: bool = False
    operation_gate_required_before_execution: bool = True
    blocked_reason: str = "preview_only"
    denied_operations: tuple[str, ...] = ()
    requires_approval_operations: tuple[str, ...] = ()
    refs: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.resource_policy_state != "preview":
            raise ValueError("ControlKernelPreviewContext only accepts preview resource policy state")
        if self.resource_policy_adopted:
            raise ValueError("ControlKernelPreviewContext cannot carry adopted policy")
        if not self.preview_only:
            raise ValueError("ControlKernelPreviewContext must remain preview_only")
        if self.runtime_directive_enabled:
            raise ValueError("ControlKernelPreviewContext cannot enable runtime directives")
        if self.runtime_executable:
            raise ValueError("ControlKernelPreviewContext cannot be runtime executable")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["denied_operations"] = list(self.denied_operations)
        payload["requires_approval_operations"] = list(self.requires_approval_operations)
        return payload
