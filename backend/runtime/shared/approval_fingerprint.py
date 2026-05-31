from __future__ import annotations

import hashlib
import json
from typing import Any


def build_approval_risk_fingerprint(
    *,
    operation_id: str,
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
    sandbox_policy: dict[str, Any] | None = None,
    file_management_policy: dict[str, Any] | None = None,
) -> str:
    payload = {
        "operation_id": str(operation_id or "").strip(),
        "tool_name": str(tool_name or "").strip(),
        "tool_args": _risk_relevant_tool_args(tool_args or {}),
        "sandbox": _risk_relevant_sandbox(sandbox_policy or {}),
        "file_management": _risk_relevant_file_management(file_management_policy or {}),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _risk_relevant_tool_args(tool_args: dict[str, Any]) -> dict[str, Any]:
    args = dict(tool_args or {})
    relevant: dict[str, Any] = {}
    for key in ("path", "filepath", "command", "code", "url", "method"):
        if key in args:
            relevant[key] = args.get(key)
    if "content" in args:
        relevant["content_sha256"] = _text_sha256(args.get("content"))
    if "old_text" in args:
        relevant["old_text_sha256"] = _text_sha256(args.get("old_text"))
    if "new_text" in args:
        relevant["new_text_sha256"] = _text_sha256(args.get("new_text"))
    return relevant


def _text_sha256(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _risk_relevant_sandbox(sandbox_policy: dict[str, Any]) -> dict[str, Any]:
    policy = dict(sandbox_policy or {})
    return {
        "enabled": bool(policy.get("enabled") is True),
        "mode": str(policy.get("mode") or ""),
        "sandbox_root": str(policy.get("sandbox_root") or ""),
        "workspace_root": str(policy.get("workspace_root") or ""),
        "write_scopes": [str(item) for item in list(policy.get("write_scopes") or [])],
        "read_scopes": [str(item) for item in list(policy.get("read_scopes") or [])],
    }


def _risk_relevant_file_management(file_management_policy: dict[str, Any]) -> dict[str, Any]:
    policy = dict(file_management_policy or {})
    return {
        "enabled": bool(policy.get("enabled") is True),
        "environment_id": str(policy.get("environment_id") or ""),
        "profile_id": str(policy.get("profile_id") or ""),
        "repositories": {
            str(key): str(value)
            for key, value in sorted(dict(policy.get("repositories") or {}).items())
            if str(key).strip() and str(value).strip()
        },
        "workspace_root": str(policy.get("workspace_root") or ""),
        "sandbox_root": str(policy.get("sandbox_root") or ""),
        "managed_storage_root": str(policy.get("managed_storage_root") or ""),
    }


