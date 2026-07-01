from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout

from .repository import ProjectNetworkRepository, content_hash
from .work_product_models import GraphBuildWorkProductEnvelope


@dataclass(frozen=True, slots=True)
class ProjectNetworkSemanticArtifactSet:
    build_id: str
    artifact_root: str
    manifest_path: str
    deep_network_route_index_path: str
    signal_chain_index_path: str
    signal_chain_report_path: str
    hierarchy_report_path: str
    link_signal_audit_path: str
    link_signal_audit_report_path: str
    source_work_product_count: int
    route_node_count: int
    route_edge_count: int
    signal_chain_count: int
    audit_signal_count: int
    authority: str = "task_system.project_network.semantic_artifact_set"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


class ProjectNetworkSemanticArtifactMaterializer:
    """Materializes agent-authored project-network facts into navigable artifacts.

    This class does not create semantic facts. It indexes work product payloads
    that were already accepted from graph agents, then writes route and audit
    views that later agents can use as stable navigation handles.
    """

    authority = "task_system.project_network.semantic_artifact_materializer"

    def __init__(
        self,
        *,
        base_dir: str | Path,
        repository: ProjectNetworkRepository | None = None,
    ) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.layout = layout
        self.repository = repository or ProjectNetworkRepository(base_dir)
        self.root = layout.tasks_dir / "project_network_artifacts"

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "ProjectNetworkSemanticArtifactMaterializer":
        return cls(base_dir=base_dir)

    def materialize_build(self, build_id: str, *, graph_run_id: str = "") -> ProjectNetworkSemanticArtifactSet:
        target_build_id = str(build_id or "").strip()
        if not target_build_id:
            raise ValueError("ProjectNetworkSemanticArtifactMaterializer requires build_id")
        products = _current_products(self.repository.list_work_products(build_id=target_build_id, limit=10000))
        route_index = self._build_route_index(target_build_id, products, graph_run_id=graph_run_id)
        link_audit = self._build_link_signal_audit(route_index)
        artifact_root = self.root / _safe_segment(target_build_id)
        artifact_root.mkdir(parents=True, exist_ok=True)

        route_index_path = artifact_root / "deep_network_route_index.json"
        signal_chain_index_path = artifact_root / "signal_chain_index.json"
        signal_chain_report_path = artifact_root / "signal_chain_report.md"
        link_audit_path = artifact_root / "link_signal_audit.json"
        hierarchy_report_path = artifact_root / "hierarchical_review_report.md"
        link_audit_report_path = artifact_root / "link_signal_audit.md"
        manifest_path = artifact_root / "manifest.json"

        signal_chain_index = self._build_signal_chain_index(route_index)
        _write_json(route_index_path, route_index)
        _write_json(signal_chain_index_path, signal_chain_index)
        _write_json(link_audit_path, link_audit)
        hierarchy_report = _render_hierarchy_report(route_index, link_audit)
        signal_report = _render_signal_chain_report(signal_chain_index)
        link_report = _render_link_audit_report(link_audit)
        _write_text(hierarchy_report_path, hierarchy_report)
        _write_text(signal_chain_report_path, signal_report)
        _write_text(link_audit_report_path, link_report)

        artifact_set = ProjectNetworkSemanticArtifactSet(
            build_id=target_build_id,
            artifact_root=str(artifact_root),
            manifest_path=str(manifest_path),
            deep_network_route_index_path=str(route_index_path),
            signal_chain_index_path=str(signal_chain_index_path),
            signal_chain_report_path=str(signal_chain_report_path),
            hierarchy_report_path=str(hierarchy_report_path),
            link_signal_audit_path=str(link_audit_path),
            link_signal_audit_report_path=str(link_audit_report_path),
            source_work_product_count=len(products),
            route_node_count=len(dict(route_index.get("nodes") or {})),
            route_edge_count=len(list(route_index.get("edges") or [])),
            signal_chain_count=len(list(signal_chain_index.get("chains") or [])),
            audit_signal_count=len(list(link_audit.get("signals") or [])),
        )
        manifest = {
            **artifact_set.to_dict(),
            "generated_at": route_index["generated_at"],
            "route_index_hash": content_hash(route_index),
            "signal_chain_index_hash": content_hash(signal_chain_index),
            "link_signal_audit_hash": content_hash(link_audit),
            "authority": self.authority,
        }
        _write_json(manifest_path, manifest)
        return artifact_set

    def _build_route_index(
        self,
        build_id: str,
        products: tuple[GraphBuildWorkProductEnvelope, ...],
        *,
        graph_run_id: str = "",
    ) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        directory_summaries: list[dict[str, Any]] = []
        module_indexes: list[dict[str, Any]] = []

        for product in products:
            payload = dict(product.payload or {})
            product_card = _product_card(product)
            top_node = _node_from_semantic_label(
                payload.get("semantic_label"),
                fallback_ref=product.stable_ref,
                fallback_kind=product.product_kind,
                source_product=product_card,
            )
            if top_node:
                _merge_node(nodes, top_node)
            for node in _extract_payload_nodes(product):
                _merge_node(nodes, node)
            edges.extend(_extract_payload_edges(product))
            if product.product_kind == "directory_summary":
                directory_summaries.append(_directory_summary_card(product))
            elif product.product_kind == "module_index":
                module_indexes.append(_module_index_card(product))

        outgoing: dict[str, list[str]] = {}
        incoming: dict[str, list[str]] = {}
        edge_cards: list[dict[str, Any]] = []
        for index, edge in enumerate(edges, start=1):
            edge_id = edge.get("edge_id") or _edge_id(build_id, edge, index)
            normalized = {**edge, "edge_id": edge_id}
            edge_cards.append(normalized)
            outgoing.setdefault(str(normalized.get("source_ref") or ""), []).append(edge_id)
            incoming.setdefault(str(normalized.get("target_ref") or ""), []).append(edge_id)

        tags: dict[str, list[str]] = {}
        for stable_ref, node in nodes.items():
            label = dict(node.get("semantic_label") or {})
            for tag in _strings(label.get("tags") or node.get("tags")):
                tags.setdefault(tag, []).append(stable_ref)

        return {
            "authority": self.authority,
            "build_id": build_id,
            "graph_run_id": str(graph_run_id or ""),
            "generated_at": _utc_now(),
            "control_plane": "deep_network_route_index",
            "purpose": "fast agent landing and navigation; this index answers where to inspect next, not what chain judgment to make",
            "source_work_products": [_product_card(product) for product in products],
            "nodes": nodes,
            "edges": edge_cards,
            "lookup": {
                "outgoing_edge_ids_by_ref": outgoing,
                "incoming_edge_ids_by_ref": incoming,
                "stable_refs_by_tag": {key: sorted(set(value)) for key, value in sorted(tags.items())},
                "stable_refs_by_kind": _stable_refs_by_kind(nodes),
                "stable_refs_by_path_prefix": _stable_refs_by_path_prefix(nodes),
            },
            "hierarchy": {
                "directories": directory_summaries,
                "modules": module_indexes,
            },
        }

    def _build_signal_chain_index(self, route_index: dict[str, Any]) -> dict[str, Any]:
        edges = [dict(item) for item in list(route_index.get("edges") or []) if isinstance(item, dict)]
        nodes = dict(route_index.get("nodes") or {})
        chains: list[dict[str, Any]] = []
        by_source: dict[str, list[dict[str, Any]]] = {}
        by_target: dict[str, list[dict[str, Any]]] = {}
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            source_ref = str(edge.get("source_ref") or "")
            target_ref = str(edge.get("target_ref") or "")
            edge_kind = str(edge.get("edge_kind") or "relation")
            if source_ref:
                by_source.setdefault(source_ref, []).append(edge)
            if target_ref:
                by_target.setdefault(target_ref, []).append(edge)
            by_kind.setdefault(edge_kind, []).append(edge)

        for source_ref, source_edges in sorted(by_source.items()):
            chains.append(_chain_card(source_ref, source_edges, nodes=nodes))
        unresolved_candidates = [
            _edge_chain_summary(edge, nodes=nodes)
            for edge in edges
            if "candidate" in str(edge.get("status") or "").lower()
            or "candidate" in str(edge.get("signal_kind") or "").lower()
        ]
        conflict_signals = [
            _edge_chain_summary(edge, nodes=nodes)
            for edge in edges
            if "conflict" in str(edge.get("status") or "").lower()
            or "conflict" in str(edge.get("signal_kind") or "").lower()
        ]
        return {
            "authority": "task_system.project_network.signal_chain_index",
            "build_id": str(route_index.get("build_id") or ""),
            "generated_at": _utc_now(),
            "control_plane": "signal_chain_index",
            "purpose": "fast chain summarization and relation judgment; this index answers how known refs are connected",
            "summary": {
                "source_count": len(by_source),
                "target_count": len(by_target),
                "edge_kind_count": len(by_kind),
                "chain_count": len(chains),
                "unresolved_candidate_count": len(unresolved_candidates),
                "conflict_signal_count": len(conflict_signals),
            },
            "chains": chains,
            "edge_ids_by_kind": {
                key: [str(edge.get("edge_id") or "") for edge in values if str(edge.get("edge_id") or "")]
                for key, values in sorted(by_kind.items())
            },
            "unresolved_candidates": unresolved_candidates,
            "conflict_signals": conflict_signals,
        }

    def _build_link_signal_audit(self, route_index: dict[str, Any]) -> dict[str, Any]:
        nodes = dict(route_index.get("nodes") or {})
        known_refs = set(nodes)
        signals: list[dict[str, Any]] = []
        accepted_count = 0
        candidate_count = 0
        conflict_count = 0
        for edge in list(route_index.get("edges") or []):
            status = str(edge.get("status") or "").lower()
            signal_kind = str(edge.get("signal_kind") or "").lower()
            if status == "accepted" or signal_kind == "accepted_edge":
                accepted_count += 1
            if "candidate" in status or "candidate" in signal_kind:
                candidate_count += 1
            if "conflict" in status or "conflict" in signal_kind:
                conflict_count += 1
            signals.extend(_edge_audit_signals(edge, known_refs=known_refs))
        return {
            "authority": "task_system.project_network.link_signal_audit",
            "build_id": str(route_index.get("build_id") or ""),
            "generated_at": _utc_now(),
            "control_plane": "link_signal_quality_audit",
            "purpose": "quality gate for signal-chain trust; this audit reports missing evidence, unknown refs, and unresolved signals",
            "summary": {
                "node_count": len(nodes),
                "edge_count": len(list(route_index.get("edges") or [])),
                "accepted_edge_count": accepted_count,
                "candidate_edge_count": candidate_count,
                "conflict_signal_count": conflict_count,
                "audit_signal_count": len(signals),
                "error_count": sum(1 for item in signals if item.get("severity") == "error"),
                "warning_count": sum(1 for item in signals if item.get("severity") == "warning"),
            },
            "signals": signals,
        }


