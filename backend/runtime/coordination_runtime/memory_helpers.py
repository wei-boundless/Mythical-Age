from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from memory_system.working_memory_service import WorkingMemoryService

from .result_helpers import (
    _candidate_from_source_output,
    _extract_source_output_value,
    _first_dict,
    _json_text,
    _refs_from_output_value,
    _scalar_text,
)
from .runtime_payloads import _safe_int


def _artifact_repository_root_for_runtime(root_dir: Any) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "runtime_state":
        return runtime_root.parent / "artifact_repository"
    return runtime_root / "artifact_repository"


def _workspace_root_from_runtime_root(root_dir: Any) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "backend" and runtime_root.parent.exists():
        return runtime_root.parent.resolve()
    if runtime_root.name == "runtime_state" and runtime_root.parent.name == "storage" and runtime_root.parent.parent.exists():
        return runtime_root.parent.parent.resolve()
    if runtime_root.name == "storage" and runtime_root.parent.exists():
        return runtime_root.parent.resolve()
    return runtime_root


def _first_policy_value(policy: dict[str, Any], key: str, default: str) -> str:
    values = [str(item).strip() for item in list(policy.get(key) or []) if str(item).strip()]
    return values[0] if values else str(default or "").strip()


def _formal_memory_only_context(
    *,
    task_run_id: str,
    graph_id: str,
    owner_node_id: str,
    node_run_id: str,
    run_attempt_id: str,
) -> dict[str, Any]:
    return {
        "task_run_id": task_run_id,
        "graph_id": graph_id,
        "owner_node_id": owner_node_id,
        "node_run_id": node_run_id,
        "run_attempt_id": run_attempt_id,
        "read_log_id": "",
        "denied_reason": "",
        "required_refs": [],
        "preferred_refs": [],
        "required_items": [],
        "preferred_items": [],
        "missing_required_records": [],
        "working_memory.required": {"item_count": 0, "refs": [], "items": [], "content_mode": "summary"},
        "working_memory.preferred": {"item_count": 0, "refs": [], "items": [], "content_mode": "summary"},
        "working_memory.artifact_refs": {"item_count": 0, "refs": [], "content_mode": "refs_only"},
        "working_memory.conflict_warnings": {"item_count": 0, "refs": [], "items": [], "content_mode": "summary"},
        "diagnostics": {
            "formal_memory_primary": True,
            "working_memory_legacy_read_enabled": False,
        },
    }


