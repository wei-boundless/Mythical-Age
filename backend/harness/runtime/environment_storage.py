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


def execution_scoped_environment_storage_space(
    environment_payload: dict[str, Any],
    *,
    session_id: str,
    execution_isolation: dict[str, Any],
    task_run_id: str = "",
) -> dict[str, Any]:
    """Resolve runtime-owned storage for an isolated TaskThread.

    Session scoped storage remains the interactive-turn default. Once a task has
    an execution capsule, runtime-owned state, artifacts, cache, and memory
    candidates must be rooted under the task thread or graph node attempt so
    siblings cannot write into the same namespace by accident.
    """

    isolation = dict(execution_isolation or {})
    if not _valid_execution_isolation(isolation):
        return session_scoped_environment_storage_space(environment_payload, session_id=session_id)
    environment = dict(environment_payload or {})
    storage = dict(environment.get("storage_space") or {})
    namespace = normalize_logical_path(storage.get("storage_namespace")) or _environment_namespace(environment)
    if not namespace:
        namespace = "general/workspace"
    root = _execution_storage_root(
        namespace=namespace,
        session_id=session_id,
        task_run_id=task_run_id,
        isolation=isolation,
    )
    resolved = {
        **storage,
        "environment_storage_root": root,
        "runtime_state_root": f"{root}/runtime_state",
        "artifact_root": f"{root}/artifacts",
        "cache_root": f"{root}/cache",
        "task_library_root": f"{root}/task_library",
        "memory_candidate_root": f"{root}/memory_candidates",
        "storage_scope": _execution_storage_scope(isolation),
        "task_run_id": str(task_run_id or ""),
        "task_thread_id": str(isolation.get("task_thread_id") or ""),
        "task_group_id": str(isolation.get("task_group_id") or ""),
        "capsule_id": str(isolation.get("capsule_id") or ""),
        "lease_id": str(isolation.get("lease_id") or ""),
        "artifact_namespace": str(isolation.get("artifact_namespace") or ""),
        "memory_namespace": str(isolation.get("memory_namespace") or ""),
        "authority": "harness.runtime.execution_scoped_environment_storage",
    }
    return {key: value for key, value in resolved.items() if value not in ("", None, [], {}, ())}


def apply_execution_scoped_environment_storage(
    environment_payload: dict[str, Any],
    *,
    session_id: str,
    execution_isolation: dict[str, Any],
    task_run_id: str = "",
) -> dict[str, Any]:
    payload = dict(environment_payload or {})
    payload["storage_space"] = execution_scoped_environment_storage_space(
        payload,
        session_id=session_id,
        execution_isolation=execution_isolation,
        task_run_id=task_run_id,
    )
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


def _valid_execution_isolation(isolation: dict[str, Any]) -> bool:
    return all(
        str(isolation.get(key) or "").strip()
        for key in ("capsule_id", "lease_id", "task_thread_id")
    )


def _execution_storage_scope(isolation: dict[str, Any]) -> str:
    if str(isolation.get("graph_run_id") or "").strip() or str(isolation.get("graph_node_id") or "").strip() or str(isolation.get("task_group_id") or "").startswith("taskgroup:graph:"):
        return "graph_node_attempt"
    return "task_thread"


def _execution_storage_root(
    *,
    namespace: str,
    session_id: str,
    task_run_id: str,
    isolation: dict[str, Any],
) -> str:
    clean_namespace = normalize_logical_path(namespace) or "general/workspace"
    task_group_id = str(isolation.get("task_group_id") or "").strip()
    graph_run_id = str(isolation.get("graph_run_id") or "").strip()
    graph_node_id = str(isolation.get("graph_node_id") or "").strip()
    graph_work_order_id = str(isolation.get("graph_work_order_id") or "").strip()
    worker_policy = dict(isolation.get("worker_policy") or {}) if isinstance(isolation.get("worker_policy"), dict) else {}
    if not graph_run_id:
        graph_run_id = str(worker_policy.get("graph_run_id") or "").strip()
    if not graph_node_id:
        graph_node_id = str(worker_policy.get("node_id") or worker_policy.get("graph_node_id") or "").strip()
    if not graph_work_order_id:
        graph_work_order_id = str(worker_policy.get("work_order_id") or worker_policy.get("graph_work_order_id") or "").strip()
    if task_group_id.startswith("taskgroup:graph:") or graph_run_id or graph_node_id:
        group_segment = _safe_path_segment(task_group_id or graph_run_id, fallback="graph_group")
        node_segment = _safe_path_segment(graph_node_id, fallback="node")
        attempt_segment = _safe_path_segment(
            str(isolation.get("attempt_id") or graph_work_order_id or task_run_id or isolation.get("capsule_id") or ""),
            fallback="attempt",
        )
        return normalize_logical_path(
            f"mythical-agent/task-groups/{group_segment}/nodes/{node_segment}/attempts/{attempt_segment}/environments/{clean_namespace}"
        )
    thread_segment = _safe_path_segment(isolation.get("task_thread_id"), fallback="task_thread")
    task_segment = _safe_path_segment(task_run_id, fallback=_safe_path_segment(session_id, fallback="task_run"))
    return normalize_logical_path(
        f"mythical-agent/task-threads/{thread_segment}/task-runs/{task_segment}/environments/{clean_namespace}"
    )


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