def _current_products(products: tuple[GraphBuildWorkProductEnvelope, ...]) -> tuple[GraphBuildWorkProductEnvelope, ...]:
    selected: dict[tuple[str, str], GraphBuildWorkProductEnvelope] = {}
    for product in products:
        if product.status in {"rejected", "superseded"}:
            continue
        key = (product.product_kind, product.stable_ref or product.work_product_id)
        if key not in selected:
            selected[key] = product
    return tuple(selected.values())


def _product_card(product: GraphBuildWorkProductEnvelope) -> dict[str, Any]:
    return _drop_empty(
        {
            "work_product_id": product.work_product_id,
            "product_kind": product.product_kind,
            "stable_ref": product.stable_ref,
            "layer_id": product.layer_id,
            "graph_run_id": product.graph_run_id,
            "node_id": product.node_id,
            "status": product.status,
        }
    )


def _node_from_semantic_label(
    raw_label: Any,
    *,
    fallback_ref: str,
    fallback_kind: str,
    source_product: dict[str, Any],
) -> dict[str, Any]:
    label = dict(raw_label or {}) if isinstance(raw_label, dict) else {}
    stable_ref = str(label.get("stable_ref") or fallback_ref or "").strip()
    if not stable_ref:
        return {}
    return _drop_empty(
        {
            "stable_ref": stable_ref,
            "node_kind": str(label.get("node_kind") or fallback_kind or "semantic_node"),
            "name": str(label.get("label") or stable_ref),
            "semantic_label": label or {"stable_ref": stable_ref, "label": stable_ref},
            "evidence_refs": _strings(label.get("evidence_refs")),
            "anchor_refs": _strings(label.get("anchor_refs")),
            "confidence": str(label.get("confidence") or ""),
            "source_products": [source_product],
        }
    )


