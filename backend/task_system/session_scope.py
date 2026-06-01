from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


DEFAULT_CHAT_SCOPE = {
    "workspace_view": "chat",
    "task_environment_id": "",
    "project_id": "",
}


@dataclass(frozen=True, slots=True)
class SessionScope:
    workspace_view: str = "chat"
    task_environment_id: str = ""
    project_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "workspace_view": self.workspace_view,
            "task_environment_id": self.task_environment_id,
            "project_id": self.project_id,
        }

    @property
    def key(self) -> str:
        return session_scope_key(self)


def normalize_session_scope(scope: dict[str, Any] | SessionScope | None, *, environment_id: str = "") -> SessionScope:
    if isinstance(scope, SessionScope):
        raw = scope.to_dict()
    else:
        raw = dict(scope or {})
    workspace_view = str(raw.get("workspace_view") or raw.get("view") or DEFAULT_CHAT_SCOPE["workspace_view"]).strip() or "chat"
    task_environment_id = str(
        raw.get("task_environment_id")
        or raw.get("environment_id")
        or environment_id
        or DEFAULT_CHAT_SCOPE["task_environment_id"]
    ).strip()
    project_id = str(raw.get("project_id") or "").strip()
    return SessionScope(
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )


def session_scope_key(scope: dict[str, Any] | SessionScope | None) -> str:
    normalized = normalize_session_scope(scope)
    return "|".join([normalized.workspace_view, normalized.task_environment_id, normalized.project_id])


def session_scope_matches(left: dict[str, Any] | SessionScope | None, right: dict[str, Any] | SessionScope | None) -> bool:
    return normalize_session_scope(left).to_dict() == normalize_session_scope(right).to_dict()


def request_scope_from_query(
    *,
    workspace_view: str | None = None,
    task_environment_id: str | None = None,
    project_id: str | None = None,
) -> SessionScope | None:
    if workspace_view is None and task_environment_id is None and project_id is None:
        return None
    return normalize_session_scope(
        {
            "workspace_view": workspace_view or "",
            "task_environment_id": task_environment_id or "",
            "project_id": project_id or "",
        }
    )


def session_record_scope(session_manager: Any, session_id: str) -> SessionScope:
    return normalize_session_scope(dict(session_manager.get_history(session_id).get("scope") or {}))


def assert_session_scope(
    session_manager: Any,
    session_id: str,
    expected_scope: dict[str, Any] | SessionScope | None,
    *,
    allow_missing_scope: bool = True,
) -> SessionScope:
    actual = session_record_scope(session_manager, session_id)
    expected = normalize_session_scope(expected_scope)
    if not allow_missing_scope and expected_scope is None:
        raise HTTPException(status_code=400, detail="session_scope is required")
    if actual.to_dict() != expected.to_dict():
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Session scope mismatch",
                "session_id": session_id,
                "actual_scope": actual.to_dict(),
                "expected_scope": expected.to_dict(),
            },
        )
    return actual


def assert_optional_session_scope(
    session_manager: Any,
    session_id: str,
    expected_scope: dict[str, Any] | SessionScope | None,
) -> SessionScope:
    if expected_scope is None:
        return session_record_scope(session_manager, session_id)
    return assert_session_scope(session_manager, session_id, expected_scope)


def require_request_scope(scope: dict[str, Any] | SessionScope | None) -> SessionScope:
    if scope is None:
        raise HTTPException(status_code=400, detail="session_scope is required")
    return normalize_session_scope(scope)

