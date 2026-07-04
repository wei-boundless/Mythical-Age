from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
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
    unified_control_graph_path: str
    unified_control_graph_report_path: str
    project_architecture_overview_path: str
    semantic_coordinates_path: str
    deep_network_route_index_path: str
    signal_chain_index_path: str
    link_signal_audit_path: str
    project_network_review_path: str
    project_semantic_coordinates_report_path: str
    project_signal_chain_review_path: str
    project_network_reports_root: str
    project_network_reports_index_path: str
    source_work_product_count: int
    semantic_coordinate_count: int
    reliable_route_count: int
    unresolved_route_count: int
    signal_chain_count: int
    audit_signal_count: int
    file_report_count: int
    directory_report_count: int
    layer_report_count: int
    authority: str = "project_network_system.semantic_artifact_set"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


class ProjectNetworkSemanticArtifactMaterializer:
    """Materializes project-network work products into control-system artifacts.

    This layer does not create semantic facts. It normalizes accepted agent work
    products into human reports and machine indexes with separated control-plane
    responsibilities:

    - semantic coordinates summarize meaning.
    - route index answers where an agent can land.
    - signal chain index answers how known refs relate.
    - audit answers which refs/edges are not trustworthy yet.
    """

    authority = "project_network_system.semantic_artifact_materializer"

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
        self.human_reports_root = layout.project_root / "PROJECT_NETWORK_REPORTS"

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "ProjectNetworkSemanticArtifactMaterializer":
        return cls(base_dir=base_dir)

    def materialize_build(self, build_id: str, *, graph_run_id: str = "") -> ProjectNetworkSemanticArtifactSet:
        target_build_id = str(build_id or "").strip()
        if not target_build_id:
            raise ValueError("ProjectNetworkSemanticArtifactMaterializer requires build_id")

        products = _current_products(self.repository.list_work_products(build_id=target_build_id, limit=10000))
        model = _build_control_model(
            build_id=target_build_id,
            products=products,
            layout=self.layout,
            graph_run_id=graph_run_id,
        )

        artifact_root = self.root / _safe_segment(target_build_id)
        artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_reports_root = artifact_root / "reports"
        artifact_files_root = artifact_root / "files"
        artifact_dirs_root = artifact_root / "directories"
        artifact_layers_root = artifact_root / "layers"
        human_files_root = self.human_reports_root / "files"
        human_dirs_root = self.human_reports_root / "directories"
        human_layers_root = self.human_reports_root / "layers"
        for path in (human_files_root, human_dirs_root, human_layers_root):
            _reset_report_subtree(path)
        for path in (artifact_reports_root, artifact_files_root, artifact_dirs_root, artifact_layers_root, human_files_root, human_dirs_root, human_layers_root):
            path.mkdir(parents=True, exist_ok=True)

        semantic_coordinates_path = artifact_root / "semantic_coordinates.json"
        route_index_path = artifact_root / "deep_network_route_index.json"
        signal_chain_index_path = artifact_root / "signal_chain_index.json"
        link_audit_path = artifact_root / "link_signal_audit.json"
        unified_control_graph_path = artifact_root / "unified_control_graph.json"
        manifest_path = artifact_root / "manifest.json"

        project_review_path = self.layout.project_root / "PROJECT_NETWORK_REVIEW.md"
        architecture_overview_path = self.layout.project_root / "PROJECT_ARCHITECTURE_OVERVIEW.md"
        semantic_report_path = self.layout.project_root / "PROJECT_SEMANTIC_COORDINATES.md"
        signal_report_path = self.layout.project_root / "PROJECT_SIGNAL_CHAIN_REVIEW.md"
        unified_report_path = self.layout.project_root / "PROJECT_UNIFIED_CONTROL_GRAPH.md"
        reports_index_path = self.human_reports_root / "README.md"

        file_reports = _write_file_reports(
            module_cards=model["module_cards"],
            artifact_root=artifact_files_root,
            human_root=human_files_root,
        )
        directory_reports = _write_directory_reports(
            directory_cards=model["directory_cards"],
            artifact_root=artifact_dirs_root,
            human_root=human_dirs_root,
        )

        coordinates = _build_semantic_coordinates(model)
        route_index = _build_route_index(model)
        signal_chain_index = _build_signal_chain_index(model)
        link_audit = _build_link_signal_audit(model, route_index=route_index, signal_chain_index=signal_chain_index)
        unified_control_graph = _build_unified_control_graph(
            model,
            coordinates=coordinates,
            route_index=route_index,
            signal_chain_index=signal_chain_index,
            link_audit=link_audit,
        )
        layer_reports = _write_layer_reports(
            unified_control_graph=unified_control_graph,
            artifact_root=artifact_layers_root,
            human_root=human_layers_root,
        )

        _write_json(unified_control_graph_path, unified_control_graph)
        _write_json(semantic_coordinates_path, coordinates)
        _write_json(route_index_path, route_index)
        _write_json(signal_chain_index_path, signal_chain_index)
        _write_json(link_audit_path, link_audit)

        _write_text(project_review_path, _render_project_network_review(model, file_reports=file_reports, directory_reports=directory_reports, link_audit=link_audit))
        _write_text(architecture_overview_path, _render_project_architecture_overview(model, unified_control_graph=unified_control_graph, link_audit=link_audit))
        _write_text(semantic_report_path, _render_semantic_coordinates_report(coordinates))
        _write_text(signal_report_path, _render_signal_chain_review(signal_chain_index, link_audit))
        _write_text(unified_report_path, _render_unified_control_graph_report(unified_control_graph, layer_reports=layer_reports, file_reports=file_reports, directory_reports=directory_reports))
        _write_text(reports_index_path, _render_reports_index(model, file_reports=file_reports, directory_reports=directory_reports, layer_reports=layer_reports, root_reports={
            "architecture_overview": architecture_overview_path,
            "project_network_review": project_review_path,
            "semantic_coordinates": semantic_report_path,
            "signal_chain_review": signal_report_path,
            "unified_control_graph": unified_report_path,
        }))
        _write_text(artifact_reports_root / "PROJECT_NETWORK_REVIEW.md", project_review_path.read_text(encoding="utf-8"))
        _write_text(artifact_reports_root / "PROJECT_ARCHITECTURE_OVERVIEW.md", architecture_overview_path.read_text(encoding="utf-8"))
        _write_text(artifact_reports_root / "PROJECT_SEMANTIC_COORDINATES.md", semantic_report_path.read_text(encoding="utf-8"))
        _write_text(artifact_reports_root / "PROJECT_SIGNAL_CHAIN_REVIEW.md", signal_report_path.read_text(encoding="utf-8"))
        _write_text(artifact_reports_root / "PROJECT_UNIFIED_CONTROL_GRAPH.md", unified_report_path.read_text(encoding="utf-8"))
        _write_text(artifact_reports_root / "README.md", reports_index_path.read_text(encoding="utf-8"))

        artifact_set = ProjectNetworkSemanticArtifactSet(
            build_id=target_build_id,
            artifact_root=str(artifact_root),
            manifest_path=str(manifest_path),
            unified_control_graph_path=str(unified_control_graph_path),
            unified_control_graph_report_path=str(unified_report_path),
            project_architecture_overview_path=str(architecture_overview_path),
            semantic_coordinates_path=str(semantic_coordinates_path),
            deep_network_route_index_path=str(route_index_path),
            signal_chain_index_path=str(signal_chain_index_path),
            link_signal_audit_path=str(link_audit_path),
            project_network_review_path=str(project_review_path),
            project_semantic_coordinates_report_path=str(semantic_report_path),
            project_signal_chain_review_path=str(signal_report_path),
            project_network_reports_root=str(self.human_reports_root),
            project_network_reports_index_path=str(reports_index_path),
            source_work_product_count=len(products),
            semantic_coordinate_count=len(list(coordinates.get("coordinates") or [])),
            reliable_route_count=len(list(route_index.get("reliable_routes") or [])),
            unresolved_route_count=len(list(route_index.get("unresolved_routes") or [])),
            signal_chain_count=len(list(signal_chain_index.get("chains") or [])),
            audit_signal_count=len(list(link_audit.get("signals") or [])),
            file_report_count=len(file_reports),
            directory_report_count=len(directory_reports),
            layer_report_count=len(layer_reports),
        )
        manifest = {
            **artifact_set.to_dict(),
            "generated_at": model["generated_at"],
            "unified_control_graph_hash": content_hash(unified_control_graph),
            "semantic_coordinates_hash": content_hash(coordinates),
            "route_index_hash": content_hash(route_index),
            "signal_chain_index_hash": content_hash(signal_chain_index),
            "link_signal_audit_hash": content_hash(link_audit),
            "file_reports": file_reports,
            "directory_reports": directory_reports,
            "layer_reports": layer_reports,
            "authority": self.authority,
        }
        _write_json(manifest_path, manifest)
        return artifact_set


def _build_control_model(
    *,
    build_id: str,
    products: tuple[GraphBuildWorkProductEnvelope, ...],
    layout: ProjectLayout,
    graph_run_id: str,
) -> dict[str, Any]:
    module_cards: list[dict[str, Any]] = []
    directory_cards: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for product in products:
        if product.product_kind == "module_index":
            card = _module_card(product, layout=layout)
            module_cards.append(card)
            for node in card["nodes"]:
                _merge_node(nodes, node)
            edges.extend(card["edges"])
            edges.extend(card["relation_candidates"])
        elif product.product_kind == "directory_summary":
            card = _directory_card(product, layout=layout)
            directory_cards.append(card)
            for node in card["nodes"]:
                _merge_node(nodes, node)
            edges.extend(card["edges"])
            edges.extend(card["accepted_relation_candidates"])
            edges.extend(card["conflicts"])

    _inject_physical_structure_edges(
        build_id=build_id,
        nodes=nodes,
        edges=edges,
        module_cards=module_cards,
        directory_cards=directory_cards,
        layout=layout,
    )
    normalized_edges = _dedupe_edges(
        [
            {**edge, "edge_id": str(edge.get("edge_id") or _edge_id(build_id, edge, index))}
            for index, edge in enumerate(edges, start=1)
            if isinstance(edge, dict)
        ]
    )
    return {
        "authority": ProjectNetworkSemanticArtifactMaterializer.authority,
        "build_id": build_id,
        "graph_run_id": str(graph_run_id or ""),
        "generated_at": _utc_now(),
        "layout": layout,
        "source_work_products": [_product_card(product) for product in products],
        "module_cards": module_cards,
        "directory_cards": directory_cards,
        "nodes": nodes,
        "edges": normalized_edges,
    }


def _inject_physical_structure_edges(
    *,
    build_id: str,
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    module_cards: list[dict[str, Any]],
    directory_cards: list[dict[str, Any]],
    layout: ProjectLayout,
) -> None:
    root_ref = "folder://."
    _merge_node(nodes, _structural_node(root_ref, node_kind="system_root", label="Workspace root", summary="Physical root of the project control network.", layout=layout))

    folder_refs: set[str] = {root_ref}
    for card in directory_cards:
        folder_ref = _normalize_folder_ref(str(card.get("stable_ref") or ""))
        if folder_ref:
            folder_refs.add(folder_ref)
            folder_refs.update(_ancestor_folder_refs(folder_ref))

    file_refs: list[str] = []
    for card in module_cards:
        file_ref = _normalize_file_ref_from_card(card, layout=layout)
        if not file_ref:
            continue
        file_refs.append(file_ref)
        parent_ref = _parent_folder_ref_for_file(file_ref)
        folder_refs.add(parent_ref)
        folder_refs.update(_ancestor_folder_refs(parent_ref))
        _merge_node(nodes, _structural_node(file_ref, node_kind="file_module", label=_display_path_from_ref(file_ref), summary="Physical file module in the project control network.", layout=layout))
        edges.append(_physical_structure_edge(build_id, parent_ref, file_ref, edge_kind="contains_file"))

    for folder_ref in sorted(folder_refs):
        _merge_node(nodes, _structural_node(folder_ref, node_kind="directory" if folder_ref != root_ref else "system_root", label=_display_path_from_ref(folder_ref) or "Workspace root", summary="Physical directory in the project control network.", layout=layout))
        if folder_ref == root_ref:
            continue
        parent_ref = _parent_folder_ref(folder_ref)
        edges.append(_physical_structure_edge(build_id, parent_ref, folder_ref, edge_kind="contains_directory"))


def _structural_node(ref: str, *, node_kind: str, label: str, summary: str, layout: ProjectLayout) -> dict[str, Any]:
    validation = _validate_physical_ref(ref, layout=layout)
    return _drop_empty(
        {
            "stable_ref": ref,
            "node_kind": node_kind,
            "name": label or ref,
            "responsibility": summary,
            "semantic_label": {
                "stable_ref": ref,
                "label": label or ref,
                "summary": summary,
                "tags": ["physical_structure", node_kind],
                "confidence": "system",
            },
            "evidence_refs": [ref],
            "anchor_refs": [ref],
            "confidence": "system",
            "physical_validation": validation,
            "source_products": [
                {
                    "work_product_id": "system:physical_structure:" + content_hash({"ref": ref})[:16],
                    "product_kind": "physical_structure",
                    "stable_ref": ref,
                    "status": "accepted",
                }
            ],
        }
    )


