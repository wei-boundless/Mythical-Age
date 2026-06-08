from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VSCodeContextSnapshot:
    session_id: str
    editor_context: dict[str, Any]
    received_at: float
    workspace_root: str = ""
    connection_id: str = ""
    authority: str = "integrations.vscode_connection.editor_context"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "editor_context": dict(self.editor_context),
            "received_at": self.received_at,
            "workspace_root": self.workspace_root,
            "connection_id": self.connection_id,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class VSCodeConnectionStatus:
    session_id: str
    status: str
    connected: bool
    stale: bool
    last_seen_at: float = 0.0
    workspace_root: str = ""
    project_key: str = ""
    active_file: dict[str, Any] = field(default_factory=dict)
    connection_session_id: str = ""
    connection_id: str = ""
    reused_project_connection: bool = False
    authority: str = "integrations.vscode_connection.status"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "connected": self.connected,
            "stale": self.stale,
            "last_seen_at": self.last_seen_at,
            "workspace_root": self.workspace_root,
            "project_key": self.project_key,
            "active_file": dict(self.active_file),
            "connection_session_id": self.connection_session_id,
            "connection_id": self.connection_id,
            "reused_project_connection": self.reused_project_connection,
            "authority": self.authority,
        }


class VSCodeConnectionConflict(ValueError):
    pass
