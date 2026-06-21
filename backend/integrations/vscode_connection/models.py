from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VSCodeConnectionLease:
    session_id: str
    workspace_root: str
    project_key: str
    connection_id: str
    acquired_at: float
    last_heartbeat_at: float
    expires_at: float
    source: str = ""
    client_name: str = ""
    duplicate_rejected_count: int = 0
    authority: str = "integrations.vscode_connection.lease"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace_root": self.workspace_root,
            "project_key": self.project_key,
            "connection_id": self.connection_id,
            "acquired_at": self.acquired_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "expires_at": self.expires_at,
            "source": self.source,
            "client_name": self.client_name,
            "duplicate_rejected_count": self.duplicate_rejected_count,
            "authority": self.authority,
        }


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
    age_seconds: float = 0.0
    stale_after_seconds: float = 0.0
    workspace_root: str = ""
    project_key: str = ""
    active_file: dict[str, Any] = field(default_factory=dict)
    visible_files: list[dict[str, Any]] = field(default_factory=list)
    open_tabs: list[dict[str, Any]] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    connection_id: str = ""
    lease_active: bool = False
    lease_expires_at: float = 0.0
    lease_last_heartbeat_at: float = 0.0
    duplicate_rejected_count: int = 0
    poller_count: int = 0
    authority: str = "integrations.vscode_connection.status"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "connected": self.connected,
            "stale": self.stale,
            "last_seen_at": self.last_seen_at,
            "age_seconds": self.age_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "workspace_root": self.workspace_root,
            "project_key": self.project_key,
            "active_file": dict(self.active_file),
            "visible_files": [dict(item) for item in self.visible_files],
            "open_tabs": [dict(item) for item in self.open_tabs],
            "limits": dict(self.limits),
            "connection_id": self.connection_id,
            "lease_active": self.lease_active,
            "lease_expires_at": self.lease_expires_at,
            "lease_last_heartbeat_at": self.lease_last_heartbeat_at,
            "duplicate_rejected_count": self.duplicate_rejected_count,
            "poller_count": self.poller_count,
            "authority": self.authority,
        }


class VSCodeConnectionConflict(ValueError):
    pass


class VSCodeConnectionLeaseConflict(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retry_after_ms: int = 15_000,
        status_code: int = 429,
        owner: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after_ms = int(retry_after_ms)
        self.status_code = int(status_code)
        self.owner = dict(owner or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retry_after_ms": self.retry_after_ms,
            "owner": dict(self.owner),
            "authority": "integrations.vscode_connection.lease_conflict",
        }