def _physical_structure_edge(build_id: str, source_ref: str, target_ref: str, *, edge_kind: str) -> dict[str, Any]:
    return _drop_empty(
        {
            "edge_id": "pnedge:" + content_hash({"build_id": build_id, "source_ref": source_ref, "target_ref": target_ref, "edge_kind": edge_kind})[:20],
            "signal_kind": "physical_structure",
            "source_ref": source_ref,
            "target_ref": target_ref,
            "edge_kind": edge_kind,
            "direction": "downstream",
            "status": "accepted",
            "evidence_refs": [target_ref],
            "anchor_refs": [source_ref, target_ref],
            "confidence": "system",
            "summary": "Physical containment extracted from the project file tree.",
            "authority": "project_network_system.physical_structure_edge",
        }
    )


def _module_card(product: GraphBuildWorkProductEnvelope, *, layout: ProjectLayout) -> dict[str, Any]:
    payload = dict(product.payload or {})
    file_ref = str(payload.get("file_ref") or product.stable_ref or "").strip()
    label = _label(payload.get("semantic_label"), fallback_ref=file_ref, fallback_kind="file_module")
    physical_binding = _physical_binding(
        payload.get("physical_binding"),
        stable_ref=file_ref,
        path=str(payload.get("file_path") or ""),
        file_hash=str(payload.get("file_hash") or ""),
        layout=layout,
        binding_kind="file",
    )
    semantic_coordinate = _semantic_coordinate(
        payload.get("semantic_coordinate"),
        stable_ref=file_ref,
        layer="file",
        label=label,
        summary=str(payload.get("module_summary") or label.get("summary") or ""),
        source_product=product,
        physical_binding=physical_binding,
    )
    network = dict(payload.get("semantic_network_index") or {})
    control_nodes = _node_values(payload.get("control_nodes") or payload.get("semantic_nodes") or network.get("nodes"))
    nodes = _dedupe_by_key(
        [
            _node_from_coordinate(semantic_coordinate, product=product, layout=layout),
            *[_normalize_node(item, product=product, layout=layout) for item in control_nodes],
        ],
        key="stable_ref",
    )
    accepted_edges = _edge_values(payload.get("accepted_internal_edges") or payload.get("semantic_edges") or network.get("edges"))
    relation_candidates = _edge_values(payload.get("relation_candidates"))
    return {
        "product": _product_card(product),
        "stable_ref": file_ref,
        "file_path": str(payload.get("file_path") or ""),
        "file_hash": str(payload.get("file_hash") or ""),
        "physical_binding": physical_binding,
        "semantic_coordinate": semantic_coordinate,
        "module_summary": str(payload.get("module_summary") or label.get("summary") or ""),
        "module_review_report": _mapping(payload.get("module_review_report")),
        "public_surface": _list_items(payload.get("public_surface")),
        "control_nodes": control_nodes,
        "io_surface": _mapping(payload.get("io_surface")),
        "nodes": [item for item in nodes if item],
        "edges": [edge for item in accepted_edges if (edge := _normalize_edge(item, product=product, signal_kind="accepted_edge", default_status="accepted"))],
        "relation_candidates": [
            edge
            for item in relation_candidates
            if (edge := _normalize_edge(item, product=product, signal_kind="relation_candidate", default_status="candidate"))
        ],
        "coverage": _mapping(payload.get("coverage")),
        "limitations": _strings(payload.get("limitations")),
        "uncovered_refs": _strings(payload.get("uncovered_refs")),
    }


def _directory_card(product: GraphBuildWorkProductEnvelope, *, layout: ProjectLayout) -> dict[str, Any]:
    payload = dict(product.payload or {})
    folder_ref = _normalize_physical_ref_scheme(str(payload.get("folder_stable_ref") or product.stable_ref or "").strip())
    label = _label(payload.get("semantic_label"), fallback_ref=folder_ref, fallback_kind="directory")
    physical_binding = _physical_binding(
        payload.get("physical_binding"),
        stable_ref=folder_ref,
        path=_folder_path_from_ref(folder_ref),
        file_hash="",
        layout=layout,
        binding_kind="directory",
    )
    semantic_coordinate = _semantic_coordinate(
        payload.get("semantic_coordinate"),
        stable_ref=folder_ref,
        layer="directory",
        label=label,
        summary=str(payload.get("directory_summary") or label.get("summary") or ""),
        source_product=product,
        physical_binding=physical_binding,
    )
    network = dict(payload.get("semantic_network_index") or {})
    directory_nodes = _node_values(payload.get("directory_nodes") or network.get("directory_nodes"))
    module_nodes = _node_values(payload.get("module_nodes") or network.get("module_nodes"))
    nodes = _dedupe_by_key(
        [
            _node_from_coordinate(semantic_coordinate, product=product, layout=layout),
            *[_normalize_node(item, product=product, layout=layout) for item in [*directory_nodes, *module_nodes]],
        ],
        key="stable_ref",
    )
    edges = _edge_values(payload.get("directory_control_routes") or payload.get("semantic_edges") or network.get("edges"))
    accepted_candidates = _edge_values(payload.get("accepted_relation_candidates"))
    conflicts = _edge_values(payload.get("conflicts"))
    return {
        "product": _product_card(product),
        "stable_ref": folder_ref,
        "directory_frame_id": str(payload.get("directory_frame_id") or ""),
        "physical_binding": physical_binding,
        "semantic_coordinate": semantic_coordinate,
        "directory_summary": str(payload.get("directory_summary") or label.get("summary") or ""),
        "directory_review_report": _mapping(payload.get("directory_review_report")),
        "child_coordinate_summary": _mapping(payload.get("child_coordinate_summary")),
        "nodes": [item for item in nodes if item],
        "edges": [edge for item in edges if (edge := _normalize_edge(item, product=product, signal_kind="accepted_edge", default_status="accepted"))],
        "accepted_relation_candidates": [
            edge
            for item in accepted_candidates
            if (edge := _normalize_edge(item, product=product, signal_kind="accepted_relation_candidate", default_status="candidate"))
        ],
        "conflicts": [edge for item in conflicts if (edge := _normalize_edge(item, product=product, signal_kind="conflict", default_status="conflict"))],
        "direct_module_refs": _strings(payload.get("direct_module_refs")),
        "child_summary_refs": _strings(payload.get("child_summary_refs")),
        "coverage": _mapping(payload.get("coverage")),
        "uncovered_refs": _strings(payload.get("uncovered_refs")),
        "parent_return_payload": _mapping(payload.get("parent_return_payload")),
    }


def _build_semantic_coordinates(model: dict[str, Any]) -> dict[str, Any]:
    coordinates: list[dict[str, Any]] = []
    for item in [*model["directory_cards"], *model["module_cards"]]:
        coordinate = dict(item.get("semantic_coordinate") or {})
        if coordinate:
            coordinates.append(coordinate)
    for stable_ref, node in sorted(dict(model["nodes"]).items()):
        coordinate = _coordinate_from_node(stable_ref, dict(node))
        if coordinate:
            coordinates.append(coordinate)
    coordinates = _coalesce_semantic_coordinates(coordinates)
    return {
        "authority": "project_network_system.semantic_coordinates",
        "control_plane": "semantic_coordinates",
        "purpose": "summarized semantic road signs for agent and human navigation; this is not a raw node dump",
        "build_id": model["build_id"],
        "generated_at": model["generated_at"],
        "summary": {
            "coordinate_count": len(coordinates),
            "system_count": sum(1 for item in coordinates if item.get("layer") == "system"),
            "directory_count": sum(1 for item in coordinates if item.get("layer") == "directory"),
            "file_count": sum(1 for item in coordinates if item.get("layer") == "file"),
            "symbol_count": sum(1 for item in coordinates if item.get("layer") == "symbol"),
        },
        "coordinates": coordinates,
        "lookup": {
            "coordinate_refs_by_tag": _refs_by_tag(coordinates),
            "coordinate_refs_by_layer": _refs_by_layer(coordinates),
        },
    }


def _build_route_index(model: dict[str, Any]) -> dict[str, Any]:
    reliable: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for stable_ref, node in sorted(dict(model["nodes"]).items()):
        route = _route_card(stable_ref, dict(node))
        validation = dict(route.get("physical_validation") or {})
        if validation.get("status") == "resolved":
            reliable.append(route)
        else:
            unresolved.append(route)
    return {
        "authority": "project_network_system.deep_network_route_index",
        "control_plane": "deep_network_route_index",
        "purpose": "fast agent landing and navigation only; chain meaning belongs to signal_chain_index",
        "build_id": model["build_id"],
        "generated_at": model["generated_at"],
        "reliable_routes": reliable,
        "unresolved_routes": unresolved,
        "lookup": {
            "route_refs_by_tag": _refs_by_tag(reliable),
            "route_refs_by_kind": _refs_by_kind(reliable),
            "route_refs_by_path_prefix": _refs_by_path_prefix(reliable),
        },
    }


def _build_signal_chain_index(model: dict[str, Any]) -> dict[str, Any]:
    edges = _dedupe_edges([dict(edge) for edge in list(model.get("edges") or [])])
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
        chains.append(_chain_card(source_ref, source_edges, model=model))
    return {
        "authority": "project_network_system.signal_chain_index",
        "control_plane": "signal_chain_index",
        "purpose": "chain summarization and relation judgment support; this is not the landing route index",
        "build_id": model["build_id"],
        "generated_at": model["generated_at"],
        "summary": {
            "edge_count": len(edges),
            "chain_count": len(chains),
            "source_count": len(by_source),
            "target_count": len(by_target),
            "edge_kind_count": len(by_kind),
            "accepted_edge_count": sum(1 for edge in edges if _edge_status(edge) == "accepted"),
            "candidate_edge_count": sum(1 for edge in edges if "candidate" in _edge_status(edge)),
            "conflict_edge_count": sum(1 for edge in edges if "conflict" in _edge_status(edge)),
        },
        "chains": chains,
        "accepted_edges": [_edge_summary(edge, model=model) for edge in edges if _edge_status(edge) == "accepted"],
        "candidate_edges": [_edge_summary(edge, model=model) for edge in edges if "candidate" in _edge_status(edge)],
        "conflict_edges": [_edge_summary(edge, model=model) for edge in edges if "conflict" in _edge_status(edge)],
        "edge_ids_by_kind": {
            key: [str(edge.get("edge_id") or "") for edge in values if str(edge.get("edge_id") or "")]
            for key, values in sorted(by_kind.items())
        },
    }


