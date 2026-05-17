from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def resolve_context_packets(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    explicit_inputs: dict[str, Any],
    working_memory_context: dict[str, Any] | None,
    dispatch_context: dict[str, Any],
) -> dict[str, Any]:
    """Resolve deterministic context packets for one stage dispatch."""

    memory_snapshot = resolve_memory_snapshot(
        working_memory_context=working_memory_context or {},
        dispatch_context=dispatch_context,
        state=state,
        stage_id=stage_id,
        node_id=node_id,
    )
    artifact_packet = resolve_artifact_context_packet(
        state=state,
        stage_id=stage_id,
        node_id=node_id,
        explicit_inputs=explicit_inputs,
        dispatch_context=dispatch_context,
    )
    revision_packet = resolve_revision_packet(
        state=state,
        stage_id=stage_id,
        node_id=node_id,
        dispatch_context=dispatch_context,
    )
    handoff_packets = resolve_handoff_packets(
        state=state,
        stage_id=stage_id,
        node_id=node_id,
        dispatch_context=dispatch_context,
    )
    return {
        "memory_snapshot": memory_snapshot,
        "artifact_context_packet": artifact_packet,
        "revision_packet": revision_packet,
        "handoff_packets": handoff_packets,
        "handoff_packet_refs": [str(item.get("packet_id") or "") for item in handoff_packets if str(item.get("packet_id") or "")],
        "context_packet_summary": {
            "memory_record_count": len(list(memory_snapshot.get("resolved_records") or [])),
            "artifact_ref_count": len(list(artifact_packet.get("artifact_refs") or [])),
            "revision_packet_present": bool(revision_packet),
            "handoff_packet_count": len(handoff_packets),
        },
        "authority": "orchestration.context_packet_resolver",
    }


def resolve_memory_snapshot(
    *,
    working_memory_context: dict[str, Any],
    dispatch_context: dict[str, Any],
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
) -> dict[str, Any]:
    refs = _working_memory_refs_from_context(working_memory_context)
    resolved_records = _working_memory_records_from_context(working_memory_context)
    formal_record_refs = [
        str(item.get("version_id") or item.get("record_id") or "")
        for item in resolved_records
        if str(item.get("authority") or "").startswith("formal_memory")
        and str(item.get("version_id") or item.get("record_id") or "")
    ]
    if not refs:
        refs = [
            str(item.get("work_memory_id") or item.get("version_id") or item.get("record_id") or "")
            for item in resolved_records
            if str(item.get("work_memory_id") or item.get("version_id") or item.get("record_id") or "")
        ]
    read_edge_ids = [
        str(edge.get("edge_id") or "")
        for edge in _graph_edges(state)
        if _edge_targets(edge, stage_id=stage_id, node_id=node_id) and _edge_kind(edge).startswith("memory_")
    ]
    snapshot_id = f"memsnap:{_short_hash({'dispatch': dispatch_context, 'refs': refs, 'stage_id': stage_id})}"
    return {
        "snapshot_id": snapshot_id,
        "dispatch_event_id": str(dispatch_context.get("dispatch_event_id") or ""),
        "clock_seq": int(dispatch_context.get("clock_seq") or 0),
        "scope_path": list(dispatch_context.get("scope_path") or []),
        "stage_id": stage_id,
        "node_id": node_id,
        "read_edge_ids": [item for item in read_edge_ids if item],
        "repository_refs": _repository_refs_for_stage(state=state, stage_id=stage_id, node_id=node_id),
        "repository_read_edges": [dict(item) for item in list(working_memory_context.get("repository_read_edges") or []) if isinstance(item, dict)],
        "resolved_record_refs": refs,
        "resolved_records": resolved_records,
        "formal_memory_record_refs": _dedupe(formal_record_refs),
        "formal_memory_read_log_ids": [
            str(item).strip()
            for item in list(working_memory_context.get("formal_memory.read_log_ids") or [])
            if str(item).strip()
        ],
        "source_counts": {
            "formal_memory": len(formal_record_refs),
            "working_memory": len([ref for ref in refs if ref not in formal_record_refs]),
        },
        "resolved_versions": [
            {
                "record_ref": ref,
                "version_selector": _version_selector_for_record(ref, resolved_records=resolved_records) or "working_memory_selection",
                "visible_at_clock_seq": int(dispatch_context.get("clock_seq") or 0),
            }
            for ref in refs
        ],
        "missing_required_records": list(working_memory_context.get("missing_required_records") or []),
        "read_receipt_id": str(working_memory_context.get("read_log_id") or ""),
        "authority": "task_graph.memory_snapshot",
    }


