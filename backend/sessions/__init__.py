from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from permissions.policy import normalize_permission_mode
from project_layout import ProjectLayout

logger = logging.getLogger(__name__)


class InvalidSessionId(ValueError):
    pass


class SessionStorageError(RuntimeError):
    pass


class SessionPayloadCorrupt(SessionStorageError):
    pass


class SessionTaskBindingConflict(ValueError):
    pass


class SessionTaskBindingMissing(ValueError):
    pass


class SessionProjectBindingConflict(ValueError):
    pass


class SessionProjectBindingMissing(ValueError):
    pass


DEFAULT_SESSION_PERMISSION_MODE = "full_access"


class SessionManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.sessions_dir = ProjectLayout.from_backend_dir(self.base_dir).sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._session_locks: dict[str, threading.RLock] = {}

    def list_sessions(
        self,
        *,
        workspace_view: str | None = None,
        task_environment_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sessions = [
            self._summary_from_payload(item)
            for item in self._load_all()
            if _scope_matches(
                item,
                workspace_view=workspace_view,
                task_environment_id=task_environment_id,
                project_id=project_id,
            )
        ]
        return sorted(sessions, key=lambda item: float(item.get("updated_at") or 0), reverse=True)

    def get_session_summary(self, session_id: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        return self._summary_from_payload(payload)

    def create_session(
        self,
        *,
        title: str = "New Session",
        scope: dict[str, Any] | None = None,
        project_binding: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        now = time.time()
        session_id = str(session_id or "").strip() or f"session-{uuid.uuid4().hex[:16]}"
        path = self._session_path(session_id)
        if path.exists():
            return self.get_session_summary(session_id)
        initial_state: dict[str, Any] = {}
        binding = _normalize_project_binding(project_binding, validate_root=True, timestamp=now)
        if binding:
            initial_state["project_binding"] = binding
        payload = {
            "id": session_id,
            "title": str(title or "New Session").strip() or "New Session",
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "api_transcript": [],
            "compressed_context": "",
            "provider_protocol_compaction_created_at": 0.0,
            "scope": _normalize_scope(scope),
            "task_binding": {},
            "conversation_state": _normalize_conversation_state(initial_state),
        }
        self._write_payload(session_id, payload)
        return self._summary_from_payload(payload)

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            payload["title"] = str(title or "").strip() or payload.get("title") or "New Session"
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return self._summary_from_payload(payload)

    def set_title(self, session_id: str, title: str) -> dict[str, Any]:
        return self.rename_session(session_id, title)

    def delete_session(self, session_id: str) -> bool:
        with self._session_lock(session_id):
            path = self._session_path(session_id)
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                raise SessionStorageError(f"failed to delete session payload: {session_id}") from exc
            return True

    def load_session(self, session_id: str) -> list[dict[str, Any]]:
        return _public_messages(list(self._read_payload(session_id).get("messages") or []))

    def load_session_record(self, session_id: str) -> dict[str, Any]:
        return self.get_history(session_id)

    def load_session_for_agent(self, session_id: str) -> list[dict[str, Any]]:
        payload = self.get_history(session_id)
        messages = [
            _agent_message(item)
            for item in list(payload.get("messages") or [])
            if isinstance(item, dict)
        ]
        return [item for item in messages if item is not None]

    def load_session_for_api(self, session_id: str) -> list[dict[str, Any]]:
        payload = self._read_payload(session_id)
        transcript = [
            _api_message(item)
            for item in list(payload.get("api_transcript") or [])
            if isinstance(item, dict)
        ]
        transcript = _suppress_superseded_stream_failure_boundaries([item for item in transcript if item is not None])
        if transcript:
            return transcript
        return self.load_session_for_agent(session_id)

    def get_history(self, session_id: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        return {
            "id": str(payload.get("id") or session_id),
            "title": str(payload.get("title") or "New Session"),
            "created_at": float(payload.get("created_at") or 0),
            "updated_at": float(payload.get("updated_at") or 0),
            "compressed_context": str(payload.get("compressed_context") or ""),
            "provider_protocol_compaction_created_at": _float(payload.get("provider_protocol_compaction_created_at")),
            "scope": _normalize_scope(dict(payload.get("scope") or {})),
            "task_binding": _normalize_task_binding(dict(payload.get("task_binding") or {})),
            "conversation_state": _normalize_conversation_state(dict(payload.get("conversation_state") or {})),
            "messages": _public_messages(list(payload.get("messages") or [])),
        }

    def get_task_binding(self, session_id: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        return _normalize_task_binding(dict(payload.get("task_binding") or {}))

    def get_conversation_state(self, session_id: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        return _normalize_conversation_state(dict(payload.get("conversation_state") or {}))

    def get_project_binding(self, session_id: str) -> dict[str, Any]:
        state = self.get_conversation_state(session_id)
        return _normalize_project_binding(dict(state.get("project_binding") or {}), validate_root=False)

    def require_project_binding(self, session_id: str) -> dict[str, Any]:
        binding = self.get_project_binding(session_id)
        if not binding:
            raise SessionProjectBindingMissing("session has no project binding")
        return binding

    def bind_project(
        self,
        session_id: str,
        *,
        workspace_root: str,
        source: str = "manual",
    ) -> dict[str, Any]:
        now = time.time()
        next_binding = _normalize_project_binding(
            {
                "workspace_root": workspace_root,
                "source": source,
                "bound_at": now,
                "last_seen_at": now,
            },
            validate_root=True,
            timestamp=now,
        )
        if not next_binding:
            raise ValueError("workspace_root is required")
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            state = _normalize_conversation_state(dict(payload.get("conversation_state") or {}))
            current = _normalize_project_binding(dict(state.get("project_binding") or {}), validate_root=False)
            if current:
                if not _same_workspace_root(current["workspace_root"], next_binding["workspace_root"]):
                    raise SessionProjectBindingConflict("session already has a different project binding")
                refreshed = {
                    **current,
                    "last_seen_at": now,
                    "source": current.get("source") or next_binding.get("source") or "manual",
                    "immutable": True,
                    "authority": "sessions.project_binding",
                }
                state["project_binding"] = _normalize_project_binding(refreshed, validate_root=False)
                payload["conversation_state"] = state
                payload["updated_at"] = now
                self._write_payload(session_id, payload)
                return state["project_binding"]
            state["project_binding"] = next_binding
            payload["conversation_state"] = state
            payload["updated_at"] = now
            self._write_payload(session_id, payload)
            return next_binding

    def clear_project_binding(
        self,
        session_id: str,
        *,
        workspace_root: str | None = None,
    ) -> dict[str, Any]:
        expected_root = str(workspace_root or "").strip()
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            state = _normalize_conversation_state(dict(payload.get("conversation_state") or {}))
            current = _normalize_project_binding(dict(state.get("project_binding") or {}), validate_root=False)
            if not current:
                return self._summary_from_payload(payload)
            if expected_root and not _same_workspace_root(current["workspace_root"], expected_root):
                raise SessionProjectBindingConflict("session has a different project binding")
            state["project_binding"] = {}
            payload["conversation_state"] = state
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return self._summary_from_payload(payload)

    def set_active_task_environment(self, session_id: str, active_environment: dict[str, Any]) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            state = _normalize_conversation_state(dict(payload.get("conversation_state") or {}))
            state["active_task_environment"] = _normalize_active_task_environment(active_environment)
            payload["conversation_state"] = state
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return state

    def set_permission_mode(self, session_id: str, permission_mode: str) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            state = _normalize_conversation_state(dict(payload.get("conversation_state") or {}))
            state["permission_mode"] = _normalize_session_permission_mode(permission_mode)
            payload["conversation_state"] = state
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return state

    def update_turn_environment_snapshot(
        self,
        session_id: str,
        *,
        turn_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        target_turn_id = str(turn_id or "").strip()
        if not target_turn_id:
            raise ValueError("turn_id is required")
        clean_snapshot = _normalize_turn_environment_snapshot(snapshot)
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            messages = []
            updated = False
            for item in list(payload.get("messages") or []):
                if not isinstance(item, dict):
                    messages.append(item)
                    continue
                if str(item.get("turn_id") or "").strip() == target_turn_id:
                    item = {**item, "turn_environment_snapshot": clean_snapshot}
                    updated = True
                messages.append(item)
            payload["messages"] = messages
            if updated:
                payload["updated_at"] = time.time()
                self._write_payload(session_id, payload)
            return {"updated": updated, "turn_environment_snapshot": clean_snapshot}

    def bind_session_graph_instance(
        self,
        session_id: str,
        *,
        graph_run_id: str,
        task_run_id: str = "",
        graph_id: str = "",
        graph_harness_config_id: str = "",
        session_scope: dict[str, Any] | None = None,
        task_environment_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any]:
        target_graph_run_id = str(graph_run_id or "").strip()
        if not target_graph_run_id:
            raise ValueError("graph_run_id is required")
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            current = _normalize_task_binding(dict(payload.get("task_binding") or {}))
            if current:
                current_graph_run_id = str(current.get("graph_run_id") or "").strip()
                if current_graph_run_id != target_graph_run_id:
                    raise SessionTaskBindingConflict("session already has a different graph task binding")
                return current
            now = time.time()
            scope = _normalize_scope(session_scope)
            binding = _normalize_task_binding(
                {
                    "kind": "task_graph",
                    "graph_run_id": target_graph_run_id,
                    "task_run_id": task_run_id,
                    "graph_id": graph_id,
                    "graph_harness_config_id": graph_harness_config_id,
                    "task_environment_id": task_environment_id or scope["task_environment_id"],
                    "project_id": project_id or scope["project_id"],
                    "session_scope": scope,
                    "bound_at": now,
                    "updated_at": now,
                    "authority": "sessions.session_task_binding",
                }
            )
            payload["task_binding"] = binding
            payload["updated_at"] = now
            self._write_payload(session_id, payload)
            return binding

    def assert_session_graph_instance(self, session_id: str, graph_run_id: str) -> dict[str, Any]:
        target_graph_run_id = str(graph_run_id or "").strip()
        if not target_graph_run_id:
            raise ValueError("graph_run_id is required")
        binding = self.get_task_binding(session_id)
        if not binding:
            raise SessionTaskBindingMissing("session has no graph task binding")
        if str(binding.get("graph_run_id") or "").strip() != target_graph_run_id:
            raise SessionTaskBindingConflict("session graph task binding mismatch")
        return binding

    def append_messages(self, session_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            existing = list(payload.get("messages") or [])
            now = time.time()
            for item in messages:
                if not isinstance(item, dict):
                    continue
                message = _public_message(item)
                if message is None:
                    continue
                if not message.get("created_at"):
                    message["created_at"] = now
                existing.append(message)
            payload["messages"] = existing
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return existing

    def remove_stream_failure_boundary_messages(self, session_id: str, *, turn_id: str) -> dict[str, Any]:
        target_turn_id = str(turn_id or "").strip()
        if not target_turn_id:
            return {
                "removed_messages": 0,
                "removed_api_messages": 0,
                "authority": "sessions.stream_failure_boundary_cleanup",
            }
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            messages = list(payload.get("messages") or [])
            api_transcript = list(payload.get("api_transcript") or [])
            kept_messages, removed_messages = _remove_stream_failure_boundary_messages_for_turn(
                messages,
                turn_id=target_turn_id,
            )
            kept_api_transcript, removed_api_messages = _remove_stream_failure_boundary_messages_for_turn(
                api_transcript,
                turn_id=target_turn_id,
            )
            if removed_messages or removed_api_messages:
                payload["messages"] = kept_messages
                payload["api_transcript"] = kept_api_transcript
                payload["updated_at"] = time.time()
                self._write_payload(session_id, payload)
            return {
                "removed_messages": removed_messages,
                "removed_api_messages": removed_api_messages,
                "authority": "sessions.stream_failure_boundary_cleanup",
            }

    def append_api_messages(self, session_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            existing = list(payload.get("api_transcript") or [])
            now = time.time()
            if str(payload.get("compressed_context") or "").strip() and _float(payload.get("provider_protocol_compaction_created_at")) <= 0:
                payload["provider_protocol_compaction_created_at"] = now
            for item in messages:
                if not isinstance(item, dict):
                    continue
                message = _api_message(item)
                if message is not None:
                    if not message.get("created_at"):
                        message["created_at"] = now
                    existing.append(message)
            payload["api_transcript"] = existing
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return existing

    def replace_runtime_context(
        self,
        session_id: str,
        *,
        messages: list[dict[str, Any]],
        compressed_context: str | None = None,
    ) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            if not list(payload.get("api_transcript") or []):
                payload["api_transcript"] = [
                    item
                    for item in (_api_message(message) for message in list(payload.get("messages") or []) if isinstance(message, dict))
                    if item is not None
                ]
            normalized_messages: list[dict[str, Any]] = []
            for item in list(messages or []):
                if not isinstance(item, dict):
                    continue
                message = _public_message(item)
                if message is None:
                    continue
                normalized_messages.append(message)
            payload["messages"] = normalized_messages
            if compressed_context is not None:
                payload["compressed_context"] = str(compressed_context or "")
                payload["provider_protocol_compaction_created_at"] = time.time() if str(compressed_context or "").strip() else 0.0
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return self.get_history(session_id)

    def truncate_messages_from(self, session_id: str, message_index: int) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            messages = list(payload.get("messages") or [])
            public_entries = _public_messages_with_raw_index(messages)
            if message_index < 0 or message_index > len(public_entries):
                raise ValueError("message_index out of range")
            if message_index == len(public_entries):
                raw_cutoff = len(messages)
            else:
                raw_cutoff = public_entries[message_index][0]
            kept_raw_messages = messages[:raw_cutoff]
            kept_public_messages = _public_messages(kept_raw_messages)
            payload["messages"] = kept_public_messages
            payload["api_transcript"] = _truncated_api_transcript(
                list(payload.get("api_transcript") or []),
                kept_messages=kept_public_messages,
            )
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return self.get_history(session_id)

    def _load_all(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                payload = self._read_payload_from_path(path, session_id=path.stem)
            except SessionStorageError as exc:
                logger.warning("Skipping unreadable session payload %s: %s", path, exc)
                rows.append(_unreadable_session_payload(path, error=str(exc)))
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _summary_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = _public_messages(list(payload.get("messages") or []))
        summary = {
            "id": str(payload.get("id") or ""),
            "title": str(payload.get("title") or "New Session"),
            "created_at": float(payload.get("created_at") or 0),
            "updated_at": float(payload.get("updated_at") or 0),
            "message_count": len(messages),
            "scope": _normalize_scope(dict(payload.get("scope") or {})),
            "task_binding": _normalize_task_binding(dict(payload.get("task_binding") or {})),
            "conversation_state": _normalize_conversation_state(dict(payload.get("conversation_state") or {})),
        }
        storage_status = str(payload.get("storage_status") or "").strip()
        if storage_status:
            summary["storage_status"] = storage_status
            summary["storage_error"] = str(payload.get("storage_error") or "")
        return summary

    def _read_payload(self, session_id: str) -> dict[str, Any]:
        path = self._session_path(session_id)
        if not path.exists():
            raise ValueError("Unknown session_id")
        return self._read_payload_from_path(path, session_id=session_id)

    def _read_payload_from_path(self, path: Path, *, session_id: str) -> dict[str, Any]:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SessionPayloadCorrupt(f"corrupt session payload: {session_id}") from exc
        except OSError as exc:
            raise SessionStorageError(f"failed to read session payload: {session_id}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SessionPayloadCorrupt(f"corrupt session payload: {session_id}") from exc
        if not isinstance(payload, dict):
            raise SessionPayloadCorrupt(f"invalid session payload: {session_id}")
        return payload

    def _write_payload(self, session_id: str, payload: dict[str, Any]) -> None:
        path = self._session_path(session_id)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                handle.write(content)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            _replace_file_atomically(tmp_path, path)
        except OSError as exc:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise SessionStorageError(f"failed to write session payload: {session_id}") from exc

    def _session_path(self, session_id: str) -> Path:
        safe = _safe_session_id(session_id)
        path = (self.sessions_dir / f"{safe}.json").resolve()
        root = self.sessions_dir.resolve()
        if root != path.parent:
            raise ValueError("Invalid session_id")
        return path

    @contextmanager
    def _session_lock(self, session_id: str) -> Iterator[None]:
        safe = _safe_session_id(session_id)
        with self._locks_guard:
            lock = self._session_locks.get(safe)
            if lock is None:
                lock = threading.RLock()
                self._session_locks[safe] = lock
        with lock:
            yield


def _replace_file_atomically(source: Path, target: Path) -> None:
    retry_delays = (0.01, 0.025, 0.05, 0.1)
    for attempt in range(len(retry_delays) + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt >= len(retry_delays):
                raise
            time.sleep(retry_delays[attempt])


def _unreadable_session_payload(path: Path, *, error: str) -> dict[str, Any]:
    try:
        updated_at = path.stat().st_mtime
    except OSError:
        updated_at = 0.0
    return {
        "id": path.stem,
        "title": "Unreadable session",
        "created_at": updated_at,
        "updated_at": updated_at,
        "messages": [],
        "scope": _normalize_scope({}),
        "task_binding": {},
        "conversation_state": _normalize_conversation_state({}),
        "storage_status": "unreadable",
        "storage_error": error,
    }


def _safe_session_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value or "").strip())
    if not safe or safe in {".", ".."}:
        raise InvalidSessionId("Invalid session_id")
    return safe


def _normalize_scope(scope: dict[str, Any] | None) -> dict[str, str]:
    raw = dict(scope or {})
    workspace_view = str(raw.get("workspace_view") or raw.get("view") or "chat").strip() or "chat"
    task_environment_id = str(raw.get("task_environment_id") or raw.get("environment_id") or "").strip()
    project_id = str(raw.get("project_id") or "").strip()
    return {
        "workspace_view": workspace_view,
        "task_environment_id": task_environment_id,
        "project_id": project_id,
    }


def _normalize_task_binding(binding: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(binding or {})
    graph_run_id = str(raw.get("graph_run_id") or "").strip()
    if not graph_run_id:
        return {}
    session_scope = _normalize_scope(dict(raw.get("session_scope") or raw.get("scope") or {}))
    task_environment_id = str(raw.get("task_environment_id") or session_scope["task_environment_id"] or "").strip()
    project_id = str(raw.get("project_id") or session_scope["project_id"] or "").strip()
    session_scope["task_environment_id"] = task_environment_id
    session_scope["project_id"] = project_id
    return {
        "kind": str(raw.get("kind") or "task_graph").strip() or "task_graph",
        "graph_run_id": graph_run_id,
        "task_run_id": str(raw.get("task_run_id") or "").strip(),
        "graph_id": str(raw.get("graph_id") or "").strip(),
        "graph_harness_config_id": str(raw.get("graph_harness_config_id") or raw.get("config_id") or "").strip(),
        "task_environment_id": task_environment_id,
        "project_id": project_id,
        "session_scope": session_scope,
        "bound_at": float(raw.get("bound_at") or raw.get("created_at") or 0.0),
        "updated_at": float(raw.get("updated_at") or raw.get("bound_at") or 0.0),
        "authority": str(raw.get("authority") or "sessions.session_task_binding"),
    }


def _normalize_active_task_environment(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    environment_id = str(raw.get("task_environment_id") or raw.get("environment_id") or "").strip()
    if not environment_id:
        return {}
    return {
        "task_environment_id": environment_id,
        "environment_label": str(raw.get("environment_label") or raw.get("label") or environment_id).strip() or environment_id,
        "source": str(raw.get("source") or "conversation").strip() or "conversation",
        "updated_at": float(raw.get("updated_at") or time.time()),
        "authority": "sessions.conversation_active_task_environment",
    }


def _normalize_project_binding(
    payload: dict[str, Any] | None,
    *,
    validate_root: bool,
    timestamp: float | None = None,
) -> dict[str, Any]:
    raw = dict(payload or {})
    workspace_root = str(raw.get("workspace_root") or raw.get("root") or "").strip()
    if not workspace_root:
        return {}
    root = Path(workspace_root).expanduser().resolve()
    if validate_root and (not root.exists() or not root.is_dir()):
        raise ValueError("project binding workspace_root must be an existing directory")
    now = float(timestamp or time.time())
    bound_at = float(raw.get("bound_at") or raw.get("created_at") or now)
    last_seen_at = float(raw.get("last_seen_at") or raw.get("updated_at") or bound_at)
    return {
        "workspace_root": str(root),
        "source": str(raw.get("source") or "manual").strip() or "manual",
        "bound_at": bound_at,
        "last_seen_at": last_seen_at,
        "immutable": True,
        "authority": "sessions.project_binding",
    }


def _normalize_conversation_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    active = _normalize_active_task_environment(dict(raw.get("active_task_environment") or {}))
    project_binding = _normalize_project_binding(dict(raw.get("project_binding") or {}), validate_root=False)
    return {
        "active_task_environment": active,
        "project_binding": project_binding,
        "permission_mode": _normalize_session_permission_mode(raw.get("permission_mode")),
        "authority": str(raw.get("authority") or "sessions.conversation_state"),
    }


def _normalize_session_permission_mode(mode: Any) -> str:
    normalized = normalize_permission_mode(str(mode or "").strip() or DEFAULT_SESSION_PERMISSION_MODE)
    return normalized if normalized else DEFAULT_SESSION_PERMISSION_MODE


def _normalize_turn_environment_snapshot(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    environment_id = str(raw.get("task_environment_id") or raw.get("environment_id") or "").strip()
    prompt_refs = [
        str(item or "").strip()
        for item in list(raw.get("environment_prompt_refs") or [])
        if str(item or "").strip()
    ]
    return {
        "turn_id": str(raw.get("turn_id") or "").strip(),
        "task_environment_id": environment_id,
        "environment_kind": str(raw.get("environment_kind") or "").strip(),
        "environment_prompt_refs": prompt_refs,
        "runtime_assembly_id": str(raw.get("runtime_assembly_id") or raw.get("assembly_id") or "").strip(),
        "task_run_id": str(raw.get("task_run_id") or "").strip(),
        "authority": "sessions.turn_environment_snapshot",
    }


def _scope_matches(
    payload: dict[str, Any],
    *,
    workspace_view: str | None = None,
    task_environment_id: str | None = None,
    project_id: str | None = None,
) -> bool:
    scope = _normalize_scope(dict(payload.get("scope") or {}))
    if workspace_view is not None and scope["workspace_view"] != str(workspace_view or "").strip():
        return False
    if task_environment_id is not None and scope["task_environment_id"] != str(task_environment_id or "").strip():
        return False
    if project_id is not None and scope["project_id"] != str(project_id or "").strip():
        return False
    return True


def _same_workspace_root(left: str, right: str) -> bool:
    try:
        left_key = os.path.normcase(str(Path(left).resolve()))
        right_key = os.path.normcase(str(Path(right).resolve()))
    except Exception:
        left_key = os.path.normcase(str(left or ""))
        right_key = os.path.normcase(str(right or ""))
    return left_key == right_key


_PUBLIC_MESSAGE_PROTOCOL_KEYS = {
    "name",
    "reasoning_content",
    "tool_call_id",
    "tool_calls",
}


def _public_messages(messages: list[Any]) -> list[dict[str, Any]]:
    return _suppress_superseded_stream_failure_boundaries([
        message
        for _, message in _public_messages_with_raw_index(messages)
    ])


def _public_messages_with_raw_index(messages: list[Any]) -> list[tuple[int, dict[str, Any]]]:
    result: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(list(messages or [])):
        if not isinstance(item, dict):
            continue
        message = _public_message(item)
        if message is not None:
            result.append((index, message))
    return result


def _public_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    role = str(payload.get("role") or "").strip()
    if role not in {"user", "assistant"}:
        return None
    if role == "assistant" and _has_protocol_tool_calls(payload):
        return None
    content = str(payload.get("content") or "")
    image = payload.get("image")
    has_image = isinstance(image, dict) and bool(str(image.get("src") or "").strip())
    if not content.strip() and not has_image:
        return None
    message = {
        key: value
        for key, value in dict(payload).items()
        if key not in _PUBLIC_MESSAGE_PROTOCOL_KEYS
    }
    message["role"] = role
    message["content"] = content
    return message


def _has_protocol_tool_calls(payload: dict[str, Any]) -> bool:
    tool_calls = payload.get("tool_calls")
    return isinstance(tool_calls, list) and bool(tool_calls)


_STREAM_FAILURE_BOUNDARY_SOURCE = "harness.runtime.stream_failure_reconciliation"
_STREAM_FAILURE_BOUNDARY_MARKERS = (
    "执行流因运行进程重启中断",
    "工具结果没有交回模型完成收口",
    "执行流结束时没有产生完整终止事件",
    "执行流被系统取消",
    "执行流异常中断",
)


def _suppress_superseded_stream_failure_boundaries(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
    result: list[dict[str, Any]] = []
    for index, message in enumerate(normalized):
        turn_id = str(message.get("turn_id") or "").strip()
        if (
            turn_id
            and _is_stream_failure_boundary_message(message)
            and _has_later_non_boundary_assistant_for_turn(normalized, start_index=index + 1, turn_id=turn_id)
        ):
            continue
        result.append(message)
    return result


def _has_later_non_boundary_assistant_for_turn(messages: list[dict[str, Any]], *, start_index: int, turn_id: str) -> bool:
    target_turn_id = str(turn_id or "").strip()
    if not target_turn_id:
        return False
    for item in messages[start_index:]:
        if str(item.get("turn_id") or "").strip() != target_turn_id:
            continue
        if str(item.get("role") or "").strip() != "assistant":
            continue
        if _is_stream_failure_boundary_message(item):
            continue
        content = str(item.get("content") or "").strip()
        image = item.get("image")
        has_image = isinstance(image, dict) and bool(str(image.get("src") or "").strip())
        if content or has_image:
            return True
    return False


def _remove_stream_failure_boundary_messages_for_turn(messages: list[Any], *, turn_id: str) -> tuple[list[Any], int]:
    target_turn_id = str(turn_id or "").strip()
    kept: list[Any] = []
    removed = 0
    for item in list(messages or []):
        if (
            isinstance(item, dict)
            and str(item.get("turn_id") or "").strip() == target_turn_id
            and _is_stream_failure_boundary_message(item)
        ):
            removed += 1
            continue
        kept.append(item)
    return kept, removed


def _is_stream_failure_boundary_message(message: dict[str, Any]) -> bool:
    if str(message.get("role") or "").strip() != "assistant":
        return False
    if str(message.get("answer_source") or "").strip() == _STREAM_FAILURE_BOUNDARY_SOURCE:
        return True
    if str(message.get("runtime_failure_code") or "").strip():
        return True
    content = str(message.get("content") or "")
    return any(marker in content for marker in _STREAM_FAILURE_BOUNDARY_MARKERS)


def _agent_message(payload: dict[str, Any]) -> dict[str, str] | None:
    role = str(payload.get("role") or "").strip()
    if role not in {"user", "assistant"}:
        return None
    content = str(payload.get("content") or "")
    if not content:
        return None
    return {"role": role, "content": content}


def _api_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    role = str(payload.get("role") or payload.get("type") or "").strip()
    if role not in {"user", "assistant", "tool"}:
        return None
    content = str(payload.get("content") or "")
    message: dict[str, Any] = {"role": role, "content": content}
    for key in ("turn_id", "name", "tool_call_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            message[key] = value
    created_at = _float(payload.get("created_at"))
    if created_at > 0:
        message["created_at"] = created_at
    if role == "assistant":
        reasoning_content = str(payload.get("reasoning_content") or "").strip()
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        tool_calls = payload.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            message["tool_calls"] = [dict(item) for item in tool_calls if isinstance(item, dict)]
    if role == "tool" and not message.get("tool_call_id"):
        return None
    if role != "assistant" and not content and role != "tool":
        return None
    if role == "assistant" and not content and not message.get("tool_calls") and not message.get("reasoning_content"):
        return None
    return message


def _truncated_api_transcript(
    transcript: list[Any],
    *,
    kept_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kept_turn_ids = {
        str(item.get("turn_id") or "").strip()
        for item in kept_messages
        if isinstance(item, dict) and str(item.get("turn_id") or "").strip()
    }
    if not kept_turn_ids:
        return [
            item
            for item in (_api_message(message) for message in kept_messages if isinstance(message, dict))
            if item is not None
        ]
    result: list[dict[str, Any]] = []
    for item in transcript:
        if not isinstance(item, dict):
            continue
        message = _api_message(item)
        if message is None:
            continue
        turn_id = str(message.get("turn_id") or "").strip()
        if turn_id and turn_id in kept_turn_ids:
            result.append(message)
    return result


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def validate_session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized != _safe_session_id(normalized):
        raise InvalidSessionId("Invalid session_id")
    return normalized


