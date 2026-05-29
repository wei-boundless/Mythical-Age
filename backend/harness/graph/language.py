from __future__ import annotations

from typing import Any


RESOURCE_NODE_TYPES = {
    "memory",
    "memory_resource",
    "memory_repository",
    "memory_collection",
    "artifact_repository",
    "thread_ledger",
    "progress_ledger",
    "issue_ledger",
    "runtime_state_store",
    "working_memory_store",
}

EXECUTABLE_MEMORY_NODE_TYPES = {"memory_commit", "memory_finalize"}

MEMORY_EDGE_TYPES = {"memory_read", "memory_write", "memory_write_candidate", "memory_commit", "memory_handoff"}
ARTIFACT_EDGE_TYPES = {"artifact_read", "artifact_write", "artifact_context", "artifact_commit"}
FILE_EDGE_TYPES = {"file_read", "file_write", "file_context", "file_commit"}
REVISION_EDGE_TYPES = {"revision_request", "review_feedback", "repair_feedback", "conditional_feedback", "repair_route"}
EVENT_EDGE_TYPES = {"event", "event_emit", "event_subscribe", "event_notify"}
AUDIT_EDGE_TYPES = {"audit", "audit_report", "audit_observation"}
DEPENDENCY_EDGE_TYPES = {
    "handoff",
    "structured_handoff",
    "control",
    "gate",
    "gate_pass",
    "barrier",
    "temporal_dependency",
    "temporal_after",
    "phase_dependency",
    "sequence_dependency",
}

KNOWN_EDGE_TYPES = (
    MEMORY_EDGE_TYPES
    | ARTIFACT_EDGE_TYPES
    | FILE_EDGE_TYPES
    | REVISION_EDGE_TYPES
    | EVENT_EDGE_TYPES
    | AUDIT_EDGE_TYPES
    | DEPENDENCY_EDGE_TYPES
)

EDGE_SEMANTIC_ROLES = {"control", "memory", "artifact", "file", "revision", "event", "audit", "extension"}
EDGE_SCHEDULER_ROLES = {"dependency", "conditional_dependency", "context", "commit", "event", "audit", "none"}


def harness_edge_semantic_role(*, edge_type: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = dict(metadata or {})
    explicit = str(
        metadata.get("harness_semantic_role")
        or metadata.get("graph_semantic_role")
        or metadata.get("edge_semantic_role")
        or ""
    ).strip()
    if explicit:
        _validate_role("semantic_role", explicit, EDGE_SEMANTIC_ROLES)
        return explicit
    normalized = str(edge_type or "").strip()
    if normalized in MEMORY_EDGE_TYPES:
        return "memory"
    if normalized in ARTIFACT_EDGE_TYPES:
        return "artifact"
    if normalized in FILE_EDGE_TYPES:
        return "file"
    if normalized in REVISION_EDGE_TYPES:
        return "revision"
    if normalized in EVENT_EDGE_TYPES:
        return "event"
    if normalized in AUDIT_EDGE_TYPES:
        return "audit"
    if normalized in DEPENDENCY_EDGE_TYPES:
        return "control"
    raise ValueError(f"unknown graph edge_type requires explicit extension semantic_role: {normalized}")


def harness_edge_scheduler_role(*, edge_type: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = dict(metadata or {})
    explicit = str(metadata.get("scheduler_role") or metadata.get("harness_scheduler_role") or "").strip()
    if explicit:
        _validate_role("scheduler_role", explicit, EDGE_SCHEDULER_ROLES)
        return explicit
    normalized = str(edge_type or "").strip()
    if normalized in DEPENDENCY_EDGE_TYPES:
        return "dependency"
    if normalized in REVISION_EDGE_TYPES:
        return "conditional_dependency"
    if normalized in {"memory_read", "memory_handoff", "artifact_read", "artifact_context", "file_read", "file_context"}:
        return "context"
    if normalized in {
        "memory_commit",
        "memory_write",
        "memory_write_candidate",
        "artifact_write",
        "artifact_commit",
        "file_write",
        "file_commit",
    }:
        return "commit"
    if normalized in EVENT_EDGE_TYPES:
        return "event"
    if normalized in AUDIT_EDGE_TYPES:
        return "audit"
    raise ValueError(f"unknown graph edge_type requires explicit scheduler_role=none: {normalized}")


def validate_harness_edge_config(edge: dict[str, Any], *, nodes_by_id: dict[str, dict[str, Any]] | None = None) -> None:
    edge_id = str(edge.get("edge_id") or "").strip()
    source_node_id = str(edge.get("source_node_id") or "").strip()
    target_node_id = str(edge.get("target_node_id") or "").strip()
    edge_type = str(edge.get("edge_type") or "").strip()
    semantic_role = str(edge.get("semantic_role") or "").strip()
    scheduler_role = str(edge.get("scheduler_role") or "").strip()
    label = edge_id or f"{source_node_id}->{target_node_id}" or "<unknown>"
    if not edge_id:
        raise ValueError("GraphHarnessConfig edge requires edge_id")
    if not source_node_id:
        raise ValueError(f"GraphHarnessConfig edge requires source_node_id: {label}")
    if not target_node_id:
        raise ValueError(f"GraphHarnessConfig edge requires target_node_id: {label}")
    if not edge_type:
        raise ValueError(f"GraphHarnessConfig edge requires edge_type: {label}")
    _validate_role(f"edge semantic_role for {label}", semantic_role, EDGE_SEMANTIC_ROLES)
    _validate_role(f"edge scheduler_role for {label}", scheduler_role, EDGE_SCHEDULER_ROLES)
    if edge_type not in KNOWN_EDGE_TYPES and not (semantic_role == "extension" and scheduler_role == "none"):
        raise ValueError(f"GraphHarnessConfig unknown edge_type must be explicit extension/none: {label}")
    if nodes_by_id is not None:
        if source_node_id not in nodes_by_id:
            raise ValueError(f"GraphHarnessConfig edge source node not found: {label}")
        if target_node_id not in nodes_by_id:
            raise ValueError(f"GraphHarnessConfig edge target node not found: {label}")


def edge_is_scheduler_dependency(edge: dict[str, Any], *, nodes_by_id: dict[str, dict[str, Any]]) -> bool:
    scheduler_role = str(edge.get("scheduler_role") or "").strip()
    _validate_role("scheduler_role", scheduler_role, EDGE_SCHEDULER_ROLES)
    if scheduler_role == "dependency":
        return True
    if scheduler_role == "commit":
        return _commit_edge_targets_commit_executor(edge=edge, nodes_by_id=nodes_by_id)
    return False


def _commit_edge_targets_commit_executor(*, edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> bool:
    target_node = nodes_by_id.get(str(edge.get("target_node_id") or "")) or {}
    target_type = str(target_node.get("node_type") or "").strip()
    return target_type in EXECUTABLE_MEMORY_NODE_TYPES


def _validate_role(label: str, value: str, allowed: set[str]) -> None:
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise ValueError(f"unsupported graph edge {label}: {normalized}")