def resolve_artifact_context_packet(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    explicit_inputs: dict[str, Any],
    dispatch_context: dict[str, Any],
) -> dict[str, Any]:
    incoming_edges = [
        edge
        for edge in _graph_edges(state)
        if _edge_targets(edge, stage_id=stage_id, node_id=node_id)
    ]
    stage_results = dict(state.get("stage_results") or {})
    result_record_index = {
        str(key): dict(value)
        for key, value in dict(state.get("result_record_index") or {}).items()
        if str(key) and isinstance(value, dict)
    }
    accepted_by_scope = {
        str(scope): {str(stage): str(record_id) for stage, record_id in dict(records or {}).items() if str(stage) and str(record_id)}
        for scope, records in dict(state.get("accepted_result_records_by_scope") or {}).items()
        if str(scope) and isinstance(records, dict)
    }
    scope_key = str(dispatch_context.get("dependency_scope_key") or "") or _scope_key(dispatch_context.get("scope_path") or [])
    artifact_refs: list[str] = []
    trace_refs: list[str] = []
    source_node_ids: list[str] = []
    source_result_record_ids: list[str] = []
    edge_ids: list[str] = []
    missing_required: list[str] = []
    expanded_text_by_input_key: dict[str, str] = {}

    for edge in incoming_edges:
        edge_id = str(edge.get("edge_id") or f"{edge.get('source_node_id', '')}->{edge.get('target_node_id', '')}")
        source = str(edge.get("source_node_id") or "")
        result = _stage_result_for_current_scope(
            state=state,
            source=source,
            stage_results=stage_results,
            result_record_index=result_record_index,
            accepted_by_scope=accepted_by_scope,
            scope_key=scope_key,
        )
        if not result:
            if _edge_requires_artifact(edge):
                missing_required.append(edge_id)
            elif _edge_requires_timeline_result(edge):
                missing_required.append(f"timeline_result:{edge_id}")
            continue
        edge_ids.append(edge_id)
        source_node_ids.append(source)
        source_result_record_ids.append(_result_record_id_from_stage_result(result))
        artifact_refs.extend(_string_list(result.get("artifact_refs")))
        trace_refs.extend(_string_list(result.get("trace_refs")))
        policy = dict(edge.get("artifact_ref_policy") or {})
        target_input_key = str(policy.get("target_input_key") or "").strip()
        if target_input_key:
            refs = _string_list(result.get("artifact_refs"))
            if refs:
                expanded_text_by_input_key[target_input_key] = "\n\n".join(
                    _read_artifact_ref_text(ref, max_chars=int(policy.get("max_chars") or 0))
                    for ref in refs
                ).strip()

    explicit_artifact_refs = _artifact_refs_from_explicit_inputs(explicit_inputs)
    artifact_refs.extend(ref for ref in explicit_artifact_refs if ref not in artifact_refs)

    packet = {
        "packet_id": f"artctx:{_short_hash({'dispatch': dispatch_context, 'artifact_refs': artifact_refs, 'stage_id': stage_id})}",
        "dispatch_event_id": str(dispatch_context.get("dispatch_event_id") or ""),
        "clock_seq": int(dispatch_context.get("clock_seq") or 0),
        "scope_path": list(dispatch_context.get("scope_path") or []),
        "stage_id": stage_id,
        "node_id": node_id,
        "edge_ids": [item for item in edge_ids if item],
        "source_node_ids": _dedupe(source_node_ids),
        "source_result_record_ids": [item for item in _dedupe(source_result_record_ids) if item],
        "artifact_refs": _dedupe(artifact_refs),
        "trace_refs": _dedupe(trace_refs),
        "expanded_text_by_input_key": {key: value for key, value in expanded_text_by_input_key.items() if value},
        "missing_required_artifacts": _dedupe(missing_required),
        "authority": "task_graph.artifact_context_packet",
    }
    return packet


