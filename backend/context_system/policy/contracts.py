from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from context_system.models.context_models import ContextPackage, SealedContextReceipt


ContextDecision = Literal["include", "drop"]


@dataclass(slots=True, frozen=True)
class ContextCandidateDecision:
    candidate_id: str
    memory_layer: str
    target_section: str
    decision: ContextDecision
    reason: str
    token_estimate: int = 0
    priority: int = 0
    budget_class: str = "optional"
    requires_verification_before_use: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ContextPolicyResult:
    package: ContextPackage
    decisions: tuple[ContextCandidateDecision, ...]
    sealed_receipt: SealedContextReceipt
    read_only: bool = True
    authority: str = "context_policy_result"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ValueError("ContextPolicyResult must remain read_only")
        if self.authority != "context_policy_result":
            raise ValueError("ContextPolicyResult cannot carry runtime authority")
        if not self.sealed_receipt.read_only:
            raise ValueError("ContextPolicyResult sealed receipt must remain read_only")
        if self.package.sealed_receipt is not None and self.package.sealed_receipt != self.sealed_receipt:
            raise ValueError("ContextPolicyResult package receipt mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self.package.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "sealed_receipt": self.sealed_receipt.to_dict(),
            "read_only": self.read_only,
            "authority": self.authority,
            "diagnostics": dict(self.diagnostics),
        }
