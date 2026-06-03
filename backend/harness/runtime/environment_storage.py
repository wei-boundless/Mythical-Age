from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_scope import normalize_logical_path


ENVIRONMENT_STORAGE_DIR_KEYS = (
    "environment_storage_root",
    "runtime_state_root",
    "artifact_root",
    "cache_root",
    "task_library_root",
)


def ensure_environment_storage_dirs(*, project_root: Path, storage_space: dict[str, Any]) -> list[str]:
    root = Path(project_root).resolve()
    created_or_existing: list[str] = []
    for key in ENVIRONMENT_STORAGE_DIR_KEYS:
        logical_path = normalize_logical_path(str(dict(storage_space or {}).get(key) or ""))
        if not logical_path:
            continue
        target = (root / logical_path).resolve()
        if not _is_inside(target, root):
            continue
        target.mkdir(parents=True, exist_ok=True)
        created_or_existing.append(logical_path)
    return created_or_existing


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
