from __future__ import annotations

import threading
import time
from typing import Any

from project_workspaces import project_workspace_key
from sessions import SessionProjectBindingConflict

from .models import VSCodeConnectionConflict, VSCodeConnectionStatus, VSCodeContextSnapshot
from .path_normalization import normalize_workspace_root

DEFAULT_STALE_AFTER_SECONDS = 60.0
LAUNCH_INTENT_TTL_SECONDS = 300.0
ACTIVE_FILE_PREVIEW_LIMIT = 24_000
SELECTION_TEXT_LIMIT = 8_000
VISIBLE_FILES_LIMIT = 20
DIAGNOSTICS_LIMIT = 80
WORKSPACE_ROOTS_LIMIT = 8


class VSCodeConnectionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots_by_session: dict[str, VSCodeContextSnapshot] = {}
        self._snapshots_by_project_key: dict[str, VSCodeContextSnapshot] = {}
        self._launch_intents: dict[str, dict[str, Any]] = {}

    def clear(self) -> None:
        with self._lock:
            self._snapshots_by_session.clear()
            self._snapshots_by_project_key.clear()
            self._launch_intents.clear()

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

    def resolve_launch_intent(self, *, workspace_roots: list[str], session_manager: Any | None = None) -> dict[str, Any]:
        roots = [
            normalize_workspace_root(item)
            for item in list(workspace_roots or [])[:WORKSPACE_ROOTS_LIMIT]
            if str(item or "").strip()
        ]
        if not roots:
            return {"session_id": "", "reason": "no_workspace_roots"}
        now = time.time()
        with self._lock:
            for key, intent in list(self._launch_intents.items()):
                if float(intent.get("expires_at") or 0) <= now:
                    self._launch_intents.pop(key, None)
                    continue
                intent_root = normalize_workspace_root(intent.get("workspace_root"))
                if any(intent_root == root for root in roots):
                    return {
                        "session_id": str(intent.get("session_id") or ""),
                        "workspace_root": intent_root,
                        "matched": True,
                        "authority": "integrations.vscode_connection.launch_intent",
                    }
        project_session = _latest_project_session(session_manager, roots)
        if project_session:
            return {
                "session_id": project_session["session_id"],
                "workspace_root": project_session["workspace_root"],
                "matched": True,
                "match_source": "project_session_binding",
                "authority": "integrations.vscode_connection.project_session_binding",
            }
        return {"session_id": "", "reason": "no_matching_launch_intent"}

    def record_context(self, *, session_manager: Any, session_id: str, editor_context: dict[str, Any]) -> VSCodeContextSnapshot:
        target_session_id = str(session_id or "").strip()
        if not target_session_id:
            raise ValueError("session_id is required")
        payload = _normalize_editor_context(editor_context)
        workspace_root = _bind_or_validate_workspace_roots(
            session_manager=session_manager,
            session_id=target_session_id,
            workspace_roots=list(payload.get("workspace_roots") or []),
        )
        now = time.time()
        snapshot = VSCodeContextSnapshot(
            session_id=target_session_id,
            editor_context=payload,
            received_at=now,
            workspace_root=workspace_root,
            connection_id=f"vscode:{target_session_id}",
        )
        with self._lock:
            self._snapshots_by_session[target_session_id] = snapshot
            if workspace_root:
                self._snapshots_by_project_key[project_workspace_key(workspace_root)] = snapshot
        return snapshot

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
        with self._lock:
            candidates = [self._snapshots_by_session.get(target_session_id)]
            if project_root:
                candidates.append(self._snapshots_by_project_key.get(project_workspace_key(project_root)))
            snapshot = max(
                [item for item in candidates if item is not None],
                key=lambda item: item.received_at,
                default=None,
            )
        if snapshot is None:
            return None
        if max_age_seconds is not None and max_age_seconds > 0:
            if time.time() - snapshot.received_at > max_age_seconds:
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
        snapshot = self.latest_snapshot(target_session_id, session_manager=session_manager, max_age_seconds=None)
        if snapshot is None:
            project_root = _session_project_root(session_manager, target_session_id) if session_manager is not None else ""
            return VSCodeConnectionStatus(
                session_id=target_session_id,
                status="disconnected",
                connected=False,
                stale=True,
                workspace_root=project_root,
                project_key=project_workspace_key(project_root) if project_root else "",
            )
        age = time.time() - snapshot.received_at
        stale = age > stale_after_seconds
        active_file = dict(dict(snapshot.editor_context).get("active_file") or {})
        project_root = _session_project_root(session_manager, target_session_id) if session_manager is not None else ""
        workspace_root = project_root or snapshot.workspace_root
        return VSCodeConnectionStatus(
            session_id=target_session_id,
            status="stale" if stale else "connected",
            connected=True,
            stale=stale,
            last_seen_at=snapshot.received_at,
            workspace_root=workspace_root,
            project_key=project_workspace_key(workspace_root) if workspace_root else "",
            active_file=active_file,
            connection_session_id=snapshot.session_id,
            connection_id=snapshot.connection_id,
            reused_project_connection=bool(snapshot.session_id and snapshot.session_id != target_session_id),
        )

    def project_status(self, workspace_root: str, *, stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS) -> VSCodeConnectionStatus:
        project_root = normalize_workspace_root(workspace_root)
        project_key = project_workspace_key(project_root) if project_root else ""
        with self._lock:
            snapshot = self._snapshots_by_project_key.get(project_key) if project_key else None
        if snapshot is None:
            return VSCodeConnectionStatus(
                session_id="",
                status="disconnected",
                connected=False,
                stale=True,
                workspace_root=project_root,
                project_key=project_key,
            )
        age = time.time() - snapshot.received_at
        stale = age > stale_after_seconds
        active_file = dict(dict(snapshot.editor_context).get("active_file") or {})
        return VSCodeConnectionStatus(
            session_id="",
            status="stale" if stale else "connected",
            connected=True,
            stale=stale,
            last_seen_at=snapshot.received_at,
            workspace_root=project_root,
            project_key=project_key,
            active_file=active_file,
            connection_session_id=snapshot.session_id,
            connection_id=snapshot.connection_id,
            reused_project_connection=True,
        )


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


