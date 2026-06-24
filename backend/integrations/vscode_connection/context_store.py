from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from project_workspaces.service import project_workspace_key
from sessions import SessionProjectBindingConflict

from .models import (
    VSCodeConnectionConflict,
    VSCodeConnectionLease,
    VSCodeConnectionLeaseConflict,
    VSCodeConnectionStatus,
    VSCodeContextSnapshot,
)
from .path_normalization import normalize_workspace_root

DEFAULT_STALE_AFTER_SECONDS = 60.0
CONNECTION_LEASE_TTL_SECONDS = 45.0
LEASE_CONFLICT_RETRY_AFTER_MS = 15_000
LAUNCH_INTENT_TTL_SECONDS = 300.0
ACTIVE_FILE_PREVIEW_LIMIT = 24_000
SELECTION_TEXT_LIMIT = 8_000
VISIBLE_FILES_LIMIT = 20
OPEN_TABS_LIMIT = 100
DIAGNOSTICS_LIMIT = 80
WORKSPACE_ROOTS_LIMIT = 8
COMMAND_QUEUE_LIMIT = 50


class VSCodeConnectionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots_by_session: dict[str, VSCodeContextSnapshot] = {}
        self._leases_by_key: dict[str, VSCodeConnectionLease] = {}
        self._launch_intents: dict[str, dict[str, Any]] = {}
        self._commands_by_session: dict[str, list[dict[str, Any]]] = {}
        self._command_results_by_session: dict[str, dict[str, dict[str, Any]]] = {}
        self._active_command_polls: set[str] = set()

    def clear(self) -> None:
        with self._lock:
            self._snapshots_by_session.clear()
            self._leases_by_key.clear()
            self._launch_intents.clear()
            self._commands_by_session.clear()
            self._command_results_by_session.clear()
            self._active_command_polls.clear()

    def register_launch_intent(self, *, session_id: str, workspace_root: str) -> dict[str, Any]:
        target_session_id = str(session_id or "").strip()
        normalized_root = normalize_workspace_root(workspace_root)
        if not target_session_id:
            raise ValueError("session_id is required")
        if not normalized_root:
            raise VSCodeConnectionConflict("workspace_root is required")
        now = time.time()
        intent = {
            "session_id": target_session_id,
            "workspace_root": normalized_root,
            "created_at": now,
            "expires_at": now + LAUNCH_INTENT_TTL_SECONDS,
            "authority": "integrations.vscode_connection.launch_intent",
        }
        with self._lock:
            self._launch_intents[target_session_id] = intent
        return dict(intent)

    def resolve_launch_intent(
        self,
        *,
        workspace_roots: list[str],
        connection_id: str = "",
    ) -> dict[str, Any]:
        roots = [
            normalize_workspace_root(item)
            for item in list(workspace_roots or [])[:WORKSPACE_ROOTS_LIMIT]
            if str(item or "").strip()
        ]
        if not roots:
            return {"session_id": "", "reason": "no_workspace_roots"}
        now = time.time()
        payload: dict[str, Any] | None = None
        with self._lock:
            for key, intent in list(self._launch_intents.items()):
                if float(intent.get("expires_at") or 0) <= now:
                    self._launch_intents.pop(key, None)
                    continue
                intent_root = normalize_workspace_root(intent.get("workspace_root"))
                if any(intent_root == root for root in roots):
                    payload = {
                        "session_id": str(intent.get("session_id") or ""),
                        "workspace_root": intent_root,
                        "matched": True,
                        "authority": "integrations.vscode_connection.launch_intent",
                    }
                    break
        if payload is None:
            return {"session_id": "", "reason": "no_matching_launch_intent"}
        self._assert_resolve_allowed(payload, connection_id=connection_id)
        return payload

    def acquire_connection(
        self,
        *,
        session_manager: Any,
        session_id: str,
        workspace_roots: list[str],
        connection_id: str = "",
        source: str = "",
        client_name: str = "",
    ) -> VSCodeConnectionLease:
        target_session_id = str(session_id or "").strip()
        if not target_session_id:
            raise ValueError("session_id is required")
        normalized_connection_id = _normalize_connection_id(connection_id) or f"vscode:{uuid.uuid4().hex}"
        workspace_root = self._connection_workspace_root(
            session_manager=session_manager,
            session_id=target_session_id,
            workspace_roots=workspace_roots,
            bind=True,
        )
        if not workspace_root:
            raise VSCodeConnectionConflict("workspace_root is required")
        now = time.time()
        key = _lease_key(target_session_id, workspace_root)
        with self._lock:
            self._prune_expired_leases_locked(now)
            existing = self._leases_by_key.get(key)
            if existing is not None and existing.connection_id != normalized_connection_id and existing.expires_at > now:
                rejected = self._increment_duplicate_rejection_locked(key, existing)
                raise _lease_owned_conflict(rejected, now=now)
            lease = VSCodeConnectionLease(
                session_id=target_session_id,
                workspace_root=workspace_root,
                project_key=project_workspace_key(workspace_root),
                connection_id=normalized_connection_id,
                acquired_at=existing.acquired_at if existing and existing.connection_id == normalized_connection_id else now,
                last_heartbeat_at=now,
                expires_at=now + CONNECTION_LEASE_TTL_SECONDS,
                source=str(source or "vscode").strip()[:120],
                client_name=str(client_name or "").strip()[:240],
                duplicate_rejected_count=int(existing.duplicate_rejected_count if existing else 0),
            )
            self._leases_by_key[key] = lease
            return lease

    def heartbeat_connection(
        self,
        *,
        session_manager: Any,
        session_id: str,
        connection_id: str,
        workspace_roots: list[str] | None = None,
    ) -> VSCodeConnectionLease:
        target_session_id = str(session_id or "").strip()
        workspace_root = self._connection_workspace_root(
            session_manager=session_manager,
            session_id=target_session_id,
            workspace_roots=list(workspace_roots or []),
            bind=False,
        )
        lease = self.require_connection_owner(
            session_id=target_session_id,
            connection_id=connection_id,
            workspace_root=workspace_root,
            session_manager=session_manager,
        )
        return self._renew_lease(lease)

    def release_connection(
        self,
        *,
        session_manager: Any,
        session_id: str,
        connection_id: str,
    ) -> dict[str, Any]:
        lease = self.require_connection_owner(
            session_id=session_id,
            connection_id=connection_id,
            session_manager=session_manager,
        )
        with self._lock:
            self._leases_by_key.pop(_lease_key(lease.session_id, lease.workspace_root), None)
            self._active_command_polls.discard(lease.connection_id)
        return {"released": True, "lease": lease.to_dict(), "authority": "integrations.vscode_connection.lease_release"}

    def record_context(
        self,
        *,
        session_manager: Any,
        session_id: str,
        connection_id: str,
        editor_context: dict[str, Any],
    ) -> VSCodeContextSnapshot:
        target_session_id = str(session_id or "").strip()
        if not target_session_id:
            raise ValueError("session_id is required")
        payload = _normalize_editor_context(editor_context)
        workspace_root = _bind_or_validate_workspace_roots(
            session_manager=session_manager,
            session_id=target_session_id,
            workspace_roots=list(payload.get("workspace_roots") or []),
        )
        lease = self.require_connection_owner(
            session_id=target_session_id,
            connection_id=connection_id,
            workspace_root=workspace_root,
            session_manager=session_manager,
        )
        now = time.time()
        snapshot = VSCodeContextSnapshot(
            session_id=target_session_id,
            editor_context=payload,
            received_at=now,
            workspace_root=workspace_root,
            connection_id=lease.connection_id,
        )
        with self._lock:
            self._snapshots_by_session[target_session_id] = snapshot
        self._renew_lease(lease, now=now)
        return snapshot

    def require_connection_owner(
        self,
        *,
        session_id: str,
        connection_id: str,
        workspace_root: str = "",
        session_manager: Any | None = None,
    ) -> VSCodeConnectionLease:
        target_session_id = str(session_id or "").strip()
        normalized_connection_id = _normalize_connection_id(connection_id)
        if not target_session_id:
            raise ValueError("session_id is required")
        if not normalized_connection_id:
            raise VSCodeConnectionLeaseConflict(
                "connection_id is required",
                code="connection_id_required",
                retry_after_ms=LEASE_CONFLICT_RETRY_AFTER_MS,
                status_code=409,
            )
        root = normalize_workspace_root(workspace_root) or _session_project_root(session_manager, target_session_id)
        now = time.time()
        with self._lock:
            self._prune_expired_leases_locked(now)
            lease = self._lease_for_session_locked(target_session_id, root)
            if lease is None:
                raise VSCodeConnectionLeaseConflict(
                    "VS Code connection lease is required",
                    code="lease_required",
                    retry_after_ms=LEASE_CONFLICT_RETRY_AFTER_MS,
                    status_code=409,
                )
            if lease.connection_id != normalized_connection_id:
                rejected = self._increment_duplicate_rejection_locked(_lease_key(lease.session_id, lease.workspace_root), lease)
                raise _lease_owned_conflict(rejected, now=now)
            return lease

    def begin_command_poll(
        self,
        *,
        session_id: str,
        connection_id: str,
        session_manager: Any | None = None,
    ) -> VSCodeConnectionLease:
        lease = self.require_connection_owner(
            session_id=session_id,
            connection_id=connection_id,
            session_manager=session_manager,
        )
        with self._lock:
            if lease.connection_id in self._active_command_polls:
                raise VSCodeConnectionLeaseConflict(
                    "VS Code connection already has an active command poll",
                    code="duplicate_poller",
                    retry_after_ms=LEASE_CONFLICT_RETRY_AFTER_MS,
                    status_code=429,
                    owner=lease.to_dict(),
                )
            self._active_command_polls.add(lease.connection_id)
        return lease

    def end_command_poll(self, connection_id: str) -> None:
        normalized_connection_id = _normalize_connection_id(connection_id)
        if not normalized_connection_id:
            return
        with self._lock:
            self._active_command_polls.discard(normalized_connection_id)

    def _connection_workspace_root(
        self,
        *,
        session_manager: Any,
        session_id: str,
        workspace_roots: list[str],
        bind: bool,
    ) -> str:
        roots = [item for item in (normalize_workspace_root(root) for root in workspace_roots) if item]
        if roots and bind:
            return _bind_or_validate_workspace_roots(
                session_manager=session_manager,
                session_id=session_id,
                workspace_roots=roots,
            )
        if roots and not bind:
            project_root = _session_project_root(session_manager, session_id)
            if project_root and any(project_root == root for root in roots):
                return project_root
            return roots[0]
        return _session_project_root(session_manager, session_id)

    def _assert_resolve_allowed(self, payload: dict[str, Any], *, connection_id: str) -> None:
        session_id = str(payload.get("session_id") or "").strip()
        workspace_root = normalize_workspace_root(payload.get("workspace_root"))
        if not session_id or not workspace_root:
            return
        normalized_connection_id = _normalize_connection_id(connection_id)
        now = time.time()
        with self._lock:
            self._prune_expired_leases_locked(now)
            lease = self._leases_by_key.get(_lease_key(session_id, workspace_root))
            if lease is None:
                return
            if normalized_connection_id and lease.connection_id == normalized_connection_id:
                return
            rejected = self._increment_duplicate_rejection_locked(_lease_key(session_id, workspace_root), lease)
            raise _lease_owned_conflict(rejected, now=now)

    def _renew_lease(self, lease: VSCodeConnectionLease, *, now: float | None = None) -> VSCodeConnectionLease:
        timestamp = float(now or time.time())
        renewed = VSCodeConnectionLease(
            session_id=lease.session_id,
            workspace_root=lease.workspace_root,
            project_key=lease.project_key,
            connection_id=lease.connection_id,
            acquired_at=lease.acquired_at,
            last_heartbeat_at=timestamp,
            expires_at=timestamp + CONNECTION_LEASE_TTL_SECONDS,
            source=lease.source,
            client_name=lease.client_name,
            duplicate_rejected_count=lease.duplicate_rejected_count,
        )
        with self._lock:
            self._leases_by_key[_lease_key(renewed.session_id, renewed.workspace_root)] = renewed
        return renewed

    def _lease_for_session_locked(self, session_id: str, workspace_root: str = "") -> VSCodeConnectionLease | None:
        if workspace_root:
            return self._leases_by_key.get(_lease_key(session_id, workspace_root))
        candidates = [lease for lease in self._leases_by_key.values() if lease.session_id == session_id]
        return max(candidates, key=lambda item: item.last_heartbeat_at, default=None)

    def _prune_expired_leases_locked(self, now: float) -> None:
        expired_connection_ids: set[str] = set()
        for key, lease in list(self._leases_by_key.items()):
            if lease.expires_at <= now:
                expired_connection_ids.add(lease.connection_id)
                self._leases_by_key.pop(key, None)
        for connection_id in expired_connection_ids:
            self._active_command_polls.discard(connection_id)

    def _increment_duplicate_rejection_locked(self, key: str, lease: VSCodeConnectionLease) -> VSCodeConnectionLease:
        updated = VSCodeConnectionLease(
            session_id=lease.session_id,
            workspace_root=lease.workspace_root,
            project_key=lease.project_key,
            connection_id=lease.connection_id,
            acquired_at=lease.acquired_at,
            last_heartbeat_at=lease.last_heartbeat_at,
            expires_at=lease.expires_at,
            source=lease.source,
            client_name=lease.client_name,
            duplicate_rejected_count=lease.duplicate_rejected_count + 1,
        )
        self._leases_by_key[key] = updated
        return updated

    def latest_snapshot(
        self,
        session_id: str,
        *,
        session_manager: Any | None = None,
        max_age_seconds: float | None = None,
    ) -> VSCodeContextSnapshot | None:
        target_session_id = str(session_id or "").strip()
        if not target_session_id:
            return None
        project_root = _session_project_root(session_manager, target_session_id) if session_manager is not None else ""
        now = time.time()
        with self._lock:
            self._prune_expired_leases_locked(now)
            snapshot = self._snapshots_by_session.get(target_session_id)
            lease = self._lease_for_session_locked(target_session_id, project_root)
        if snapshot is None:
            return None
        if lease is None:
            return None
        if snapshot.connection_id and snapshot.connection_id != lease.connection_id:
            return None
        if max_age_seconds is not None and max_age_seconds > 0:
            if now - snapshot.received_at > max_age_seconds:
                return None
        return snapshot

    def latest_editor_context(
        self,
        session_id: str,
        *,
        session_manager: Any | None = None,
        max_age_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> dict[str, Any]:
        snapshot = self.latest_snapshot(
            session_id,
            session_manager=session_manager,
            max_age_seconds=max_age_seconds,
        )
        return dict(snapshot.editor_context) if snapshot is not None else {}

    def status(
        self,
        session_id: str,
        *,
        session_manager: Any | None = None,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> VSCodeConnectionStatus:
        target_session_id = str(session_id or "").strip()
        now = time.time()
        project_root = _session_project_root(session_manager, target_session_id) if session_manager is not None else ""
        snapshot = self.latest_snapshot(target_session_id, session_manager=session_manager, max_age_seconds=None)
        with self._lock:
            self._prune_expired_leases_locked(now)
            lease = self._lease_for_session_locked(target_session_id, project_root)
            poller_count = 1 if lease and lease.connection_id in self._active_command_polls else 0
        if snapshot is None and lease is None:
            return VSCodeConnectionStatus(
                session_id=target_session_id,
                status="disconnected",
                connected=False,
                stale=True,
                stale_after_seconds=stale_after_seconds,
                workspace_root=project_root,
                project_key=project_workspace_key(project_root) if project_root else "",
            )
        editor_context = dict(snapshot.editor_context) if snapshot is not None else {}
        last_seen_at = max(float(snapshot.received_at if snapshot else 0.0), float(lease.last_heartbeat_at if lease else 0.0))
        age = now - last_seen_at if last_seen_at else 0.0
        stale = bool(lease is None or age > stale_after_seconds)
        active_file = dict(editor_context.get("active_file") or {})
        visible_files = [dict(item) for item in list(editor_context.get("visible_files") or [])]
        open_tabs = [dict(item) for item in list(editor_context.get("open_tabs") or [])]
        limits = dict(editor_context.get("limits") or {})
        workspace_root = project_root or (snapshot.workspace_root if snapshot else "") or (lease.workspace_root if lease else "")
        connection_id = lease.connection_id if lease is not None else (snapshot.connection_id if snapshot is not None else "")
        return VSCodeConnectionStatus(
            session_id=target_session_id,
            status="stale" if stale else "connected",
            connected=not stale,
            stale=stale,
            last_seen_at=last_seen_at,
            age_seconds=max(0.0, age),
            stale_after_seconds=stale_after_seconds,
            workspace_root=workspace_root,
            project_key=project_workspace_key(workspace_root) if workspace_root else "",
            active_file=active_file,
            visible_files=visible_files,
            open_tabs=open_tabs,
            limits=limits,
            connection_id=connection_id,
            lease_active=lease is not None,
            lease_expires_at=float(lease.expires_at if lease else 0.0),
            lease_last_heartbeat_at=float(lease.last_heartbeat_at if lease else 0.0),
            duplicate_rejected_count=int(lease.duplicate_rejected_count if lease else 0),
            poller_count=poller_count,
        )

    def enqueue_command(self, *, session_id: str, command: dict[str, Any]) -> dict[str, Any]:
        target_session_id = str(session_id or "").strip()
        if not target_session_id:
            raise ValueError("session_id is required")
        payload = dict(command or {})
        command_id = str(payload.get("command_id") or "").strip() or f"vscode-command-{uuid.uuid4().hex}"
        queued = {
            **payload,
            "command_id": command_id,
            "queued_at": time.time(),
            "authority": "integrations.vscode_connection.command",
        }
        with self._lock:
            queue = self._commands_by_session.setdefault(target_session_id, [])
            queue.append(queued)
            if len(queue) > COMMAND_QUEUE_LIMIT:
                del queue[: len(queue) - COMMAND_QUEUE_LIMIT]
        return dict(queued)

    def pop_next_command(self, session_id: str) -> dict[str, Any]:
        target_session_id = str(session_id or "").strip()
        if not target_session_id:
            return {}
        with self._lock:
            queue = self._commands_by_session.get(target_session_id) or []
            if not queue:
                return {}
            command = queue.pop(0)
            if not queue:
                self._commands_by_session.pop(target_session_id, None)
        return dict(command)

    def record_command_result(
        self,
        *,
        session_id: str,
        command_id: str,
        connection_id: str,
        result: dict[str, Any],
        session_manager: Any | None = None,
    ) -> dict[str, Any]:
        target_session_id = str(session_id or "").strip()
        target_command_id = str(command_id or "").strip()
        if not target_session_id:
            raise ValueError("session_id is required")
        if not target_command_id:
            raise ValueError("command_id is required")
        lease = self.require_connection_owner(
            session_id=target_session_id,
            connection_id=connection_id,
            session_manager=session_manager,
        )
        payload = {
            "session_id": target_session_id,
            "command_id": target_command_id,
            "connection_id": lease.connection_id,
            "status": str(dict(result or {}).get("status") or "").strip() or "unknown",
            "message": str(dict(result or {}).get("message") or "").strip()[:2000],
            "dirty": bool(dict(result or {}).get("dirty")),
            "document_sha256": str(dict(result or {}).get("document_sha256") or "").strip(),
            "applied_at": str(dict(result or {}).get("applied_at") or "").strip(),
            "metadata": dict(dict(result or {}).get("metadata") or {}),
            "received_at": time.time(),
            "authority": "integrations.vscode_connection.command_result",
        }
        with self._lock:
            results = self._command_results_by_session.setdefault(target_session_id, {})
            results[target_command_id] = payload
            if len(results) > COMMAND_QUEUE_LIMIT:
                oldest = sorted(results.items(), key=lambda item: float(item[1].get("received_at") or 0))
                for key, _ in oldest[: len(results) - COMMAND_QUEUE_LIMIT]:
                    results.pop(key, None)
        return dict(payload)

    def command_result(self, *, session_id: str, command_id: str) -> dict[str, Any]:
        target_session_id = str(session_id or "").strip()
        target_command_id = str(command_id or "").strip()
        if not target_session_id or not target_command_id:
            return {}
        with self._lock:
            return dict((self._command_results_by_session.get(target_session_id) or {}).get(target_command_id) or {})


def _bind_or_validate_workspace_roots(*, session_manager: Any, session_id: str, workspace_roots: list[str]) -> str:
    roots = [
        normalize_workspace_root(item)
        for item in workspace_roots[:WORKSPACE_ROOTS_LIMIT]
        if str(item or "").strip()
    ]
    roots = list(dict.fromkeys(item for item in roots if item))
    if not roots:
        return ""
    binding = session_manager.get_project_binding(session_id)
    if binding:
        bound_root = normalize_workspace_root(binding.get("workspace_root"))
        for root in roots:
            try:
                session_manager.bind_project(session_id, workspace_root=root, source="vscode")
                return bound_root or root
            except SessionProjectBindingConflict:
                continue
            except ValueError as exc:
                raise VSCodeConnectionConflict(str(exc)) from exc
        raise VSCodeConnectionConflict(f"VS Code workspace root does not match bound session project: {bound_root}")
    if len(roots) != 1:
        raise VSCodeConnectionConflict("multiple VS Code workspace roots require explicit project binding")
    try:
        binding = session_manager.bind_project(session_id, workspace_root=roots[0], source="vscode")
    except SessionProjectBindingConflict as exc:
        raise VSCodeConnectionConflict(str(exc)) from exc
    return normalize_workspace_root(binding.get("workspace_root"))


def _normalize_connection_id(value: object) -> str:
    text = str(value or "").strip()
    return "".join(char if char.isalnum() or char in {"-", "_", ":", "."} else "-" for char in text)[:240]


def _lease_key(session_id: str, workspace_root: str) -> str:
    return f"{str(session_id or '').strip()}::{project_workspace_key(workspace_root)}"


def _lease_owned_conflict(lease: VSCodeConnectionLease, *, now: float) -> VSCodeConnectionLeaseConflict:
    retry_after_ms = max(
        LEASE_CONFLICT_RETRY_AFTER_MS,
        int(max(1.0, lease.expires_at - now) * 1000),
    )
    return VSCodeConnectionLeaseConflict(
        "VS Code connection lease is owned by another connection",
        code="lease_owned",
        retry_after_ms=retry_after_ms,
        status_code=429,
        owner=lease.to_dict(),
    )


def _session_project_root(session_manager: Any | None, session_id: str) -> str:
    if session_manager is None:
        return ""
    try:
        binding = session_manager.get_project_binding(session_id)
    except Exception:
        return ""
    return normalize_workspace_root(dict(binding or {}).get("workspace_root"))


def _normalize_editor_context(value: dict[str, Any]) -> dict[str, Any]:
    raw = dict(value or {})
    active_file = _normalize_active_file(raw.get("active_file"))
    visible_files = [
        item
        for item in (_normalize_visible_file(entry) for entry in list(raw.get("visible_files") or [])[:VISIBLE_FILES_LIMIT])
        if item
    ]
    open_tabs = _dedupe_editor_files(
        [
            item
            for item in (_normalize_open_tab(entry) for entry in list(raw.get("open_tabs") or [])[:OPEN_TABS_LIMIT])
            if item
        ],
        limit=OPEN_TABS_LIMIT,
    )
    diagnostics = [
        item
        for item in (_normalize_diagnostic(entry) for entry in list(raw.get("diagnostics") or [])[:DIAGNOSTICS_LIMIT])
        if item
    ]
    workspace_roots = [
        root
        for root in (
            normalize_workspace_root(entry)
            for entry in list(raw.get("workspace_roots") or [])[:WORKSPACE_ROOTS_LIMIT]
        )
        if root
    ]
    limits = dict(raw.get("limits") or {})
    limits.update(
        {
            "visible_files_count": len(visible_files),
            "open_tabs_count": len(open_tabs),
            "diagnostics_count": len(diagnostics),
        }
    )
    result: dict[str, Any] = {
        "source": "vscode",
        "captured_at": str(raw.get("captured_at") or ""),
        "workspace_roots": list(dict.fromkeys(workspace_roots)),
        "visible_files": visible_files,
        "open_tabs": open_tabs,
        "diagnostics": diagnostics,
        "limits": limits,
        "authority": "integrations.vscode_connection.editor_context",
    }
    if active_file:
        result["active_file"] = active_file
    return result


def _normalize_active_file(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    path = str(value.get("path") or "").strip()
    if not path:
        return {}
    result: dict[str, Any] = {
        "path": path,
        "label": str(value.get("label") or _file_label(path)).strip()[:240],
        "language_id": str(value.get("language_id") or "").strip(),
        "dirty": bool(value.get("dirty")),
    }
    selection = _normalize_selection(value.get("selection"))
    if selection:
        result["selection"] = selection
    preview = _normalize_content_preview(value.get("content_preview"))
    if preview:
        result["content_preview"] = preview
    visible_ranges = list(value.get("visible_ranges") or [])[:8]
    if visible_ranges:
        result["visible_ranges"] = visible_ranges
    return result


def _normalize_selection(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        "start": dict(value.get("start") or {}),
        "end": dict(value.get("end") or {}),
        "truncated": bool(value.get("truncated")),
    }
    text = str(value.get("text") or "")
    if text:
        result["text"] = text[:SELECTION_TEXT_LIMIT]
        result["truncated"] = bool(value.get("truncated")) or len(text) > SELECTION_TEXT_LIMIT
    return result


def _normalize_content_preview(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    text = str(value.get("text") or "")
    if not text:
        return {}
    return {
        "text": text[:ACTIVE_FILE_PREVIEW_LIMIT],
        "truncated": bool(value.get("truncated")) or len(text) > ACTIVE_FILE_PREVIEW_LIMIT,
        "source": str(value.get("source") or "saved_document").strip() or "saved_document",
    }


def _normalize_visible_file(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    path = str(value.get("path") or "").strip()
    if not path:
        return {}
    return {
        "path": path,
        "label": str(value.get("label") or _file_label(path)).strip()[:240],
        "language_id": str(value.get("language_id") or "").strip(),
        "dirty": bool(value.get("dirty")),
    }


def _normalize_open_tab(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    path = str(value.get("path") or value.get("uri") or "").strip()
    if not path:
        return {}
    return {
        "path": path,
        "label": str(value.get("label") or _file_label(path)).strip()[:240],
        "language_id": str(value.get("language_id") or value.get("languageId") or "").strip(),
        "dirty": bool(value.get("dirty")),
        "active": bool(value.get("active")),
        "visible": bool(value.get("visible")),
    }


def _dedupe_editor_files(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        path = str(item.get("path") or "").strip()
        key = path.replace("\\", "/").rstrip("/").lower()
        if not path or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _file_label(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").rstrip("/")
    return normalized.split("/")[-1] if normalized else ""


def _normalize_diagnostic(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    path = str(value.get("path") or "").strip()
    message = str(value.get("message") or "").strip()
    if not path or not message:
        return {}
    return {
        "path": path,
        "severity": str(value.get("severity") or "information").strip() or "information",
        "message": message[:2000],
        "range": dict(value.get("range") or {}),
    }


_STORE = VSCodeConnectionStore()


def get_vscode_connection_store() -> VSCodeConnectionStore:
    return _STORE

