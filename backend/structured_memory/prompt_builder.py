from __future__ import annotations

from .compact import ContextCompactor
from .memory_manager import MemoryManager
from .models import Message
from .session_memory import SessionMemoryManager
from .team_memory import TeamMemoryManager
from prompting import build_long_term_context_bundle


class PromptBuilder:
    """Demo-only prompt assembler for the standalone structured-memory example.

    The application runtime owns prompt assembly on the main path. This adapter
    remains only for the minimal demo agent in this package.
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        session_memory_manager: SessionMemoryManager,
        compactor: ContextCompactor | None = None,
        team_memory_manager: TeamMemoryManager | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.session_memory_manager = session_memory_manager
        self.compactor = compactor
        self.team_memory_manager = team_memory_manager

    def build_system_prompt(
        self,
        base_system_prompt: str,
        include_note_bodies: bool = True,
        note_limit: int = 5,
    ) -> str:
        del include_note_bodies
        del note_limit

        sections = [base_system_prompt.strip()]

        long_term_context = build_long_term_context_bundle(self.memory_manager.root_dir.parent)
        static_context = long_term_context.render(
            truncate=lambda text, _limit: text,
            limit=100_000,
            include_memory_block=True,
        ).strip()
        if static_context:
            sections.extend(["", static_context])

        session_memory = self.session_memory_manager.load().strip()
        if session_memory:
            sections.extend(["", "## Session Memory", session_memory])

        if self.team_memory_manager is not None:
            sections.extend(
                [
                    "",
                    "## Team Memory",
                    self.team_memory_manager.load_index().strip(),
                ]
            )

        return "\n".join(sections).strip() + "\n"

    def build_runtime_messages(
        self,
        base_system_prompt: str,
        conversation: list[Message],
    ) -> list[Message]:
        system_prompt = self.build_system_prompt(base_system_prompt)
        runtime_messages = [Message(role="system", content=system_prompt)]
        working_messages = list(conversation)
        if self.compactor is not None:
            working_messages = self.compactor.maybe_compact(working_messages).messages
        runtime_messages.extend(working_messages)
        return runtime_messages
