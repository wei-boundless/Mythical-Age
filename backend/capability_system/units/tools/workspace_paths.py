from __future__ import annotations

from pathlib import Path
from typing import Iterable


def workspace_root_for_tool(root_dir: Path) -> Path:
    resolved = Path(root_dir).resolve()
    if resolved.name == "backend" and resolved.parent.exists():
        return resolved.parent.resolve()
    return resolved


def resolve_workspace_path(root_dir: Path, path: str = ".") -> Path:
    workspace_root = workspace_root_for_tool(root_dir)
    normalized = str(path or ".").strip() or "."
    candidate = (workspace_root / normalized).resolve()
    if workspace_root not in candidate.parents and candidate != workspace_root:
        raise ValueError("Path traversal detected.")
    return candidate


def relative_workspace_path(root_dir: Path, path: Path) -> str:
    workspace_root = workspace_root_for_tool(root_dir)
    try:
        return path.resolve().relative_to(workspace_root).as_posix()
    except ValueError:
        return str(path.resolve())


def safe_workspace_roots(root_dir: Path, roots: Iterable[str] | None, defaults: Iterable[str]) -> list[Path]:
    workspace_root = workspace_root_for_tool(root_dir)
    requested = [str(item or "").strip().replace("\\", "/") for item in list(roots or [])]
    if not requested:
        requested = list(defaults)
    safe: list[Path] = []
    seen: set[Path] = set()
    for item in requested:
        if not item or item.startswith("-"):
            continue
        candidate = (workspace_root / item).resolve()
        try:
            candidate.relative_to(workspace_root)
        except ValueError:
            continue
        if not candidate.exists() or candidate in seen:
            continue
        seen.add(candidate)
        safe.append(candidate)
    return safe
