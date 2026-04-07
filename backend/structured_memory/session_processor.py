from __future__ import annotations

from .dialogue_state import DialogueState
from .models import Message
from .process_engine import ProcessStateEngine
from .turn_understanding import TurnUnderstandingAnalyzer
from .understanding_reconciliation import UnderstandingReconciler


class SessionUnderstandingProcessor:
    """Interprets session truth into flow-aware working memory state."""

    def __init__(self) -> None:
        self.turn_analyzer = TurnUnderstandingAnalyzer()
        self.reconciler = UnderstandingReconciler()
        self.process_engine = ProcessStateEngine(self.turn_analyzer)

    def process(
        self,
        messages: list[Message],
        previous_state: DialogueState,
        *,
        max_items: int = 6,
    ) -> DialogueState:
        snapshot = self.turn_analyzer.analyze(messages, previous_state)
        reconciled = self.reconciler.review(snapshot, previous_state)
        return self.process_engine.assemble(
            reconciled.snapshot,
            previous_state,
            decision=reconciled.decision,
            max_items=max_items,
        )
