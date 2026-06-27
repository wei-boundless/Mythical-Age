from __future__ import annotations

import copy
import hashlib
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
from core.project_layout import ProjectLayout

try:
    import orjson
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
    orjson = None

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
        self._summary_cache_guard = threading.Lock()
        self._summary_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}

    def list_sessions(
        self,
        *,
        workspace_view: str | None = None,
        task_environment_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sessions = [
            item
            for item in self._list_session_summaries()
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

    def session_storage_signature(self, session_id: str) -> tuple[int, int]:
        with self._session_lock(session_id):
            path = self._session_path(session_id)
            try:
                stat = path.stat()
            except OSError as exc:
                raise ValueError("Unknown session_id") from exc
            return int(stat.st_mtime_ns), int(stat.st_size)

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
            "compaction_generation": "0",
            "compaction_generation_updated_at": 0.0,
            "scope": _normalize_scope(scope),
            "task_binding": {},
            "conversation_state": _normalize_conversation_state(initial_state),
        }
        self._write_payload(session_id, payload)
        return self._summary_from_payload(payload)

    def fork_session(
        self,
        parent_session_id: str,
        *,
        title: str = "",
        session_id: str = "",
        workspace_effect_policy: str = "shared_workspace",
    ) -> dict[str, Any]:
        parent_id = str(parent_session_id or "").strip()
        now = time.time()
        with self._session_lock(parent_id):
            parent_payload = self._read_payload(parent_id)
            child_id = str(session_id or "").strip() or f"session-{uuid.uuid4().hex[:16]}"
            child_path = self._session_path(child_id)
            if child_path.exists():
                raise ValueError("fork target session already exists")
            provider_anchor = self._latest_provider_visible_anchor(parent_id)
            provider_request_commit = self._latest_provider_request_context_commit(parent_id)
            context_commit = self._create_context_commit_record(
                parent_id,
                parent_payload,
                provider_anchor=provider_anchor,
            )
            fork_id = f"fork-{uuid.uuid4().hex[:16]}"
            provider_cache_scope_id = _fork_provider_cache_scope_id(parent_payload, parent_session_id=parent_id)
            parent_file_evidence_scope = self._session_file_evidence_scope(parent_id)
            child_file_evidence_scope = self._session_file_evidence_scope(child_id)
            file_state_snapshot = self._session_file_state_snapshot(parent_id)
            file_state_materialization = self._materialize_fork_file_state(
                parent_session_id=parent_id,
                child_session_id=child_id,
                snapshot=file_state_snapshot,
                parent_file_evidence_scope=parent_file_evidence_scope,
                child_file_evidence_scope=child_file_evidence_scope,
                fork_id=fork_id,
            )
            read_evidence_state_ref = _fork_state_ref(
                "read_evidence",
                {
                    "file_evidence_scope": parent_file_evidence_scope,
                    "file_state_snapshot": file_state_snapshot,
                },
            )
            tool_context_projection = _fork_tool_context_projection(provider_request_commit.get("tool_context_projection"))
            content_replacement_state = _fork_content_replacement_state(
                parent_payload=parent_payload,
                provider_request_commit=provider_request_commit,
            )
            forked_from = {
                "fork_id": fork_id,
                "parent_session_id": parent_id,
                "fork_point_context_commit_id": str(context_commit.get("record_id") or ""),
                "fork_point_turn_id": str(context_commit.get("turn_id") or ""),
                "fork_point_public_message_count": len(list(parent_payload.get("messages") or [])),
                "fork_point_api_transcript_count": len(list(parent_payload.get("api_transcript") or [])),
                "fork_point_provider_visible_ledger_anchor": provider_anchor,
                "fork_point_cache_spine_hash": str(context_commit.get("cache_spine_hash") or ""),
                "fork_point_provider_request_commit_id": str(provider_request_commit.get("record_id") or ""),
                "fork_point_provider_request_cache_spine_hash": str(provider_request_commit.get("cache_spine_hash") or ""),
                "fork_point_provider_payload_prefix_hash": str(provider_request_commit.get("provider_payload_prefix_hash") or ""),
                "fork_point_provider_payload_message_prefix_hash": str(provider_request_commit.get("provider_payload_message_prefix_hash") or ""),
                "fork_point_provider_payload_messages_hash": str(provider_request_commit.get("provider_payload_messages_hash") or ""),
                "fork_point_transport_contract_hash": str(provider_request_commit.get("transport_contract_hash") or ""),
                "fork_point_cache_sensitive_params_hash": str(provider_request_commit.get("cache_sensitive_params_hash") or ""),
                "fork_point_tool_catalog_hash": str(provider_request_commit.get("tool_catalog_hash") or ""),
                "fork_point_stable_tool_catalog_hash": str(provider_request_commit.get("stable_tool_catalog_hash") or ""),
                "fork_point_tool_context_anchor": str(provider_request_commit.get("tool_context_anchor") or ""),
                "fork_point_tool_context_projection": tool_context_projection,
                "fork_point_read_evidence_scope": parent_file_evidence_scope,
                "fork_child_read_evidence_scope": child_file_evidence_scope,
                "fork_point_read_evidence_state_ref": read_evidence_state_ref,
                "fork_point_read_evidence_file_count": len(file_state_snapshot),
                "fork_point_file_state_snapshot": file_state_snapshot,
                "fork_file_state_materialization": file_state_materialization,
                "fork_point_content_replacement_state_ref": str(content_replacement_state.get("state_ref") or ""),
                "fork_point_content_replacement_state": content_replacement_state,
                "provider_cache_scope_id": provider_cache_scope_id,
                "fork_point_compaction_generation": str(
                    context_commit.get("compaction_generation")
                    or parent_payload.get("compaction_generation")
                    or "0"
                ),
                "workspace_effect_policy": _normalize_workspace_effect_policy(workspace_effect_policy),
                "created_at": now,
                "authority": "sessions.fork_context_snapshot",
            }
            child_payload = copy.deepcopy(parent_payload)
            child_payload["id"] = child_id
            child_payload["title"] = str(title or "").strip() or _fork_title(str(parent_payload.get("title") or "New Session"))
            child_payload["created_at"] = now
            child_payload["updated_at"] = now
            child_payload["parent_session_id"] = parent_id
            child_payload["forked_from"] = forked_from
            child_payload["messages"] = _rewrite_message_session_refs(list(child_payload.get("messages") or []), parent_id=parent_id, child_id=child_id)
            child_payload["api_transcript"] = _rewrite_message_session_refs(list(child_payload.get("api_transcript") or []), parent_id=parent_id, child_id=child_id)
            child_payload["task_binding"] = copy.deepcopy(dict(parent_payload.get("task_binding") or {}))
            child_payload["scope"] = _normalize_scope(dict(parent_payload.get("scope") or {}))
            child_payload["conversation_state"] = _normalize_conversation_state(dict(parent_payload.get("conversation_state") or {}))
            self._write_payload(child_id, child_payload)
            return self._summary_from_payload(child_payload)

    def rename_session(self, session_id: str, title: str, *, preserve_updated_at: bool = False) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            payload["title"] = str(title or "").strip() or payload.get("title") or "New Session"
            if not preserve_updated_at:
                payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return self._summary_from_payload(payload)

    def set_title(self, session_id: str, title: str) -> dict[str, Any]:
        return self.rename_session(session_id, title)

    def set_title_if_default(
        self,
        session_id: str,
        title: str,
        *,
        default_title: str = "New Session",
        preserve_updated_at: bool = False,
    ) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            current_title = str(payload.get("title") or "").strip() or default_title
            if current_title != default_title:
                return self._summary_from_payload(payload)
            next_title = str(title or "").strip()
            if not next_title:
                return self._summary_from_payload(payload)
            payload["title"] = next_title
            if not preserve_updated_at:
                payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return self._summary_from_payload(payload)

    def delete_session(self, session_id: str) -> bool:
        with self._session_lock(session_id):
            path = self._session_path(session_id)
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                raise SessionStorageError(f"failed to delete session payload: {session_id}") from exc
            self._invalidate_summary_cache(session_id)
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
        transcript = [item for item in transcript if item is not None]
        if transcript:
            return transcript
        return self.load_session_for_agent(session_id)

    def get_history(self, session_id: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        return self._history_from_payload(session_id, payload)

    def _history_from_payload(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(payload.get("id") or session_id),
            "title": str(payload.get("title") or "New Session"),
            "created_at": float(payload.get("created_at") or 0),
            "updated_at": float(payload.get("updated_at") or 0),
            "parent_session_id": str(payload.get("parent_session_id") or ""),
            "forked_from": dict(payload.get("forked_from") or {}),
            "compressed_context": str(payload.get("compressed_context") or ""),
            "provider_protocol_compaction_created_at": _float(payload.get("provider_protocol_compaction_created_at")),
            "compaction_generation": str(payload.get("compaction_generation") or "0"),
            "compaction_generation_updated_at": _float(payload.get("compaction_generation_updated_at")),
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

    def set_chat_model_selection(self, session_id: str, selection: dict[str, Any]) -> dict[str, Any]:
        with self._session_lock(session_id):
            payload = self._read_payload(session_id)
            state = _normalize_conversation_state(dict(payload.get("conversation_state") or {}))
            state["chat_model_selection"] = _normalize_chat_model_selection(selection)
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
        graph_config_id: str = "",
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
                    "graph_config_id": graph_config_id,
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
        compaction_generation_reason: str = "",
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
            if str(compaction_generation_reason or "").strip():
                _bump_compaction_generation(
                    payload,
                    reason=str(compaction_generation_reason or "").strip(),
                )
            payload["updated_at"] = time.time()
            self._write_payload(session_id, payload)
            return self._history_from_payload(session_id, payload)

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
            return self._history_from_payload(session_id, payload)

    def _load_all(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                with self._session_lock(path.stem):
                    payload = self._read_payload_from_path(path, session_id=path.stem)
            except SessionStorageError as exc:
                logger.warning("Skipping unreadable session payload %s: %s", path, exc)
                rows.append(_unreadable_session_payload(path, error=str(exc)))
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _list_session_summaries(self) -> list[dict[str, Any]]:
        return [self._summary_from_path(path) for path in self.sessions_dir.glob("*.json")]

    def _summary_from_path(self, path: Path) -> dict[str, Any]:
        session_id = path.stem
        with self._session_lock(session_id):
            try:
                stat = path.stat()
            except OSError as exc:
                logger.warning("Skipping unreadable session payload %s: %s", path, exc)
                return self._summary_from_payload(_unreadable_session_payload(path, error=str(exc)))
            cached = self._cached_summary(path.name, mtime_ns=stat.st_mtime_ns, size=stat.st_size)
            if cached is not None:
                return cached
            try:
                payload = self._read_payload_from_path(path, session_id=session_id)
                summary = self._summary_from_payload(payload)
            except SessionStorageError as exc:
                logger.warning("Skipping unreadable session payload %s: %s", path, exc)
                summary = self._summary_from_payload(_unreadable_session_payload(path, error=str(exc)))
            try:
                latest_stat = path.stat()
                mtime_ns = latest_stat.st_mtime_ns
                size = latest_stat.st_size
            except OSError:
                mtime_ns = stat.st_mtime_ns
                size = stat.st_size
            self._store_cached_summary(path.name, mtime_ns=mtime_ns, size=size, summary=summary)
            return _clone_summary(summary)

    def _summary_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        message_count = _public_message_count(list(payload.get("messages") or []))
        summary = {
            "id": str(payload.get("id") or ""),
            "title": str(payload.get("title") or "New Session"),
            "created_at": float(payload.get("created_at") or 0),
            "updated_at": float(payload.get("updated_at") or 0),
            "parent_session_id": str(payload.get("parent_session_id") or ""),
            "forked_from": dict(payload.get("forked_from") or {}),
            "message_count": message_count,
            "compaction_generation": str(payload.get("compaction_generation") or "0"),
            "compaction_generation_updated_at": _float(payload.get("compaction_generation_updated_at")),
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
        with self._session_lock(session_id):
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
            payload = orjson.loads(raw) if orjson is not None else json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SessionPayloadCorrupt(f"corrupt session payload: {session_id}") from exc
        except ValueError as exc:
            raise SessionPayloadCorrupt(f"corrupt session payload: {session_id}") from exc
        if not isinstance(payload, dict):
            raise SessionPayloadCorrupt(f"invalid session payload: {session_id}")
        return payload

    def _write_payload(self, session_id: str, payload: dict[str, Any]) -> None:
        with self._session_lock(session_id):
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
                self._invalidate_summary_cache(session_id)
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

    def _cached_summary(self, cache_key: str, *, mtime_ns: int, size: int) -> dict[str, Any] | None:
        with self._summary_cache_guard:
            cached = self._summary_cache.get(cache_key)
            if cached is None:
                return None
            cached_mtime_ns, cached_size, summary = cached
            if cached_mtime_ns != int(mtime_ns) or cached_size != int(size):
                self._summary_cache.pop(cache_key, None)
                return None
            return _clone_summary(summary)

    def _store_cached_summary(self, cache_key: str, *, mtime_ns: int, size: int, summary: dict[str, Any]) -> None:
        with self._summary_cache_guard:
            self._summary_cache[cache_key] = (int(mtime_ns), int(size), _clone_summary(summary))

    def _invalidate_summary_cache(self, session_id: str) -> None:
        try:
            cache_key = f"{_safe_session_id(session_id)}.json"
        except InvalidSessionId:
            return
        with self._summary_cache_guard:
            self._summary_cache.pop(cache_key, None)

    def _latest_provider_visible_anchor(self, session_id: str) -> dict[str, Any]:
        try:
            from runtime.context_management.provider_visible_context_ledger import latest_provider_visible_context_success_anchor

            return latest_provider_visible_context_success_anchor(storage_root=self.base_dir, scope=session_id)
        except Exception:
            logger.exception("Failed to load provider-visible context anchor for fork: %s", session_id)
            return {}

    def _latest_provider_request_context_commit(self, session_id: str) -> dict[str, Any]:
        try:
            from runtime.context_management.context_commit_record import latest_provider_request_context_commit_record

            return latest_provider_request_context_commit_record(
                storage_root=self.base_dir,
                session_id=session_id,
                status="succeeded",
            )
        except Exception:
            logger.exception("Failed to load provider request context commit for fork: %s", session_id)
            return {}

    def _create_context_commit_record(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        provider_anchor: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from runtime.context_management.context_commit_record import create_session_context_commit_record

            return create_session_context_commit_record(
                storage_root=self.base_dir,
                session_id=session_id,
                session_payload=dict(payload or {}),
                provider_visible_anchor=dict(provider_anchor or {}),
                reason="session_fork_point",
            )
        except Exception:
            logger.exception("Failed to create context commit record for fork: %s", session_id)
            return {}

    def _session_file_evidence_scope(self, session_id: str) -> dict[str, Any]:
        try:
            from runtime.memory.file_evidence_scope import session_file_evidence_scope

            return session_file_evidence_scope(session_id)
        except Exception:
            logger.exception("Failed to create session file evidence scope for fork: %s", session_id)
            return {}

    def _session_file_state_snapshot(self, session_id: str) -> list[dict[str, Any]]:
        scope = self._session_file_evidence_scope(session_id)
        if not scope:
            return []
        try:
            from runtime.memory.file_state_store import FileStateAuthorityStore

            return [
                dict(item)
                for item in list(FileStateAuthorityStore(self.base_dir).snapshot_scope(scope, limit=20) or [])
                if isinstance(item, dict)
            ]
        except Exception:
            logger.exception("Failed to load file evidence snapshot for fork: %s", session_id)
            return []

    def _materialize_fork_file_state(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
        snapshot: list[dict[str, Any]],
        parent_file_evidence_scope: dict[str, Any],
        child_file_evidence_scope: dict[str, Any],
        fork_id: str,
    ) -> dict[str, Any]:
        if not snapshot:
            return {
                "status": "empty",
                "source_file_evidence_scope": dict(parent_file_evidence_scope or {}),
                "target_file_evidence_scope": dict(child_file_evidence_scope or {}),
                "authority": "sessions.fork_context_snapshot.file_state_materialization",
            }
        try:
            from runtime.memory.file_state_store import FileStateAuthorityStore

            result = FileStateAuthorityStore(self.base_dir).materialize_snapshot_scope(
                child_file_evidence_scope,
                snapshot,
                source_scope=parent_file_evidence_scope,
                observation_ref=f"fork:{fork_id}:file_state_snapshot",
                tool_call_id="session_fork",
            )
            return {
                **dict(result or {}),
                "parent_session_id": str(parent_session_id or ""),
                "child_session_id": str(child_session_id or ""),
                "fork_id": str(fork_id or ""),
                "authority": "sessions.fork_context_snapshot.file_state_materialization",
            }
        except Exception:
            logger.exception("Failed to materialize fork file state: %s -> %s", parent_session_id, child_session_id)
            return {
                "status": "failed",
                "source_file_evidence_scope": dict(parent_file_evidence_scope or {}),
                "target_file_evidence_scope": dict(child_file_evidence_scope or {}),
                "parent_session_id": str(parent_session_id or ""),
                "child_session_id": str(child_session_id or ""),
                "fork_id": str(fork_id or ""),
                "authority": "sessions.fork_context_snapshot.file_state_materialization",
            }


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


def _clone_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(summary or {}))


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


def _fork_title(parent_title: str) -> str:
    base = str(parent_title or "New Session").strip() or "New Session"
    suffix = " fork"
    limit = 100
    if len(base) + len(suffix) <= limit:
        return base + suffix
    return base[: max(1, limit - len(suffix))].rstrip() + suffix


def _fork_provider_cache_scope_id(parent_payload: dict[str, Any], *, parent_session_id: str) -> str:
    forked_from = (
        dict(parent_payload.get("forked_from") or {})
        if isinstance(parent_payload.get("forked_from"), dict)
        else {}
    )
    inherited = str(forked_from.get("provider_cache_scope_id") or "").strip()
    if inherited:
        return inherited
    return str(parent_session_id or "").strip()


def _fork_tool_context_projection(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    segments = [
        _drop_empty(
            {
                "segment_id": str(item.get("segment_id") or ""),
                "kind": str(item.get("kind") or ""),
                "source_ref": str(item.get("source_ref") or ""),
                "tool_observation_ref": str(item.get("tool_observation_ref") or ""),
                "tool_call_id": str(item.get("tool_call_id") or ""),
                "content_hash": str(item.get("content_hash") or ""),
                "physical_prefix_lane": str(item.get("physical_prefix_lane") or ""),
                "compaction_generation": str(item.get("compaction_generation") or ""),
            }
        )
        for item in list(payload.get("tool_context_segments") or [])[:80]
        if isinstance(item, dict)
    ]
    return _drop_empty(
        {
            "tool_context_hash": str(payload.get("tool_context_hash") or ""),
            "tool_context_segment_count": _int(payload.get("tool_context_segment_count")) or len(segments),
            "tool_context_segments": segments,
            "authority": "sessions.fork_context_snapshot.tool_context_projection",
        }
    )


def _fork_content_replacement_state(
    *,
    parent_payload: dict[str, Any],
    provider_request_commit: dict[str, Any],
) -> dict[str, Any]:
    refs = _collect_content_replacement_refs(
        [
            dict(provider_request_commit or {}).get("tool_context_projection"),
            dict(provider_request_commit or {}).get("provider_payload_segments"),
            dict(provider_request_commit or {}).get("provider_payload_cache_boundary"),
            list(dict(parent_payload or {}).get("api_transcript") or [])[-24:],
        ],
        limit=80,
    )
    return _drop_empty(
        {
            "state_ref": _fork_state_ref("content_replacement", refs),
            "replacement_count": len(refs),
            "content_replacements": refs,
            "authority": "sessions.fork_context_snapshot.content_replacement_state",
        }
    )


def _collect_content_replacement_refs(value: Any, *, limit: int) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    stack: list[tuple[Any, bool]] = [(value, False)]
    visited = 0
    replacement_keys = {
        "content_replacements",
        "replacement",
        "replacements",
        "replacement_refs",
        "rehydration_plan",
        "persisted_tool_result",
    }
    while stack and len(refs) < max(1, int(limit or 1)) and visited < 4000:
        item, inside_replacement = stack.pop()
        visited += 1
        if isinstance(item, dict):
            if inside_replacement or _dict_has_replacement_identity(item):
                ref = _content_replacement_ref(item)
                ref_key = str(
                    ref.get("replacement_id")
                    or ref.get("replacement_key")
                    or ref.get("replacement_ref")
                    or ref.get("path")
                    or ref.get("content_hash")
                    or ""
                )
                if ref and ref_key and ref_key not in seen:
                    seen.add(ref_key)
                    refs.append(ref)
                    if len(refs) >= max(1, int(limit or 1)):
                        break
            for key, child in reversed(list(item.items())):
                key_text = str(key)
                child_inside = inside_replacement or key_text in replacement_keys or key_text.endswith("content_replacements")
                if not child_inside and key_text in {"content", "text", "provider_messages", "messages"}:
                    continue
                stack.append((child, child_inside))
            continue
        if isinstance(item, (list, tuple)):
            for child in reversed(list(item)[-200:]):
                stack.append((child, inside_replacement))
    return refs


def _dict_has_replacement_identity(value: dict[str, Any]) -> bool:
    return any(
        str(value.get(key) or "").strip()
        for key in (
            "replacement_id",
            "replacement_key",
            "replacement_ref",
            "rehydration_ref",
        )
    )


def _content_replacement_ref(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    return _drop_empty(
        {
            "replacement_id": str(payload.get("replacement_id") or ""),
            "replacement_key": str(payload.get("replacement_key") or ""),
            "replacement_ref": str(payload.get("replacement_ref") or payload.get("rehydration_ref") or ""),
            "path": str(payload.get("path") or ""),
            "content_hash": str(payload.get("content_hash") or ""),
            "source_kind": str(payload.get("source_kind") or ""),
            "source_id": str(payload.get("source_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or ""),
            "status": str(payload.get("status") or payload.get("store_status") or ""),
        }
    )


def _fork_state_ref(kind: str, payload: Any) -> str:
    if payload in ("", None, [], {}, ()):
        return ""
    digest = _stable_json_hash({"kind": str(kind or ""), "payload": payload}).removeprefix("sha256:")
    return f"{kind}:{digest[:24]}"


def _stable_json_hash(value: Any) -> str:
    text = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(payload or {}).items() if value not in ("", None, [], {}, ())}


def _normalize_workspace_effect_policy(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"shared_workspace", "forked_worktree", "read_only_snapshot"}:
        return normalized
    return "shared_workspace"


def _bump_compaction_generation(payload: dict[str, Any], *, reason: str) -> None:
    current = _int(payload.get("compaction_generation"))
    next_generation = str(max(0, current) + 1)
    now = time.time()
    payload["compaction_generation"] = next_generation
    payload["compaction_generation_updated_at"] = now
    payload["compaction_generation_reason"] = str(reason or "")
    payload["compaction_generation_boundary_id"] = f"ctxgen:{next_generation}:{int(now * 1000)}"


def _rewrite_message_session_refs(messages: list[Any], *, parent_id: str, child_id: str) -> list[Any]:
    result: list[Any] = []
    for item in list(messages or []):
        if not isinstance(item, dict):
            result.append(copy.deepcopy(item))
            continue
        payload = copy.deepcopy(item)
        if str(payload.get("session_id") or "").strip() == parent_id:
            payload["session_id"] = child_id
        metadata = payload.get("metadata")
        if isinstance(metadata, dict) and str(metadata.get("session_id") or "").strip() == parent_id:
            payload["metadata"] = {**metadata, "session_id": child_id}
        result.append(payload)
    return result


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
        "graph_config_id": str(raw.get("graph_config_id") or raw.get("config_id") or "").strip(),
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


def _normalize_chat_model_selection(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    selection_id = str(raw.get("selection_id") or raw.get("id") or "").strip()
    provider = str(raw.get("provider") or "").strip().lower()
    model = str(raw.get("model") or raw.get("selected_model") or "").strip()
    if not selection_id:
        if provider and model:
            selection_id = f"{provider}::{model}"
        else:
            return {}
    if selection_id == "system-default":
        provider = ""
        model = ""
    elif "::" in selection_id and (not provider or not model):
        selected_provider, selected_model = selection_id.split("::", 1)
        provider = provider or selected_provider.strip().lower()
        model = model or selected_model.strip()
    if selection_id != "system-default" and (not provider or not model):
        return {}
    selection = {
        "selection_id": selection_id,
        "provider": provider,
        "model": model,
        "source": str(raw.get("source") or "user").strip() or "user",
        "updated_at": _float(raw.get("updated_at")) or time.time(),
        "authority": "sessions.chat_model_selection",
    }
    for key in ("base_url", "credential_ref", "thinking_mode", "reasoning_effort"):
        value = str(raw.get(key) or "").strip()
        if value:
            selection[key] = value
    for key in ("stream_policy", "provider_extensions"):
        value = raw.get(key)
        if isinstance(value, dict) and value:
            selection[key] = dict(value)
    return selection


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
    chat_model_selection = _normalize_chat_model_selection(dict(raw.get("chat_model_selection") or {}))
    project_binding = _normalize_project_binding(dict(raw.get("project_binding") or {}), validate_root=False)
    return {
        "active_task_environment": active,
        "chat_model_selection": chat_model_selection,
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
    return [
        message
        for _, message in _public_messages_with_raw_index(messages)
    ]


def _public_message_count(messages: list[Any]) -> int:
    public_messages = [
        message
        for item in list(messages or [])
        if isinstance(item, dict)
        for message in [_public_message(item)]
        if message is not None
    ]
    return len(public_messages)


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
        reasoning_content = _explicit_provider_text(payload.get("reasoning_content"))
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


def _explicit_provider_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text != "" else ""


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


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def validate_session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized != _safe_session_id(normalized):
        raise InvalidSessionId("Invalid session_id")
    return normalized