def _extract_payload_nodes(product: GraphBuildWorkProductEnvelope) -> list[dict[str, Any]]:
    payload = dict(product.payload or {})
    network = dict(payload.get("semantic_network_index") or {})
    raw_nodes: list[Any] = []
    for key in ("nodes", "module_nodes", "directory_nodes"):
        value = network.get(key)
        if isinstance(value, list):
            raw_nodes.extend(value)
    result: list[dict[str, Any]] = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        label = dict(raw.get("semantic_label") or {}) if isinstance(raw.get("semantic_label"), dict) else {}
        stable_ref = str(raw.get("stable_ref") or label.get("stable_ref") or "").strip()
        if not stable_ref:
            continue
        result.append(
            _drop_empty(
                {
                    "stable_ref": stable_ref,
                    "node_kind": str(raw.get("node_kind") or label.get("node_kind") or ""),
                    "name": str(raw.get("name") or label.get("label") or stable_ref),
                    "responsibility": str(raw.get("responsibility") or raw.get("summary") or label.get("summary") or ""),
                    "semantic_label": label,
                    "evidence_refs": _strings(raw.get("evidence_refs") or label.get("evidence_refs")),
                    "anchor_refs": _strings(raw.get("anchor_refs") or label.get("anchor_refs")),
                    "confidence": str(raw.get("confidence") or label.get("confidence") or ""),
                    "source_products": [_product_card(product)],
                }
            )
        )
    return result


