from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IntentFrame:
    """Current-turn action map used as cognitive support, not a route result."""

    user_message: str
    action_hypotheses: tuple[str, ...] = ()
    target_domain_hints: tuple[str, ...] = ()
    task_complexity: str = "short"
    execution_strategy_candidates: tuple[str, ...] = ("single_react_loop",)
    evidence: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "intent.intent_frame"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action_hypotheses"] = list(self.action_hypotheses)
        payload["target_domain_hints"] = list(self.target_domain_hints)
        payload["execution_strategy_candidates"] = list(self.execution_strategy_candidates)
        return payload


@dataclass(frozen=True, slots=True)
class IntentDecision:
    """Deterministic first-pass decision; complex turns may later use a model judge."""

    primary_action: str = "start_new"
    actions: tuple[str, ...] = ("start_new",)
    target_domain_hint: str = ""
    needs_continuation: bool = False
    needs_clarification: bool = False
    retrieval_required: bool = False
    memory_recall_required: bool = False
    execution_strategy: str = "single_react_loop"
    confidence: float = 0.0
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "intent.intent_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = list(self.actions)
        return payload
