from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


WORKBENCH_CURRENT_SESSION_AUTHORITY = "workbench.current_session_ref"


class WorkbenchStateStore:
    def __init__(self, base_dir: Path) -> None:
        self.path = ProjectLayout.from_backend_dir(base_dir).runtime_state_dir / "workbench_current_session.json"
        self._lock = threading.RLock()

    def current_session_payload(self) -> dict[str, Any]:
        return {
            "authority": WORKBENCH_CURRENT_SESSION_AUTHORITY,
            "current_session": self._read_current_session(),
        }

    def set_current_session(
        self,
        *,
        session_id: str,
        scope: dict[str, Any] | None = None,
        pool_key: str = "main-chat",
    ) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required")
        current_session = {
            "authority": WORKBENCH_CURRENT_SESSION_AUTHORITY,
            "session_id": normalized_session_id,
            "scope": _normalize_scope(scope),
            "pool_key": str(pool_key or "main-chat").strip() or "main-chat",
            "updated_at": time.time(),
        }
        self._write_payload(current_session)
        return {
            "authority": WORKBENCH_CURRENT_SESSION_AUTHORITY,
            "current_session": current_session,
        }

    def clear_current_session(self, *, session_id: str = "") -> dict[str, Any]:
        expected = str(session_id or "").strip()
        with self._lock:
            current = self._read_current_session_unlocked()
            if expected and current and str(current.get("session_id") or "").strip() != expected:
                return {
                    "authority": WORKBENCH_CURRENT_SESSION_AUTHORITY,
                    "current_session": current,
                }
            self._write_payload_unlocked(None)
        return {
            "authority": WORKBENCH_CURRENT_SESSION_AUTHORITY,
            "current_session": None,
        }

    def _read_current_session(self) -> dict[str, Any] | None:
        with self._lock:
            return self._read_current_session_unlocked()

    def _read_current_session_unlocked(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return _normalize_current_session(raw.get("current_session"))

    def _write_payload(self, current_session: dict[str, Any] | None) -> None:
        with self._lock:
            self._write_payload_unlocked(current_session)

    def _write_payload_unlocked(self, current_session: dict[str, Any] | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "authority": WORKBENCH_CURRENT_SESSION_AUTHORITY,
            "current_session": current_session,
            "updated_at": time.time(),
        }
        tmp = self.path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def _normalize_current_session(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    session_id = str(raw.get("session_id") or raw.get("sessionId") or "").strip()
    if not session_id:
        return None
    return {
        "authority": WORKBENCH_CURRENT_SESSION_AUTHORITY,
        "session_id": session_id,
        "scope": _normalize_scope(raw.get("scope")),
        "pool_key": str(raw.get("pool_key") or raw.get("poolKey") or "main-chat").strip() or "main-chat",
        "updated_at": float(raw.get("updated_at") or 0),
    }


def _normalize_scope(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    workspace_view = str(raw.get("workspace_view") or "").strip()
    task_environment_id = str(raw.get("task_environment_id") or "").strip()
    project_id = str(raw.get("project_id") or "").strip()
    return {
        **({"workspace_view": workspace_view} if workspace_view else {}),
        **({"task_environment_id": task_environment_id} if task_environment_id else {}),
        **({"project_id": project_id} if project_id else {}),
    }