def _merge_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    stable_ref = str(node.get("stable_ref") or "").strip()
    if not stable_ref:
        return
    existing = dict(nodes.get(stable_ref) or {})
    source_products = [*list(existing.get("source_products") or []), *list(node.get("source_products") or [])]
    merged = {
        **node,
        **{key: value for key, value in existing.items() if key not in {"source_products", "evidence_refs", "anchor_refs"}},
        "source_products": _dedupe_dicts(source_products, key="work_product_id"),
        "evidence_refs": sorted(set(_strings(existing.get("evidence_refs")) + _strings(node.get("evidence_refs")))),
        "anchor_refs": sorted(set(_strings(existing.get("anchor_refs")) + _strings(node.get("anchor_refs")))),
    }
    nodes[stable_ref] = _drop_empty(merged)


def _extract_payload_edges(product: GraphBuildWorkProductEnvelope) -> list[dict[str, Any]]:
    payload = dict(product.payload or {})
    network = dict(payload.get("semantic_network_index") or {})
    result: list[dict[str, Any]] = []
    for raw in _list_items(network.get("edges")):
        edge = _normalize_edge(raw, product=product, signal_kind="accepted_edge", default_status="accepted")
        if edge:
            result.append(edge)
    for raw in _list_items(network.get("semantic_edges")):
        edge = _normalize_edge(raw, product=product, signal_kind="accepted_edge", default_status="accepted")
        if edge:
            result.append(edge)
    for raw in _list_items(payload.get("relation_candidates")):
        edge = _normalize_edge(raw, product=product, signal_kind="relation_candidate", default_status="candidate")
        if edge:
            result.append(edge)
    for raw in _list_items(payload.get("accepted_relation_candidates")):
        edge = _normalize_edge(raw, product=product, signal_kind="accepted_relation_candidate", default_status="candidate")
        if edge:
            result.append(edge)
    for raw in _list_items(payload.get("conflicts")):
        edge = _normalize_edge(raw, product=product, signal_kind="conflict", default_status="conflict")
        if edge:
            result.append(edge)
    return result


