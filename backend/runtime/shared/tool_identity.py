from __future__ import annotations

import hashlib
from typing import Any


def generated_tool_call_id(*, request_id: Any, tool_name: Any = "", ordinal: int | None = None) -> str:
    request_ref = str(request_id or "").strip() or "model-action"
    normalized_tool = str(tool_name or "").strip() or "tool"
    ordinal_part = "" if ordinal is None else f":{int(ordinal) + 1}"
    digest = hashlib.sha256(f"{request_ref}:{normalized_tool}{ordinal_part}".encode("utf-8")).hexdigest()[:10]
    return f"toolcall:{request_ref}:{digest}"


def ensure_tool_call_id(tool_call: dict[str, Any] | None, *, request_id: Any, ordinal: int | None = None) -> dict[str, Any]:
    payload = dict(tool_call or {})
    existing = str(payload.get("id") or payload.get("tool_call_id") or "").strip()
    if existing:
        payload["id"] = existing
        return payload
    tool_name = payload.get("tool_name") or payload.get("name") or ""
    payload["id"] = generated_tool_call_id(request_id=request_id, tool_name=tool_name, ordinal=ordinal)
    return payload


def canonical_action_tool_call_id(action_request: Any) -> str:
    tool_call = dict(getattr(action_request, "tool_call", {}) or {})
    return str(tool_call.get("id") or getattr(action_request, "tool_call_id", "") or "").strip()


def canonical_runtime_tool_call_id(action_request: Any) -> str:
    payload = dict(getattr(action_request, "payload", {}) or {})
    tool_call = dict(payload.get("tool_call") or {})
    return str(tool_call.get("id") or getattr(action_request, "tool_call_id", "") or "").strip()


def permission_decision_id(admission: Any = None, *, tool_call_id: Any = "") -> str:
    admission_id = ""
    if isinstance(admission, dict):
        admission_id = str(admission.get("admission_id") or admission.get("permission_decision_id") or "").strip()
    elif admission is not None:
        admission_id = str(getattr(admission, "admission_id", "") or getattr(admission, "permission_decision_id", "") or "").strip()
    if admission_id:
        return admission_id
    canonical_tool_id = str(tool_call_id or "").strip()
    return f"admission:{canonical_tool_id}" if canonical_tool_id else ""