def _build_unified_control_graph(
    model: dict[str, Any],
    *,
    coordinates: dict[str, Any],
    route_index: dict[str, Any],
    signal_chain_index: dict[str, Any],
    link_audit: dict[str, Any],
) -> dict[str, Any]:
    coordinate_by_ref = {
        str(item.get("physical_ref") or item.get("coordinate_ref") or ""): dict(item)
        for item in list(coordinates.get("coordinates") or [])
        if isinstance(item, dict) and str(item.get("physical_ref") or item.get("coordinate_ref") or "")
    }
    route_by_ref = {
        str(item.get("route_ref") or ""): dict(item)
        for item in [*list(route_index.get("reliable_routes") or []), *list(route_index.get("unresolved_routes") or [])]
        if isinstance(item, dict) and str(item.get("route_ref") or "")
    }
    node_signals: dict[str, list[dict[str, Any]]] = {}
    edge_signals: dict[str, list[dict[str, Any]]] = {}
    for signal in list(link_audit.get("signals") or []):
        if not isinstance(signal, dict):
            continue
        edge_id = str(signal.get("edge_id") or "").strip()
        if edge_id:
            edge_signals.setdefault(edge_id, []).append(dict(signal))
        refs = _dedupe_strings(
            [
                str(signal.get("subject_ref") or ""),
                str(signal.get("ref") or ""),
            ]
        )
        for ref in refs:
            if ref and not ref.startswith("pnedge:") and not ref.startswith("route:"):
                node_signals.setdefault(ref, []).append(dict(signal))
            if ref.startswith("route:"):
                route_ref = ref[len("route:") :]
                if route_ref:
                    node_signals.setdefault(route_ref, []).append(dict(signal))

    nodes: list[dict[str, Any]] = []
    for stable_ref, node in sorted(dict(model.get("nodes") or {}).items()):
        item = dict(node or {})
        coordinate = dict(coordinate_by_ref.get(stable_ref) or {})
        route = dict(route_by_ref.get(stable_ref) or {})
        label = dict(item.get("semantic_label") or {}) if isinstance(item.get("semantic_label"), dict) else {}
        nodes.append(
            _drop_empty(
                {
                    "stable_ref": stable_ref,
                    "node_id": stable_ref,
                    "identity": {
                        "stable_ref": stable_ref,
                        "physical_ref": str(route.get("route_ref") or coordinate.get("physical_ref") or stable_ref),
                        "node_kind": str(item.get("node_kind") or label.get("node_kind") or route.get("node_kind") or ""),
                    },
                    "physical_facts": {
                        "physical_validation": dict(item.get("physical_validation") or route.get("physical_validation") or {}),
                        "evidence_refs": _strings(route.get("evidence_refs")) or _strings(item.get("evidence_refs")),
                        "anchor_refs": _strings(route.get("anchor_refs")) or _strings(item.get("anchor_refs")),
                    },
                    "semantic_facets": {
                        "layer": str(coordinate.get("layer") or _coordinate_layer(str(item.get("node_kind") or label.get("node_kind") or route.get("node_kind") or ""))),
                        "label": str(coordinate.get("label") or label.get("label") or item.get("name") or stable_ref),
                        "summary": str(coordinate.get("summary") or label.get("summary") or item.get("responsibility") or ""),
                        "tags": _strings(coordinate.get("tags")) or _strings(label.get("tags")),
                        "control_role": str(coordinate.get("control_role") or ""),
                        "confidence": str(coordinate.get("confidence") or item.get("confidence") or route.get("confidence") or "derived"),
                    },
                    "control_surface": {
                        "recommended_next_action": str(route.get("recommended_next_action") or ""),
                        "audit_signals": [dict(signal) for signal in list(node_signals.get(stable_ref) or [])],
                    },
                    "authority": "project_network_system.unified_control_graph.node",
                }
            )
        )

    raw_edges = _dedupe_edges([dict(edge) for edge in list(model.get("edges") or []) if isinstance(edge, dict)])
    edges: list[dict[str, Any]] = []
    for edge in raw_edges:
        edge_id = str(edge.get("edge_id") or "")
        source_ref = str(edge.get("source_ref") or "")
        target_ref = str(edge.get("target_ref") or "")
        status = _edge_status(edge)
        edges.append(
            _drop_empty(
                {
                    "edge_id": edge_id,
                    "identity": {
                        "edge_id": edge_id,
                        "source_ref": source_ref,
                        "target_ref": target_ref,
                    },
                    "physical_facts": {
                        "evidence_refs": _strings(edge.get("evidence_refs")),
                        "anchor_refs": _strings(edge.get("anchor_refs")),
                    },
                    "semantic_facets": {
                        "edge_kind": str(edge.get("edge_kind") or ""),
                        "summary": str(edge.get("summary") or ""),
                        "status": status,
                        "confidence": str(edge.get("confidence") or ""),
                    },
                    "control_surface": {
                        "trace_priority": 90 if status == "accepted" else 60 if status == "candidate" else 40,
                        "audit_signals": [dict(signal) for signal in list(edge_signals.get(edge_id) or [])],
                    },
                    "authority": "project_network_system.unified_control_graph.edge",
                }
            )
        )
    return {
        "authority": "project_network_system.unified_control_graph",
        "control_plane": "unified_control_graph",
        "purpose": "single entity space for physical facts, semantic facets, and agent control surface",
        "build_id": model["build_id"],
        "generated_at": model["generated_at"],
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "accepted_edge_count": len(list(signal_chain_index.get("accepted_edges") or [])),
            "candidate_edge_count": len(list(signal_chain_index.get("candidate_edges") or [])),
            "audit_signal_count": len(list(link_audit.get("signals") or [])),
        },
        "nodes": nodes,
        "edges": edges,
    }


def _build_link_signal_audit(model: dict[str, Any], *, route_index: dict[str, Any], signal_chain_index: dict[str, Any]) -> dict[str, Any]:
    reliable_refs = {str(item.get("route_ref") or "") for item in list(route_index.get("reliable_routes") or [])}
    all_route_refs = reliable_refs | {str(item.get("route_ref") or "") for item in list(route_index.get("unresolved_routes") or [])}
    signals: list[dict[str, Any]] = []
    for route in list(route_index.get("unresolved_routes") or []):
        ref = str(route.get("route_ref") or "")
        if ref and not _external_ref(ref):
            signals.append(_audit_signal("route:" + ref, "warning", "unresolved_route_ref", "Route ref cannot be resolved to a physical landing point.", ref=ref))
    seen_edges: set[str] = set()
    for edge in list(model.get("edges") or []):
        edge_id = str(edge.get("edge_id") or "")
        if edge_id in seen_edges:
            signals.append(_audit_signal(edge_id, "warning", "duplicate_edge", "Duplicate signal edge was deduped in the signal-chain index."))
            continue
        seen_edges.add(edge_id)
        status = _edge_status(edge)
        evidence_refs = _strings(edge.get("evidence_refs"))
        anchor_refs = _strings(edge.get("anchor_refs"))
        if status == "accepted" and not evidence_refs:
            signals.append(_audit_signal(edge_id, "error", "accepted_edge_missing_evidence", "Accepted edge has no evidence refs."))
        if status == "accepted" and not anchor_refs:
            signals.append(_audit_signal(edge_id, "warning", "accepted_edge_missing_anchor", "Accepted edge has no anchor refs."))
        for role, ref in (("source", str(edge.get("source_ref") or "")), ("target", str(edge.get("target_ref") or ""))):
            if ref and ref not in all_route_refs and not _external_ref(ref):
                validation = _validate_physical_ref(ref, layout=model["layout"])
                if validation.get("status") == "resolved":
                    signals.append(
                        _audit_signal(
                            edge_id,
                            "info",
                            f"out_of_scope_{role}_ref",
                            f"{role}_ref resolves to a physical file but was not included as a semantic route card in this build.",
                            ref=ref,
                            details=validation,
                        )
                    )
                else:
                    signals.append(
                        _audit_signal(
                            edge_id,
                            "warning",
                            f"unknown_{role}_ref",
                            f"{role}_ref is neither present in semantic route cards nor physically resolvable.",
                            ref=ref,
                            details=validation,
                        )
                    )
            if ref and ref not in reliable_refs and ref in all_route_refs:
                signals.append(_audit_signal(edge_id, "info", f"unreliable_{role}_route", f"{role}_ref exists only as an unresolved route.", ref=ref))
        if "candidate" in status:
            signals.append(_audit_signal(edge_id, "info", "candidate_relation_needs_resolution", "Candidate relation should be confirmed by relation tracing or chain review."))
        if "conflict" in status:
            signals.append(_audit_signal(edge_id, "warning", "conflict_signal_present", "Conflict signal requires curator or parent-layer resolution."))
    return {
        "authority": "project_network_system.link_signal_audit",
        "control_plane": "link_signal_quality_audit",
        "purpose": "quality gate for signal-chain trust and route reliability",
        "build_id": model["build_id"],
        "generated_at": model["generated_at"],
        "summary": {
            "reliable_route_count": len(list(route_index.get("reliable_routes") or [])),
            "unresolved_route_count": len(list(route_index.get("unresolved_routes") or [])),
            "signal_chain_count": len(list(signal_chain_index.get("chains") or [])),
            "audit_signal_count": len(signals),
            "error_count": sum(1 for item in signals if item.get("severity") == "error"),
            "warning_count": sum(1 for item in signals if item.get("severity") == "warning"),
            "info_count": sum(1 for item in signals if item.get("severity") == "info"),
        },
        "signals": signals,
    }