def _working_memory_context_from_selection(
    selection: dict[str, Any],
    *,
    task_run_id: str,
    graph_id: str,
    owner_node_id: str,
    node_run_id: str,
    run_attempt_id: str,
    read_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = dict(read_policy or {})
    required_items = [item for item in list(selection.get("required_items") or []) if hasattr(item, "to_dict")]
    preferred_items = [item for item in list(selection.get("preferred_items") or []) if hasattr(item, "to_dict")]
    excluded_items = [item for item in list(selection.get("excluded_items") or []) if hasattr(item, "to_dict")]
    selection_diagnostics = dict(selection.get("diagnostics") or {})
    required_refs = [str(getattr(item, "work_memory_id", "") or "") for item in required_items if str(getattr(item, "work_memory_id", "") or "")]
    preferred_refs = [str(getattr(item, "work_memory_id", "") or "") for item in preferred_items if str(getattr(item, "work_memory_id", "") or "")]
    conflict_items = [
        item
        for item in [*required_items, *preferred_items]
        if str(getattr(item, "status", "") or "") == "conflicted" or getattr(item, "conflict_refs", ())
    ]
    conflict_refs = [str(getattr(item, "work_memory_id", "") or "") for item in conflict_items if str(getattr(item, "work_memory_id", "") or "")]
    return {
        "task_run_id": task_run_id,
        "graph_id": graph_id,
        "owner_node_id": owner_node_id,
        "node_run_id": node_run_id,
        "run_attempt_id": run_attempt_id,
        "read_log_id": str(selection.get("read_log_id") or ""),
        "denied_reason": str(selection.get("denied_reason") or ""),
        "required_refs": required_refs,
        "preferred_refs": preferred_refs,
        "required_items": [item.to_dict() for item in required_items],
        "preferred_items": [item.to_dict() for item in preferred_items],
        "missing_required_records": list(selection_diagnostics.get("missing_repository_read_edges") or []),
        "working_memory.required": {
            "item_count": len(required_refs),
            "refs": required_refs,
            "items": [item.to_dict() for item in required_items],
            "content_mode": "summary",
        },
        "working_memory.preferred": {
            "item_count": len(preferred_refs),
            "refs": preferred_refs,
            "items": [item.to_dict() for item in preferred_items],
            "content_mode": "summary",
        },
        "working_memory.artifact_refs": {
            "item_count": sum(len(tuple(getattr(item, "artifact_refs", ()) or ())) for item in [*required_items, *preferred_items]),
            "refs": [
                ref
                for item in [*required_items, *preferred_items]
                for ref in list(getattr(item, "artifact_refs", ()) or ())
                if str(ref)
            ],
            "content_mode": "refs_only",
        },
        "working_memory.conflict_warnings": {
            "item_count": len(conflict_refs),
            "refs": conflict_refs,
            "items": [item.to_dict() for item in conflict_items],
            "content_mode": "summary",
        },
        "diagnostics": {
            **selection_diagnostics,
            "requested_topics": [
                str(item).strip()
                for item in list(policy.get("topics") or [])
                if str(item).strip()
            ],
            "required_topics": [
                str(item).strip()
                for item in list(policy.get("required_topics") or [])
                if str(item).strip()
            ],
            "forbidden_topics": [
                str(item).strip()
                for item in list(policy.get("forbidden_topics") or [])
                if str(item).strip()
            ],
            "excluded_refs": [
                str(getattr(item, "work_memory_id", "") or "")
                for item in excluded_items
                if str(getattr(item, "work_memory_id", "") or "")
            ],
        },
    }


def _working_memory_read_operation_from_context(
    *,
    context: dict[str, Any],
    stage_id: str,
    node_id: str,
    agent_id: str,
) -> dict[str, Any]:
    payload = dict(context or {})
    diagnostics = dict(payload.get("diagnostics") or {})
    required = dict(payload.get("working_memory.required") or {})
    preferred = dict(payload.get("working_memory.preferred") or {})
    formal_records = [dict(item) for item in list(payload.get("formal_memory.required_records") or []) if isinstance(item, dict)]
    formal_read_log_ids = [str(item).strip() for item in list(payload.get("formal_memory.read_log_ids") or []) if str(item).strip()]
    selected_refs = [
        *[str(item).strip() for item in list(required.get("refs") or []) if str(item).strip()],
        *[
            str(item).strip()
            for item in list(preferred.get("refs") or [])
            if str(item).strip() and str(item).strip() not in list(required.get("refs") or [])
        ],
    ]
    selected_formal_refs = [
        str(item.get("version_id") or item.get("record_id") or "").strip()
        for item in formal_records
        if str(item.get("version_id") or item.get("record_id") or "").strip()
    ]
    denied_reason = str(payload.get("denied_reason") or "")
    if not selected_refs and not selected_formal_refs and not denied_reason and not str(payload.get("read_log_id") or "") and not formal_read_log_ids:
        return {}
    return {
        "operation": "memory_read",
        "stage_id": stage_id,
        "node_id": node_id,
        "reader_agent_id": agent_id,
        "node_run_id": str(payload.get("node_run_id") or ""),
        "read_log_id": str(payload.get("read_log_id") or ""),
        "formal_memory_read_log_ids": formal_read_log_ids,
        "selected_working_memory_refs": selected_refs,
        "selected_formal_memory_refs": selected_formal_refs,
        "excluded_working_memory_refs": [
            str(item).strip()
            for item in list(diagnostics.get("excluded_refs") or [])
            if str(item).strip()
        ],
        "selected_formal_memory_records": formal_records[:12],
        "selected_item_previews": [
            dict(item)
            for item in list(diagnostics.get("selected_item_previews") or [])
            if isinstance(item, dict)
        ],
        "denied_reason": denied_reason,
        "status": "denied" if denied_reason else "completed",
        "authority": "orchestration.working_memory_resource_node",
    }


def _working_memory_refs_from_context(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for section_id in ("working_memory.required", "working_memory.preferred", "working_memory.conflict_warnings"):
        for ref in list(dict(context.get(section_id) or {}).get("refs") or []):
            if str(ref).strip() and str(ref).strip() not in refs:
                refs.append(str(ref).strip())
    return refs


def _timeline_working_memory_operation(
    operation: dict[str, Any],
    *,
    existing_operations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    payload = dict(operation or {})
    sequence_index = len([item for item in list(existing_operations or []) if isinstance(item, dict)]) + 1
    payload.setdefault("created_at", time.time())
    payload.setdefault("sequence_index", sequence_index)
    payload.setdefault("timeline_kind", "working_memory_operation")
    return payload


def _graph_memory_edge_descriptors(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    operation: str,
    ) -> list[dict[str, Any]]:
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    nodes_by_id = {
        str(item.get("node_id") or item.get("id") or "").strip(): dict(item)
        for item in [
            *[raw for raw in list(graph_spec.get("nodes") or []) if isinstance(raw, dict)],
            *[raw for raw in list(graph_spec.get("resource_nodes") or []) if isinstance(raw, dict)],
        ]
        if isinstance(item, dict) and str(item.get("node_id") or item.get("id") or "").strip()
    }
    descriptors: list[dict[str, Any]] = []
    raw_edges = [
        *[dict(item) for item in list(graph_spec.get("memory_edges") or []) if isinstance(item, dict)],
        *[dict(item) for item in list(graph_spec.get("edges") or []) if isinstance(item, dict)],
    ]
    seen_edges: set[str] = set()
    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        edge = dict(raw)
        edge_id = str(edge.get("edge_id") or "").strip()
        if edge_id and edge_id in seen_edges:
            continue
        if edge_id:
            seen_edges.add(edge_id)
        edge_type = str(edge.get("edge_type") or edge.get("mode") or "").strip()
        metadata = {**edge, **dict(edge.get("metadata") or {})}
        memory_edge_type = str(metadata.get("memory_edge_type") or "").strip()
        normalized_memory_edge_type = memory_edge_type or (edge_type.replace("memory_", "") if edge_type.startswith("memory_") else "")
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if operation == "read":
            if normalized_memory_edge_type != "read" or target not in {stage_id, node_id}:
                continue
        elif operation == "write":
            if normalized_memory_edge_type not in {"write", "write_candidate", "commit"} or source not in {stage_id, node_id}:
                continue
        else:
            continue
        selector = dict(metadata.get("selector") or {})
        record_key = str(metadata.get("record_key") or selector.get("record_key") or "").strip()
        record_kind = str(metadata.get("record_kind") or selector.get("record_kind") or "").strip()
        record_keys = [
            str(item).strip()
            for item in list(metadata.get("record_keys") or selector.get("record_keys") or [])
            if str(item).strip()
        ]
        record_kinds = [
            str(item).strip()
            for item in list(metadata.get("record_kinds") or selector.get("record_kinds") or [])
            if str(item).strip()
        ]
        if record_key and record_key not in record_keys:
            record_keys.insert(0, record_key)
        if record_kind and record_kind not in record_kinds:
            record_kinds.insert(0, record_kind)
        repository_node_id = str(metadata.get("repository_node_id") or "").strip()
        if not repository_node_id:
            if operation == "read" and _is_runtime_memory_repository_node(nodes_by_id.get(source, {})):
                repository_node_id = source
            elif operation == "write" and _is_runtime_memory_repository_node(nodes_by_id.get(target, {})):
                repository_node_id = target
        repository = str(
            metadata.get("repository")
            or metadata.get("repository_id")
            or _repository_id_from_runtime_node(nodes_by_id.get(repository_node_id, {}))
            or repository_node_id
            or ""
        ).strip()
        descriptors.append(
            {
                "edge_id": str(edge.get("edge_id") or "").strip(),
                "edge_type": edge_type,
                "memory_edge_type": normalized_memory_edge_type,
                "source_node_id": source,
                "target_node_id": target,
                "repository": repository,
                "repository_node_id": repository_node_id or repository,
                "collection": str(metadata.get("collection") or selector.get("collection") or "").strip(),
                "record_key": record_key,
                "record_kind": record_kind,
                "record_keys": record_keys,
                "record_kinds": record_kinds,
                "selector": selector,
                "version_selector": metadata.get("version_selector") or selector.get("version_selector") or "",
                "on_missing": str(metadata.get("on_missing") or "").strip(),
                "source_output_key": str(metadata.get("source_output_key") or selector.get("source_output_key") or "").strip(),
                "candidate_ref_key": str(metadata.get("candidate_ref_key") or "").strip(),
                "verdict_key": str(metadata.get("verdict_key") or "").strip(),
                "required_verdict": str(metadata.get("required_verdict") or "").strip(),
                "approval_source_node_id": str(metadata.get("approval_source_node_id") or "").strip(),
                "approval_policy": str(metadata.get("approval_policy") or "").strip(),
                "model_visible_label": str(metadata.get("model_visible_label") or metadata.get("visible_label") or "").strip(),
                "usage_instruction": str(metadata.get("usage_instruction") or metadata.get("instructions") or "").strip(),
                "commit_visibility_policy": dict(
                    metadata.get("commit_visibility_policy")
                    or metadata.get("visibility_policy")
                    or edge.get("commit_visibility_policy")
                    or {}
                ),
            }
        )
    return descriptors


def _graph_edges(state: dict[str, Any]) -> list[dict[str, Any]]:
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    edges: list[dict[str, Any]] = []
    for raw in list(graph_spec.get("edges") or []):
        if not isinstance(raw, dict):
            continue
        edge = dict(raw)
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if not source or not target:
            continue
        edge["source_node_id"] = source
        edge["target_node_id"] = target
        edge.setdefault("edge_id", f"{source}->{target}")
        edges.append(edge)
    return edges


def _matching_commit_edge(*, formal: dict[str, Any], commit_edges: list[dict[str, Any]]) -> dict[str, Any]:
    repository = str(formal.get("repository_id") or formal.get("repository") or "").strip()
    collection = str(formal.get("collection_id") or formal.get("collection") or "").strip()
    record_key = str(formal.get("record_key") or "").strip()
    record_kind = str(formal.get("record_kind") or "").strip()
    for edge in commit_edges:
        selector = dict(edge.get("selector") or {})
        if repository and repository != str(edge.get("repository") or "").strip():
            continue
        if collection and collection != str(edge.get("collection") or "").strip():
            continue
        edge_record_key = str(edge.get("record_key") or selector.get("record_key") or "").strip()
        if record_key and edge_record_key and record_key != edge_record_key:
            continue
        edge_record_kind = str(edge.get("record_kind") or selector.get("record_kind") or "").strip()
        edge_record_kinds = {str(item).strip() for item in list(edge.get("record_kinds") or []) if str(item).strip()}
        if record_kind and edge_record_kind and record_kind != edge_record_kind:
            continue
        if record_kind and edge_record_kinds and record_kind not in edge_record_kinds:
            continue
        return dict(edge)
    return dict(commit_edges[0]) if commit_edges else {}


def _formal_memory_commit_requests(
    *,
    commit_edges: list[dict[str, Any]],
    output_bundle: dict[str, Any],
    accepted_candidate_refs: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    fallback_refs = [str(item).strip() for item in list(accepted_candidate_refs or []) if str(item).strip()]
    for edge in commit_edges:
        candidate_ref_key = str(edge.get("candidate_ref_key") or "").strip()
        verdict_key = str(edge.get("verdict_key") or "").strip()
        required_verdict = str(edge.get("required_verdict") or "").strip()
        verdict = ""
        if verdict_key:
            verdict_extraction = _extract_source_output_value(verdict_key, candidates=[], output_bundle=output_bundle)
            if verdict_extraction.get("found"):
                verdict = _scalar_text(verdict_extraction.get("value"))
            elif required_verdict:
                errors.append(
                    {
                        "edge_id": str(edge.get("edge_id") or ""),
                        "verdict_key": verdict_key,
                        "required_verdict": required_verdict,
                        "error": "verdict_key_not_found",
                    }
                )
                continue
        if required_verdict and verdict and verdict != required_verdict:
            errors.append(
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "verdict_key": verdict_key,
                    "verdict": verdict,
                    "required_verdict": required_verdict,
                    "error": "required_verdict_not_satisfied",
                }
            )
            continue
        if not candidate_ref_key:
            for ref in fallback_refs:
                requests.append(
                    {
                        "candidate_ref": ref,
                        "candidate_version_id": ref,
                        "edge": dict(edge),
                        "verdict": verdict,
                        "required_verdict": required_verdict,
                    }
                )
            continue
        ref_extraction = _extract_source_output_value(candidate_ref_key, candidates=[], output_bundle=output_bundle)
        if not ref_extraction.get("found"):
            errors.append(
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "candidate_ref_key": candidate_ref_key,
                    "error": "candidate_ref_key_not_found",
                }
            )
            continue
        refs = _refs_from_output_value(ref_extraction.get("value"))
        if not refs:
            errors.append(
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "candidate_ref_key": candidate_ref_key,
                    "error": "candidate_ref_empty",
                }
            )
            continue
        for ref in refs:
            requests.append(
                {
                    "candidate_ref": ref,
                    "candidate_version_id": ref,
                    "edge": dict(edge),
                    "verdict": verdict,
                    "required_verdict": required_verdict,
                }
            )
    return requests, errors


def _formal_memory_write_records(
    *,
    candidates: list[dict[str, Any]],
    memory_write_edges: list[dict[str, Any]],
    fallback_write_policy: dict[str, Any],
    output_bundle: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not memory_write_edges:
        return [dict(item) for item in candidates], []
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    fallback_scope = _first_policy_value(fallback_write_policy, "writable_scopes", "node_scope")
    for edge in memory_write_edges:
        record_keys = [str(item).strip() for item in list(edge.get("record_keys") or []) if str(item).strip()]
        record_kinds = [str(item).strip() for item in list(edge.get("record_kinds") or []) if str(item).strip()]
        edge_operation = str(edge.get("memory_edge_type") or "").strip()
        commit_state = "committed" if edge_operation == "commit" else "candidate"
        default_status = "accepted" if commit_state == "committed" else "draft"
        source_output_key = str(edge.get("source_output_key") or "").strip()
        edge_candidates = candidates
        if source_output_key:
            extraction = _extract_source_output_value(
                source_output_key,
                candidates=candidates,
                output_bundle=output_bundle,
            )
            if not extraction.get("found"):
                errors.append(
                    {
                        "edge_id": str(edge.get("edge_id") or ""),
                        "repository_id": str(edge.get("repository") or ""),
                        "collection_id": str(edge.get("collection") or ""),
                        "source_output_key": source_output_key,
                        "error": "source_output_key_not_found",
                        "message": f"memory_write_candidate edge requires source_output_key '{source_output_key}', but the node result did not provide it.",
                    }
                )
                continue
            edge_candidates = [
                _candidate_from_source_output(
                    source_output_key=source_output_key,
                    value=extraction.get("value"),
                    source=str(extraction.get("source") or ""),
                    fallback_candidate=candidates[0] if candidates else {},
                )
            ]
        for index, raw_candidate in enumerate(edge_candidates):
            candidate = dict(raw_candidate)
            candidate_kind = str(candidate.get("kind") or "").strip()
            kind = candidate_kind if (candidate_kind and (not record_kinds or candidate_kind in record_kinds)) else (record_kinds[0] if record_kinds else candidate_kind)
            if not kind:
                kind = _first_policy_value(fallback_write_policy, "writable_kinds", "intermediate_result")
            record_key = str(candidate.get("record_key") or edge.get("record_key") or (record_keys[0] if record_keys else kind)).strip()
            metadata = dict(candidate.get("metadata") or {})
            formal_memory = {
                "repository_id": str(edge.get("repository") or ""),
                "repository_node_id": str(edge.get("repository_node_id") or edge.get("repository") or ""),
                "collection_id": str(edge.get("collection") or ""),
                "record_key": record_key,
                "record_kind": kind,
                "record_kinds": record_kinds,
                "record_keys": record_keys,
                "source_output_key": source_output_key,
                "source_edge_id": str(edge.get("edge_id") or ""),
                "source_edge_type": str(edge.get("edge_type") or ""),
                "memory_edge_type": edge_operation,
                "commit_state": commit_state,
                "approval_source_node_id": str(edge.get("approval_source_node_id") or ""),
                "approval_policy": str(edge.get("approval_policy") or ""),
                "selector": dict(edge.get("selector") or {}),
                "version_selector": str(edge.get("version_selector") or ""),
                "commit_visibility_policy": dict(edge.get("commit_visibility_policy") or {}),
            }
            records.append(
                {
                    **candidate,
                    "kind": kind,
                    "scope": str(candidate.get("scope") or fallback_scope),
                    "status": str(candidate.get("status") or default_status),
                    "visibility": str(candidate.get("visibility") or "shared_in_graph"),
                    "idempotency_key": str(candidate.get("idempotency_key") or f"{edge.get('edge_id')}:{index}:{kind}"),
                    "metadata": {
                        **metadata,
                        "formal_memory": formal_memory,
                    },
                }
            )
    return records, errors


def _is_runtime_memory_repository_node(node: dict[str, Any]) -> bool:
    if not node:
        return False
    node_type = str(node.get("node_type") or "").strip()
    node_id = str(node.get("node_id") or node.get("id") or "").strip()
    work_posture = str(node.get("work_posture") or node.get("role") or "").strip()
    return (
        node_type in {"memory_repository", "working_memory_store", "runtime_state_store", "thread_ledger", "progress_ledger", "issue_ledger", "memory_resource", "memory"}
        or (node_type.endswith("repository") and "artifact" not in node_type)
        or (work_posture == "resource" and node_id.startswith("memory."))
        or node_id.startswith("memory.")
    )


def _repository_id_from_runtime_node(node: dict[str, Any]) -> str:
    metadata = dict(node.get("metadata") or {})
    repo_config = dict(metadata.get("memory_repository") or {})
    return str(repo_config.get("repository_id") or metadata.get("repository_id") or node.get("repository_id") or node.get("node_id") or "").strip()


def _filter_working_memory_refs_for_handoff(refs: list[str], policy: dict[str, Any], service: WorkingMemoryService) -> list[str]:
    explicit = [str(item).strip() for item in list(policy.get("working_memory_refs") or []) if str(item).strip()]
    if explicit:
        allowed = set(explicit)
        refs = [ref for ref in refs if ref in allowed]
    carry_kinds = {str(item).strip() for item in list(policy.get("carry_kinds") or []) if str(item).strip()}
    carry_scopes = {str(item).strip() for item in list(policy.get("carry_scopes") or []) if str(item).strip()}
    filtered: list[str] = []
    for ref in refs:
        item = service.get_item(ref)
        if item is None:
            continue
        if carry_kinds and item.kind not in carry_kinds:
            continue
        if carry_scopes and item.scope not in carry_scopes:
            continue
        filtered.append(ref)
    limit = _safe_int(policy.get("limit"), 0)
    selected = [ref for ref in filtered if ref]
    return selected[:limit] if limit > 0 else selected


def _decision_refs(payload: dict[str, Any], *keys: str) -> list[str]:
    refs: list[str] = []
    for key in keys:
        for ref in list(payload.get(key) or []):
            value = str(ref).strip()
            if value and value not in refs:
                refs.append(value)
    return refs


def _stage_working_memory_refs_for_commit(state: CoordinationRuntimeState) -> list[str]:
    refs: list[str] = []
    for result in dict(state.get("stage_results") or {}).values():
        if not isinstance(result, dict):
            continue
        for ref in list(result.get("working_memory_refs") or []):
            value = str(ref).strip()
            if value and value not in refs:
                refs.append(value)
    return refs


def _formal_memory_acknowledgement(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    operation = str(raw.get("operation") or "")
    return {
        "acknowledgement_id": str(raw.get("transaction_id") or ""),
        "transaction_id": str(raw.get("transaction_id") or ""),
        "operation": operation,
        "repository_id": str(raw.get("repository_id") or ""),
        "collection_id": str(raw.get("collection_id") or ""),
        "record_id": str(raw.get("record_id") or ""),
        "record_key": str(raw.get("record_key") or ""),
        "candidate_version_id": str(raw.get("candidate_version_id") or raw.get("version_id") or ""),
        "committed_version_id": str(raw.get("committed_version_id") or ""),
        "version_id": str(raw.get("version_id") or raw.get("candidate_version_id") or raw.get("committed_version_id") or ""),
        "version": int(raw.get("version") or 0),
        "status": str(raw.get("status") or ""),
        "visible_after_clock": str(raw.get("visible_after_clock") or ""),
        "visible_after_clock_seq": int(raw.get("visible_after_clock_seq") or 0),
        "source_clock": str(raw.get("source_clock") or ""),
        "source_clock_seq": int(raw.get("source_clock_seq") or 0),
        "content_hash": str(raw.get("content_hash") or ""),
        "reject_reason": str(raw.get("reject_reason") or ""),
        "authority": "formal_memory.commit_acknowledgement" if operation == "memory_commit" else "formal_memory.write_acknowledgement",
    }
