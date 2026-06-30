from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from context_system.models.context_models import TurnContextPackage, ContextSelectionReceipt


ContextDecision = Literal["include", "drop"]


@dataclass(slots=True, frozen=True)
class TurnContextCandidateDecision:
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
class TurnContextPolicyResult:
    package: TurnContextPackage
    decisions: tuple[TurnContextCandidateDecision, ...]
    selection_receipt: ContextSelectionReceipt
    read_only: bool = True
    authority: str = "turn_context_policy_result"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ValueError("TurnContextPolicyResult must remain read_only")
        if self.authority != "turn_context_policy_result":
            raise ValueError("TurnContextPolicyResult cannot carry runtime authority")
        if not self.selection_receipt.read_only:
            raise ValueError("TurnContextPolicyResult selection receipt must remain read_only")
        if self.package.selection_receipt is not None and self.package.selection_receipt != self.selection_receipt:
            raise ValueError("TurnContextPolicyResult package receipt mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self.package.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "selection_receipt": self.selection_receipt.to_dict(),
            "read_only": self.read_only,
            "authority": self.authority,
            "diagnostics": dict(self.diagnostics),
        }


