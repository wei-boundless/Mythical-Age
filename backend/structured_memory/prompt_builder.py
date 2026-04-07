from __future__ import annotations

from .compact import ContextCompactor
from .memory_manager import MemoryManager
from .models import Message
from .session_memory import SessionMemoryManager
from .team_memory import TeamMemoryManager


class PromptBuilder:
    """Builds prompt sections from durable memory and session memory."""

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
        sections = [base_system_prompt.strip(), "", "## Persistent Memory"]

        index_text = self.memory_manager.load_index().strip()
        sections.extend([index_text, "", "## Session Memory", self.session_memory_manager.load().strip()])

        if self.team_memory_manager is not None:
            sections.extend(
                [
                    "",
                    "## Team Memory",
                    self.team_memory_manager.load_index().strip(),
                ]
            )

        if include_note_bodies:
            notes = self.memory_manager.load_relevant_notes(limit=note_limit)
            if notes:
                sections.extend(["", "## Loaded Memory Notes"])
                for note in notes:
                    sections.extend(
                        [
                            "",
                            f"### {note.filename}",
                            f"Title: {note.title}",
                            f"Type: {note.memory_type}",
                            note.content.strip(),
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
