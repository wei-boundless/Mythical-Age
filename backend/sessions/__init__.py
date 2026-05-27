from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


class InvalidSessionId(ValueError):
    pass


class SessionManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.sessions_dir = ProjectLayout.from_backend_dir(self.base_dir).sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = [self._summary_from_payload(item) for item in self._load_all()]
        return sorted(sessions, key=lambda item: float(item.get("updated_at") or 0), reverse=True)

    def create_session(self, *, title: str = "New Session") -> dict[str, Any]:
        now = time.time()
        session_id = f"session-{uuid.uuid4().hex[:16]}"
        payload = {
            "id": session_id,
            "title": str(title or "New Session").strip() or "New Session",
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "compressed_context": "",
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

    def load_session_for_agent(
        self,
        session_id: str,
        *,
        include_compressed_context: bool = False,
    ) -> list[dict[str, Any]]:
        payload = self.get_history(session_id)
        messages = [
            _agent_message(item)
            for item in list(payload.get("messages") or [])
            if isinstance(item, dict)
        ]
        filtered = [item for item in messages if item is not None]
        compressed_context = str(payload.get("compressed_context") or "").strip()
        if include_compressed_context and compressed_context:
            return [
                {
                    "role": "assistant",
                    "content": f"[Compressed session context]\n{compressed_context}",
                },
                *filtered,
            ]
        return filtered

    def get_history(self, session_id: str) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        return {
            "id": str(payload.get("id") or session_id),
            "title": str(payload.get("title") or "New Session"),
            "created_at": float(payload.get("created_at") or 0),
            "updated_at": float(payload.get("updated_at") or 0),
            "compressed_context": str(payload.get("compressed_context") or ""),
            "messages": list(payload.get("messages") or []),
        }

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

    def truncate_messages_from(self, session_id: str, message_index: int) -> dict[str, Any]:
        payload = self._read_payload(session_id)
        messages = list(payload.get("messages") or [])
        if message_index < 0 or message_index > len(messages):
            raise ValueError("message_index out of range")
        payload["messages"] = messages[:message_index]
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


def _agent_message(payload: dict[str, Any]) -> dict[str, str] | None:
    role = str(payload.get("role") or "").strip()
    if role not in {"user", "assistant"}:
        return None
    content = str(payload.get("content") or "")
    if not content:
        return None
    return {"role": role, "content": content}


def validate_session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized != _safe_session_id(normalized):
        raise InvalidSessionId("Invalid session_id")
    return normalized