def resolve_revision_packet(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    dispatch_context: dict[str, Any],
) -> dict[str, Any]:
    packets = [
        dict(item)
        for item in list(state.get("revision_packets") or [])
        if isinstance(item, dict)
        and str(item.get("target_node_id") or item.get("target_stage_id") or "") in {stage_id, node_id}
    ]
    if not packets:
        return {}
    packet = dict(packets[-1])
    packet["target_dispatch_event_id"] = str(dispatch_context.get("dispatch_event_id") or "")
    packet["target_clock_seq"] = int(dispatch_context.get("clock_seq") or 0)
    packet["target_scope_path"] = list(dispatch_context.get("scope_path") or [])
    packet.setdefault("authority", "task_graph.revision_packet")
    return packet


def resolve_handoff_packets(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    dispatch_context: dict[str, Any],
) -> list[dict[str, Any]]:
    stage_results = dict(state.get("stage_results") or {})
    result_record_index = {
        str(key): dict(value)
        for key, value in dict(state.get("result_record_index") or {}).items()
        if str(key) and isinstance(value, dict)
    }
    accepted_by_scope = {
        str(scope): {str(stage): str(record_id) for stage, record_id in dict(records or {}).items() if str(stage) and str(record_id)}
        for scope, records in dict(state.get("accepted_result_records_by_scope") or {}).items()
        if str(scope) and isinstance(records, dict)
    }
    scope_key = str(dispatch_context.get("dependency_scope_key") or "") or _scope_key(dispatch_context.get("scope_path") or [])
    packets: list[dict[str, Any]] = []
    for edge in _graph_edges(state):
        if not _edge_targets(edge, stage_id=stage_id, node_id=node_id):
            continue
        source = str(edge.get("source_node_id") or "")
        result = _stage_result_for_current_scope(
            state=state,
            source=source,
            stage_results=stage_results,
            result_record_index=result_record_index,
            accepted_by_scope=accepted_by_scope,
            scope_key=scope_key,
        )
        if not result:
            continue
        edge_id = str(edge.get("edge_id") or f"{source}->{stage_id}")
        packet = {
            "packet_id": f"handoff:{_short_hash({'dispatch': dispatch_context, 'edge_id': edge_id, 'source': source})}",
            "source_node_id": source,
            "target_node_id": node_id or stage_id,
            "target_stage_id": stage_id,
            "edge_id": edge_id,
            "source_result_record_id": _result_record_id_from_stage_result(result),
            "payload_contract_id": str(edge.get("payload_contract_id") or ""),
            "artifact_refs": _string_list(result.get("artifact_refs")),
            "memory_refs": _string_list(result.get("working_memory_refs")),
            "summary": str(dict(result.get("diagnostics") or {}).get("summary") or ""),
            "ack_required": bool(edge.get("ack_required", True) is not False),
            "status": "payload_ready",
            "dispatch_event_id": str(dispatch_context.get("dispatch_event_id") or ""),
            "authority": "task_graph.handoff_packet",
        }
        packets.append(packet)
    return packets


