from __future__ import annotations

from dataclasses import replace
from typing import Any

from .repository import content_hash
from .skeleton_models import SkeletonEdgeRecord, SkeletonFactRecord, SkeletonNodeRecord
from .skeleton_refs import skeleton_edge_id, skeleton_node_id


HIERARCHY_EDGE_KINDS = {
    "contains_folder",
    "contains_file",
    "defines_module",
    "defines_class",
    "defines_function",
    "defines_method",
}
CODE_LINK_EDGE_KINDS = {"calls_text", "imports_text"}


def normalize_skeleton_facts(
    *,
    build_id: str,
    generation: int,
    facts: tuple[SkeletonFactRecord, ...] | list[SkeletonFactRecord],
) -> tuple[tuple[SkeletonNodeRecord, ...], tuple[SkeletonEdgeRecord, ...]]:
    fact_tuple = tuple(facts)
    node_inputs = _collect_node_inputs(fact_tuple)
    stable_to_node_id = {
        stable_ref: skeleton_node_id(build_id, generation, stable_ref)
        for stable_ref in node_inputs
    }
    parent_refs = {
        stable_ref: str(payload.get("parent_ref") or "").strip()
        for stable_ref, payload in node_inputs.items()
        if str(payload.get("parent_ref") or "").strip()
    }
    nodes = {
        stable_ref: _node_record(
            build_id=build_id,
            generation=generation,
            stable_ref=stable_ref,
            payload=payload,
            stable_to_node_id=stable_to_node_id,
            parent_refs=parent_refs,
        )
        for stable_ref, payload in node_inputs.items()
    }
    edges = _edge_records(
        build_id=build_id,
        generation=generation,
        facts=fact_tuple,
        nodes=nodes,
        stable_to_node_id=stable_to_node_id,
    )
    enriched_nodes = _enrich_node_relationships(nodes=tuple(nodes.values()), edges=edges)
    return enriched_nodes, edges


