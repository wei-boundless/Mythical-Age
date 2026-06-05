from __future__ import annotations

from pathlib import Path
import re
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


def session_scoped_environment_storage_space(
    environment_payload: dict[str, Any],
    *,
    session_id: str,
) -> dict[str, Any]:
    """Resolve the runtime artifact defaults for a concrete session.

    This is a default placement policy, not a write restriction. User-requested
    project paths remain project paths; only environment-owned runtime artifacts
    and scratch/cache directories are rooted here.
    """

    environment = dict(environment_payload or {})
    storage = dict(environment.get("storage_space") or {})
    session_segment = _safe_path_segment(session_id, fallback="session")
    namespace = normalize_logical_path(storage.get("storage_namespace")) or _environment_namespace(environment)
    if not namespace:
        namespace = "general/workspace"
    root = normalize_logical_path(f"mythical-agent/sessions/{session_segment}/environments/{namespace}")
    resolved = {
        **storage,
        "environment_storage_root": root,
        "runtime_state_root": f"{root}/runtime_state",
        "artifact_root": f"{root}/artifacts",
        "cache_root": f"{root}/cache",
        "task_library_root": f"{root}/task_library",
        "authority": "harness.runtime.session_scoped_environment_storage",
    }
    return {key: value for key, value in resolved.items() if value not in ("", None, [], {}, ())}


def apply_session_scoped_environment_storage(
    environment_payload: dict[str, Any],
    *,
    session_id: str,
) -> dict[str, Any]:
    payload = dict(environment_payload or {})
    payload["storage_space"] = session_scoped_environment_storage_space(payload, session_id=session_id)
    return payload


def _environment_namespace(environment_payload: dict[str, Any]) -> str:
    resource = dict(environment_payload.get("resource_space") or {})
    namespace = normalize_logical_path(resource.get("storage_namespace"))
    if namespace:
        return namespace
    environment_id = str(environment_payload.get("environment_id") or environment_payload.get("requested_environment_id") or "").strip()
    if not environment_id:
        return ""
    return normalize_logical_path(environment_id.replace(".", "/"))


def _safe_path_segment(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    return safe[:96] or fallback


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