def _normalize_edge(
    raw: Any,
    *,
    product: GraphBuildWorkProductEnvelope,
    signal_kind: str,
    default_status: str,
) -> dict[str, Any]:
    if isinstance(raw, str):
        return _drop_empty(
            {
                "signal_kind": signal_kind,
                "status": default_status,
                "summary": raw,
                "source_work_product": _product_card(product),
            }
        )
    if not isinstance(raw, dict):
        return {}
    source_ref = str(raw.get("source_ref") or raw.get("from_ref") or raw.get("source") or "").strip()
    target_ref = str(raw.get("target_ref") or raw.get("to_ref") or raw.get("target") or "").strip()
    if not source_ref and not target_ref:
        return {}
    return _drop_empty(
        {
            "signal_kind": signal_kind,
            "source_ref": source_ref,
            "target_ref": target_ref,
            "edge_kind": str(raw.get("edge_kind") or raw.get("relation_kind") or signal_kind),
            "direction": str(raw.get("direction") or ""),
            "status": str(raw.get("status") or default_status),
            "evidence_refs": _strings(raw.get("evidence_refs")),
            "anchor_refs": _strings(raw.get("anchor_refs")),
            "confidence": str(raw.get("confidence") or ""),
            "limitations": _strings(raw.get("limitations")),
            "summary": str(raw.get("summary") or raw.get("reason") or ""),
            "source_work_product": _product_card(product),
        }
    )


def _directory_summary_card(product: GraphBuildWorkProductEnvelope) -> dict[str, Any]:
    payload = dict(product.payload or {})
    label = dict(payload.get("semantic_label") or {}) if isinstance(payload.get("semantic_label"), dict) else {}
    return _drop_empty(
        {
            "stable_ref": product.stable_ref,
            "label": str(label.get("label") or product.stable_ref),
            "summary": str(label.get("summary") or payload.get("directory_summary") or ""),
            "tags": _strings(label.get("tags")),
            "coverage": payload.get("coverage"),
            "direct_module_refs": _strings(payload.get("direct_module_refs")),
            "child_summary_refs": _strings(payload.get("child_summary_refs")),
            "parent_return_payload": payload.get("parent_return_payload"),
            "work_product_id": product.work_product_id,
        }
    )


def _module_index_card(product: GraphBuildWorkProductEnvelope) -> dict[str, Any]:
    payload = dict(product.payload or {})
    label = dict(payload.get("semantic_label") or {}) if isinstance(payload.get("semantic_label"), dict) else {}
    network = dict(payload.get("semantic_network_index") or {})
    return _drop_empty(
        {
            "stable_ref": product.stable_ref,
            "label": str(label.get("label") or product.stable_ref),
            "summary": str(label.get("summary") or payload.get("module_summary") or ""),
            "tags": _strings(label.get("tags")),
            "node_count": len(_list_items(network.get("nodes"))),
            "edge_count": len(_list_items(network.get("edges"))),
            "candidate_count": len(_list_items(payload.get("relation_candidates"))),
            "coverage": payload.get("coverage"),
            "limitations": _strings(payload.get("limitations")),
            "uncovered_refs": _strings(payload.get("uncovered_refs")),
            "work_product_id": product.work_product_id,
        }
    )