def _collect_node_inputs(facts: tuple[SkeletonFactRecord, ...]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for fact in facts:
        if fact.predicate != "declares_node":
            continue
        stable_ref = str(fact.subject_ref or "").strip()
        if not stable_ref:
            continue
        qualifiers = dict(fact.qualifiers or {})
        payload = {**records.get(stable_ref, {}), **qualifiers}
        payload["source_fact_ids"] = [*list(records.get(stable_ref, {}).get("source_fact_ids") or []), fact.fact_id]
        records[stable_ref] = payload
    return records


def _node_record(
    *,
    build_id: str,
    generation: int,
    stable_ref: str,
    payload: dict[str, Any],
    stable_to_node_id: dict[str, str],
    parent_refs: dict[str, str],
) -> SkeletonNodeRecord:
    node_kind = str(payload.get("node_kind") or payload.get("object_literal") or "unknown").strip()
    parent_node_ids = tuple(
        stable_to_node_id[parent_ref]
        for parent_ref in (str(payload.get("parent_ref") or "").strip(),)
        if parent_ref and parent_ref in stable_to_node_id
    )
    ancestor_node_ids = tuple(
        stable_to_node_id[ancestor_ref]
        for ancestor_ref in _ancestor_refs(stable_ref, parent_refs)
        if ancestor_ref in stable_to_node_id
    )
    node_payload = dict(payload.get("payload") or {})
    node_payload.update(
        {
            "physical_layer": _physical_layer(node_kind),
            "source_fact_ids": list(payload.get("source_fact_ids") or []),
        }
    )
    return SkeletonNodeRecord(
        node_id=stable_to_node_id[stable_ref],
        build_id=build_id,
        generation=generation,
        node_kind=node_kind,
        stable_ref=stable_ref,
        display_name=str(payload.get("display_name") or stable_ref).strip(),
        path=str(payload.get("path") or "").strip(),
        layer_kind=str(payload.get("layer_kind") or _physical_layer(node_kind)).strip(),
        hierarchy_path=str(payload.get("hierarchy_path") or stable_ref).strip(),
        parent_node_ids=parent_node_ids,
        ancestor_node_ids=ancestor_node_ids,
        anchor_ref=str(payload.get("anchor_ref") or "").strip(),
        file_hash=str(payload.get("file_hash") or "").strip(),
        extractor="skeleton_normalizer.v1",
        confidence="exact",
        status="active",
        payload=node_payload,
    )


def _ancestor_refs(stable_ref: str, parent_refs: dict[str, str]) -> list[str]:
    ancestors: list[str] = []
    seen: set[str] = set()
    current = parent_refs.get(stable_ref, "")
    while current and current not in seen:
        seen.add(current)
        ancestors.append(current)
        current = parent_refs.get(current, "")
    return ancestors


def _edge_records(
    *,
    build_id: str,
    generation: int,
    facts: tuple[SkeletonFactRecord, ...],
    nodes: dict[str, SkeletonNodeRecord],
    stable_to_node_id: dict[str, str],
) -> tuple[SkeletonEdgeRecord, ...]:
    edges: list[SkeletonEdgeRecord] = []
    symbol_index = _symbol_index(nodes)
    for fact in facts:
        if fact.predicate not in {"contains", "defines", "calls_text", "imports_text"}:
            continue
        src_ref = str(fact.subject_ref or "").strip()
        if src_ref not in stable_to_node_id:
            continue
        edge_kind = str(dict(fact.qualifiers or {}).get("edge_kind") or fact.predicate).strip()
        dst_ref = str(fact.object_ref or "").strip()
        dst_node_id = stable_to_node_id.get(dst_ref, "")
        dst_candidate = str(fact.object_literal or "").strip()
        confidence = fact.confidence
        resolution_status = "resolved" if dst_node_id else "unresolved"
        if fact.predicate == "calls_text" and not dst_node_id:
            resolved_ref = _resolve_call_candidate(src_ref=src_ref, fact=fact, nodes=nodes, symbol_index=symbol_index)
            if resolved_ref:
                dst_ref = resolved_ref
                dst_node_id = stable_to_node_id.get(resolved_ref, "")
                resolution_status = "resolved" if dst_node_id else "unresolved"
                confidence = "derived"
        payload = {
            "predicate": fact.predicate,
            "source_kind": fact.source_kind,
            "candidate_text": dst_candidate,
            "resolution_basis": "stable_ref" if fact.object_ref else "local_ast_text_match" if dst_node_id else "text_candidate_only",
            **dict(fact.qualifiers or {}),
        }
        edges.append(
            SkeletonEdgeRecord(
                edge_id=skeleton_edge_id(
                    build_id,
                    generation,
                    edge_kind,
                    src_ref,
                    dst_ref or dst_candidate,
                    fact.fact_id,
                ),
                build_id=build_id,
                generation=generation,
                edge_kind=edge_kind,
                src_node_id=stable_to_node_id[src_ref],
                dst_node_id=dst_node_id,
                dst_candidate_ref="" if dst_node_id else dst_candidate,
                src_anchor_ref=str(dict(fact.qualifiers or {}).get("anchor_ref") or ""),
                dst_anchor_ref="",
                evidence_refs=tuple(fact.evidence_refs),
                source_fact_ids=(fact.fact_id,),
                extractor="skeleton_normalizer.v1",
                confidence=confidence,
                resolution_status=resolution_status,  # type: ignore[arg-type]
                freshness="fresh",
                payload=payload,
            )
        )
    return tuple(_dedupe_edges(edges))


def _symbol_index(nodes: dict[str, SkeletonNodeRecord]) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    for stable_ref, node in nodes.items():
        if node.node_kind not in {"py_function", "py_method", "py_class"}:
            continue
        qualname = str(node.payload.get("qualname") or node.display_name or "").strip()
        short_name = qualname.rsplit(".", 1)[-1] if qualname else str(node.payload.get("name") or "").strip()
        file_path = node.path
        for key in {(file_path, qualname), (file_path, short_name)}:
            if key[1]:
                index.setdefault(key, []).append(stable_ref)
    return index


def _resolve_call_candidate(
    *,
    src_ref: str,
    fact: SkeletonFactRecord,
    nodes: dict[str, SkeletonNodeRecord],
    symbol_index: dict[tuple[str, str], list[str]],
) -> str:
    src_node = nodes.get(src_ref)
    if src_node is None:
        return ""
    qualifiers = dict(fact.qualifiers or {})
    function_text = str(qualifiers.get("function_text") or fact.object_literal or "").strip()
    callee_text = str(fact.object_literal or "").strip()
    candidates: list[str] = []
    if function_text:
        candidates.extend(symbol_index.get((src_node.path, function_text), ()))
    if callee_text:
        candidates.extend(symbol_index.get((src_node.path, callee_text), ()))
    unique = tuple(dict.fromkeys(item for item in candidates if item != src_ref))
    return unique[0] if len(unique) == 1 else ""


def _dedupe_edges(edges: list[SkeletonEdgeRecord]) -> list[SkeletonEdgeRecord]:
    by_key: dict[tuple[str, str, str, str], SkeletonEdgeRecord] = {}
    for edge in edges:
        key = (edge.edge_kind, edge.src_node_id, edge.dst_node_id, edge.dst_candidate_ref)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = edge
            continue
        by_key[key] = replace(
            existing,
            source_fact_ids=tuple(dict.fromkeys((*existing.source_fact_ids, *edge.source_fact_ids))),
            evidence_refs=tuple(dict.fromkeys((*existing.evidence_refs, *edge.evidence_refs))),
            payload={**existing.payload, "merged_edge_hash": content_hash([existing.edge_id, edge.edge_id])},
        )
    return list(by_key.values())


def _enrich_node_relationships(
    *,
    nodes: tuple[SkeletonNodeRecord, ...],
    edges: tuple[SkeletonEdgeRecord, ...],
) -> tuple[SkeletonNodeRecord, ...]:
    by_id = {node.node_id: node for node in nodes}
    child_counts: dict[str, dict[str, int]] = {}
    child_ids: dict[str, dict[str, list[str]]] = {}
    outbound_counts: dict[str, dict[str, int]] = {}
    inbound_counts: dict[str, dict[str, int]] = {}
    outgoing_call_target_node_ids: dict[str, list[str]] = {}
    outgoing_call_candidate_texts: dict[str, list[str]] = {}
    incoming_call_source_node_ids: dict[str, list[str]] = {}
    import_candidate_texts: dict[str, list[str]] = {}
    for edge in edges:
        outbound_counts.setdefault(edge.src_node_id, {})
        outbound_counts[edge.src_node_id][edge.edge_kind] = outbound_counts[edge.src_node_id].get(edge.edge_kind, 0) + 1
        if edge.dst_node_id:
            inbound_counts.setdefault(edge.dst_node_id, {})
            inbound_counts[edge.dst_node_id][edge.edge_kind] = inbound_counts[edge.dst_node_id].get(edge.edge_kind, 0) + 1
        if edge.edge_kind in HIERARCHY_EDGE_KINDS and edge.dst_node_id:
            child = by_id.get(edge.dst_node_id)
            child_kind = child.node_kind if child is not None else "unknown"
            child_counts.setdefault(edge.src_node_id, {})
            child_counts[edge.src_node_id][child_kind] = child_counts[edge.src_node_id].get(child_kind, 0) + 1
            child_ids.setdefault(edge.src_node_id, {}).setdefault(child_kind, []).append(edge.dst_node_id)
        if edge.edge_kind == "calls_text":
            if edge.dst_node_id:
                outgoing_call_target_node_ids.setdefault(edge.src_node_id, []).append(edge.dst_node_id)
                incoming_call_source_node_ids.setdefault(edge.dst_node_id, []).append(edge.src_node_id)
            elif edge.dst_candidate_ref:
                outgoing_call_candidate_texts.setdefault(edge.src_node_id, []).append(edge.dst_candidate_ref)
        if edge.edge_kind == "imports_text" and edge.dst_candidate_ref:
            import_candidate_texts.setdefault(edge.src_node_id, []).append(edge.dst_candidate_ref)
    enriched: list[SkeletonNodeRecord] = []
    descendant_endpoint_ids = _descendant_endpoint_ids(nodes=nodes, child_ids=child_ids)
    for node in nodes:
        by_kind = child_counts.get(node.node_id, {})
        direct_ids_by_kind = {
            kind: _sort_node_ids(ids, by_id=by_id)
            for kind, ids in sorted(child_ids.get(node.node_id, {}).items())
        }
        endpoint_ids_by_kind = {
            kind: _sort_node_ids(ids, by_id=by_id)[:120]
            for kind, ids in sorted(descendant_endpoint_ids.get(node.node_id, {}).items())
        }
        payload = {
            **node.payload,
            "direct_child_count": sum(by_kind.values()),
            "direct_child_count_by_kind": dict(sorted(by_kind.items())),
            "direct_child_node_ids_by_kind": direct_ids_by_kind,
            "descendant_endpoint_count_by_kind": {kind: len(ids) for kind, ids in sorted(descendant_endpoint_ids.get(node.node_id, {}).items())},
            "descendant_endpoint_node_ids_by_kind": endpoint_ids_by_kind,
            "outbound_edge_count_by_kind": dict(sorted(outbound_counts.get(node.node_id, {}).items())),
            "inbound_edge_count_by_kind": dict(sorted(inbound_counts.get(node.node_id, {}).items())),
            "outgoing_call_target_node_ids": list(dict.fromkeys(outgoing_call_target_node_ids.get(node.node_id, ()))),
            "outgoing_call_candidate_texts": list(dict.fromkeys(outgoing_call_candidate_texts.get(node.node_id, ()))),
            "incoming_call_source_node_ids": list(dict.fromkeys(incoming_call_source_node_ids.get(node.node_id, ()))),
            "import_candidate_texts": list(dict.fromkeys(import_candidate_texts.get(node.node_id, ()))),
        }
        enriched.append(replace(node, payload=payload))
    return tuple(sorted(enriched, key=lambda item: (item.hierarchy_path, item.node_kind, item.stable_ref)))


def _descendant_endpoint_ids(
    *,
    nodes: tuple[SkeletonNodeRecord, ...],
    child_ids: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    by_id = {node.node_id: node for node in nodes}
    cache: dict[str, dict[str, list[str]]] = {}

    def collect(node_id: str, visiting: set[str]) -> dict[str, list[str]]:
        if node_id in cache:
            return cache[node_id]
        if node_id in visiting:
            return {}
        visiting.add(node_id)
        result: dict[str, list[str]] = {}
        for ids in child_ids.get(node_id, {}).values():
            for child_id in ids:
                child = by_id.get(child_id)
                if child is None:
                    continue
                if child.node_kind in {"py_function", "py_method"}:
                    result.setdefault(child.node_kind, []).append(child_id)
                for kind, nested_ids in collect(child_id, visiting).items():
                    result.setdefault(kind, []).extend(nested_ids)
        visiting.remove(node_id)
        cache[node_id] = {
            kind: list(dict.fromkeys(ids))
            for kind, ids in result.items()
        }
        return cache[node_id]

    return {node.node_id: collect(node.node_id, set()) for node in nodes}


def _sort_node_ids(node_ids: list[str], *, by_id: dict[str, SkeletonNodeRecord]) -> list[str]:
    return sorted(
        dict.fromkeys(node_ids),
        key=lambda node_id: (
            int(dict(by_id.get(node_id).payload if by_id.get(node_id) is not None else {}).get("start_line") or 0),
            by_id.get(node_id).hierarchy_path if by_id.get(node_id) is not None else node_id,
        ),
    )


def _physical_layer(node_kind: str) -> str:
    return {
        "repo": "repository",
        "folder": "folder",
        "file": "file",
        "py_module": "module",
        "py_class": "class",
        "py_function": "function",
        "py_method": "method",
    }.get(node_kind, "unknown")
