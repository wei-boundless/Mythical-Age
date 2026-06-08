from __future__ import annotations

from pathlib import Path


def normalize_workspace_root(value: object, *, validate_exists: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    root = Path(raw).expanduser().resolve()
    if validate_exists and (not root.exists() or not root.is_dir()):
        raise ValueError("VS Code workspace root must be an existing directory")
    return str(root)


def same_workspace_root(left: object, right: object) -> bool:
    left_root = normalize_workspace_root(left)
    right_root = normalize_workspace_root(right)
    return bool(left_root and right_root and left_root == right_root)
