from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactNamespace:
    namespace_id: str
    storage_owner: str
    durability_class: str
    retention_tier: str
    protected_reason: str = ""
    storage_root: str = ""
    scope_kind: str = ""
    scope_id: str = ""
    authority: str = "artifact_system.namespace_policy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_artifact_namespace(
    *,
    logical_repository_id: str,
    task_run_id: str = "",
    graph_id: str = "",
    graph_run_id: str = "",
    artifact_root: str = "",
    lifecycle_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactNamespace:
    policy = dict(lifecycle_policy or {})
    meta = dict(metadata or {})
    root = _normalize_logical_path(artifact_root)
    explicit_durability = str(
        policy.get("durability_class")
        or policy.get("durability")
        or meta.get("durability_class")
        or ""
    ).strip()
    storage_owner = str(policy.get("storage_owner") or meta.get("storage_owner") or "").strip()
    namespace_id = str(policy.get("namespace_id") or meta.get("namespace_id") or "").strip()
    scope_kind = str(policy.get("scope_kind") or policy.get("scope") or "").strip()
    scope_id = str(policy.get("scope_id") or meta.get("scope_id") or "").strip()

    graph_task_instance_id = _graph_task_instance_id(root) or str(meta.get("graph_task_instance_id") or "").strip()
    if graph_task_instance_id:
        storage_owner = storage_owner or "graph_task_instance"
        namespace_id = namespace_id or f"graph_task_instance:{_safe_id(graph_task_instance_id)}"
        scope_kind = scope_kind or "project_scoped"
        scope_id = scope_id or graph_task_instance_id
    elif graph_run_id:
        storage_owner = storage_owner or _storage_owner_from_root(root)
        namespace_id = namespace_id or f"graph_run:{_safe_id(graph_run_id)}"
        scope_kind = scope_kind or "run_scoped"
        scope_id = scope_id or graph_run_id
    elif task_run_id:
        storage_owner = storage_owner or _storage_owner_from_root(root)
        namespace_id = namespace_id or f"task_run:{_safe_id(task_run_id)}"
        scope_kind = scope_kind or "run_scoped"
        scope_id = scope_id or task_run_id
    else:
        storage_owner = storage_owner or _storage_owner_from_root(root)
        namespace_id = namespace_id or f"repository:{_safe_id(logical_repository_id or 'default')}"
        scope_kind = scope_kind or "durable"
        scope_id = scope_id or logical_repository_id or "default"

    durability_class = _normalize_durability_class(explicit_durability) or _durability_from_root(
        root,
        storage_owner=storage_owner,
    )
    retention_tier = str(policy.get("retention_tier") or meta.get("retention_tier") or "").strip()
    retention_tier = retention_tier or retention_tier_for_durability(durability_class)
    protected_reason = str(policy.get("protected_reason") or meta.get("protected_reason") or "").strip()
    protected_reason = protected_reason or _protected_reason_for_durability(durability_class, storage_owner=storage_owner)

    return ArtifactNamespace(
        namespace_id=namespace_id,
        storage_owner=storage_owner,
        durability_class=durability_class,
        retention_tier=retention_tier,
        protected_reason=protected_reason,
        storage_root=root,
        scope_kind=scope_kind,
        scope_id=scope_id,
    )


def retention_tier_for_durability(durability_class: str) -> str:
    durability = _normalize_durability_class(durability_class)
    if durability in {"user_asset", "project_artifact"}:
        return "durable_protected"
    if durability == "runtime_fact":
        return "L0_hot"
    if durability == "runtime_artifact":
        return "L2_cold"
    return "L3_rebuildable"


def _durability_from_root(root: str, *, storage_owner: str) -> str:
    normalized = _normalize_logical_path(root).lower()
    if normalized.startswith("storage/graph_task_instances/"):
        if "/runs/" in f"/{normalized}/" and "/artifacts" not in f"/{normalized}/":
            return "runtime_artifact"
        return "project_artifact"
    if normalized.startswith("storage/task_environments/") or normalized.startswith("mythical-agent/sessions/"):
        return "project_artifact"
    if normalized.startswith("storage/generated/"):
        return "runtime_artifact"
    if normalized.startswith("storage/runtime_state/"):
        return "runtime_fact"
    if normalized.startswith("storage/runtime_cache/"):
        return "rebuildable_cache"
    if normalized.startswith("output/"):
        return "diagnostic_artifact"
    if storage_owner == "graph_task_instance":
        return "project_artifact"
    return "project_artifact"


def _storage_owner_from_root(root: str) -> str:
    normalized = _normalize_logical_path(root).lower()
    if normalized.startswith("storage/graph_task_instances/"):
        return "graph_task_instance"
    if normalized.startswith("storage/task_environments/") or normalized.startswith("mythical-agent/sessions/"):
        return "task_environment"
    if normalized.startswith("storage/generated/"):
        return "generated_asset"
    if normalized.startswith("storage/runtime_state/"):
        return "runtime_state"
    if normalized.startswith("storage/runtime_cache/"):
        return "runtime_cache"
    if normalized.startswith("output/"):
        return "diagnostic_output"
    return "workspace"


def _protected_reason_for_durability(durability_class: str, *, storage_owner: str) -> str:
    durability = _normalize_durability_class(durability_class)
    if durability == "user_asset":
        return "user_asset_not_cache"
    if durability == "project_artifact":
        if storage_owner == "graph_task_instance":
            return "graph_task_instance_project_artifact"
        return "project_artifact_not_cache"
    if durability == "runtime_fact":
        return "runtime_fact_governed_by_runtime_policy"
    return ""


def _normalize_durability_class(value: str) -> str:
    normalized = str(value or "").strip()
    allowed = {
        "user_asset",
        "project_artifact",
        "runtime_artifact",
        "runtime_fact",
        "diagnostic_artifact",
        "rebuildable_cache",
    }
    return normalized if normalized in allowed else ""


def _graph_task_instance_id(root: str) -> str:
    normalized = _normalize_logical_path(root)
    parts = PurePosixPath(normalized).parts
    if len(parts) >= 3 and parts[0] == "storage" and parts[1] == "graph_task_instances":
        return str(parts[2] or "")
    return ""


def _normalize_logical_path(value: Any) -> str:
    normalized = str(value or "").replace("\\", "/").strip().strip("'\"`")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.strip("/")
    if not normalized or normalized == ".":
        return ""
    if "://" in normalized or normalized.startswith(("/", "\\")):
        return ""
    if len(normalized) >= 2 and normalized[1] == ":":
        return ""
    if normalized.startswith("../") or "/../" in f"/{normalized}/":
        return ""
    return normalized


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    return safe.strip("._-")[:160] or "artifact_namespace"