def _write_file_reports(*, module_cards: list[dict[str, Any]], artifact_root: Path, human_root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for card in module_cards:
        name = _safe_segment(str(card.get("stable_ref") or card.get("file_path") or "file"))
        text = _render_file_report(card)
        artifact_md = artifact_root / f"{name}.review.md"
        artifact_json = artifact_root / f"{name}.semantic.json"
        human_md = human_root / f"{name}.review.md"
        _write_text(artifact_md, text)
        _write_json(artifact_json, card)
        _write_text(human_md, text)
        result.append({"stable_ref": card.get("stable_ref"), "artifact_report_path": str(artifact_md), "artifact_semantic_path": str(artifact_json), "human_report_path": str(human_md)})
    return result


def _write_directory_reports(*, directory_cards: list[dict[str, Any]], artifact_root: Path, human_root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for card in directory_cards:
        name = _safe_segment(str(card.get("stable_ref") or "directory"))
        text = _render_directory_report(card)
        artifact_md = artifact_root / f"{name}.summary.md"
        artifact_json = artifact_root / f"{name}.semantic.json"
        human_md = human_root / f"{name}.summary.md"
        _write_text(artifact_md, text)
        _write_json(artifact_json, card)
        _write_text(human_md, text)
        result.append({"stable_ref": card.get("stable_ref"), "artifact_report_path": str(artifact_md), "artifact_semantic_path": str(artifact_json), "human_report_path": str(human_md)})
    return result


def _write_layer_reports(*, unified_control_graph: dict[str, Any], artifact_root: Path, human_root: Path) -> list[dict[str, Any]]:
    nodes = [dict(item) for item in list(unified_control_graph.get("nodes") or []) if isinstance(item, dict)]
    edges = [dict(item) for item in list(unified_control_graph.get("edges") or []) if isinstance(item, dict)]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        layer = str(dict(node.get("semantic_facets") or {}).get("layer") or _layer_from_node_kind(dict(node.get("identity") or {}).get("node_kind")) or "semantic")
        grouped.setdefault(layer, []).append(node)
    result: list[dict[str, Any]] = []
    for layer, layer_nodes in sorted(grouped.items()):
        layer_edges = _edges_touching_nodes(edges, layer_nodes)
        text = _render_layer_report(layer, layer_nodes=layer_nodes, layer_edges=layer_edges, graph=unified_control_graph)
        name = _safe_segment(f"layer-{layer}")
        artifact_md = artifact_root / f"{name}.md"
        artifact_json = artifact_root / f"{name}.json"
        human_md = human_root / f"{name}.md"
        _write_text(artifact_md, text)
        _write_json(
            artifact_json,
            {
                "layer": layer,
                "nodes": layer_nodes,
                "edges": layer_edges,
                "authority": "project_network_system.layer_report_payload",
            },
        )
        _write_text(human_md, text)
        result.append(
            {
                "layer": layer,
                "node_count": len(layer_nodes),
                "edge_count": len(layer_edges),
                "artifact_report_path": str(artifact_md),
                "artifact_semantic_path": str(artifact_json),
                "human_report_path": str(human_md),
            }
        )
    return result


def _render_project_network_review(model: dict[str, Any], *, file_reports: list[dict[str, Any]], directory_reports: list[dict[str, Any]], link_audit: dict[str, Any]) -> str:
    audit_summary = dict(link_audit.get("summary") or {})
    lines = [
        "# Project Network Review",
        "",
        f"- build_id: `{model.get('build_id')}`",
        f"- generated_at: `{model.get('generated_at')}`",
        f"- source_work_products: {len(list(model.get('source_work_products') or []))}",
        f"- file_reports: {len(file_reports)}",
        f"- directory_reports: {len(directory_reports)}",
        f"- reliable_routes: {audit_summary.get('reliable_route_count', 0)}",
        f"- unresolved_routes: {audit_summary.get('unresolved_route_count', 0)}",
        f"- audit_warnings: {audit_summary.get('warning_count', 0)}",
        "",
        "## Directory Summaries",
        "",
    ]
    if not directory_reports:
        lines.append("- No directory reports.")
    for item in directory_reports:
        lines.append(f"- `{item.get('stable_ref')}` -> `{_relative(item.get('human_report_path'), model['layout'].project_root)}`")
    lines.extend(["", "## File Reviews", ""])
    if not file_reports:
        lines.append("- No file reports.")
    for item in file_reports:
        lines.append(f"- `{item.get('stable_ref')}` -> `{_relative(item.get('human_report_path'), model['layout'].project_root)}`")
    lines.extend(["", "## Audit Summary", ""])
    for key, value in audit_summary.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines).rstrip() + "\n"


def _render_project_architecture_overview(
    model: dict[str, Any],
    *,
    unified_control_graph: dict[str, Any],
    link_audit: dict[str, Any],
) -> str:
    nodes = [dict(item) for item in list(unified_control_graph.get("nodes") or []) if isinstance(item, dict)]
    edges = [_graph_edge(item) for item in list(unified_control_graph.get("edges") or []) if isinstance(item, dict)]
    edges = [item for item in edges if item]
    node_lookup = {_graph_node_ref(node): node for node in nodes if _graph_node_ref(node)}
    top_systems = _top_level_system_nodes(nodes)
    top_system_refs = {_display_path_from_ref(_graph_node_ref(node)) for node in top_systems}
    cross_system_edges = _cross_system_edges(edges, known_systems=top_system_refs)
    audit_summary = dict(link_audit.get("summary") or {})
    lines = [
        "# Project Architecture Overview",
        "",
        f"- build_id: `{model.get('build_id')}`",
        f"- generated_at: `{model.get('generated_at')}`",
        f"- top_level_systems: {len(top_systems)}",
        f"- nodes: {len(nodes)}",
        f"- edges: {len(edges)}",
        f"- accepted_edges: {audit_summary.get('accepted_edge_count', 0) or dict(unified_control_graph.get('summary') or {}).get('accepted_edge_count', 0)}",
        f"- candidate_edges: {audit_summary.get('candidate_edge_count', 0) or dict(unified_control_graph.get('summary') or {}).get('candidate_edge_count', 0)}",
        f"- audit_warnings: {audit_summary.get('warning_count', 0)}",
        "",
        "## Control Layers",
        "",
        "- physical_skeleton: directory, file, and symbol refs are the landing authority.",
        "- semantic_overlay: labels, summaries, tags, and control roles explain what each landing point means.",
        "- signal_chain: accepted and candidate edges explain how modules, APIs, IPC, stores, and symbols relate.",
        "- agent_control: navigation starts from a physical ref, uses semantic intent to select the next landing point, and treats candidate edges as repair targets.",
        "",
        "## Top-Level Systems",
        "",
    ]
    if not top_systems:
        lines.append("- No top-level system nodes were materialized.")
    for node in top_systems:
        ref = _graph_node_ref(node)
        semantic = dict(node.get("semantic_facets") or {})
        children = _direct_child_edges(edges, ref)
        child_refs = [str(item.get("target_ref") or "") for item in children]
        child_nodes = [node_lookup.get(child_ref) for child_ref in child_refs if child_ref in node_lookup]
        child_dirs = [item for item in child_nodes if item and _graph_node_kind(item) in {"directory", "system_root"}]
        child_files = [item for item in child_nodes if item and _graph_node_kind(item) == "file_module"]
        lines.extend(
            [
                f"### {semantic.get('label') or _display_path_from_ref(ref) or ref}",
                "",
                f"- ref: `{ref}`",
                f"- role: {semantic.get('control_role') or '-'}",
                f"- summary: {semantic.get('summary') or '-'}",
                f"- direct_child_directories: {len(child_dirs)}",
                f"- direct_child_files: {len(child_files)}",
            ]
        )
        important_children = [item for item in child_nodes if item][:10]
        if important_children:
            lines.extend(["", "Key child landing points:"])
            for child in important_children:
                child_ref = _graph_node_ref(child)
                child_semantic = dict(child.get("semantic_facets") or {})
                lines.append(f"- `{child_ref}` [{_graph_node_kind(child)}] {child_semantic.get('label') or _display_path_from_ref(child_ref)}")
        lines.append("")
    lines.extend(["## Cross-System Signals", ""])
    if not cross_system_edges:
        lines.append("- No cross-system signal edges were materialized.")
    for edge in cross_system_edges[:40]:
        lines.append(
            f"- `{edge.get('source_ref')}` -> `{edge.get('target_ref')}` "
            f"via `{edge.get('edge_kind')}` [{edge.get('status')}] {edge.get('summary') or ''}"
        )
    signals = [dict(item) for item in list(link_audit.get("signals") or []) if isinstance(item, dict)]
    grouped_signals = _count_by(signals, lambda item: str(item.get("code") or "unknown"))
    lines.extend(["", "## Known Gaps", ""])
    if not grouped_signals:
        lines.append("- No audit signals.")
    for code, count in sorted(grouped_signals.items(), key=lambda item: (-item[1], item[0]))[:20]:
        lines.append(f"- {code}: {count}")
    lines.extend(
        [
            "",
            "## Navigation Contract",
            "",
            "- For a project-level question, start here, then jump to the top-level system directory report.",
            "- For a feature question, use `project_network.locate` first, then `trace` the selected file or symbol.",
            "- Treat accepted edges as readable routes; treat candidate or unknown refs as maintenance work, not trusted architecture.",
            "- When a candidate bridge blocks understanding, queue a repair against the source and target refs instead of guessing.",
            "",
            "## Detail Report Entry Points",
            "",
            "- reports_index: `PROJECT_NETWORK_REPORTS/README.md`",
            "- directory_reports: `PROJECT_NETWORK_REPORTS/directories/`",
            "- file_reports: `PROJECT_NETWORK_REPORTS/files/`",
            "- layer_reports: `PROJECT_NETWORK_REPORTS/layers/`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_unified_control_graph_report(
    unified_control_graph: dict[str, Any],
    *,
    layer_reports: list[dict[str, Any]],
    file_reports: list[dict[str, Any]],
    directory_reports: list[dict[str, Any]],
) -> str:
    summary = dict(unified_control_graph.get("summary") or {})
    nodes = [dict(item) for item in list(unified_control_graph.get("nodes") or []) if isinstance(item, dict)]
    edges = [dict(item) for item in list(unified_control_graph.get("edges") or []) if isinstance(item, dict)]
    layers = _count_by(nodes, lambda item: str(dict(item.get("semantic_facets") or {}).get("layer") or "semantic"))
    kinds = _count_by(nodes, lambda item: str(dict(item.get("identity") or {}).get("node_kind") or "unknown"))
    edge_status = _count_by(edges, lambda item: str(dict(item.get("semantic_facets") or {}).get("status") or "unknown"))
    audit_signals = _collect_control_graph_signals(nodes, edges)
    lines = [
        "# Project Unified Control Graph",
        "",
        f"- build_id: `{unified_control_graph.get('build_id')}`",
        f"- generated_at: `{unified_control_graph.get('generated_at')}`",
        f"- node_count: {summary.get('node_count', len(nodes))}",
        f"- edge_count: {summary.get('edge_count', len(edges))}",
        f"- accepted_edge_count: {summary.get('accepted_edge_count', 0)}",
        f"- candidate_edge_count: {summary.get('candidate_edge_count', 0)}",
        f"- audit_signal_count: {summary.get('audit_signal_count', len(audit_signals))}",
        "",
        "## Layer Reports",
        "",
    ]
    if not layer_reports:
        lines.append("- No layer reports.")
    for item in layer_reports:
        lines.append(f"- `{item.get('layer')}` nodes={item.get('node_count', 0)} edges={item.get('edge_count', 0)} -> `{_relative(item.get('human_report_path'), Path.cwd())}`")
    lines.extend(["", "## Node Layers", ""])
    lines.extend(f"- {key}: {value}" for key, value in layers.items())
    lines.extend(["", "## Node Kinds", ""])
    lines.extend(f"- {key}: {value}" for key, value in kinds.items())
    lines.extend(["", "## Edge Status", ""])
    lines.extend(f"- {key}: {value}" for key, value in edge_status.items())
    lines.extend(["", "## Human Detail Reports", ""])
    lines.append(f"- directory_reports: {len(directory_reports)}")
    lines.append(f"- file_reports: {len(file_reports)}")
    if audit_signals:
        lines.extend(["", "## Highest Priority Audit Signals", ""])
        for signal in audit_signals[:50]:
            lines.append(f"- [{signal.get('severity')}] {signal.get('code')} `{signal.get('ref') or signal.get('subject_ref') or signal.get('edge_id')}`")
    return "\n".join(lines).rstrip() + "\n"


def _render_reports_index(
    model: dict[str, Any],
    *,
    file_reports: list[dict[str, Any]],
    directory_reports: list[dict[str, Any]],
    layer_reports: list[dict[str, Any]],
    root_reports: dict[str, Path],
) -> str:
    project_root = model["layout"].project_root
    lines = [
        "# Project Network Reports",
        "",
        f"- build_id: `{model.get('build_id')}`",
        f"- generated_at: `{model.get('generated_at')}`",
        "",
        "## Root Reports",
        "",
    ]
    for title, path in root_reports.items():
        lines.append(f"- {title}: `{_relative(path, project_root)}`")
    lines.extend(["", "## Layer Reports", ""])
    for item in layer_reports:
        lines.append(f"- `{item.get('layer')}` nodes={item.get('node_count', 0)} edges={item.get('edge_count', 0)} -> `{_relative(item.get('human_report_path'), project_root)}`")
    directory_groups = _group_report_refs_by_top_level(directory_reports)
    file_groups = _group_report_refs_by_top_level(file_reports)
    lines.extend(["", "## Report Inventory By System", ""])
    for system in sorted(set(directory_groups) | set(file_groups)):
        lines.append(f"- `{system}` directories={len(directory_groups.get(system, []))} files={len(file_groups.get(system, []))}")
    lines.extend(["", "## Top Directory Reports", ""])
    if not directory_reports:
        lines.append("- No directory summary reports have been accepted yet.")
    for item in _prioritized_report_entries(directory_reports, max_items=80):
        lines.append(f"- `{item.get('stable_ref')}` -> `{_relative(item.get('human_report_path'), project_root)}`")
    lines.extend(["", "## File Report Groups", ""])
    if not file_reports:
        lines.append("- No file review reports have been accepted yet.")
    for system, items in sorted(file_groups.items()):
        sample = ", ".join(f"`{item.get('stable_ref')}`" for item in items[:8])
        suffix = " ..." if len(items) > 8 else ""
        lines.append(f"- `{system}` ({len(items)} files): {sample}{suffix}")
    lines.extend(["", "## Detail Report Folders", ""])
    lines.append("- directory report folder: `PROJECT_NETWORK_REPORTS/directories/`")
    lines.append("- file report folder: `PROJECT_NETWORK_REPORTS/files/`")
    return "\n".join(lines).rstrip() + "\n"


def _render_layer_report(layer: str, *, layer_nodes: list[dict[str, Any]], layer_edges: list[dict[str, Any]], graph: dict[str, Any]) -> str:
    lines = [
        f"# Project Network Layer: {layer}",
        "",
        f"- build_id: `{graph.get('build_id')}`",
        f"- node_count: {len(layer_nodes)}",
        f"- edge_count: {len(layer_edges)}",
        "",
        "## Nodes",
        "",
    ]
    for node in sorted(layer_nodes, key=lambda item: _node_report_key(item))[:300]:
        identity = dict(node.get("identity") or {})
        semantic = dict(node.get("semantic_facets") or {})
        physical = dict(node.get("physical_facts") or {})
        validation = dict(physical.get("physical_validation") or {})
        lines.append(
            f"- `{identity.get('stable_ref') or node.get('stable_ref')}` "
            f"[{identity.get('node_kind') or '-'}; {validation.get('status') or 'unvalidated'}] "
            f"{semantic.get('label') or ''}: {semantic.get('summary') or ''}"
        )
    lines.extend(["", "## Edges", ""])
    for edge in sorted(layer_edges, key=lambda item: str(item.get("edge_id") or ""))[:300]:
        identity = dict(edge.get("identity") or {})
        semantic = dict(edge.get("semantic_facets") or {})
        lines.append(
            f"- `{identity.get('source_ref')}` -> `{identity.get('target_ref')}` "
            f"via `{semantic.get('edge_kind') or ''}` [{semantic.get('status') or ''}] {semantic.get('summary') or ''}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_semantic_coordinates_report(coordinates: dict[str, Any]) -> str:
    summary = dict(coordinates.get("summary") or {})
    lines = [
        "# Project Semantic Coordinates",
        "",
        f"- build_id: `{coordinates.get('build_id')}`",
        f"- generated_at: `{coordinates.get('generated_at')}`",
        f"- coordinate_count: {summary.get('coordinate_count', 0)}",
        "",
        "## Coordinates",
        "",
    ]
    for item in list(coordinates.get("coordinates") or []):
        lines.extend(
            [
                f"### {item.get('label') or item.get('coordinate_ref')}",
                "",
                f"- coordinate_ref: `{item.get('coordinate_ref')}`",
                f"- physical_ref: `{item.get('physical_ref')}`",
                f"- layer: {item.get('layer')}",
                f"- control_role: {item.get('control_role') or '-'}",
                f"- summary: {item.get('summary') or ''}",
                f"- tags: {', '.join(_strings(item.get('tags'))) or '-'}",
                f"- confidence: {item.get('confidence') or '-'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _graph_node_ref(node: dict[str, Any]) -> str:
    identity = dict(node.get("identity") or {})
    return str(identity.get("stable_ref") or node.get("stable_ref") or node.get("node_id") or "").strip()


def _graph_node_kind(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    return str(dict(node.get("identity") or {}).get("node_kind") or "").strip()


def _graph_edge(edge: dict[str, Any]) -> dict[str, Any]:
    identity = dict(edge.get("identity") or {})
    semantic = dict(edge.get("semantic_facets") or {})
    source_ref = str(identity.get("source_ref") or "").strip()
    target_ref = str(identity.get("target_ref") or "").strip()
    if not source_ref or not target_ref or source_ref.lower() in {"none", "null"} or target_ref.lower() in {"none", "null"}:
        return {}
    return _drop_empty(
        {
            "edge_id": str(edge.get("edge_id") or identity.get("edge_id") or ""),
            "source_ref": source_ref,
            "target_ref": target_ref,
            "edge_kind": str(semantic.get("edge_kind") or ""),
            "summary": str(semantic.get("summary") or ""),
            "status": str(semantic.get("status") or ""),
            "confidence": str(semantic.get("confidence") or ""),
        }
    )


def _top_level_system_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        ref = _graph_node_ref(node)
        if not ref.startswith("folder://") or ref == "folder://.":
            continue
        raw = ref[len("folder://") :].replace("\\", "/").strip("/")
        if raw and "/" not in raw:
            result.append(node)
    preferred = {"AGENT": 0, "CLIENT": 1, "TASK": 2, "MEMORY": 3, "FILE": 4, "README": 5}
    return sorted(result, key=lambda item: (preferred.get(_display_path_from_ref(_graph_node_ref(item)), 50), _display_path_from_ref(_graph_node_ref(item))))


def _direct_child_edges(edges: list[dict[str, Any]], parent_ref: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if str(edge.get("source_ref") or "") != parent_ref:
            continue
        if str(edge.get("edge_kind") or "") not in {"contains", "contains_file", "contains_directory", "owns", "ownership"}:
            continue
        target_ref = str(edge.get("target_ref") or "")
        if target_ref and target_ref not in result:
            result[target_ref] = edge
    return sorted(result.values(), key=lambda item: str(item.get("target_ref") or ""))


def _cross_system_edges(edges: list[dict[str, Any]], *, known_systems: set[str]) -> list[dict[str, Any]]:
    result = []
    for edge in edges:
        source_system = _top_level_ref_segment(str(edge.get("source_ref") or ""))
        target_system = _top_level_ref_segment(str(edge.get("target_ref") or ""))
        if source_system not in known_systems or target_system not in known_systems:
            continue
        if not source_system or not target_system or source_system == target_system:
            continue
        if str(edge.get("edge_kind") or "").startswith("contains"):
            continue
        result.append(edge)
    status_rank = {"accepted": 0, "candidate": 1, "conflict": 2}
    return sorted(result, key=lambda item: (status_rank.get(str(item.get("status") or ""), 9), str(item.get("source_ref") or ""), str(item.get("target_ref") or "")))


def _top_level_ref_segment(ref: str) -> str:
    target = str(ref or "")
    if "://" in target:
        target = target.split("://", 1)[1]
    target = target.split("#", 1)[0].replace("\\", "/").strip("/")
    if target in {"", "."}:
        return "."
    return target.split("/", 1)[0]


def _group_report_refs_by_top_level(reports: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in reports:
        system = _top_level_ref_segment(str(item.get("stable_ref") or "")) or "unknown"
        grouped.setdefault(system, []).append(item)
    return {key: sorted(value, key=lambda item: str(item.get("stable_ref") or "")) for key, value in grouped.items()}


def _prioritized_report_entries(reports: list[dict[str, Any]], *, max_items: int) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, str]:
        ref = str(item.get("stable_ref") or "")
        path = ref.split("://", 1)[1] if "://" in ref else ref
        path = path.replace("\\", "/").strip("/")
        depth = 0 if path in {"", "."} else len([part for part in path.split("/") if part])
        return (depth, ref)

    return sorted(reports, key=key)[:max(1, max_items)]


def _render_signal_chain_review(signal_chain_index: dict[str, Any], link_audit: dict[str, Any]) -> str:
    summary = dict(signal_chain_index.get("summary") or {})
    audit_summary = dict(link_audit.get("summary") or {})
    lines = [
        "# Project Signal Chain Review",
        "",
        f"- build_id: `{signal_chain_index.get('build_id')}`",
        f"- generated_at: `{signal_chain_index.get('generated_at')}`",
        f"- chain_count: {summary.get('chain_count', 0)}",
        f"- accepted_edges: {summary.get('accepted_edge_count', 0)}",
        f"- candidate_edges: {summary.get('candidate_edge_count', 0)}",
        f"- conflict_edges: {summary.get('conflict_edge_count', 0)}",
        f"- audit_signals: {audit_summary.get('audit_signal_count', 0)}",
        "",
        "## Chains",
        "",
    ]
    for chain in list(signal_chain_index.get("chains") or []):
        lines.extend(
            [
                f"### {chain.get('source_label') or chain.get('source_ref')}",
                "",
                f"- source_ref: `{chain.get('source_ref')}`",
                f"- outgoing_count: {chain.get('outgoing_count', 0)}",
                f"- accepted_count: {chain.get('accepted_count', 0)}",
                f"- candidate_count: {chain.get('candidate_count', 0)}",
                f"- conflict_count: {chain.get('conflict_count', 0)}",
                "",
            ]
        )
        for edge in list(chain.get("outgoing") or [])[:12]:
            lines.append(f"- `{edge.get('edge_kind')}` -> `{edge.get('target_ref')}` [{edge.get('status')}]")
        lines.append("")
    if link_audit.get("signals"):
        lines.extend(["## Audit Signals", ""])
        for signal in list(link_audit.get("signals") or [])[:80]:
            lines.append(f"- [{signal.get('severity')}] {signal.get('code')} `{signal.get('ref') or signal.get('subject_ref') or signal.get('edge_id')}`")
    return "\n".join(lines).rstrip() + "\n"


def _render_file_report(card: dict[str, Any]) -> str:
    coordinate = dict(card.get("semantic_coordinate") or {})
    lines = [
        f"# File Review: {coordinate.get('label') or card.get('stable_ref')}",
        "",
        f"- file_ref: `{card.get('stable_ref')}`",
        f"- file_path: `{card.get('file_path') or ''}`",
        f"- file_hash: `{card.get('file_hash') or ''}`",
        f"- physical_status: {dict(card.get('physical_binding') or {}).get('resolution_status') or '-'}",
        f"- confidence: {coordinate.get('confidence') or '-'}",
        "",
        "## Semantic Coordinate",
        "",
        f"- summary: {coordinate.get('summary') or card.get('module_summary') or ''}",
        f"- control_role: {coordinate.get('control_role') or '-'}",
        f"- tags: {', '.join(_strings(coordinate.get('tags'))) or '-'}",
        "",
        "## IO Surface",
        "",
    ]
    io_surface = dict(card.get("io_surface") or {})
    if io_surface:
        for key, value in io_surface.items():
            lines.append(f"- {key}: {_short(value)}")
    else:
        lines.append("- Not declared.")
    lines.extend(["", "## Control Nodes", ""])
    for node in list(card.get("nodes") or [])[:80]:
        lines.append(f"- `{node.get('stable_ref')}` [{node.get('node_kind')}] {_node_status_text(node)} {node.get('name') or node.get('responsibility') or ''}")
    lines.extend(["", "## Signal Edges", ""])
    for edge in [*list(card.get("edges") or []), *list(card.get("relation_candidates") or [])][:80]:
        lines.append(f"- `{edge.get('source_ref')}` -> `{edge.get('target_ref')}` via `{edge.get('edge_kind')}` {_edge_report_text(edge)}")
    if card.get("limitations"):
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {item}" for item in _strings(card.get("limitations")))
    return "\n".join(lines).rstrip() + "\n"


def _render_directory_report(card: dict[str, Any]) -> str:
    coordinate = dict(card.get("semantic_coordinate") or {})
    lines = [
        f"# Directory Summary: {coordinate.get('label') or card.get('stable_ref')}",
        "",
        f"- folder_ref: `{card.get('stable_ref')}`",
        f"- directory_frame_id: `{card.get('directory_frame_id') or ''}`",
        f"- physical_status: {dict(card.get('physical_binding') or {}).get('resolution_status') or '-'}",
        f"- confidence: {coordinate.get('confidence') or '-'}",
        "",
        "## Semantic Coordinate",
        "",
        f"- summary: {coordinate.get('summary') or card.get('directory_summary') or ''}",
        f"- control_role: {coordinate.get('control_role') or '-'}",
        f"- tags: {', '.join(_strings(coordinate.get('tags'))) or '-'}",
        "",
        "## Child Coverage",
        "",
        f"- direct_module_refs: {len(list(card.get('direct_module_refs') or []))}",
        f"- child_summary_refs: {len(list(card.get('child_summary_refs') or []))}",
        f"- uncovered_refs: {len(list(card.get('uncovered_refs') or []))}",
        "",
        "## Directory Nodes",
        "",
    ]
    for node in list(card.get("nodes") or [])[:100]:
        lines.append(f"- `{node.get('stable_ref')}` [{node.get('node_kind')}] {_node_status_text(node)} {node.get('name') or node.get('responsibility') or ''}")
    lines.extend(["", "## Directory Signals", ""])
    for edge in [*list(card.get("edges") or []), *list(card.get("accepted_relation_candidates") or []), *list(card.get("conflicts") or [])][:100]:
        lines.append(f"- `{edge.get('source_ref')}` -> `{edge.get('target_ref')}` via `{edge.get('edge_kind')}` {_edge_report_text(edge)}")
    return "\n".join(lines).rstrip() + "\n"


def _node_status_text(node: dict[str, Any]) -> str:
    validation = dict(node.get("physical_validation") or {})
    status = str(validation.get("status") or "unvalidated")
    basis = str(validation.get("basis") or "")
    return f"[{status}/{basis}]" if basis else f"[{status}]"


def _edge_report_text(edge: dict[str, Any]) -> str:
    return (
        f"[{_edge_status(edge)}; "
        f"evidence={len(_strings(edge.get('evidence_refs')))}; "
        f"anchors={len(_strings(edge.get('anchor_refs')))}]"
    )


def _edges_touching_nodes(edges: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = {
        str(dict(node.get("identity") or {}).get("stable_ref") or node.get("stable_ref") or "")
        for node in nodes
        if isinstance(node, dict)
    }
    result = []
    for edge in edges:
        identity = dict(edge.get("identity") or {})
        if str(identity.get("source_ref") or "") in refs or str(identity.get("target_ref") or "") in refs:
            result.append(edge)
    return result


def _layer_from_node_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    if kind in {"system_root", "repository", "workspace"}:
        return "system"
    if "directory" in kind or "folder" in kind:
        return "directory"
    if "file" in kind or "module" in kind:
        return "file"
    if kind:
        return _coordinate_layer(kind)
    return "semantic"


def _count_by(items: list[dict[str, Any]], key_fn: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        key = str(key_fn(item) or "unknown")
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _collect_control_graph_signals(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for node in nodes:
        signals.extend(dict(item) for item in list(dict(node.get("control_surface") or {}).get("audit_signals") or []) if isinstance(item, dict))
    for edge in edges:
        signals.extend(dict(item) for item in list(dict(edge.get("control_surface") or {}).get("audit_signals") or []) if isinstance(item, dict))
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    deduped = _dedupe_by_key(signals, key="code")
    return sorted(deduped, key=lambda item: (severity_rank.get(str(item.get("severity") or ""), 9), str(item.get("code") or ""), str(item.get("ref") or "")))


def _node_report_key(node: dict[str, Any]) -> str:
    identity = dict(node.get("identity") or {})
    semantic = dict(node.get("semantic_facets") or {})
    return "|".join(
        [
            str(semantic.get("layer") or ""),
            str(identity.get("node_kind") or ""),
            str(identity.get("stable_ref") or node.get("stable_ref") or ""),
        ]
    )


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


def _label(value: Any, *, fallback_ref: str, fallback_kind: str) -> dict[str, Any]:
    raw = dict(value or {}) if isinstance(value, dict) else ({"label": str(value)} if isinstance(value, str) and value.strip() else {})
    return _drop_empty(
        {
            **raw,
            "stable_ref": str(raw.get("stable_ref") or fallback_ref or "").strip(),
            "node_kind": str(raw.get("node_kind") or fallback_kind or "").strip(),
            "label": str(raw.get("label") or raw.get("name") or fallback_ref or "").strip(),
            "summary": str(raw.get("summary") or "").strip(),
            "tags": _strings(raw.get("tags") or raw.get("intent_tags")),
            "evidence_refs": _strings(raw.get("evidence_refs")),
            "anchor_refs": _strings(raw.get("anchor_refs") or raw.get("anchor_ref")),
            "confidence": str(raw.get("confidence") or "derived").strip(),
        }
    )


def _physical_binding(value: Any, *, stable_ref: str, path: str, file_hash: str, layout: ProjectLayout, binding_kind: str) -> dict[str, Any]:
    binding = dict(value or {}) if isinstance(value, dict) else {}
    ref = str(binding.get("stable_ref") or binding.get("physical_ref") or stable_ref or "").strip()
    validation = _validate_physical_ref(
        ref,
        layout=layout,
        path_hint=path,
        evidence_refs=_strings(binding.get("evidence_refs")),
        anchor_refs=_strings(binding.get("anchor_refs") or binding.get("anchor_ref")),
    )
    return _drop_empty(
        {
            **binding,
            "stable_ref": ref,
            "physical_ref": ref,
            "path": str(binding.get("path") or path or validation.get("path") or "").strip(),
            "file_hash": str(binding.get("file_hash") or file_hash or "").strip(),
            "binding_kind": str(binding.get("binding_kind") or binding_kind or "").strip(),
            "resolution_status": validation.get("status"),
            "resolution_basis": validation.get("basis"),
            "authority": "project_network_system.physical_binding",
        }
    )


def _semantic_coordinate(
    value: Any,
    *,
    stable_ref: str,
    layer: str,
    label: dict[str, Any],
    summary: str,
    source_product: GraphBuildWorkProductEnvelope,
    physical_binding: dict[str, Any],
) -> dict[str, Any]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    coordinate_ref = str(raw.get("coordinate_ref") or raw.get("stable_ref") or stable_ref or "").strip()
    declared_physical_ref = _normalize_physical_ref_scheme(str(raw.get("physical_ref") or "").strip())
    physical_ref = _normalize_physical_ref_scheme(str(stable_ref or declared_physical_ref or "").strip())
    binding_warnings = _strings(raw.get("binding_warnings"))
    if declared_physical_ref and physical_ref and declared_physical_ref != physical_ref:
        binding_warnings.append("physical_ref_normalized_to_authoritative_stable_ref")
    tags = _strings(raw.get("tags")) or _strings(label.get("tags"))
    return _drop_empty(
        {
            **raw,
            "coordinate_ref": coordinate_ref,
            "physical_ref": physical_ref,
            "declared_physical_ref": declared_physical_ref if declared_physical_ref and declared_physical_ref != physical_ref else "",
            "binding_warnings": _dedupe_strings(binding_warnings),
            "layer": str(raw.get("layer") or layer or "").strip(),
            "label": str(raw.get("label") or label.get("label") or stable_ref or "").strip(),
            "summary": str(raw.get("summary") or summary or label.get("summary") or "").strip(),
            "tags": tags,
            "control_role": str(raw.get("control_role") or _control_role_from_tags(tags) or "").strip(),
            "entry_refs": _strings(raw.get("entry_refs")),
            "downstream_refs": _strings(raw.get("downstream_refs")),
            "evidence_refs": _strings(raw.get("evidence_refs")) or _strings(label.get("evidence_refs")) or [source_product.work_product_id],
            "anchor_refs": _strings(raw.get("anchor_refs")) or _strings(label.get("anchor_refs")) or _strings(physical_binding.get("physical_ref")),
            "confidence": str(raw.get("confidence") or label.get("confidence") or source_product.confidence or "derived").strip(),
            "source_work_product_id": source_product.work_product_id,
            "authority": "project_network_system.semantic_coordinate",
        }
    )


def _coalesce_semantic_coordinates(coordinates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for coordinate in coordinates:
        item = dict(coordinate or {})
        key = _semantic_coordinate_merge_key(item)
        if not key:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in grouped:
            grouped[key] = _canonical_semantic_coordinate(item, key=key)
            order.append(key)
            continue
        grouped[key] = _merge_semantic_coordinate(grouped[key], item, key=key)
    return [grouped[key] for key in order if grouped.get(key)]


def _semantic_coordinate_merge_key(coordinate: dict[str, Any]) -> str:
    physical_ref = _normalize_physical_ref_scheme(str(coordinate.get("physical_ref") or "").strip())
    if physical_ref:
        return physical_ref
    return _normalize_physical_ref_scheme(str(coordinate.get("coordinate_ref") or "").strip())


def _canonical_semantic_coordinate(coordinate: dict[str, Any], *, key: str) -> dict[str, Any]:
    item = dict(coordinate or {})
    physical_ref = _normalize_physical_ref_scheme(str(item.get("physical_ref") or key or "").strip())
    coordinate_ref = _canonical_coordinate_ref(item, physical_ref=physical_ref)
    return _drop_empty(
        {
            **item,
            "coordinate_ref": coordinate_ref,
            "physical_ref": physical_ref,
            "merged_coordinate_refs": _merged_coordinate_refs(item, coordinate_ref=coordinate_ref),
        }
    )


def _merge_semantic_coordinate(existing: dict[str, Any], incoming: dict[str, Any], *, key: str) -> dict[str, Any]:
    left = dict(existing or {})
    right = dict(incoming or {})
    physical_ref = _normalize_physical_ref_scheme(str(left.get("physical_ref") or right.get("physical_ref") or key or "").strip())
    coordinate_ref = _canonical_coordinate_ref({**right, **left}, physical_ref=physical_ref)
    merged_refs = _dedupe_strings(
        [
            *_strings(left.get("merged_coordinate_refs")),
            *_strings(right.get("merged_coordinate_refs")),
            str(left.get("coordinate_ref") or ""),
            str(right.get("coordinate_ref") or ""),
            coordinate_ref,
        ]
    )
    return _drop_empty(
        {
            **right,
            **{field: value for field, value in left.items() if value not in ("", None, [], {}, ())},
            "coordinate_ref": coordinate_ref,
            "physical_ref": physical_ref,
            "layer": _preferred_coordinate_field(left, right, "layer"),
            "label": _preferred_coordinate_field(left, right, "label"),
            "summary": _preferred_coordinate_field(left, right, "summary"),
            "control_role": _preferred_coordinate_field(left, right, "control_role"),
            "confidence": _preferred_coordinate_field(left, right, "confidence"),
            "tags": _dedupe_strings([*_strings(left.get("tags")), *_strings(right.get("tags"))]),
            "entry_refs": _dedupe_strings([*_strings(left.get("entry_refs")), *_strings(right.get("entry_refs"))]),
            "downstream_refs": _dedupe_strings([*_strings(left.get("downstream_refs")), *_strings(right.get("downstream_refs"))]),
            "evidence_refs": _dedupe_strings([*_strings(left.get("evidence_refs")), *_strings(right.get("evidence_refs"))]),
            "anchor_refs": _dedupe_strings([*_strings(left.get("anchor_refs")), *_strings(right.get("anchor_refs"))]),
            "merged_coordinate_refs": merged_refs,
            "source_work_product_id": _preferred_coordinate_field(left, right, "source_work_product_id"),
            "authority": "project_network_system.semantic_coordinate",
        }
    )


def _canonical_coordinate_ref(coordinate: dict[str, Any], *, physical_ref: str) -> str:
    if physical_ref and not physical_ref.startswith("coordinate://"):
        return physical_ref
    coordinate_ref = _normalize_physical_ref_scheme(str(coordinate.get("coordinate_ref") or "").strip())
    if coordinate_ref:
        return coordinate_ref
    return physical_ref


def _merged_coordinate_refs(coordinate: dict[str, Any], *, coordinate_ref: str) -> list[str]:
    return _dedupe_strings(
        [
            *_strings(coordinate.get("merged_coordinate_refs")),
            str(coordinate.get("coordinate_ref") or ""),
            str(coordinate.get("physical_ref") or ""),
            coordinate_ref,
        ]
    )


def _preferred_coordinate_field(left: dict[str, Any], right: dict[str, Any], field: str) -> Any:
    left_value = left.get(field)
    if left_value not in ("", None, [], {}, ()):
        return left_value
    return right.get(field)


def _node_from_coordinate(coordinate: dict[str, Any], *, product: GraphBuildWorkProductEnvelope, layout: ProjectLayout) -> dict[str, Any]:
    stable_ref = _normalize_physical_ref_scheme(str(coordinate.get("physical_ref") or coordinate.get("coordinate_ref") or "").strip())
    if not stable_ref:
        return {}
    validation = _validate_physical_ref(
        stable_ref,
        layout=layout,
        evidence_refs=_strings(coordinate.get("evidence_refs")),
        anchor_refs=_strings(coordinate.get("anchor_refs")),
    )
    node_kind = _node_kind_from_coordinate_layer(str(coordinate.get("layer") or ""), fallback=product.product_kind)
    return _drop_empty(
        {
            "stable_ref": stable_ref,
            "node_kind": node_kind,
            "name": coordinate.get("label") or stable_ref,
            "responsibility": coordinate.get("summary"),
            "semantic_label": {
                "stable_ref": stable_ref,
                "label": coordinate.get("label") or stable_ref,
                "summary": coordinate.get("summary") or "",
                "tags": _strings(coordinate.get("tags")),
                "evidence_refs": _strings(coordinate.get("evidence_refs")),
                "anchor_refs": _strings(coordinate.get("anchor_refs")),
                "confidence": coordinate.get("confidence") or product.confidence,
            },
            "evidence_refs": _strings(coordinate.get("evidence_refs")),
            "anchor_refs": _strings(coordinate.get("anchor_refs")),
            "confidence": coordinate.get("confidence") or product.confidence,
            "physical_validation": validation,
            "source_products": [_product_card(product)],
        }
    )


def _normalize_node(item: dict[str, Any], *, product: GraphBuildWorkProductEnvelope, layout: ProjectLayout) -> dict[str, Any]:
    label = _label(item.get("semantic_label"), fallback_ref=str(item.get("stable_ref") or item.get("node_ref") or ""), fallback_kind=str(item.get("node_kind") or item.get("kind") or "semantic_node"))
    stable_ref = _normalize_physical_ref_scheme(str(item.get("stable_ref") or item.get("node_ref") or label.get("stable_ref") or "").strip())
    if not stable_ref:
        return {}
    validation = _validate_physical_ref(
        stable_ref,
        layout=layout,
        evidence_refs=_strings(item.get("evidence_refs")) or _strings(label.get("evidence_refs")),
        anchor_refs=_strings(item.get("anchor_refs") or item.get("anchor_ref")) or _strings(label.get("anchor_refs")),
    )
    display_name = str(item.get("name") or item.get("label") or label.get("label") or stable_ref)
    if stable_ref == str(product.stable_ref or "").strip() and str(label.get("label") or "").strip():
        display_name = str(label.get("label") or "").strip()
    return _drop_empty(
        {
            **item,
            "stable_ref": stable_ref,
            "node_kind": str(item.get("node_kind") or item.get("kind") or label.get("node_kind") or "semantic_node"),
            "name": display_name,
            "responsibility": str(item.get("responsibility") or item.get("summary") or label.get("summary") or ""),
            "semantic_label": label,
            "evidence_refs": _strings(item.get("evidence_refs")) or _strings(label.get("evidence_refs")),
            "anchor_refs": _strings(item.get("anchor_refs") or item.get("anchor_ref")) or _strings(label.get("anchor_refs")),
            "confidence": str(item.get("confidence") or label.get("confidence") or "derived"),
            "physical_validation": validation,
            "source_products": [_product_card(product)],
        }
    )


def _normalize_edge(raw: dict[str, Any], *, product: GraphBuildWorkProductEnvelope, signal_kind: str, default_status: str) -> dict[str, Any]:
    source_ref = _normalize_physical_ref_scheme(str(raw.get("source_ref") or raw.get("from_ref") or raw.get("source") or "").strip())
    target_ref = _normalize_physical_ref_scheme(str(raw.get("target_ref") or raw.get("to_ref") or raw.get("target") or "").strip())
    if source_ref.lower() in {"none", "null"}:
        source_ref = ""
    if target_ref.lower() in {"none", "null"}:
        target_ref = ""
    if not source_ref or not target_ref:
        return {}
    return _drop_empty(
        {
            **raw,
            "signal_kind": str(raw.get("signal_kind") or signal_kind),
            "source_ref": source_ref,
            "target_ref": target_ref,
            "edge_kind": str(raw.get("edge_kind") or raw.get("relation_kind") or signal_kind),
            "direction": str(raw.get("direction") or ""),
            "status": str(raw.get("status") or default_status),
            "evidence_refs": _strings(raw.get("evidence_refs")),
            "anchor_refs": _strings(raw.get("anchor_refs") or raw.get("anchor_ref")),
            "confidence": str(raw.get("confidence") or product.confidence or "derived"),
            "limitations": _strings(raw.get("limitations")),
            "summary": str(raw.get("summary") or raw.get("reason") or ""),
            "source_work_product": _product_card(product),
        }
    )


def _merge_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    stable_ref = str(node.get("stable_ref") or "").strip()
    if not stable_ref:
        return
    existing = dict(nodes.get(stable_ref) or {})
    source_products = [*list(existing.get("source_products") or []), *list(node.get("source_products") or [])]
    merged = {
        **node,
        **{key: value for key, value in existing.items() if key not in {"source_products", "evidence_refs", "anchor_refs"}},
        "source_products": _dedupe_by_key(source_products, key="work_product_id"),
        "evidence_refs": sorted(set(_strings(existing.get("evidence_refs")) + _strings(node.get("evidence_refs")))),
        "anchor_refs": sorted(set(_strings(existing.get("anchor_refs")) + _strings(node.get("anchor_refs")))),
        "physical_validation": _best_physical_validation(existing.get("physical_validation"), node.get("physical_validation")),
    }
    nodes[stable_ref] = _drop_empty(merged)


def _coordinate_from_node(stable_ref: str, node: dict[str, Any]) -> dict[str, Any]:
    label = dict(node.get("semantic_label") or {}) if isinstance(node.get("semantic_label"), dict) else {}
    return _drop_empty(
        {
            "coordinate_ref": stable_ref,
            "physical_ref": stable_ref,
            "layer": _coordinate_layer(str(node.get("node_kind") or label.get("node_kind") or "")),
            "label": str(label.get("label") or node.get("name") or stable_ref),
            "summary": str(label.get("summary") or node.get("responsibility") or ""),
            "tags": _strings(label.get("tags")),
            "control_role": _control_role_from_tags(_strings(label.get("tags"))),
            "evidence_refs": _strings(node.get("evidence_refs") or label.get("evidence_refs")),
            "anchor_refs": _strings(node.get("anchor_refs") or label.get("anchor_refs")),
            "confidence": str(node.get("confidence") or label.get("confidence") or "derived"),
            "authority": "project_network_system.semantic_coordinate",
        }
    )


def _route_card(stable_ref: str, node: dict[str, Any]) -> dict[str, Any]:
    label = dict(node.get("semantic_label") or {}) if isinstance(node.get("semantic_label"), dict) else {}
    validation = dict(node.get("physical_validation") or {})
    if not validation:
        validation = {"status": "external" if _external_ref(stable_ref) else "unresolved", "basis": "not_validated"}
    return _drop_empty(
        {
            "route_ref": stable_ref,
            "label": str(label.get("label") or node.get("name") or stable_ref),
            "node_kind": str(node.get("node_kind") or label.get("node_kind") or ""),
            "summary": str(label.get("summary") or node.get("responsibility") or ""),
            "tags": _strings(label.get("tags")),
            "confidence": str(node.get("confidence") or label.get("confidence") or ""),
            "evidence_refs": _strings(node.get("evidence_refs") or label.get("evidence_refs")),
            "anchor_refs": _strings(node.get("anchor_refs") or label.get("anchor_refs")),
            "physical_validation": validation,
            "recommended_next_action": "read_physical_slice" if validation.get("status") == "resolved" else "resolve_or_repair_ref",
        }
    )


def _normalize_physical_ref_scheme(ref: str) -> str:
    value = str(ref or "").strip()
    if value.startswith("folder://"):
        path = value[len("folder://") :]
        path_without_anchor = path.split("#", 1)[0]
        if Path(path_without_anchor).suffix:
            return "file://" + path
    return value


def _chain_card(source_ref: str, edges: list[dict[str, Any]], *, model: dict[str, Any]) -> dict[str, Any]:
    outgoing = [_edge_summary(edge, model=model) for edge in edges]
    statuses = [_edge_status(edge) for edge in edges]
    return _drop_empty(
        {
            "chain_ref": "pnchain:" + content_hash({"build_id": model["build_id"], "source_ref": source_ref})[:20],
            "source_ref": source_ref,
            "source_label": _node_label(model, source_ref),
            "outgoing_count": len(outgoing),
            "accepted_count": sum(1 for status in statuses if status == "accepted"),
            "candidate_count": sum(1 for status in statuses if "candidate" in status),
            "conflict_count": sum(1 for status in statuses if "conflict" in status),
            "edge_kinds": sorted(set(str(edge.get("edge_kind") or "") for edge in edges if str(edge.get("edge_kind") or ""))),
            "outgoing": outgoing,
        }
    )


def _edge_summary(edge: dict[str, Any], *, model: dict[str, Any]) -> dict[str, Any]:
    source_ref = str(edge.get("source_ref") or "")
    target_ref = str(edge.get("target_ref") or "")
    return _drop_empty(
        {
            "edge_id": str(edge.get("edge_id") or ""),
            "source_ref": source_ref,
            "source_label": _node_label(model, source_ref),
            "target_ref": target_ref,
            "target_label": _node_label(model, target_ref),
            "edge_kind": str(edge.get("edge_kind") or ""),
            "status": _edge_status(edge),
            "signal_kind": str(edge.get("signal_kind") or ""),
            "confidence": str(edge.get("confidence") or ""),
            "evidence_count": len(_strings(edge.get("evidence_refs"))),
            "anchor_count": len(_strings(edge.get("anchor_refs"))),
            "limitations": _strings(edge.get("limitations")),
        }
    )


def _node_label(model: dict[str, Any], stable_ref: str) -> str:
    node = dict(dict(model.get("nodes") or {}).get(stable_ref) or {})
    label = dict(node.get("semantic_label") or {}) if isinstance(node.get("semantic_label"), dict) else {}
    return str(label.get("label") or node.get("name") or stable_ref or "")


def _validate_physical_ref(
    ref: str,
    *,
    layout: ProjectLayout,
    path_hint: str = "",
    evidence_refs: tuple[str, ...] | list[str] = (),
    anchor_refs: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    target = str(ref or "").strip()
    if not target:
        return {"status": "unresolved", "basis": "missing_ref"}
    if target == "repo://workspace":
        return {"status": "resolved", "basis": "repo_ref", "path": str(layout.project_root)}
    if _external_ref(target):
        return {"status": "external", "basis": "external_ref"}
    descriptor = _physical_ref_descriptor(target)
    expected = str(descriptor.get("expected") or "path")
    fragment = str(descriptor.get("fragment") or "")
    if bool(descriptor.get("repo_root")) and expected == "directory":
        return _drop_empty(
            {
                "status": "resolved",
                "basis": "workspace_directory_anchor" if fragment else "workspace_directory",
                "path": str(layout.project_root),
                "fragment": fragment,
            }
        )
    candidate_paths: list[str] = []
    rel = str(descriptor.get("rel") or "").strip()
    if rel:
        candidate_paths.append(rel)
        if expected == "file" and _looks_like_filename_only(rel):
            candidate_paths.extend(_project_relative_file_candidates(str(layout.project_root), rel))
    supporting_hints = _supporting_path_hints(
        layout,
        path_hint=path_hint,
        evidence_refs=_strings(evidence_refs),
        anchor_refs=_strings(anchor_refs),
    )
    if not rel:
        candidate_paths.extend(supporting_hints)
    elif _looks_like_filename_only(rel):
        candidate_paths.extend(item for item in supporting_hints if item not in candidate_paths)
    expanded_candidates = list(candidate_paths)
    for candidate in list(candidate_paths):
        if expected == "file" and _looks_like_filename_only(candidate):
            expanded_candidates.extend(_project_relative_file_candidates(str(layout.project_root), candidate))
    candidate_paths = expanded_candidates

    last_unresolved: dict[str, Any] = {}
    for candidate in _dedupe_strings(candidate_paths):
        validation = _validate_project_relative_candidate(
            layout,
            candidate,
            expected=expected,
            fragment=fragment,
        )
        if validation.get("status") == "resolved":
            return validation
        if not last_unresolved:
            last_unresolved = validation
    return last_unresolved or {"status": "unresolved", "basis": "unsupported_ref_scheme"}


def _physical_ref_descriptor(ref: str) -> dict[str, Any]:
    target = str(ref or "").strip()
    if not target:
        return {}
    if target.startswith("file://"):
        rel, fragment = _split_ref_path_and_fragment(target.split("://", 1)[1])
        return {"expected": "file", "rel": rel, "fragment": fragment, "basis": "file_ref"}
    if target.startswith("folder://"):
        rel, fragment = _split_ref_path_and_fragment(target.split("://", 1)[1])
        if rel == ".":
            return {"expected": "directory", "rel": "", "fragment": fragment, "basis": "folder_root_ref", "repo_root": True}
        return {"expected": "directory", "rel": rel, "fragment": fragment, "basis": "folder_ref"}
    if target.startswith("pyast://"):
        rel, fragment = _split_ref_path_and_fragment(target.split("://", 1)[1])
        return {"expected": "file", "rel": rel, "fragment": fragment, "basis": "pyast_ref"}
    if target.startswith("handler://"):
        return _path_suffix_descriptor(target.split("://", 1)[1], expected="file", basis="handler_ref", suffix_split="/api:", fragment_prefix="handler:api:")
    if target.startswith("function://"):
        return _path_suffix_descriptor(target.split("://", 1)[1], expected="file", basis="function_ref", suffix_split="/", fragment_prefix="function:")
    if target.startswith("func://"):
        return _path_suffix_descriptor(target.split("://", 1)[1], expected="file", basis="func_ref", suffix_split="/", fragment_prefix="function:")
    if target.startswith("fn://"):
        return _path_suffix_descriptor(target.split("://", 1)[1], expected="file", basis="fn_ref", suffix_split="/", fragment_prefix="function:")
    if target.startswith("type://"):
        return _path_suffix_descriptor(target.split("://", 1)[1], expected="file", basis="type_ref", suffix_split="/", fragment_prefix="type:")
    if target.startswith("pyvar://"):
        return _path_suffix_descriptor(target.split("://", 1)[1], expected="file", basis="pyvar_ref", suffix_split=":", fragment_prefix="pyvar:")
    if target.startswith("symbol://"):
        raw = target.split("://", 1)[1]
        if "#" not in raw and "/" in raw:
            file_part, symbol_name = raw.rsplit("/", 1)
            if _looks_like_pathish(file_part) and symbol_name and not Path(symbol_name).suffix:
                return {
                    "expected": "file",
                    "rel": file_part,
                    "fragment": _prefixed_fragment(symbol_name, "symbol:"),
                    "basis": "symbol_ref",
                }
        rel, fragment = _split_ref_path_and_fragment(raw)
        if _looks_like_pathish(rel):
            return {
                "expected": "file",
                "rel": rel,
                "fragment": _prefixed_fragment(fragment, "symbol:"),
                "basis": "symbol_ref",
            }
        symbol_name = fragment or rel
        return {
            "expected": "file",
            "rel": rel if _looks_like_filename_only(rel) else "",
            "fragment": _prefixed_fragment(symbol_name, "symbol:"),
            "basis": "symbol_ref",
        }
    if target.startswith("pn:symbol:"):
        raw = target[len("pn:symbol:") :]
        if ":" in raw:
            rel, symbol_name = raw.split(":", 1)
            return {
                "expected": "file",
                "rel": rel,
                "fragment": _prefixed_fragment(symbol_name, "symbol:"),
                "basis": "pn_symbol_ref",
            }
    if target.startswith("symbol:"):
        return {"expected": "file", "fragment": _prefixed_fragment(target.split(":", 1)[1], "symbol:"), "basis": "symbol_alias_ref"}
    if target.startswith("pnsnode:"):
        return {"expected": "file", "basis": "project_network_symbol_node_ref"}
    rel, fragment = _split_ref_path_and_fragment(target)
    if _looks_like_pathish(rel):
        return {"expected": "file", "rel": rel, "fragment": fragment, "basis": "bare_file_ref"}
    if _looks_like_symbol_name(target):
        return {"expected": "file", "fragment": _prefixed_fragment(target, "symbol:"), "basis": "bare_symbol_ref"}
    return {}


def _path_suffix_descriptor(raw: str, *, expected: str, basis: str, suffix_split: str, fragment_prefix: str) -> dict[str, Any]:
    body = str(raw or "").strip()
    if suffix_split and suffix_split in body:
        rel, suffix = body.rsplit(suffix_split, 1)
        if rel and suffix:
            prefix = fragment_prefix if suffix_split == "/api:" else fragment_prefix
            return {
                "expected": expected,
                "rel": rel,
                "fragment": prefix + suffix,
                "basis": basis,
            }
    rel, fragment = _split_ref_path_and_fragment(body)
    if rel:
        return {
            "expected": expected,
            "rel": rel,
            "fragment": _prefixed_fragment(fragment, fragment_prefix) if fragment else "",
            "basis": basis,
        }
    return {"expected": expected, "fragment": "", "basis": basis}


def _prefixed_fragment(fragment: str, prefix: str) -> str:
    value = str(fragment or "").strip()
    if not value:
        return ""
    if value.startswith(prefix) or value.startswith("@") or value.startswith(":"):
        return value
    if ":" in value:
        return value
    return prefix + value


def _looks_like_pathish(value: str) -> bool:
    target = str(value or "").strip()
    return bool(target) and ("/" in target or "\\" in target or bool(Path(target).suffix))


def _looks_like_filename_only(value: str) -> bool:
    target = str(value or "").strip()
    return bool(target) and "/" not in target and "\\" not in target and bool(Path(target).suffix)


def _looks_like_symbol_name(value: str) -> bool:
    target = str(value or "").strip()
    return bool(target) and bool(re.fullmatch(r"[@A-Za-z_][\w.$-]*", target))


def _validate_project_relative_candidate(
    layout: ProjectLayout,
    rel: str,
    *,
    expected: str,
    fragment: str,
) -> dict[str, Any]:
    candidate = str(rel or "").replace("\\", "/").strip("/")
    if not candidate and expected == "directory":
        return _drop_empty(
            {
                "status": "resolved",
                "basis": "workspace_directory_anchor" if fragment else "workspace_directory",
                "path": str(layout.project_root),
                "fragment": fragment,
            }
        )
    path = (layout.project_root / candidate).resolve()
    try:
        path.relative_to(layout.project_root)
    except ValueError:
        return {"status": "unresolved", "basis": "path_outside_project", "path": str(path)}
    validation = _validate_existing_path(path, expected=expected, fragment=fragment, basis_prefix="workspace")
    if validation.get("status") == "resolved":
        return validation
    if candidate and not candidate.startswith("backend/"):
        backend_path = (layout.backend_dir / candidate).resolve()
        try:
            backend_path.relative_to(layout.backend_dir)
        except ValueError:
            backend_validation = {"status": "unresolved", "basis": "backend_path_outside_project", "path": str(backend_path)}
        else:
            backend_validation = _validate_existing_path(backend_path, expected=expected, fragment=fragment, basis_prefix="backend_import")
        if backend_validation.get("status") == "resolved":
            return backend_validation
    return {"status": "unresolved", "basis": f"missing_workspace_{expected}", "path": str(path)}


def _supporting_path_hints(
    layout: ProjectLayout,
    *,
    path_hint: str,
    evidence_refs: list[str],
    anchor_refs: list[str],
) -> list[str]:
    hints: list[str] = []
    if path_hint:
        hints.append(_strip_freeform_path(path_hint))
    for source in [*anchor_refs, *evidence_refs]:
        hints.extend(_paths_from_freeform_ref(source))
    normalized: list[str] = []
    for hint in _dedupe_strings(hints):
        rel = _to_project_relative_path(layout, hint)
        if rel:
            normalized.append(rel)
    return normalized


def _paths_from_freeform_ref(value: str) -> list[str]:
    target = str(value or "").strip()
    if not target:
        return []
    results: list[str] = []
    for pattern in (r"(?:file|pyast)://[^\s`'\"]+", r"[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)+\.[A-Za-z0-9_+-]+"):
        for match in re.finditer(pattern, target):
            item = str(match.group(0) or "").strip()
            if item.startswith(("file://", "pyast://")):
                rel, _ = _split_ref_path_and_fragment(item.split("://", 1)[1])
                if rel:
                    results.append(rel)
            else:
                results.append(_strip_freeform_path(item))
    if not results and _looks_like_filename_only(target):
        results.append(target)
    return _dedupe_strings(results)


def _strip_freeform_path(value: str) -> str:
    target = str(value or "").strip().strip("`'\"")
    if not target:
        return ""
    for marker in ("#L", "#", ":::", "::", "?symbol="):
        if marker in target:
            return target.split(marker, 1)[0]
    if ":" in target and "/" in target:
        head, tail = target.rsplit(":", 1)
        if tail.isdigit() or re.fullmatch(r"\d+(?:-\d+)?", tail):
            return head
    return target


def _to_project_relative_path(layout: ProjectLayout, value: str) -> str:
    target = str(value or "").replace("\\", "/").strip()
    if not target:
        return ""
    if target.startswith(("file://", "folder://", "pyast://")):
        target = target.split("://", 1)[1]
    target = _strip_freeform_path(target).lstrip("/")
    if not target:
        return ""
    absolute = Path(target)
    if absolute.is_absolute():
        try:
            return str(absolute.resolve().relative_to(layout.project_root.resolve())).replace("\\", "/")
        except ValueError:
            return ""
    return target


@lru_cache(maxsize=256)
def _project_relative_file_candidates(project_root: str, filename: str) -> tuple[str, ...]:
    root = Path(project_root)
    target = str(filename or "").strip()
    if not target:
        return ()
    results = []
    for path in root.rglob(target):
        if path.is_file():
            try:
                results.append(str(path.resolve().relative_to(root.resolve())).replace("\\", "/"))
            except ValueError:
                continue
    unique = tuple(sorted(set(results)))
    return unique if len(unique) == 1 else ()


def _validate_existing_path(path: Path, *, expected: str, fragment: str, basis_prefix: str) -> dict[str, Any]:
    if expected == "file" and path.is_file():
        return _drop_empty({"status": "resolved", "basis": f"{basis_prefix}_file_anchor" if fragment else f"{basis_prefix}_file", "path": str(path), "fragment": fragment})
    if expected == "directory" and path.is_dir():
        return _drop_empty({"status": "resolved", "basis": f"{basis_prefix}_directory_anchor" if fragment else f"{basis_prefix}_directory", "path": str(path), "fragment": fragment})
    if expected == "path" and path.exists():
        return {"status": "resolved", "basis": f"{basis_prefix}_path", "path": str(path)}
    return {"status": "unresolved", "basis": f"missing_{basis_prefix}_{expected}", "path": str(path)}


def _split_ref_path_and_fragment(value: str) -> tuple[str, str]:
    raw = str(value or "")
    if "?symbol=" in raw:
        rel, fragment = raw.split("?symbol=", 1)
        return rel, _prefixed_fragment(fragment, "symbol:")
    if ":::" in raw:
        rel, fragment = raw.split(":::", 1)
        return rel, fragment
    if "::" in raw:
        rel, fragment = raw.split("::", 1)
        return rel, _prefixed_fragment(fragment, "symbol:")
    if "#" not in raw:
        return raw, ""
    rel, fragment = raw.split("#", 1)
    return rel, fragment


def _best_physical_validation(first: Any, second: Any) -> dict[str, Any]:
    left = dict(first or {}) if isinstance(first, dict) else {}
    right = dict(second or {}) if isinstance(second, dict) else {}
    if _validation_rank(right) > _validation_rank(left):
        return right
    return left or right


def _validation_rank(value: dict[str, Any]) -> int:
    status = str(value.get("status") or "")
    basis = str(value.get("basis") or "")
    if status == "resolved" and basis.endswith("_anchor"):
        return 4
    if status == "resolved":
        return 3
    if status == "external":
        return 2
    if status == "unresolved":
        return 1
    return 0


def _refs_by_tag(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        ref = str(item.get("coordinate_ref") or item.get("route_ref") or item.get("physical_ref") or "")
        for tag in _strings(item.get("tags")):
            result.setdefault(tag, []).append(ref)
    return {key: sorted(set(value)) for key, value in sorted(result.items())}


def _refs_by_layer(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        ref = str(item.get("coordinate_ref") or item.get("physical_ref") or "")
        layer = str(item.get("layer") or "unknown")
        if ref:
            result.setdefault(layer, []).append(ref)
    return {key: sorted(set(value)) for key, value in sorted(result.items())}


def _refs_by_kind(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        ref = str(item.get("route_ref") or "")
        kind = str(item.get("node_kind") or "unknown")
        if ref:
            result.setdefault(kind, []).append(ref)
    return {key: sorted(set(value)) for key, value in sorted(result.items())}


def _refs_by_path_prefix(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        ref = str(item.get("route_ref") or "")
        if "://" not in ref:
            continue
        path = ref.split("://", 1)[1].split("#", 1)[0]
        parts = [part for part in path.split("/") if part]
        for depth in range(1, min(len(parts), 4) + 1):
            result.setdefault("/".join(parts[:depth]), []).append(ref)
    return {key: sorted(set(value)) for key, value in sorted(result.items())}


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if not edge:
            continue
        source_ref = str(edge.get("source_ref") or "").strip()
        target_ref = str(edge.get("target_ref") or "").strip()
        if not source_ref or not target_ref or source_ref.lower() in {"none", "null"} or target_ref.lower() in {"none", "null"}:
            continue
        key = "|".join(str(edge.get(part) or "") for part in ("source_ref", "target_ref", "edge_kind", "signal_kind", "status"))
        if key.strip("|"):
            result[key] = edge
    return list(result.values())


def _dedupe_by_key(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        lookup = str(dict(item or {}).get(key) or dict(item or {}).get("stable_ref") or dict(item or {}).get("id") or "")
        result[lookup or json.dumps(item, ensure_ascii=False, sort_keys=True)] = dict(item)
    return list(result.values())


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


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


def _audit_signal(subject_ref: str, severity: str, code: str, message: str, *, ref: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return _drop_empty(
        {
            "subject_ref": subject_ref,
            "edge_id": subject_ref if subject_ref.startswith("pnedge:") else "",
            "severity": severity,
            "code": code,
            "message": message,
            "ref": ref,
            "details": details or {},
            "authority": "project_network_system.link_signal_audit.signal",
        }
    )


def _edge_status(edge: dict[str, Any]) -> str:
    status = str(edge.get("status") or edge.get("signal_kind") or "").lower()
    if "conflict" in status:
        return "conflict"
    if "candidate" in status:
        return "candidate"
    if status == "accepted" or str(edge.get("signal_kind") or "") == "accepted_edge":
        return "accepted"
    return status or "candidate"


def _coordinate_layer(kind: str) -> str:
    lowered = kind.lower()
    if "directory" in lowered or "folder" in lowered:
        return "directory"
    if "file" in lowered or "module" in lowered:
        return "file"
    if lowered in {"class", "function", "method", "configuration", "registry_entry", "route", "tool_entry", "prompt_entry", "data_model"}:
        return "symbol"
    return "semantic"


def _node_kind_from_coordinate_layer(layer: str, *, fallback: str) -> str:
    lowered = str(layer or "").lower()
    if lowered == "directory":
        return "directory"
    if lowered == "file":
        return "file_module"
    if lowered == "symbol":
        return "semantic_symbol"
    return str(fallback or "semantic_node")


def _control_role_from_tags(tags: list[str]) -> str:
    joined = " ".join(tags).lower()
    for role in ("permission", "tool", "prompt", "memory", "context", "runtime", "graph", "state", "api", "config"):
        if role in joined:
            return role
    return ""


def _folder_path_from_ref(ref: str) -> str:
    if ref.startswith("folder://"):
        value = ref.split("://", 1)[1]
        return "" if value == "." else value
    return ""


def _normalize_file_ref_from_card(card: dict[str, Any], *, layout: ProjectLayout) -> str:
    ref = _normalize_physical_ref_scheme(str(card.get("stable_ref") or "").strip())
    if ref.startswith("file://"):
        return ref
    path = str(card.get("file_path") or "").strip()
    rel = _to_project_relative_path(layout, path)
    if rel:
        return "file://" + rel.replace("\\", "/").strip("/")
    return ""


def _normalize_folder_ref(ref: str) -> str:
    value = _normalize_physical_ref_scheme(str(ref or "").strip())
    if not value:
        return ""
    if value == "repo://workspace":
        return "folder://."
    if value.startswith("folder://"):
        raw = value[len("folder://") :].replace("\\", "/").strip("/")
        return "folder://." if raw in {"", "."} else "folder://" + raw
    if value.startswith("file://"):
        return _parent_folder_ref_for_file(value)
    if _looks_like_pathish(value):
        raw = value.replace("\\", "/").strip("/")
        if Path(raw).suffix:
            parent = str(Path(raw).parent).replace("\\", "/")
            return "folder://." if parent in {"", "."} else "folder://" + parent
        return "folder://." if raw in {"", "."} else "folder://" + raw
    return ""


def _parent_folder_ref_for_file(file_ref: str) -> str:
    rel = str(file_ref or "")
    if rel.startswith("file://"):
        rel = rel[len("file://") :]
    rel = rel.split("#", 1)[0].replace("\\", "/").strip("/")
    parent = str(Path(rel).parent).replace("\\", "/")
    return "folder://." if parent in {"", "."} else "folder://" + parent.strip("/")


def _parent_folder_ref(folder_ref: str) -> str:
    raw = str(folder_ref or "")
    if raw.startswith("folder://"):
        raw = raw[len("folder://") :]
    raw = raw.replace("\\", "/").strip("/")
    if raw in {"", "."}:
        return "folder://."
    parent = str(Path(raw).parent).replace("\\", "/")
    return "folder://." if parent in {"", "."} else "folder://" + parent.strip("/")


def _ancestor_folder_refs(folder_ref: str) -> set[str]:
    result: set[str] = set()
    current = _normalize_folder_ref(folder_ref)
    while current and current != "folder://.":
        parent = _parent_folder_ref(current)
        if not parent or parent in result:
            break
        result.add(parent)
        current = parent
    return result


def _display_path_from_ref(ref: str) -> str:
    value = str(ref or "")
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("#", 1)[0].replace("\\", "/").strip("/")
    return "" if value == "." else value


def _node_values(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in _list_items(value) if isinstance(item, dict)]


def _edge_values(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str) and value.strip():
        return [{"summary": value.strip()}]
    return [dict(item) for item in _list_items(value) if isinstance(item, dict)]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        return {"summary": value.strip()}
    if isinstance(value, list):
        return {"items": [dict(item) if isinstance(item, dict) else str(item) for item in value]}
    return {}


def _list_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [dict(value)]
    return []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, sort_keys=True)]
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value or "")
    return text if len(text) <= 240 else text[:237] + "..."


def _relative(path: Any, root: Path) -> str:
    try:
        return str(Path(str(path)).resolve().relative_to(root.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return str(path or "")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _reset_report_subtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return safe[:180] or "project_network_artifact"


def _external_ref(ref: str) -> bool:
    return bool(ref.startswith(("external://", "python://", "input:", "rtobj:", "http://", "https://")))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}

