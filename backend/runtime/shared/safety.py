from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system.workspace_file_service import WorkspaceFileService
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
    workspace_files = WorkspaceFileService(root_dir)
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

    write_root_values = list(safety_envelope.get("write_roots") or [])
    if not write_root_values:
        write_root_values = list(safety_envelope.get("default_write_roots") or [])
    write_roots = [
        _normalize_relative_path(item)
        for item in write_root_values
        if _normalize_relative_path(item)
    ]
    forbidden_paths = [
        _normalize_relative_path(item)
        for item in list(safety_envelope.get("forbidden_paths") or [])
        if _normalize_relative_path(item)
    ]
    write_mode = str(safety_envelope.get("write_mode") or "none").strip()

    def _validate(operation_input: dict[str, Any]) -> bool | tuple[bool, str] | OperationGateResult:
        input_payload = dict(operation_input or {})
        operation_id = str(input_payload.get("operation_id") or "").strip()
        args = dict(input_payload.get("args") or {})
        raw_path = str(input_payload.get("path") or args.get("path") or "").strip()
        if not raw_path:
            return True
        normalized = _normalize_relative_path(raw_path)
        if not normalized:
            return False, "filesystem path is required"
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
            if write_mode in {"bounded_create", "scoped_patch"} and write_roots:
                if not any(
                    normalized_candidate == allowed or normalized_candidate.startswith(f"{allowed}/")
                    for allowed in write_roots
                ):
                    return False, f"path outside task write roots: {normalized_candidate}"
        return True

    return _validate


def _shell_validator(*, sandbox_policy: dict[str, Any]):
    sandbox_enabled = bool(sandbox_policy.get("enabled") is True and sandbox_policy.get("sandbox_root"))

    def _validate(operation_input: dict[str, Any]) -> bool | tuple[bool, str] | OperationGateResult:
        if sandbox_enabled:
            return True
        try:
            from capability_system.validators import validate_shell_read_only
        except Exception:
            return False, "shell safety validator unavailable"
        return validate_shell_read_only(operation_input)

    return _validate


def _normalize_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text