def _edge_audit_signals(edge: dict[str, Any], *, known_refs: set[str]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    edge_id = str(edge.get("edge_id") or "")
    status = str(edge.get("status") or "").lower()
    signal_kind = str(edge.get("signal_kind") or "")
    source_ref = str(edge.get("source_ref") or "")
    target_ref = str(edge.get("target_ref") or "")
    evidence_refs = _strings(edge.get("evidence_refs"))
    anchor_refs = _strings(edge.get("anchor_refs"))
    is_accepted = status == "accepted" or signal_kind == "accepted_edge"
    if is_accepted and not evidence_refs:
        signals.append(_audit_signal(edge_id, "error", "accepted_edge_missing_evidence", "Accepted edge has no evidence_refs."))
    if is_accepted and not anchor_refs:
        signals.append(_audit_signal(edge_id, "warning", "accepted_edge_missing_anchor", "Accepted edge has no anchor_refs."))
    for role, ref in (("source", source_ref), ("target", target_ref)):
        if ref and ref not in known_refs and not _external_ref(ref):
            signals.append(_audit_signal(edge_id, "warning", f"unknown_{role}_ref", f"{role}_ref is not present in the route node index.", ref=ref))
    confidence = str(edge.get("confidence") or "").lower()
    if confidence in {"low", "0.1", "0.2", "0.3", "0.4"}:
        signals.append(_audit_signal(edge_id, "info", "low_confidence_edge", "Edge is marked low confidence."))
    if "candidate" in status or "candidate" in signal_kind:
        signals.append(_audit_signal(edge_id, "info", "candidate_relation_needs_resolution", "Candidate relation should be confirmed by a later relation-trace pass."))
    if "conflict" in status or "conflict" in signal_kind:
        signals.append(_audit_signal(edge_id, "warning", "conflict_signal_present", "Conflict signal requires parent-layer or human resolution."))
    return signals


def _audit_signal(edge_id: str, severity: str, code: str, message: str, *, ref: str = "") -> dict[str, Any]:
    return _drop_empty(
        {
            "edge_id": edge_id,
            "severity": severity,
            "code": code,
            "message": message,
            "ref": ref,
            "authority": "task_system.project_network.link_signal_audit.signal",
        }
    )


def _render_hierarchy_report(route_index: dict[str, Any], link_audit: dict[str, Any]) -> str:
    hierarchy = dict(route_index.get("hierarchy") or {})
    directories = list(hierarchy.get("directories") or [])
    modules = list(hierarchy.get("modules") or [])
    summary = dict(link_audit.get("summary") or {})
    lines = [
        "# Project Network Hierarchical Review",
        "",
        f"- build_id: `{route_index.get('build_id')}`",
        f"- generated_at: `{route_index.get('generated_at')}`",
        f"- source_work_products: {len(list(route_index.get('source_work_products') or []))}",
        f"- route_nodes: {len(dict(route_index.get('nodes') or {}))}",
        f"- route_edges: {len(list(route_index.get('edges') or []))}",
        f"- audit_signals: {summary.get('audit_signal_count', 0)}",
        "",
        "## Directory Routes",
        "",
    ]
    if not directories:
        lines.append("- No directory_summary work products.")
    for item in directories:
        lines.extend(
            [
                f"### {item.get('label') or item.get('stable_ref')}",
                "",
                f"- stable_ref: `{item.get('stable_ref')}`",
                f"- summary: {item.get('summary') or ''}",
                f"- direct_module_refs: {len(list(item.get('direct_module_refs') or []))}",
                f"- child_summary_refs: {len(list(item.get('child_summary_refs') or []))}",
                f"- work_product_id: `{item.get('work_product_id')}`",
                "",
            ]
        )
    lines.extend(["## Module Routes", ""])
    if not modules:
        lines.append("- No module_index work products.")
    for item in modules:
        lines.extend(
            [
                f"### {item.get('label') or item.get('stable_ref')}",
                "",
                f"- stable_ref: `{item.get('stable_ref')}`",
                f"- summary: {item.get('summary') or ''}",
                f"- nodes: {item.get('node_count', 0)}",
                f"- accepted_edges: {item.get('edge_count', 0)}",
                f"- relation_candidates: {item.get('candidate_count', 0)}",
                f"- work_product_id: `{item.get('work_product_id')}`",
                "",
            ]
        )
        limitations = _strings(item.get("limitations"))
        if limitations:
            lines.append("Limitations:")
            lines.extend(f"- {value}" for value in limitations)
            lines.append("")
    lines.extend(
        [
            "## Link Signal Summary",
            "",
            f"- accepted_edge_count: {summary.get('accepted_edge_count', 0)}",
            f"- candidate_edge_count: {summary.get('candidate_edge_count', 0)}",
            f"- conflict_signal_count: {summary.get('conflict_signal_count', 0)}",
            f"- error_count: {summary.get('error_count', 0)}",
            f"- warning_count: {summary.get('warning_count', 0)}",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_signal_chain_report(signal_chain_index: dict[str, Any]) -> str:
    summary = dict(signal_chain_index.get("summary") or {})
    lines = [
        "# Project Network Signal Chain Index",
        "",
        f"- build_id: `{signal_chain_index.get('build_id')}`",
        f"- generated_at: `{signal_chain_index.get('generated_at')}`",
        f"- chain_count: {summary.get('chain_count', 0)}",
        f"- edge_kind_count: {summary.get('edge_kind_count', 0)}",
        f"- unresolved_candidate_count: {summary.get('unresolved_candidate_count', 0)}",
        f"- conflict_signal_count: {summary.get('conflict_signal_count', 0)}",
        "",
        "## Chains",
        "",
    ]
    chains = list(signal_chain_index.get("chains") or [])
    if not chains:
        lines.append("- No signal chains.")
    for chain in chains:
        lines.extend(
            [
                f"### {chain.get('source_label') or chain.get('source_ref')}",
                "",
                f"- source_ref: `{chain.get('source_ref')}`",
                f"- outgoing_count: {chain.get('outgoing_count', 0)}",
                f"- accepted_count: {chain.get('accepted_count', 0)}",
                f"- candidate_count: {chain.get('candidate_count', 0)}",
                f"- edge_kinds: {', '.join(_strings(chain.get('edge_kinds'))) or '-'}",
                "",
            ]
        )
        for edge in list(chain.get("outgoing") or [])[:12]:
            lines.append(
                f"- `{edge.get('edge_kind')}` -> `{edge.get('target_ref')}`"
                f" [{edge.get('status') or edge.get('signal_kind')}]"
            )
        lines.append("")
    candidates = list(signal_chain_index.get("unresolved_candidates") or [])
    if candidates:
        lines.extend(["## Unresolved Candidates", ""])
        for edge in candidates[:40]:
            lines.append(f"- `{edge.get('source_ref')}` -> `{edge.get('target_ref')}` via `{edge.get('edge_kind')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_link_audit_report(link_audit: dict[str, Any]) -> str:
    summary = dict(link_audit.get("summary") or {})
    lines = [
        "# Project Network Link Signal Audit",
        "",
        f"- build_id: `{link_audit.get('build_id')}`",
        f"- generated_at: `{link_audit.get('generated_at')}`",
        f"- node_count: {summary.get('node_count', 0)}",
        f"- edge_count: {summary.get('edge_count', 0)}",
        f"- accepted_edge_count: {summary.get('accepted_edge_count', 0)}",
        f"- candidate_edge_count: {summary.get('candidate_edge_count', 0)}",
        f"- conflict_signal_count: {summary.get('conflict_signal_count', 0)}",
        f"- audit_signal_count: {summary.get('audit_signal_count', 0)}",
        "",
        "## Signals",
        "",
    ]
    signals = list(link_audit.get("signals") or [])
    if not signals:
        lines.append("- No link audit signals.")
    for signal in signals:
        lines.append(
            f"- [{signal.get('severity')}] {signal.get('code')} on `{signal.get('edge_id')}`"
            + (f": {signal.get('message')}" if signal.get("message") else "")
        )
    return "\n".join(lines).rstrip() + "\n"


def _chain_card(source_ref: str, edges: list[dict[str, Any]], *, nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    outgoing = [_edge_chain_summary(edge, nodes=nodes) for edge in edges]
    statuses = [str(edge.get("status") or edge.get("signal_kind") or "") for edge in outgoing]
    kinds = sorted(set(str(edge.get("edge_kind") or "") for edge in outgoing if str(edge.get("edge_kind") or "")))
    return _drop_empty(
        {
            "source_ref": source_ref,
            "source_label": _node_label(nodes.get(source_ref)),
            "outgoing_count": len(outgoing),
            "accepted_count": sum(1 for status in statuses if status == "accepted"),
            "candidate_count": sum(1 for status in statuses if "candidate" in status),
            "conflict_count": sum(1 for status in statuses if "conflict" in status),
            "edge_kinds": kinds,
            "outgoing": outgoing,
        }
    )


def _edge_chain_summary(edge: dict[str, Any], *, nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_ref = str(edge.get("source_ref") or "")
    target_ref = str(edge.get("target_ref") or "")
    return _drop_empty(
        {
            "edge_id": str(edge.get("edge_id") or ""),
            "source_ref": source_ref,
            "source_label": _node_label(nodes.get(source_ref)),
            "target_ref": target_ref,
            "target_label": _node_label(nodes.get(target_ref)),
            "edge_kind": str(edge.get("edge_kind") or ""),
            "status": str(edge.get("status") or edge.get("signal_kind") or ""),
            "signal_kind": str(edge.get("signal_kind") or ""),
            "confidence": str(edge.get("confidence") or ""),
            "evidence_count": len(_strings(edge.get("evidence_refs"))),
            "anchor_count": len(_strings(edge.get("anchor_refs"))),
            "limitations": _strings(edge.get("limitations")),
        }
    )


def _node_label(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    label = dict(node.get("semantic_label") or {}) if isinstance(node.get("semantic_label"), dict) else {}
    return str(label.get("label") or node.get("name") or node.get("stable_ref") or "")


def _stable_refs_by_kind(nodes: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for stable_ref, node in nodes.items():
        kind = str(node.get("node_kind") or dict(node.get("semantic_label") or {}).get("node_kind") or "unknown")
        result.setdefault(kind, []).append(stable_ref)
    return {key: sorted(value) for key, value in sorted(result.items())}


def _stable_refs_by_path_prefix(nodes: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for stable_ref in nodes:
        if "://" not in stable_ref:
            continue
        path = stable_ref.split("://", 1)[1]
        parts = [part for part in path.split("/") if part]
        for depth in range(1, min(len(parts), 4) + 1):
            prefix = "/".join(parts[:depth])
            result.setdefault(prefix, []).append(stable_ref)
    return {key: sorted(set(value)) for key, value in sorted(result.items())}


def _edge_id(build_id: str, edge: dict[str, Any], index: int) -> str:
    return "pnedge:" + content_hash(
        {
            "build_id": build_id,
            "index": index,
            "source_ref": edge.get("source_ref"),
            "target_ref": edge.get("target_ref"),
            "edge_kind": edge.get("edge_kind"),
            "signal_kind": edge.get("signal_kind"),
        }
    )[:20]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return safe[:180] or "project_network_build"


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, sort_keys=True)]
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _list_items(value: Any) -> list[Any]:
    return list(value or []) if isinstance(value, list | tuple) else []


def _dedupe_dicts(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        lookup = str(dict(item or {}).get(key) or dict(item or {}).get("stable_ref") or dict(item or {}).get("id") or "")
        result[lookup or json.dumps(item, sort_keys=True, ensure_ascii=False)] = dict(item)
    return list(result.values())


def _external_ref(ref: str) -> bool:
    return bool(ref.startswith(("external://", "python://", "input:", "rtobj:", "http://", "https://")))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