def build_revision_packet_from_review(
    *,
    state: dict[str, Any],
    review_stage_id: str,
    target_stage_id: str,
    event: dict[str, Any],
    accepted: bool,
) -> dict[str, Any]:
    request = dict(state.get("stage_execution_request") or {})
    dispatch_context = dict(request.get("dispatch_context") or {})
    artifact_packet = dict(request.get("artifact_context_packet") or {})
    previous_candidate_refs = _string_list(artifact_packet.get("artifact_refs"))
    if not previous_candidate_refs:
        previous_candidate_refs = _artifact_refs_from_explicit_inputs(dict(request.get("explicit_inputs") or state.get("pending_inputs") or {}))
    review_refs = _string_list(event.get("artifact_refs"))
    review_diagnostics = dict(event.get("diagnostics") or {})
    review_verdict = str(
        review_diagnostics.get("verdict")
        or review_diagnostics.get("review_verdict")
        or ("accepted" if accepted else "revise")
    )
    required_changes = (
        review_diagnostics.get("required_changes")
        or review_diagnostics.get("issues")
        or review_diagnostics.get("revision_requirements")
        or []
    )
    if isinstance(required_changes, str):
        required_changes = [required_changes]
    cycle_index = 1 + sum(
        1
        for item in list(state.get("revision_packets") or [])
        if isinstance(item, dict)
        and str(item.get("review_node_id") or item.get("review_stage_id") or "") == review_stage_id
        and str(item.get("target_node_id") or item.get("target_stage_id") or "") == target_stage_id
    )
    revision_cycle_id = f"revision:{_safe_id(review_stage_id)}:{_safe_id(target_stage_id)}:{cycle_index:03d}"
    return {
        "revision_packet_id": f"revpkt:{_short_hash({'cycle': revision_cycle_id, 'event': event, 'dispatch': dispatch_context})}",
        "revision_cycle_id": revision_cycle_id,
        "source_dispatch_event_id": str(dispatch_context.get("dispatch_event_id") or ""),
        "source_clock_seq": int(dispatch_context.get("clock_seq") or 0),
        "review_node_id": review_stage_id,
        "review_stage_id": review_stage_id,
        "target_node_id": target_stage_id,
        "target_stage_id": target_stage_id,
        "previous_candidate_artifact_refs": _dedupe(previous_candidate_refs),
        "previous_candidate_result_record_id": _previous_candidate_result_record_id(state=state, artifact_packet=artifact_packet),
        "review_result_refs": _dedupe(review_refs),
        "review_result_ref": str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
        "review_verdict": review_verdict,
        "required_changes": [str(item) for item in list(required_changes or []) if str(item)],
        "carry_input_keys": ["previous_candidate_artifact_refs", "review_result_refs", "required_changes"],
        "clear_input_keys": [],
        "status": "open",
        "authority": "task_graph.revision_packet",
    }


def _graph_edges(state: dict[str, Any]) -> list[dict[str, Any]]:
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    return [dict(item) for item in list(graph_spec.get("edges") or []) if isinstance(item, dict)]


def _edge_targets(edge: dict[str, Any], *, stage_id: str, node_id: str) -> bool:
    target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "")
    return target in {stage_id, node_id}


def _edge_kind(edge: dict[str, Any]) -> str:
    metadata = dict(edge.get("metadata") or {})
    return str(edge.get("edge_type") or edge.get("mode") or metadata.get("dependency_role") or "")


def _edge_requires_artifact(edge: dict[str, Any]) -> bool:
    if str(edge.get("wait_policy") or "") in {"required", "wait_required_contracts"}:
        return True
    metadata = dict(edge.get("metadata") or {})
    if str(metadata.get("on_missing") or "") == "block":
        return True
    policy = dict(edge.get("artifact_ref_policy") or {})
    return policy.get("required") is True


def _edge_requires_timeline_result(edge: dict[str, Any]) -> bool:
    metadata = dict(edge.get("metadata") or {})
    policy = dict(edge.get("timeline_dependency") or metadata.get("timeline_dependency") or metadata.get("temporal_control") or {})
    return policy.get("required") is True or policy.get("require_current_scope") is True


def _stage_result_for_current_scope(
    *,
    state: dict[str, Any],
    source: str,
    stage_results: dict[str, Any],
    result_record_index: dict[str, dict[str, Any]],
    accepted_by_scope: dict[str, dict[str, str]],
    scope_key: str,
) -> dict[str, Any]:
    if scope_key:
        record_id = str(dict(accepted_by_scope.get(scope_key) or {}).get(source) or "")
        if record_id:
            record = dict(result_record_index.get(record_id) or {})
            if record.get("accepted") is True:
                instance = dict(dict(state.get("stage_results_by_instance") or {}).get(record_id) or {})
                if instance:
                    return instance
    if not accepted_by_scope:
        result = dict(stage_results.get(source) or {})
        record = dict(result.get("timeline_result_record") or {})
        if result and record.get("accepted") is True:
            return result
    return {}