def _session_project_root(session_manager: Any | None, session_id: str) -> str:
    if session_manager is None:
        return ""
    try:
        binding = session_manager.get_project_binding(session_id)
    except Exception:
        return ""
    return normalize_workspace_root(dict(binding or {}).get("workspace_root"))


def _latest_project_session(session_manager: Any | None, workspace_roots: list[str]) -> dict[str, str]:
    if session_manager is None:
        return {}
    roots = [item for item in (normalize_workspace_root(root) for root in workspace_roots) if item]
    if not roots:
        return {}
    try:
        sessions = list(session_manager.list_sessions() or [])
    except Exception:
        return {}
    for session in sorted(sessions, key=lambda item: float(dict(item).get("updated_at") or 0), reverse=True):
        session_id = str(dict(session).get("id") or "").strip()
        state = dict(dict(session).get("conversation_state") or {})
        binding = dict(state.get("project_binding") or {})
        session_root = normalize_workspace_root(binding.get("workspace_root"))
        if session_id and any(session_root == root for root in roots):
            return {"session_id": session_id, "workspace_root": session_root}
    return {}


def _normalize_editor_context(value: dict[str, Any]) -> dict[str, Any]:
    raw = dict(value or {})
    active_file = _normalize_active_file(raw.get("active_file"))
    visible_files = [
        item
        for item in (_normalize_visible_file(entry) for entry in list(raw.get("visible_files") or [])[:VISIBLE_FILES_LIMIT])
        if item
    ]
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
    result: dict[str, Any] = {
        "source": "vscode",
        "captured_at": str(raw.get("captured_at") or ""),
        "workspace_roots": list(dict.fromkeys(workspace_roots)),
        "visible_files": visible_files,
        "diagnostics": diagnostics,
        "limits": dict(raw.get("limits") or {}),
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
        "language_id": str(value.get("language_id") or "").strip(),
        "dirty": bool(value.get("dirty")),
    }


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
