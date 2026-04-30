from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PATH_KEYS = ("path", "file_path", "target_path", "root", "cwd")
PATH_LIST_KEYS = ("paths", "file_paths", "target_paths")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]")
VARIABLE_RE = re.compile(r"(^|[^\\])(\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%)")


def validate_filesystem_path(operation_input: dict[str, Any]) -> tuple[bool, str]:
    """Conservative workspace path validator for filesystem operations."""

    paths = _extract_paths(operation_input)
    if not paths:
        return False, "filesystem path is missing"
    workspace_root_raw = str(operation_input.get("workspace_root") or "").strip()
    workspace_root = Path(workspace_root_raw).resolve() if workspace_root_raw else None
    for raw_path in paths:
        ok, reason = _validate_single_path(raw_path, workspace_root=workspace_root)
        if not ok:
            return ok, reason
    return True, "filesystem path passed workspace validator"


def _extract_paths(operation_input: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in PATH_KEYS:
        value = operation_input.get(key)
        if value is not None:
            paths.append(str(value))
    for key in PATH_LIST_KEYS:
        value = operation_input.get(key)
        if isinstance(value, (list, tuple)):
            paths.extend(str(item) for item in value)
    return paths


def _validate_single_path(raw_path: str, *, workspace_root: Path | None) -> tuple[bool, str]:
    value = str(raw_path or "").strip()
    if not value:
        return False, "filesystem path is empty"
    if value.startswith("\\\\") or value.startswith("//"):
        return False, "filesystem path uses UNC/network path"
    if "://" in value:
        return False, "filesystem path uses URL syntax"
    if CONTROL_CHARS_RE.search(value):
        return False, "filesystem path contains control characters"
    if VARIABLE_RE.search(value) or value.startswith("~"):
        return False, "filesystem path uses expansion syntax"
    if "*" in value or "?" in value:
        return False, "filesystem path uses glob expansion"

    candidate = Path(value)
    if workspace_root is None:
        if candidate.is_absolute():
            return False, "absolute filesystem path requires workspace_root"
        if ".." in candidate.parts:
            return False, "filesystem path escapes through parent traversal"
        return True, "filesystem path passed relative validator"

    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        return False, "filesystem path is outside workspace_root"
    return True, "filesystem path passed workspace validator"