def _result_record_id_from_stage_result(result: dict[str, Any]) -> str:
    record = dict(result.get("timeline_result_record") or {})
    return str(record.get("result_record_id") or "")


def _previous_candidate_result_record_id(*, state: dict[str, Any], artifact_packet: dict[str, Any]) -> str:
    source_ids = artifact_packet.get("source_node_ids")
    if not isinstance(source_ids, list) or not source_ids:
        return ""
    source = str(source_ids[0] or "")
    result = dict(dict(state.get("stage_results") or {}).get(source) or {})
    return _result_record_id_from_stage_result(result)


def _scope_key(scope_path: Any) -> str:
    return "/".join(str(item).strip().replace("/", "_") for item in list(scope_path or ["run"]) if str(item).strip()) or "run"


def _repository_refs_for_stage(*, state: dict[str, Any], stage_id: str, node_id: str) -> list[str]:
    refs: list[str] = []
    for edge in _graph_edges(state):
        if not _edge_targets(edge, stage_id=stage_id, node_id=node_id):
            continue
        metadata = dict(edge.get("metadata") or {})
        repository = str(metadata.get("repository") or metadata.get("repository_ref") or "").strip()
        if repository:
            refs.append(repository)
    return _dedupe(refs)


def _working_memory_refs_from_context(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("required_refs", "preferred_refs", "selected_working_memory_refs", "working_memory_refs"):
        refs.extend(_string_list(context.get(key)))
    for section_id in ("working_memory.required", "working_memory.preferred", "working_memory.conflict_warnings"):
        refs.extend(_string_list(dict(context.get(section_id) or {}).get("refs")))
    return _dedupe(refs)


def _working_memory_records_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("required_items", "preferred_items"):
        for item in list(context.get(key) or []):
            if isinstance(item, dict):
                records.append(dict(item))
    for section_id in ("working_memory.required", "working_memory.preferred"):
        for item in list(dict(context.get(section_id) or {}).get("items") or []):
            if isinstance(item, dict):
                records.append(dict(item))
    for item in list(context.get("formal_memory.required_records") or []):
        if isinstance(item, dict):
            records.append(dict(item))
    for item in list(dict(context.get("formal_memory") or {}).get("required_records") or []):
        if isinstance(item, dict):
            records.append(dict(item))
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        ref = str(record.get("work_memory_id") or record.get("version_id") or record.get("record_id") or "")
        if ref and ref in seen:
            continue
        if ref:
            seen.add(ref)
        deduped.append(record)
    return deduped


def _version_selector_for_record(ref: str, *, resolved_records: list[dict[str, Any]]) -> str:
    for record in resolved_records:
        record_ref = str(record.get("work_memory_id") or record.get("version_id") or record.get("record_id") or "")
        if record_ref != ref:
            continue
        if record.get("version_id") and str(record.get("version_id") or "") == ref:
            return str(record.get("version_selector") or "formal_memory_selected_version")
        metadata = dict(record.get("metadata") or {})
        formal = dict(metadata.get("formal_memory") or metadata.get("memory_record") or {})
        version_selector = str(formal.get("version_selector") or "").strip()
        if version_selector:
            return version_selector
    return ""


def _artifact_refs_from_explicit_inputs(explicit_inputs: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in dict(explicit_inputs or {}).values():
        refs.extend(_artifact_refs_from_value(value))
    return _dedupe(refs)


def _artifact_refs_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("artifact:") else []
    if isinstance(value, dict):
        refs: list[str] = []
        for item in value.values():
            refs.extend(_artifact_refs_from_value(item))
        return refs
    if isinstance(value, (list, tuple)):
        refs: list[str] = []
        for item in value:
            refs.extend(_artifact_refs_from_value(item))
        return refs
    return []


def _read_artifact_ref_text(ref: str, *, max_chars: int = 0) -> str:
    raw = str(ref or "").strip()
    if not raw.startswith("artifact:"):
        return ""
    rel = raw[len("artifact:") :]
    candidates = [Path(rel)]
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / rel)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8", errors="ignore")
                return content[:max_chars] if max_chars > 0 else content
        except OSError:
            continue
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _short_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:80]
