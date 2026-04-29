from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from context_management import ContextPackage


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
    preview_only: bool = True
    authority: str = "context_policy_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("ContextPolicyResult must remain preview_only")
        if self.authority != "context_policy_preview":
            raise ValueError("ContextPolicyResult cannot carry runtime authority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self.package.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "preview_only": self.preview_only,
            "authority": self.authority,
            "diagnostics": dict(self.diagnostics),
        }
