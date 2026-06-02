from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


class InvalidSessionId(ValueError):
    pass


class SessionTaskBindingConflict(ValueError):
    pass


class SessionTaskBindingMissing(ValueError):
    pass


class SessionManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.sessions_dir = ProjectLayout.from_backend_dir(self.base_dir).sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

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

    def create_session(self, *, title: str = "New Session", scope: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        session_id = f"session-{uuid.uuid4().hex[:16]}"
        payload = {
            "id": session_id,
            "title": str(title or "New Session").strip() or "New Session",
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "api_transcript": [],
            "compressed_context": "",
            "scope": _normalize_scope(scope),
            "task_binding": {},
        }
        self._write_payload(session_id, payload)
        return self._summary_from_payload(payload)

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        payload["title"] = str(title or "").strip() or payload.get("title") or "New Session"
        payload["updated_at"] = time.time()
        self._write_payload(session_id, payload)
        return self._summary_from_payload(payload)

    def set_title(self, session_id: str, title: str) -> dict[str, Any]:
        return self.rename_session(session_id, title)

    def delete_session(self, session_id: str) -> bool:
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
        return True

    def load_session(self, session_id: str) -> list[dict[str, Any]]:
        return list(self._read_payload(session_id).get("messages") or [])

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
        return {
            "id": str(payload.get("id") or session_id),
            "title": str(payload.get("title") or "New Session"),
            "created_at": float(payload.get("created_at") or 0),
            "updated_at": float(payload.get("updated_at") or 0),
            "compressed_context": str(payload.get("compressed_context") or ""),
            "scope": _normalize_scope(dict(payload.get("scope") or {})),
            "task_binding": _normalize_task_binding(dict(payload.get("task_binding") or {})),
            "messages": list(payload.get("messages") or []),
        }

    def get_task_binding(self, session_id: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        return _normalize_task_binding(dict(payload.get("task_binding") or {}))

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
        payload = self._read_payload(session_id)
        existing = list(payload.get("messages") or [])
        for item in messages:
            if isinstance(item, dict):
                role = str(item.get("role") or "").strip() or "assistant"
                content = str(item.get("content") or "")
                message = {**item, "role": role, "content": content}
                existing.append(message)
        payload["messages"] = existing
        payload["updated_at"] = time.time()
        self._write_payload(session_id, payload)
        return existing

    def append_api_messages(self, session_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = self._read_payload(session_id)
        existing = list(payload.get("api_transcript") or [])
        for item in messages:
            if not isinstance(item, dict):
                continue
            message = _api_message(item)
            if message is not None:
                existing.append(message)
        payload["api_transcript"] = existing
        payload["updated_at"] = time.time()
        self._write_payload(session_id, payload)
        return existing

    def truncate_messages_from(self, session_id: str, message_index: int) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        messages = list(payload.get("messages") or [])
        if message_index < 0 or message_index > len(messages):
            raise ValueError("message_index out of range")
        kept_messages = messages[:message_index]
        payload["messages"] = kept_messages
        payload["api_transcript"] = _truncated_api_transcript(
            list(payload.get("api_transcript") or []),
            kept_messages=kept_messages,
        )
        payload["updated_at"] = time.time()
        self._write_payload(session_id, payload)
        return self.get_history(session_id)

    def _load_all(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _summary_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = list(payload.get("messages") or [])
        return {
            "id": str(payload.get("id") or ""),
            "title": str(payload.get("title") or "New Session"),
            "created_at": float(payload.get("created_at") or 0),
            "updated_at": float(payload.get("updated_at") or 0),
            "message_count": len(messages),
            "scope": _normalize_scope(dict(payload.get("scope") or {})),
            "task_binding": _normalize_task_binding(dict(payload.get("task_binding") or {})),
        }

    def _read_payload(self, session_id: str) -> dict[str, Any]:
        path = self._session_path(session_id)
        if not path.exists():
            raise ValueError("Unknown session_id")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid session payload")
        return payload

    def _write_payload(self, session_id: str, payload: dict[str, Any]) -> None:
        path = self._session_path(session_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _session_path(self, session_id: str) -> Path:
        safe = _safe_session_id(session_id)
        path = (self.sessions_dir / f"{safe}.json").resolve()
        root = self.sessions_dir.resolve()
        if root != path.parent:
            raise ValueError("Invalid session_id")
        return path


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


def validate_session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized != _safe_session_id(normalized):
        raise InvalidSessionId("Invalid session_id")
    return normalized


