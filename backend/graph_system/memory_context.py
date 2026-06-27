from __future__ import annotations

from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, normalize_artifact_ref

from .models import ExecutableGraphConfig, GraphLoopState, safe_id, stable_hash


class GraphMemoryContextResolutionError(RuntimeError):
    """Raised when a graph memory read contract cannot be satisfied."""

    def __init__(
        self,
        *,
        reason: str,
        node_id: str,
        work_order_id: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = str(reason or "").strip() or "memory_context_resolution_failed"
        self.node_id = str(node_id or "").strip()
        self.work_order_id = str(work_order_id or "").strip()
        self.details = dict(details or {})


class MemoryContextAssembler:
    """Resolve graph memory read contracts into model-visible snapshots."""

    authority = "graph_system.memory_context_assembler"

    def __init__(self, *, services: Any | None = None) -> None:
        self._services = services

    def resolve_for_node(
        self,
        *,
        graph_config: ExecutableGraphConfig,
        state: GraphLoopState,
        node: dict[str, Any],
        work_order_id: str,
        read_protocols: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        node_id = str(node.get("node_id") or "").strip()
        protocols = [
            item
            for item in (
                _normalize_read_protocol(raw, graph_config=graph_config)
                for raw in list(read_protocols or [])
                if isinstance(raw, dict)
            )
            if item
        ]
        if not protocols:
            return {
                "resolved_snapshots": [],
                "memory_receipt_refs": [],
                "diagnostics": {
                    "read_protocol_count": 0,
                    "resolved_record_count": 0,
                    "authority": self.authority,
                },
                "authority": self.authority,
            }
        service = getattr(self._services, "formal_memory_service", None) if self._services is not None else None
        if service is None:
            raise GraphMemoryContextResolutionError(
                reason="formal_memory_service_unavailable",
                node_id=node_id,
                work_order_id=work_order_id,
                message="Graph memory read contract requires formal_memory_service",
                details={
                    "read_protocol_count": len(protocols),
                    "authority": self.authority,
                },
            )

        runtime_scope = _runtime_scope(graph_config=graph_config, state=state)
        selection = service.select_for_node(
            read_edges=[_formal_memory_read_edge(item) for item in protocols],
            task_run_id=state.task_run_id,
            node_run_id=work_order_id,
            clock=f"graph:{state.graph_run_id}",
            clock_seq=_graph_clock_seq(state),
            limit=_max_read_limit(protocols),
            runtime_scope=runtime_scope,
        )
        missing = [dict(item) for item in list(dict(selection or {}).get("missing_required_records") or []) if isinstance(item, dict)]
        blocking_missing = [item for item in missing if _missing_record_blocks(item)]
        if blocking_missing:
            first = blocking_missing[0]
            raise GraphMemoryContextResolutionError(
                reason="missing_required_records",
                node_id=node_id,
                work_order_id=work_order_id,
                message=(
                    "Graph memory read contract could not resolve required records: "
                    f"{first.get('edge_id') or node_id}:{first.get('reason') or 'missing_required_records'}"
                ),
                details={
                    "read_protocol_count": len(protocols),
                    "missing_record_count": len(missing),
                    "missing_required_records": blocking_missing,
                    "runtime_scope": _public_runtime_scope(runtime_scope),
                    "authority": self.authority,
                },
            )
        records = [dict(item) for item in list(dict(selection or {}).get("required_records") or []) if isinstance(item, dict)]
        snapshots = _snapshots_from_selection(
            graph_config=graph_config,
            state=state,
            node_id=node_id,
            work_order_id=work_order_id,
            protocols=protocols,
            records=records,
            selection=dict(selection or {}),
        )
        return {
            "resolved_snapshots": snapshots,
            "memory_receipt_refs": [
                {"read_log_id": str(item), "authority": "formal_memory.read_log"}
                for item in list(dict(selection or {}).get("read_log_ids") or [])
                if str(item)
            ],
            "diagnostics": {
                "read_protocol_count": len(protocols),
                "resolved_record_count": len(records),
                "missing_record_count": len(missing),
                "missing_required_records": missing,
                "runtime_scope": _public_runtime_scope(runtime_scope),
                "authority": self.authority,
            },
            "authority": self.authority,
        }


def _normalize_read_protocol(raw: dict[str, Any], *, graph_config: ExecutableGraphConfig) -> dict[str, Any]:
    edge = dict(raw or {})
    metadata = dict(edge.get("metadata") or {})
    selector = dict(edge.get("selector") or metadata.get("selector") or {})
    bindings = dict(edge.get("contract_bindings") or {})
    memory_binding = dict(bindings.get("memory") or {})
    working_policy = dict(edge.get("working_memory_handoff_policy") or {})
    operation = str(
        edge.get("operation")
        or memory_binding.get("operation")
        or working_policy.get("operation")
        or edge.get("memory_edge_type")
        or metadata.get("memory_edge_type")
        or ""
    ).strip()
    edge_type = str(edge.get("edge_type") or metadata.get("edge_type") or "").strip()
    if edge_type == "memory_read":
        operation = "read"
    if operation not in {"read", "memory_read"}:
        return {}
    repository = str(
        edge.get("repository")
        or edge.get("repository_id")
        or edge.get("repository_node_id")
        or memory_binding.get("repository")
        or memory_binding.get("repository_id")
        or memory_binding.get("repository_node_id")
        or working_policy.get("repository")
        or working_policy.get("repository_node_id")
        or metadata.get("repository")
        or metadata.get("repository_id")
        or metadata.get("repository_node_id")
        or edge.get("source_node_id")
        or ""
    ).strip()
    repository = _logical_repository_id(repository, graph_config=graph_config)
    collection = str(
        edge.get("collection")
        or edge.get("collection_id")
        or memory_binding.get("collection")
        or working_policy.get("collection")
        or metadata.get("collection")
        or selector.get("collection")
        or ""
    ).strip()
    record_kinds = _strings(
        edge.get("record_kinds")
        or memory_binding.get("record_kinds")
        or memory_binding.get("topics")
        or working_policy.get("record_kinds")
        or working_policy.get("topics")
        or metadata.get("record_kinds")
        or selector.get("record_kinds")
        or selector.get("record_kind")
    )
    normalized_selector = {
        **selector,
        **({"collection": collection} if collection else {}),
        **({"record_key": str(edge.get("record_key") or metadata.get("record_key") or selector.get("record_key") or "").strip()} if str(edge.get("record_key") or metadata.get("record_key") or selector.get("record_key") or "").strip() else {}),
        **({"record_kinds": record_kinds} if record_kinds else {}),
    }
    return _drop_empty(
        {
            **edge,
            "edge_id": str(edge.get("edge_id") or "").strip(),
            "edge_type": "memory_read",
            "operation": "read",
            "source_node_id": str(edge.get("source_node_id") or "").strip(),
            "target_node_id": str(edge.get("target_node_id") or "").strip(),
            "repository": repository,
            "repository_id": repository,
            "collection": collection,
            "collection_id": collection,
            "selector": normalized_selector,
            "version_selector": str(edge.get("version_selector") or metadata.get("version_selector") or selector.get("version_selector") or "").strip(),
            "on_missing": str(edge.get("on_missing") or metadata.get("on_missing") or selector.get("on_missing") or "").strip(),
            "model_visible_label": str(edge.get("model_visible_label") or metadata.get("model_visible_label") or memory_binding.get("model_visible_label") or working_policy.get("model_visible_label") or "").strip(),
            "usage_instruction": str(edge.get("usage_instruction") or metadata.get("usage_instruction") or "").strip(),
            "lifecycle_policy": dict(edge.get("lifecycle_policy") or edge.get("resource_lifecycle_policy") or metadata.get("lifecycle_policy") or metadata.get("resource_lifecycle_policy") or {}),
            "resource_lifecycle_policy": dict(edge.get("resource_lifecycle_policy") or edge.get("lifecycle_policy") or metadata.get("resource_lifecycle_policy") or metadata.get("lifecycle_policy") or {}),
            "content_requirement": dict(edge.get("content_requirement") or metadata.get("content_requirement") or metadata.get("memory_content_requirement") or {}),
            "authority": "graph_system.memory_read_contract",
        }
    )


def _formal_memory_read_edge(protocol: dict[str, Any]) -> dict[str, Any]:
    selector = dict(protocol.get("selector") or {})
    return {
        **dict(protocol),
        "repository": str(protocol.get("repository") or protocol.get("repository_id") or "").strip(),
        "repository_id": str(protocol.get("repository") or protocol.get("repository_id") or "").strip(),
        "collection": str(protocol.get("collection") or protocol.get("collection_id") or selector.get("collection") or "").strip(),
        "collection_id": str(protocol.get("collection") or protocol.get("collection_id") or selector.get("collection") or "").strip(),
        "selector": selector,
        "lifecycle_policy": dict(protocol.get("lifecycle_policy") or protocol.get("resource_lifecycle_policy") or {}),
        "content_requirement": dict(protocol.get("content_requirement") or {}),
    }


def _snapshots_from_selection(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node_id: str,
    work_order_id: str,
    protocols: list[dict[str, Any]],
    records: list[dict[str, Any]],
    selection: dict[str, Any],
) -> list[dict[str, Any]]:
    records_by_edge: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        edge_id = str(record.get("read_edge_id") or "").strip()
        records_by_edge.setdefault(edge_id, []).append(_model_visible_record(record))
    snapshots: list[dict[str, Any]] = []
    read_log_by_edge = {
        str(item.get("edge_id") or ""): dict(item)
        for item in list(selection.get("read_logs") or [])
        if isinstance(item, dict)
    }
    for protocol in protocols:
        edge_id = str(protocol.get("edge_id") or "").strip()
        edge_records = records_by_edge.get(edge_id, [])
        read_log = read_log_by_edge.get(edge_id, {})
        snapshots.append(
            {
                "snapshot_id": "memsnap:"
                + safe_id(
                    stable_hash(
                        [
                            state.graph_run_id,
                            node_id,
                            work_order_id,
                            edge_id,
                            [item.get("version_id") for item in edge_records],
                        ]
                    )[:24]
                ),
                "graph_id": graph_config.graph_id,
                "node_id": node_id,
                "edge_id": edge_id,
                "logical_repository_id": str(protocol.get("repository") or protocol.get("repository_id") or ""),
                "collection_id": str(protocol.get("collection") or protocol.get("collection_id") or ""),
                "record_count": len(edge_records),
                "records": edge_records,
                "read_log_id": str(read_log.get("read_log_id") or ""),
                "model_visible_label": str(protocol.get("model_visible_label") or ""),
                "usage_instruction": str(protocol.get("usage_instruction") or ""),
                "summary": _snapshot_summary(protocol=protocol, records=edge_records),
                "authority": "graph_system.resolved_memory_snapshot",
            }
        )
    return snapshots


def _model_visible_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record or {})
    return _drop_empty(
        {
            "record_id": str(payload.get("record_id") or ""),
            "version_id": str(payload.get("version_id") or ""),
            "record_key": str(payload.get("record_key") or ""),
            "record_kind": str(payload.get("record_kind") or ""),
            "status": str(payload.get("status") or ""),
            "canonical_text": str(payload.get("canonical_text") or ""),
            "summary": str(payload.get("summary") or ""),
            "artifact_refs": [
                artifact_ref_value(item)
                for item in dedupe_artifact_refs([normalize_artifact_ref(ref) for ref in list(payload.get("artifact_refs") or [])])
                if artifact_ref_value(item)
            ],
            "model_visible_label": str(payload.get("model_visible_label") or ""),
            "usage_instruction": str(payload.get("usage_instruction") or ""),
            "content_warnings": [dict(item) for item in list(payload.get("content_warnings") or []) if isinstance(item, dict)],
            "authority": "formal_memory.resolved_record.model_visible",
        }
    )


def _snapshot_summary(*, protocol: dict[str, Any], records: list[dict[str, Any]]) -> str:
    label = str(protocol.get("model_visible_label") or protocol.get("collection") or protocol.get("edge_id") or "memory").strip()
    if not records:
        return f"{label}: 当前未解析到可见记录。"
    return f"{label}: 已解析 {len(records)} 条授权记忆记录。"


def _logical_repository_id(repository: str, *, graph_config: ExecutableGraphConfig) -> str:
    raw = str(repository or "").strip()
    if not raw:
        return ""
    resource = _resource_node_by_id(graph_config, raw)
    if not resource:
        return raw
    metadata = dict(resource.get("metadata") or {})
    memory_repository = dict(metadata.get("memory_repository") or {})
    return str(
        memory_repository.get("repository_id")
        or metadata.get("repository_id")
        or resource.get("repository_id")
        or raw
    ).strip() or raw


def _resource_node_by_id(graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    target = str(node_id or "").strip()
    for item in [*list(graph_config.nodes), *list(dict(graph_config.resources or {}).get("resource_nodes") or [])]:
        if not isinstance(item, dict):
            continue
        if target in {str(item.get("node_id") or ""), str(item.get("resource_id") or "")}:
            return dict(item)
    return {}


def _runtime_scope(*, graph_config: ExecutableGraphConfig, state: GraphLoopState) -> dict[str, Any]:
    return {
        **dict(dict(graph_config.environment or {}).get("runtime_scope") or {}),
        **dict(dict(state.diagnostics or {}).get("runtime_scope") or {}),
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "graph_id": graph_config.graph_id,
        "graph_run_id": state.graph_run_id,
        "task_run_id": state.task_run_id,
        "authority": "graph_system.memory_context_runtime_scope",
    }


def _graph_clock_seq(state: GraphLoopState) -> int:
    return max(0, int(state.event_cursor or 0) + 1)


def _max_read_limit(protocols: list[dict[str, Any]]) -> int:
    limits: list[int] = []
    for protocol in protocols:
        selector = dict(protocol.get("selector") or {})
        for value in (selector.get("limit"), protocol.get("limit"), dict(protocol.get("snapshot_budget") or {}).get("default_max_records")):
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                limits.append(number)
    return max(limits or [50])


def _missing_record_blocks(item: dict[str, Any]) -> bool:
    on_missing = str(item.get("on_missing") or "").strip()
    reason = str(item.get("reason") or "").strip()
    if reason in {"missing_repository_or_collection", "formal_memory_scope_resolution_failed"}:
        return True
    return on_missing in {"block", "required", "fail_closed"}


def _public_runtime_scope(runtime_scope: dict[str, Any]) -> dict[str, Any]:
    return {
        key: runtime_scope.get(key)
        for key in ("task_environment_id", "project_id", "scope_id", "memory_namespace_id")
        if runtime_scope.get(key)
    }


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}
