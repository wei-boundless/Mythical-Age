from __future__ import annotations

from pathlib import Path
from typing import Any

from graph_system.context_provider_registry import GraphContextProvider, GraphContextProviderContribution
from graph_system.models import ExecutableGraphConfig, GraphLoopState, safe_id


def register_context_providers(register) -> None:
    register(
        GraphContextProvider(
            provider_id='project_network_context',
            provide=provide_project_network_context,
            priority=100,
            initial_input_keys=("project_network_file_review", "project_network_directory_aggregate"),
            runtime_scope_keys=(
                "project_network_build_id",
                "directory_frame_id",
                "directory_root_frame_id",
                "directory_parent_frame_id",
            ),
            loop_contract_input_keys=(
                "project_network_build_id",
                "directory_frame_id",
                "directory_root_frame_id",
                "directory_parent_frame_id",
                "directory_manifest_ref",
                "folder_stable_ref",
                "folder_path",
            ),
        )
    )


def provide_project_network_context(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node: dict[str, Any],
    services: Any | None,
    initial_inputs: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> GraphContextProviderContribution:
    del state
    updates: dict[str, Any] = {}
    updates.update(_project_network_file_review_inputs(node=node, services=services))
    updates.update(_project_network_directory_aggregate_inputs(node=node, services=services))
    merged_initial_inputs = {**dict(initial_inputs or {}), **updates}
    next_inbound_context = _with_project_network_directory_aggregate_context(
        graph_config=graph_config,
        node=node,
        inbound_context=[dict(item) for item in list(inbound_context or []) if isinstance(item, dict)],
        initial_inputs=merged_initial_inputs,
    )
    return GraphContextProviderContribution(
        initial_inputs=updates,
        inbound_context=next_inbound_context,
    )


def _project_network_file_review_inputs(*, node: dict[str, Any], services: Any | None) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    shard = dict(metadata.get("semantic_shard") or {})
    assigned_scope = dict(shard.get("assigned_scope") or metadata.get("assigned_scope") or {})
    is_single_file_review = bool(metadata.get("low_config_single_file_review")) or str(assigned_scope.get("scope_kind") or "") == "single_file_module"
    if not is_single_file_review:
        return {}
    file_path = str(assigned_scope.get("file_path") or "").strip()
    if not file_path:
        return {}
    review_budget = _project_network_file_review_budget()
    text, truncated, read_error = _read_project_network_file_text(
        file_path,
        services=services,
        metadata=metadata,
        assigned_scope=assigned_scope,
        max_chars=int(review_budget["max_file_text_chars"]),
    )
    structure_projection = _project_network_file_structure_projection(
        assigned_scope=assigned_scope,
        metadata=metadata,
        services=services,
    )
    payload = _drop_empty(
        {
            "scope_kind": "single_file_module",
            "file_node_id": str(assigned_scope.get("file_node_id") or ""),
            "file_stable_ref": str(assigned_scope.get("file_stable_ref") or ""),
            "file_path": file_path,
            "file_hash": str(assigned_scope.get("file_hash") or ""),
            "folder_stable_ref": str(assigned_scope.get("folder_stable_ref") or ""),
            "project_network_target_project_root": str(metadata.get("project_network_target_project_root") or assigned_scope.get("project_network_target_project_root") or ""),
            "project_network_target_backend_dir": str(metadata.get("project_network_target_backend_dir") or assigned_scope.get("project_network_target_backend_dir") or ""),
            "directory_frame_id": str(assigned_scope.get("directory_frame_id") or metadata.get("directory_frame_id") or ""),
            "manifest_ref": str(assigned_scope.get("manifest_ref") or metadata.get("directory_manifest_ref") or ""),
            "required_anchor_refs": list(shard.get("required_anchor_refs") or metadata.get("required_anchor_refs") or []),
            "current_file_text": text,
            "current_file_text_truncated": truncated,
            "read_error": read_error,
            **structure_projection,
            "current_layer_context": {
                "current_layer": "file_module",
                "visible_hierarchy_scope": "current file module plus direct top-level symbol candidates only",
                "parent_context_policy": "folder/system refs are anchors only; do not re-summarize parent layers",
                "child_context_policy": "nested symbols are exposed as counts; function/method IO belongs to endpoint-level review",
            },
            "review_budget": review_budget,
            "input_policy": "system_supplied_single_file_packet_no_agent_file_tools",
            "authority": "project_network_tasks.context_provider.project_network_file_review_input",
        }
    )
    return {"project_network_file_review": payload} if payload else {}


def _project_network_file_review_budget() -> dict[str, Any]:
    return {
        "max_file_text_chars": 40000,
        "max_ast_symbol_cards": 10,
        "max_control_nodes": 10,
        "max_accepted_internal_edges": 8,
        "max_relation_candidates": 12,
        "max_external_stubs": 8,
        "visible_hierarchy_depth": "current_file_module_and_direct_symbols",
        "symbol_selection_policy": "public_or_control_relevant_top_level_symbols_first",
        "edge_scope": "high_signal_defines_registers_routes_configures_only",
        "call_site_policy": "summarize_counts_not_edges",
        "authority": "project_network_tasks.context_provider.project_network_file_review_budget",
    }


def _project_network_directory_aggregate_inputs(*, node: dict[str, Any], services: Any | None) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    node_contracts = dict(node.get("contracts") or {})
    bindings = dict(node.get("contract_bindings") or node_contracts.get("contract_bindings") or {})
    semantic = dict(bindings.get("semantic") or {})
    runtime_policy = dict(node.get("runtime_policy") or {})
    context_policy = dict(runtime_policy.get("context_policy") or {})
    project_network_policy = dict(context_policy.get("project_network") or {})
    directory_policy = dict(project_network_policy.get("directory_tree_reduce") or {})
    is_directory_aggregate = (
        str(semantic.get("work_unit_kind") or metadata.get("work_unit_kind") or "") == "directory_aggregate"
        or str(semantic.get("aggregation_policy") or "") == "tree_reduce_typed_work_products"
        or bool(directory_policy.get("enabled") is True)
    )
    if not is_directory_aggregate:
        return {}

    overrides = dict(node.get("node_config_overrides") or {})
    frame = dict(overrides.get("directory_frame") or {})
    manifest = dict(overrides.get("directory_manifest") or {})
    child_returns = [dict(item) for item in list(overrides.get("child_returns") or []) if isinstance(item, dict)]
    build_id = str(frame.get("build_id") or metadata.get("project_network_build_id") or "")
    frame_id = str(frame.get("frame_id") or metadata.get("directory_frame_id") or semantic.get("directory_frame_id") or "")
    repository = _project_network_repository(services, metadata=metadata)
    repository_child_returns = _project_network_current_child_returns(
        build_id=build_id,
        frame_id=frame_id,
        repository=repository,
    )
    if repository_child_returns:
        child_returns = repository_child_returns
    child_summary_refs = [str(item.get("child_summary_product_ref") or "") for item in child_returns]
    if not child_summary_refs:
        child_summary_refs = list(metadata.get("child_summary_product_refs") or [])
    direct_file_refs = _dedupe_strings(list(manifest.get("direct_file_refs") or metadata.get("direct_file_refs") or []))
    direct_module_product_refs = _project_network_direct_module_work_product_refs(
        build_id=build_id,
        frame_id=frame_id,
        direct_file_refs=direct_file_refs,
        repository=repository,
    )
    source_refs = _dedupe_strings(
        [
            *list(overrides.get("source_work_product_refs") or []),
            *list(metadata.get("source_work_product_refs") or []),
            *direct_module_product_refs,
            *child_summary_refs,
        ]
    )
    work_products = _project_network_work_product_cards(source_refs, services=services, metadata=metadata)
    if not frame and not manifest and not child_returns and not work_products:
        return {}

    payload = _drop_empty(
        {
            "scope_kind": "directory_tree_reduce_aggregate",
            "build_id": build_id,
            "directory_frame_id": frame_id,
            "root_frame_id": str(frame.get("root_frame_id") or metadata.get("directory_root_frame_id") or ""),
            "parent_frame_id": str(frame.get("parent_frame_id") or metadata.get("directory_parent_frame_id") or ""),
            "folder_stable_ref": str(frame.get("folder_stable_ref") or metadata.get("folder_stable_ref") or ""),
            "folder_path": str(frame.get("folder_path") or metadata.get("folder_path") or ""),
            "manifest_ref": str(manifest.get("manifest_id") or metadata.get("directory_manifest_ref") or ""),
            "direct_file_refs": direct_file_refs,
            "child_folder_refs": _dedupe_strings(list(manifest.get("child_folder_refs") or [])),
            "child_returns": [_child_return_card(item) for item in child_returns],
            "child_return_count": len(child_returns),
            "direct_module_work_product_refs": direct_module_product_refs,
            "source_work_product_refs": source_refs,
            "typed_work_products": work_products,
            "typed_work_product_count": len(work_products),
            "current_layer_context": {
                "current_layer": "directory_frame",
                "visible_hierarchy_scope": "current directory frame plus direct module summaries and direct child directory summaries only",
                "parent_context_policy": "parent/root refs are anchors only; do not re-summarize ancestor layers",
                "child_context_policy": "consume child work product route cards; do not reopen child files or expand grandchildren",
            },
            "input_policy": "system_supplied_directory_tree_reduce_packet_no_agent_tools",
            "authority": "project_network_tasks.context_provider.project_network_directory_aggregate_input",
        }
    )
    return {"project_network_directory_aggregate": payload} if payload else {}


def _project_network_work_product_cards(refs: list[str], *, services: Any | None, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    repository = _project_network_repository(services, metadata=metadata)
    if repository is None:
        return []
    cards: list[dict[str, Any]] = []
    for ref in refs[:64]:
        try:
            product = repository.get_work_product(ref)
        except Exception:
            product = None
        if product is None:
            continue
        payload = dict(getattr(product, "payload", {}) or {})
        network_index = dict(payload.get("semantic_network_index") or {})
        cards.append(
            _drop_empty(
                {
                    "work_product_id": str(getattr(product, "work_product_id", "") or ref),
                    "product_kind": str(getattr(product, "product_kind", "") or ""),
                    "contract_id": str(getattr(product, "contract_id", "") or ""),
                    "graph_run_id": str(getattr(product, "graph_run_id", "") or ""),
                    "node_id": str(getattr(product, "node_id", "") or ""),
                    "layer_id": str(getattr(product, "layer_id", "") or ""),
                    "stable_ref": str(getattr(product, "stable_ref", "") or payload.get("folder_stable_ref") or ""),
                    "status": str(getattr(product, "status", "") or ""),
                    "semantic_label": _truncate_value(dict(payload.get("semantic_label") or {}), max_chars=1600)
                    if isinstance(payload.get("semantic_label"), dict)
                    else str(payload.get("semantic_label") or "")[:1600],
                    "summary": str(payload.get("directory_summary") or payload.get("module_summary") or payload.get("summary") or "")[:2400],
                    "parent_return_payload": _truncate_value(dict(payload.get("parent_return_payload") or {}), max_chars=2400)
                    if isinstance(payload.get("parent_return_payload"), dict)
                    else {},
                    "coverage": _truncate_value(dict(getattr(product, "coverage", {}) or payload.get("coverage") or {}), max_chars=1600)
                    if isinstance(getattr(product, "coverage", {}) or payload.get("coverage"), dict)
                    else str(payload.get("coverage") or "")[:1600],
                    "source_work_product_refs": _dedupe_strings(
                        list(payload.get("source_work_product_refs") or [])
                        + list(network_index.get("source_work_product_refs") or [])
                    ),
                    "direct_module_refs": _dedupe_strings(list(payload.get("direct_module_refs") or [])),
                    "child_summary_refs": _dedupe_strings(list(payload.get("child_summary_refs") or [])),
                    "directory_nodes": _bounded_network_nodes(network_index.get("directory_nodes") or payload.get("directory_nodes")),
                    "module_nodes": _bounded_network_nodes(network_index.get("module_nodes") or payload.get("module_nodes")),
                    "semantic_edges": _bounded_network_edges(network_index.get("edges") or payload.get("semantic_edges")),
                    "external_stubs": _bounded_dicts(network_index.get("external_stubs") or payload.get("external_stubs"), limit=16),
                    "accepted_relation_candidates": _bounded_dicts(payload.get("accepted_relation_candidates"), limit=24),
                    "conflicts": _bounded_dicts(payload.get("conflicts"), limit=16),
                    "uncovered_refs": _dedupe_strings(list(payload.get("uncovered_refs") or []))[:32],
                    "evidence_refs": list(getattr(product, "evidence_refs", ()) or [])[:32],
                    "anchor_refs": list(getattr(product, "anchor_refs", ()) or [])[:32],
                    "confidence": str(getattr(product, "confidence", "") or ""),
                    "authority": "project_network_tasks.context_provider.project_network_work_product_card",
                }
            )
        )
    return cards


def _project_network_direct_module_work_product_refs(
    *,
    build_id: str,
    frame_id: str,
    direct_file_refs: list[str],
    repository: Any | None,
) -> list[str]:
    if repository is None or not build_id or not frame_id:
        return []
    try:
        products = list(
            repository.list_work_products(
                build_id=build_id,
                layer_id=f"directory_frame:{frame_id}",
                product_kind="module_index",
                limit=512,
            )
        )
    except Exception:
        return []
    direct_ref_set = {str(ref) for ref in direct_file_refs if str(ref)}
    if direct_ref_set:
        products = [product for product in products if str(getattr(product, "stable_ref", "") or "") in direct_ref_set]
    by_stable_ref = {str(getattr(product, "stable_ref", "") or ""): str(getattr(product, "work_product_id", "") or "") for product in products}
    ordered_refs = [by_stable_ref[ref] for ref in direct_file_refs if ref in by_stable_ref]
    remaining_refs = [
        str(getattr(product, "work_product_id", "") or "")
        for product in products
        if str(getattr(product, "work_product_id", "") or "") and str(getattr(product, "work_product_id", "") or "") not in set(ordered_refs)
    ]
    return _dedupe_strings([*ordered_refs, *remaining_refs])


def _project_network_file_structure_projection(
    *,
    assigned_scope: dict[str, Any],
    metadata: dict[str, Any],
    services: Any | None,
) -> dict[str, Any]:
    structure_repository = _project_structure_repository(services, metadata=metadata, assigned_scope=assigned_scope)
    if structure_repository is None:
        return {"file_skeleton_available": False, "ast_projection_available": False, "structure_projection_error": "project_structure_repository_unavailable"}
    build_id = str(assigned_scope.get("build_id") or metadata.get("project_network_build_id") or "").strip()
    frame_id = str(assigned_scope.get("directory_frame_id") or metadata.get("directory_frame_id") or "").strip()
    file_node_id = str(assigned_scope.get("file_node_id") or "").strip()
    file_ref = str(assigned_scope.get("file_stable_ref") or "").strip()
    skeleton_build_id = build_id
    skeleton_generation: int | None = None
    frame = None
    project_network_repository = _project_network_repository(services, metadata=metadata, assigned_scope=assigned_scope)
    if project_network_repository is not None and frame_id:
        try:
            frame = project_network_repository.get_directory_frame(frame_id)
        except Exception:
            frame = None
    if frame is not None:
        skeleton_build_id = str(getattr(frame, "skeleton_build_id", "") or skeleton_build_id).strip()
        skeleton_generation = int(getattr(frame, "skeleton_generation", 0) or 0) or None
    if not skeleton_build_id:
        return {"file_skeleton_available": False, "ast_projection_available": False, "structure_projection_error": "skeleton_build_id_missing"}
    try:
        file_node = structure_repository.get_skeleton_node(file_node_id) if file_node_id else None
        if file_node is None and file_ref:
            file_node = structure_repository.find_skeleton_node(
                build_id=skeleton_build_id,
                stable_ref=file_ref,
                generation=skeleton_generation,
            )
    except Exception as exc:
        return {"file_skeleton_available": False, "ast_projection_available": False, "structure_projection_error": f"skeleton_lookup_failed:{type(exc).__name__}"}
    if file_node is None:
        return {"file_skeleton_available": False, "ast_projection_available": False, "structure_projection_error": "file_skeleton_node_missing"}
    resolved_generation = int(getattr(file_node, "generation", 0) or skeleton_generation or 0)
    try:
        nodes = list(
            structure_repository.list_skeleton_nodes(
                build_id=skeleton_build_id,
                generation=resolved_generation,
                path=str(getattr(file_node, "path", "") or ""),
                limit=160,
            )
        )
        if not any(str(getattr(item, "node_id", "") or "") == str(getattr(file_node, "node_id", "") or "") for item in nodes):
            nodes.insert(0, file_node)
        node_ids = {str(getattr(item, "node_id", "") or "") for item in nodes if str(getattr(item, "node_id", "") or "")}
        related_edges = [
            edge
            for edge in structure_repository.list_skeleton_edges(
                build_id=skeleton_build_id,
                generation=resolved_generation,
                limit=5000,
            )
            if str(getattr(edge, "src_node_id", "") or "") in node_ids
            or str(getattr(edge, "dst_node_id", "") or "") in node_ids
        ]
    except Exception as exc:
        return {
            "file_skeleton_available": True,
            "file_skeleton_card": _project_structure_node_projection(file_node),
            "ast_projection_available": False,
            "structure_projection_error": f"ast_projection_failed:{type(exc).__name__}",
        }
    node_ref_by_id = {str(getattr(item, "node_id", "") or ""): str(getattr(item, "stable_ref", "") or "") for item in nodes}
    ast_nodes = [item for item in nodes if str(getattr(item, "node_kind", "") or "") not in {"file", "folder"}]
    symbol_window = _project_network_file_level_symbol_window(
        file_node=file_node,
        nodes=nodes,
        max_symbols=int(_project_network_file_review_budget()["max_ast_symbol_cards"]),
    )
    edges, suppressed_edge_counts = _project_network_budgeted_file_structure_edges(related_edges)
    return {
        "file_skeleton_available": True,
        "file_skeleton_card": _project_structure_node_projection(file_node),
        "ast_projection_available": bool(ast_nodes),
        "ast_projection": _drop_empty(
            {
                "mode": "current_layer_file_module_symbol_window",
                "skeleton_build_id": skeleton_build_id,
                "skeleton_generation": resolved_generation,
                "file_ref": str(getattr(file_node, "stable_ref", "") or file_ref),
                "current_layer": "file_module",
                "visible_hierarchy_scope": "file node, module root, and direct top-level symbols only",
                "node_count": len(nodes),
                "visible_node_count": len(symbol_window["nodes"]),
                "suppressed_symbol_count_by_kind": symbol_window["suppressed_symbol_count_by_kind"],
                "nested_symbol_count_by_kind": symbol_window["nested_symbol_count_by_kind"],
                "edge_count": len(edges),
                "suppressed_edge_count_by_kind": suppressed_edge_counts,
                "nodes": [_project_structure_symbol_projection(item) for item in symbol_window["nodes"]],
                "edges": [_project_structure_relation_projection(item, node_ref_by_id=node_ref_by_id) for item in edges],
                "limitations": [
                    "projection is intentionally bounded to the file-module layer",
                    "nested functions and methods are summarized by count unless promoted by a later endpoint-level review",
                    "call-site edges are summarized by count, not expanded by default",
                    "interprocedural_dataflow_not_computed",
                    "unresolved call/import candidates remain evidence candidates, not accepted semantic links",
                ],
                "authority": "project_network_tasks.context_provider.project_network_file_structure_projection",
            }
        ),
    }


def _project_network_budgeted_file_structure_edges(edges: list[Any]) -> tuple[list[Any], dict[str, int]]:
    suppressed: dict[str, int] = {}
    for edge in edges:
        kind = str(getattr(edge, "edge_kind", "") or "")
        suppressed[kind or "unknown"] = suppressed.get(kind or "unknown", 0) + 1
    return [], suppressed


def _project_network_file_level_symbol_window(*, file_node: Any, nodes: list[Any], max_symbols: int) -> dict[str, Any]:
    file_node_id = str(getattr(file_node, "node_id", "") or "")
    module_nodes = [
        item
        for item in nodes
        if str(getattr(item, "node_kind", "") or "") == "py_module"
        and (file_node_id in tuple(getattr(item, "parent_node_ids", ()) or ()) or str(getattr(item, "path", "") or "") == str(getattr(file_node, "path", "") or ""))
    ]
    module_node_ids = {str(getattr(item, "node_id", "") or "") for item in module_nodes}
    direct_parent_ids = set(module_node_ids or {file_node_id})
    direct_symbols = [
        item
        for item in nodes
        if str(getattr(item, "node_kind", "") or "") not in {"file", "folder", "py_module"}
        and any(parent_id in direct_parent_ids for parent_id in tuple(getattr(item, "parent_node_ids", ()) or ()))
    ]
    if not direct_symbols:
        direct_symbols = [
            item
            for item in nodes
            if str(getattr(item, "node_kind", "") or "") not in {"file", "folder", "py_module"}
            and file_node_id in tuple(getattr(item, "ancestor_node_ids", ()) or ())
        ]
    roots = [*module_nodes[:1]]
    ordered_symbols = sorted(direct_symbols, key=_project_network_symbol_priority)
    budget = max(1, int(max_symbols or 14))
    selected = [*roots, *ordered_symbols[: max(0, budget - len(roots))]]
    selected_ids = {str(getattr(item, "node_id", "") or "") for item in selected}
    direct_ids = {str(getattr(item, "node_id", "") or "") for item in direct_symbols}
    nested_symbols = [
        item
        for item in nodes
        if str(getattr(item, "node_kind", "") or "") not in {"file", "folder", "py_module"}
        and str(getattr(item, "node_id", "") or "") not in direct_ids
        and file_node_id in tuple(getattr(item, "ancestor_node_ids", ()) or ())
    ]
    suppressed_symbols = [item for item in direct_symbols if str(getattr(item, "node_id", "") or "") not in selected_ids]
    return {
        "nodes": selected,
        "suppressed_symbol_count_by_kind": _project_network_node_count_by_kind(suppressed_symbols),
        "nested_symbol_count_by_kind": _project_network_node_count_by_kind(nested_symbols),
    }


def _project_network_symbol_priority(node: Any) -> tuple[int, int, int, int, str]:
    payload = dict(getattr(node, "payload", {}) or {})
    kind = str(getattr(node, "node_kind", "") or "")
    name = str(payload.get("name") or getattr(node, "display_name", "") or "")
    lowered_name = name.lower()
    is_private = name.startswith("_")
    child_count = int(payload.get("direct_child_count") or 0)
    kind_priority = {
        "py_class": 0,
        "py_function": 1,
        "py_method": 2,
    }.get(kind, 5)
    control_tokens = (
        "agent",
        "build",
        "catalog",
        "config",
        "credential",
        "dispatch",
        "graph",
        "model",
        "policy",
        "profile",
        "prompt",
        "provider",
        "registry",
        "requirement",
        "resolve",
        "route",
        "runtime",
        "stream",
        "tool",
    )
    utility_tokens = ("_bool", "_dict", "_float", "_int", "_optional", "_positive", "_strings")
    signal_priority = 0 if any(token in lowered_name for token in control_tokens) else 2 if any(token in lowered_name for token in utility_tokens) else 1
    return (kind_priority, signal_priority, 1 if is_private else 0, -child_count, name)


def _project_network_node_count_by_kind(nodes: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        kind = str(getattr(node, "node_kind", "") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def _project_structure_repository(
    services: Any | None,
    *,
    metadata: dict[str, Any] | None = None,
    assigned_scope: dict[str, Any] | None = None,
) -> Any | None:
    backend_dir = _project_network_repository_base_dir(services, metadata=metadata, assigned_scope=assigned_scope)
    try:
        from file_management.project_structure.repository import ProjectStructureRepository

        return ProjectStructureRepository(backend_dir)
    except Exception:
        return None


def _project_structure_node_projection(node: Any) -> dict[str, Any]:
    payload = dict(getattr(node, "payload", {}) or {})
    projected_payload = {
        key: payload.get(key)
        for key in (
            "physical_layer",
            "suffix",
            "size_bytes",
            "line_count",
            "start_line",
            "end_line",
            "name",
            "qualname",
            "signature",
            "returns_annotation",
            "bases",
            "decorators",
            "exports",
            "parameters",
            "direct_child_count_by_kind",
            "descendant_endpoint_count_by_kind",
            "inbound_edge_count_by_kind",
            "outbound_edge_count_by_kind",
            "limitations",
        )
        if payload.get(key) not in ("", None, [], {}, ())
    }
    projected_payload["import_candidate_texts"] = _bounded_strings(payload.get("import_candidate_texts"), limit=16)
    projected_payload["outgoing_call_candidate_count"] = len(list(payload.get("outgoing_call_candidate_texts") or []))
    projected_payload["outgoing_resolved_call_count"] = len(list(payload.get("outgoing_call_target_node_ids") or []))
    projected_payload["incoming_resolved_call_count"] = len(list(payload.get("incoming_call_source_node_ids") or []))
    return _drop_empty(
        {
            "node_id": str(getattr(node, "node_id", "") or ""),
            "stable_ref": str(getattr(node, "stable_ref", "") or ""),
            "node_kind": str(getattr(node, "node_kind", "") or ""),
            "display_name": str(getattr(node, "display_name", "") or ""),
            "path": str(getattr(node, "path", "") or ""),
            "layer_kind": str(getattr(node, "layer_kind", "") or ""),
            "hierarchy_path": str(getattr(node, "hierarchy_path", "") or ""),
            "anchor_ref": str(getattr(node, "anchor_ref", "") or ""),
            "file_hash": str(getattr(node, "file_hash", "") or ""),
            "confidence": str(getattr(node, "confidence", "") or ""),
            "status": str(getattr(node, "status", "") or ""),
            "payload": _truncate_value(projected_payload, max_chars=1800),
        }
    )


def _project_structure_symbol_projection(node: Any) -> dict[str, Any]:
    payload = dict(getattr(node, "payload", {}) or {})
    start_line = payload.get("start_line")
    end_line = payload.get("end_line")
    counts = _drop_empty(
        {
            "direct_child_count_by_kind": payload.get("direct_child_count_by_kind"),
            "descendant_endpoint_count_by_kind": payload.get("descendant_endpoint_count_by_kind"),
            "inbound_edge_count_by_kind": payload.get("inbound_edge_count_by_kind"),
            "outbound_edge_count_by_kind": payload.get("outbound_edge_count_by_kind"),
            "outgoing_call_candidate_count": len(list(payload.get("outgoing_call_candidate_texts") or [])),
            "outgoing_resolved_call_count": len(list(payload.get("outgoing_call_target_node_ids") or [])),
            "incoming_resolved_call_count": len(list(payload.get("incoming_call_source_node_ids") or [])),
        }
    )
    return _drop_empty(
        {
            "stable_ref": str(getattr(node, "stable_ref", "") or ""),
            "node_kind": str(getattr(node, "node_kind", "") or ""),
            "name": str(payload.get("name") or getattr(node, "display_name", "") or ""),
            "qualname": str(payload.get("qualname") or ""),
            "signature": str(payload.get("signature") or ""),
            "lines": [start_line, end_line] if start_line or end_line else [],
            "returns": str(payload.get("returns_annotation") or ""),
            "exports": _bounded_strings(payload.get("exports"), limit=24),
            "imports": _bounded_strings(payload.get("import_candidate_texts"), limit=16),
            "endpoint_counts": _drop_empty(
                {
                    "direct_child_count_by_kind": counts.get("direct_child_count_by_kind"),
                    "descendant_endpoint_count_by_kind": counts.get("descendant_endpoint_count_by_kind"),
                }
            ),
            "limitations": _bounded_strings(payload.get("limitations"), limit=8),
            "confidence": str(getattr(node, "confidence", "") or ""),
        }
    )


def _project_structure_relation_projection(edge: Any, *, node_ref_by_id: dict[str, str]) -> dict[str, Any]:
    return _drop_empty(
        {
            "edge_kind": str(getattr(edge, "edge_kind", "") or ""),
            "source_ref": node_ref_by_id.get(str(getattr(edge, "src_node_id", "") or ""), ""),
            "target_ref": node_ref_by_id.get(str(getattr(edge, "dst_node_id", "") or ""), ""),
            "target_candidate_ref": str(getattr(edge, "dst_candidate_ref", "") or ""),
            "confidence": str(getattr(edge, "confidence", "") or ""),
            "resolution_status": str(getattr(edge, "resolution_status", "") or ""),
        }
    )


def _project_network_repository(
    services: Any | None,
    *,
    metadata: dict[str, Any] | None = None,
    assigned_scope: dict[str, Any] | None = None,
) -> Any | None:
    backend_dir = _project_network_repository_base_dir(services, metadata=metadata, assigned_scope=assigned_scope)
    try:
        from project_network_system.repository import ProjectNetworkRepository

        return ProjectNetworkRepository(backend_dir)
    except Exception:
        return None


def _project_network_current_child_returns(*, build_id: str, frame_id: str, repository: Any | None) -> list[dict[str, Any]]:
    if repository is None or not build_id or not frame_id:
        return []
    try:
        frame = repository.get_directory_frame(frame_id)
        returns = list(repository.list_directory_child_returns(build_id=build_id, parent_frame_id=frame_id))
    except Exception:
        return []
    if not returns:
        return []
    by_child_frame: dict[str, list[Any]] = {}
    for item in returns:
        if str(getattr(item, "status", "") or "") in {"rejected", "blocked", "failed"}:
            continue
        child_frame_id = str(getattr(item, "child_frame_id", "") or "")
        if child_frame_id:
            by_child_frame.setdefault(child_frame_id, []).append(item)
    selected: list[Any] = []
    expected_child_ids = list(getattr(frame, "child_frame_ids", ()) or []) if frame is not None else list(by_child_frame)
    for child_frame_id in expected_child_ids:
        candidates = by_child_frame.get(str(child_frame_id)) or []
        if not candidates:
            continue
        try:
            child_frame = repository.get_directory_frame(str(child_frame_id))
        except Exception:
            child_frame = None
        current_product_ref = str(getattr(child_frame, "aggregate_work_product_ref", "") or "")
        current = [item for item in candidates if str(getattr(item, "child_summary_product_ref", "") or "") == current_product_ref]
        selected.append(current[0] if current else candidates[0])
    selected_ids = {str(getattr(item, "return_id", "") or "") for item in selected}
    for child_frame_id, candidates in by_child_frame.items():
        if str(child_frame_id) in {str(item) for item in expected_child_ids}:
            continue
        for candidate in candidates:
            return_id = str(getattr(candidate, "return_id", "") or "")
            if return_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(return_id)
            break
    return [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in selected]


def _with_project_network_directory_aggregate_context(
    *,
    graph_config: ExecutableGraphConfig,
    node: dict[str, Any],
    inbound_context: list[dict[str, Any]],
    initial_inputs: dict[str, Any],
) -> list[dict[str, Any]]:
    aggregate = dict(initial_inputs.get("project_network_directory_aggregate") or {})
    if not aggregate:
        return inbound_context
    node_id = str(node.get("node_id") or "")
    context = {
        "context_id": f"project_network_directory_aggregate::{safe_id(node_id)}",
        "packet_type": "project_network.directory_tree_reduce_input",
        "source_node_id": "__project_network_store__",
        "target_node_id": node_id,
        "edge_id": f"project_network_store::{node_id}",
        "payload_contract_id": "project_network.directory_aggregate.inputs.v1",
        "packet_contract_id": "project_network.directory_aggregate.inputs.v1",
        "target_context_key": "project_network_directory_aggregate",
        "target_input_slot": "project_network_directory_aggregate",
        "delivery_policy": "contract_payload",
        "payload": {
            "initial_inputs": {"project_network_directory_aggregate": aggregate},
            "graph_id": graph_config.graph_id,
            "authority": "project_network_tasks.context_provider.project_network_directory_aggregate_context",
        },
        "artifact_refs": [],
        "memory_refs": [],
        "result_refs": [],
        "visibility": {
            "model_visible": True,
            "source": "system_supplied_typed_work_products",
            "authority": "project_network_tasks.context_provider.project_network_directory_aggregate_context_visibility",
        },
        "authority": "project_network_tasks.context_provider.project_network_directory_aggregate_context",
    }
    return [*inbound_context, context]


def _child_return_card(item: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "return_id": str(item.get("return_id") or ""),
            "child_frame_id": str(item.get("child_frame_id") or ""),
            "child_folder_ref": str(item.get("child_folder_ref") or ""),
            "child_summary_product_ref": str(item.get("child_summary_product_ref") or ""),
            "status": str(item.get("status") or ""),
            "coverage": dict(item.get("coverage") or {}) if isinstance(item.get("coverage"), dict) else {},
            "blockers": [str(value) for value in list(item.get("blockers") or []) if str(value)],
            "authority": "project_network_tasks.context_provider.project_network_child_return_card",
        }
    )


def _bounded_network_nodes(value: Any) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in list(value or [])[:48]:
        if not isinstance(item, dict):
            continue
        label = item.get("semantic_label")
        cards.append(
            _drop_empty(
                {
                    "stable_ref": str(item.get("stable_ref") or ""),
                    "node_kind": str(item.get("node_kind") or ""),
                    "name": str(item.get("name") or ""),
                    "semantic_label": _truncate_value(dict(label or {}), max_chars=1200)
                    if isinstance(label, dict)
                    else str(label or "")[:1200],
                    "evidence_refs": [str(ref) for ref in list(item.get("evidence_refs") or [])[:16] if str(ref)],
                    "anchor_refs": [str(ref) for ref in list(item.get("anchor_refs") or [])[:16] if str(ref)],
                    "confidence": str(item.get("confidence") or ""),
                }
            )
        )
    return cards


def _bounded_network_edges(value: Any) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in list(value or [])[:64]:
        if not isinstance(item, dict):
            continue
        cards.append(
            _drop_empty(
                {
                    "source_ref": str(item.get("source_ref") or ""),
                    "target_ref": str(item.get("target_ref") or ""),
                    "edge_kind": str(item.get("edge_kind") or ""),
                    "direction": str(item.get("direction") or ""),
                    "status": str(item.get("status") or ""),
                    "evidence_refs": [str(ref) for ref in list(item.get("evidence_refs") or [])[:16] if str(ref)],
                    "anchor_refs": [str(ref) for ref in list(item.get("anchor_refs") or [])[:16] if str(ref)],
                    "confidence": str(item.get("confidence") or ""),
                    "limitations": [str(ref) for ref in list(item.get("limitations") or [])[:8] if str(ref)]
                    if isinstance(item.get("limitations"), list)
                    else str(item.get("limitations") or "")[:800],
                }
            )
        )
    return cards


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _bounded_strings(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    else:
        candidates = list(value or [])
    return _dedupe_strings(candidates)[: max(0, int(limit or 0))]


def _read_project_network_file_text(
    path: str,
    *,
    services: Any | None,
    metadata: dict[str, Any] | None = None,
    assigned_scope: dict[str, Any] | None = None,
    max_chars: int,
) -> tuple[str, bool, str]:
    workspace_root = _project_workspace_root_from_services(services, metadata=metadata, assigned_scope=assigned_scope)
    raw = Path(str(path or "").replace("\\", "/"))
    candidates = [raw] if raw.is_absolute() else [workspace_root / raw]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(workspace_root.resolve())
        except (OSError, ValueError):
            continue
        try:
            if not resolved.exists() or not resolved.is_file():
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars], len(text) > max_chars, ""
        except OSError as exc:
            return "", False, f"file_read_failed:{type(exc).__name__}"
    return "", False, "file_not_found_or_outside_workspace"


def _project_workspace_root_from_services(
    services: Any | None,
    *,
    metadata: dict[str, Any] | None = None,
    assigned_scope: dict[str, Any] | None = None,
) -> Path:
    target_project_root = _target_project_path(metadata=metadata, assigned_scope=assigned_scope, key="project_network_target_project_root")
    if target_project_root is not None:
        return target_project_root
    backend_dir = _project_network_repository_base_dir(services, metadata=metadata, assigned_scope=assigned_scope)
    return backend_dir.parent if backend_dir.name == "backend" else backend_dir


def _project_network_repository_base_dir(
    services: Any | None,
    *,
    metadata: dict[str, Any] | None = None,
    assigned_scope: dict[str, Any] | None = None,
) -> Path:
    target_backend_dir = _target_project_path(metadata=metadata, assigned_scope=assigned_scope, key="project_network_target_backend_dir")
    if target_backend_dir is not None:
        return target_backend_dir
    target_project_root = _target_project_path(metadata=metadata, assigned_scope=assigned_scope, key="project_network_target_project_root")
    if target_project_root is not None:
        return target_project_root
    return Path(getattr(services, "backend_dir", "") or Path.cwd()).resolve()


def _target_project_path(
    *,
    metadata: dict[str, Any] | None = None,
    assigned_scope: dict[str, Any] | None = None,
    key: str,
) -> Path | None:
    for source in (dict(assigned_scope or {}), dict(metadata or {})):
        raw = str(source.get(key) or "").strip()
        if not raw:
            continue
        try:
            return Path(raw).expanduser().resolve()
        except OSError:
            continue
    return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}

def _bounded_dicts(value: Any, *, limit: int) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or [])[:limit] if isinstance(item, dict)]

def _truncate_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_chars=max_chars) for item in value]
    return value
