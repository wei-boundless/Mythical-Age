from __future__ import annotations

from .process_state import DialogueState
from .models import Message
from .process_engine import ProcessStateEngine
from .turn_projection import TurnProjectionBuilder


class SessionUnderstandingProcessor:
    """Projects session truth into working memory without deciding current-turn intent."""

    def __init__(self) -> None:
        self.turn_projector = TurnProjectionBuilder()
        self.turn_analyzer = self.turn_projector
        self.process_engine = ProcessStateEngine(self.turn_projector)

    def process(
        self,
        messages: list[Message],
        previous_state: DialogueState,
        *,
        max_items: int = 6,
    ) -> DialogueState:
        snapshot = self.turn_projector.project(messages, previous_state)
        return self.process_engine.assemble(
            snapshot,
            previous_state,
            max_items=max_items,
        )
