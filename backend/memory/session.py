from __future__ import annotations

from pathlib import Path

from context_management import ContextController
from structured_memory import Message, SessionMemoryManager


class SessionMemoryLayer:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.session_root = base_dir / "session-memory"
        self.session_root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        return self.session_root / session_id

    def manager(self, session_id: str) -> SessionMemoryManager:
        return SessionMemoryManager(self.session_dir(session_id))

    def compactor(self, session_id: str):
        from context_management import ContextCompactor

        return ContextCompactor(self.manager(session_id))

    def context_controller(self, session_id: str) -> ContextController:
        controller = ContextController(self.manager(session_id))
        controller.compactor = self.compactor(session_id)
        return controller

    def refresh(self, session_id: str, messages: list[Message]) -> str:
        return self.manager(session_id).update_from_messages(messages)
