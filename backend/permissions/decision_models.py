from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


PermissionBehavior = Literal["allow", "deny", "ask", "sandbox", "repair"]
PermissionRiskLevel = Literal["none", "low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    behavior: PermissionBehavior
    operation_id: str
    reason: str = ""
    risk_level: PermissionRiskLevel = "none"
    approval_fingerprint: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "permissions.permission_decision"

    @property
    def allowed(self) -> bool:
        return self.behavior in {"allow", "sandbox"}

    @property
    def requires_approval(self) -> bool:
        return self.behavior == "ask"

    @property
    def denied(self) -> bool:
        return self.behavior == "deny"

    @classmethod
    def allow(cls, operation_id: str, *, reason: str = "", risk_level: PermissionRiskLevel = "none", diagnostics: dict[str, Any] | None = None) -> "PermissionDecision":
        return cls(behavior="allow", operation_id=operation_id, reason=reason, risk_level=risk_level, diagnostics=dict(diagnostics or {}))

    @classmethod
    def deny(cls, operation_id: str, *, reason: str, risk_level: PermissionRiskLevel = "medium", diagnostics: dict[str, Any] | None = None) -> "PermissionDecision":
        return cls(behavior="deny", operation_id=operation_id, reason=reason, risk_level=risk_level, diagnostics=dict(diagnostics or {}))

    @classmethod
    def ask(
        cls,
        operation_id: str,
        *,
        reason: str,
        approval_fingerprint: str,
        risk_level: PermissionRiskLevel = "medium",
        diagnostics: dict[str, Any] | None = None,
    ) -> "PermissionDecision":
        return cls(
            behavior="ask",
            operation_id=operation_id,
            reason=reason,
            risk_level=risk_level,
            approval_fingerprint=approval_fingerprint,
            diagnostics=dict(diagnostics or {}),
        )

    @classmethod
    def sandbox(cls, operation_id: str, *, reason: str = "", diagnostics: dict[str, Any] | None = None) -> "PermissionDecision":
        return cls(behavior="sandbox", operation_id=operation_id, reason=reason, risk_level="low", diagnostics=dict(diagnostics or {}))

    @classmethod
    def repair(cls, operation_id: str, *, reason: str, diagnostics: dict[str, Any] | None = None) -> "PermissionDecision":
        return cls(behavior="repair", operation_id=operation_id, reason=reason, risk_level="low", diagnostics=dict(diagnostics or {}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
