from __future__ import annotations

from typing import Any


FILE_EVIDENCE_SCOPE_AUTHORITY = "runtime.file_evidence_scope"
FILE_EVIDENCE_SCOPE_KINDS = {"task_run", "session"}


def task_run_file_evidence_scope(task_run_id: str, *, session_id: str = "") -> dict[str, Any]:
    return normalize_file_evidence_scope(
        {
            "kind": "task_run",
            "scope_id": str(task_run_id or "").strip(),
            "task_run_id": str(task_run_id or "").strip(),
            "session_id": str(session_id or "").strip(),
        }
    )


def session_file_evidence_scope(session_id: str) -> dict[str, Any]:
    return normalize_file_evidence_scope(
        {
            "kind": "session",
            "scope_id": str(session_id or "").strip(),
            "session_id": str(session_id or "").strip(),
        }
    )


def normalize_file_evidence_scope(
    scope: dict[str, Any] | None,
    *,
    task_run_id: str = "",
    session_id: str = "",
    caller_kind: str = "",
) -> dict[str, Any]:
    del caller_kind
    payload = dict(scope or {})
    kind = str(payload.get("kind") or payload.get("scope_kind") or "").strip()
    fallback_task = str(task_run_id or payload.get("task_run_id") or "").strip()
    fallback_session = str(session_id or payload.get("session_id") or "").strip()
    if kind not in FILE_EVIDENCE_SCOPE_KINDS:
        return {}
    if kind == "task_run":
        resolved_task = str(payload.get("task_run_id") or fallback_task or payload.get("scope_id") or "").strip()
        if not resolved_task:
            return {}
        scope_id = str(payload.get("scope_id") or resolved_task).strip()
        return _drop_empty(
            {
                "kind": "task_run",
                "scope_id": scope_id,
                "task_run_id": resolved_task,
                "session_id": fallback_session,
                "authority": FILE_EVIDENCE_SCOPE_AUTHORITY,
            }
        )
    resolved_session = str(payload.get("session_id") or fallback_session or payload.get("scope_id") or "").strip()
    if not resolved_session:
        return {}
    scope_id = str(payload.get("scope_id") or resolved_session).strip()
    return _drop_empty(
        {
            "kind": "session",
            "scope_id": scope_id,
            "session_id": resolved_session,
            "authority": FILE_EVIDENCE_SCOPE_AUTHORITY,
        }
    )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
