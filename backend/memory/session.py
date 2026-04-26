from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from context_management import ContextController
from structured_memory import Message, SessionMemoryManager


class SessionMemoryLayer:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.session_root = base_dir / "session-memory"
        self.session_root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        return self.session_root / session_id

    def delete_session(self, session_id: str) -> bool:
        normalized = str(session_id or "").strip()
        if not normalized:
            return False

        root = self.session_root.resolve()
        target = (self.session_root / normalized).resolve()
        if target == root or root not in target.parents:
            raise ValueError("Invalid session_id")
        if not target.exists():
            return True
        if not target.is_dir():
            raise ValueError("Session memory path is not a directory")
        shutil.rmtree(target)
        return True

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

    def refresh_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> str:
        return self.manager(session_id).update_from_context_state(
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )
