from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system.tools.workspace_file_service import WorkspaceFileService
from permissions.operation_gate import OperationGateResult


def build_task_safety_validators(
    *,
    root_dir: Path,
    safety_envelope: dict[str, Any] | None,
    sandbox_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = dict(safety_envelope or {})
    sandbox = dict(sandbox_policy or {})
    return {
        "filesystem_path": _filesystem_validator(
            root_dir=root_dir,
            safety_envelope=envelope,
            sandbox_policy=sandbox,
        ),
        "shell_read_only": _shell_validator(sandbox_policy=sandbox),
    }


def _filesystem_validator(
    *,
    root_dir: Path,
    safety_envelope: dict[str, Any],
    sandbox_policy: dict[str, Any],
):
    policy_workspace_root = str(sandbox_policy.get("workspace_root") or "").strip()
    workspace_files = WorkspaceFileService(policy_workspace_root or root_dir)
    workspace_root = workspace_files.workspace_root
    sandbox_root = (
        Path(str(sandbox_policy.get("sandbox_root") or "")).resolve()
        if sandbox_policy.get("enabled") is True and sandbox_policy.get("sandbox_root")
        else None
    )
    sandbox_operations = {
        str(item or "").strip()
        for item in list(sandbox_policy.get("side_effect_operations") or [])
        if str(item or "").strip()
    }

    forbidden_paths = [
        _normalize_relative_path(item)
        for item in list(safety_envelope.get("forbidden_paths") or [])
        if _normalize_relative_path(item)
    ]

    def _validate(operation_input: dict[str, Any]) -> bool | tuple[bool, str] | OperationGateResult:
        input_payload = dict(operation_input or {})
        operation_id = str(input_payload.get("operation_id") or "").strip()
        args = dict(input_payload.get("args") or {})
        raw_path = str(input_payload.get("path") or args.get("path") or "").strip()
        if not raw_path:
            return True
        normalized = _normalize_workspace_path(raw_path, workspace_root=workspace_root)
        if not normalized:
            return False, "path traversal detected"
        write_sensitive = operation_id in {"op.write_file", "op.edit_file"}
        if not write_sensitive and not operation_id:
            write_sensitive = any(key in input_payload for key in ("content", "old_text", "new_text"))
        effective_root = (
            sandbox_root
            if sandbox_root is not None and (write_sensitive or operation_id in sandbox_operations)
            else workspace_root
        )
        try:
            candidate = workspace_files.resolve(normalized) if effective_root == workspace_root else (effective_root / normalized).resolve()
        except ValueError:
            return False, "path traversal detected"
        if effective_root not in candidate.parents and candidate != effective_root:
            return False, "path traversal detected"
        normalized_candidate = candidate.relative_to(effective_root).as_posix()
        if write_sensitive:
            if any(
                normalized_candidate == blocked or normalized_candidate.startswith(f"{blocked}/")
                for blocked in forbidden_paths
            ):
                return False, f"path blocked by task safety envelope: {normalized_candidate}"
        return True

    return _validate


def _shell_validator(*, sandbox_policy: dict[str, Any]):
    sandbox_enabled = bool(sandbox_policy.get("enabled") is True and sandbox_policy.get("sandbox_root"))

    def _validate(operation_input: dict[str, Any]) -> bool | tuple[bool, str] | OperationGateResult:
        if sandbox_enabled:
            return True
        try:
            from capability_system.tools.validators import validate_shell_read_only
        except Exception:
            return False, "shell safety validator unavailable"
        return validate_shell_read_only(operation_input)

    return _validate


def _normalize_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def _normalize_workspace_path(value: Any, *, workspace_root: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(workspace_root.resolve()).as_posix() or "."
        except ValueError:
            return ""
    return _normalize_relative_path(text)

