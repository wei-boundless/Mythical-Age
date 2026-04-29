from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ResourceDecisionKind = Literal["allow", "deny", "requires_approval", "preview_only", "unknown"]


@dataclass(frozen=True, slots=True)
class ResourceDecision:
    operation_id: str
    decision: ResourceDecisionKind
    reason: str
    risk_tags: tuple[str, ...] = ()
    requires_user_approval: bool = False
    authorization_owner: str = "ResourcePolicy"
    approval_channel: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    policy_id: str
    task_id: str
    allowed_operations: tuple[str, ...] = ()
    denied_operations: tuple[str, ...] = ()
    requires_approval_operations: tuple[str, ...] = ()
    preview_only_operations: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    allowed_workers: tuple[str, ...] = ()
    denied_workers: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    denied_agents: tuple[str, ...] = ()
    memory_read_scope: str = "none"
    memory_write_scope: str = "none"
    filesystem_scope: dict[str, Any] = field(default_factory=dict)
    network_scope: dict[str, Any] = field(default_factory=dict)
    shell_scope: dict[str, Any] = field(default_factory=dict)
    approval_policy: str = "default"
    authority: str = "resource_policy"
    preview_only: bool = True
    adopted: bool = False
    runtime_executable: bool = False
    decisions: tuple[ResourceDecision, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

