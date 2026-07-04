from __future__ import annotations

from pathlib import Path
from typing import Any

from graph_system.adapter_registry import RuntimeAlgorithmPostprocessAdapter
from graph_system.models import ExecutableGraphConfig, GraphNodeWorkOrder, safe_id, stable_hash
from graph_system.runtime_algorithm_types import RuntimeAlgorithmPostprocessResult


def register_runtime_algorithm_adapters(register) -> None:
    register(
        RuntimeAlgorithmPostprocessAdapter(
            adapter_id='project_network_work_product',
            postprocess=postprocess_project_network_runtime_algorithm_outputs,
            priority=100,
            structured_output_keys=("project_network_semantic_submissions",),
        )
    )


def postprocess_project_network_runtime_algorithm_outputs(
    structured_outputs: dict[str, Any],
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
    node: dict[str, Any],
    final_answer: str,
) -> RuntimeAlgorithmPostprocessResult | None:
    contract = _project_network_work_product_contract(node)
    if not contract:
        return None
    algorithm_kind = _node_algorithm_kind(graph_config=graph_config, node_id=work_order.node_id)
    runtime_algorithm = dict(dict(node.get("metadata") or {}).get("runtime_algorithm") or {})
    adapter_id = str(runtime_algorithm.get("adapter_id") or "").strip()
    if algorithm_kind not in {"tree_reduce", "directory_tree_reduce"} and adapter_id != "project_network_work_product":
        return None

    expected_kind = str(contract.get("product_kind") or "").strip()
    required_payload_fields = tuple(
        str(item).strip()
        for item in list(contract.get("required_payload_fields") or [])
        if str(item).strip()
    )
    del final_answer
    project_context = _project_network_context(node=node, work_order=work_order)
    raw_submissions = _raw_project_network_semantic_submissions(structured_outputs)
    products: list[dict[str, Any]] = []
    issues: list[str] = []
    if not raw_submissions:
        issues.append("missing_project_network_semantic_submissions")
    accepted_products: list[dict[str, Any]] = []
    for index, item in enumerate(raw_submissions, start=1):
        product_issues: list[str] = []
        if not isinstance(item, dict):
            issues.append(f"semantic_submission_not_object:{index}")
            continue
        raw_product = _project_network_work_product_from_semantic_submission(
            item,
            expected_kind=expected_kind,
            project_context=project_context,
            work_order=work_order,
        )
        if not raw_product:
            issues.append(f"semantic_submission_kind_unsupported:{index}")
            continue
        product = _normalize_project_network_work_product(
            raw_product,
            expected_kind=expected_kind,
            required_payload_fields=required_payload_fields,
            project_context=project_context,
            work_order=work_order,
            node=node,
        )
        products.append(product)
        product_kind = str(product.get("product_kind") or "").strip()
        if expected_kind and product_kind != expected_kind:
            product_issues.append(f"work_product_kind_mismatch:{product_kind or '<missing>'}!={expected_kind}")
        if not str(product.get("work_product_id") or product.get("id") or "").strip():
            product_issues.append(f"work_product_id_missing:{index}")
        payload = dict(product.get("payload") or {})
        for field_name in required_payload_fields:
            if _payload_field_missing(payload, field_name):
                product_issues.append(f"payload_field_missing:{field_name}")
        product_issues.extend(_semantic_network_issues(product_kind=expected_kind or product_kind, payload=payload))
        issues.extend(product_issues)
        if not product_issues:
            accepted_products.append(product)

    accepted = bool(products and not issues)
    quality_acceptance = {
        "accepted": accepted,
        "business_accepted": accepted,
        "artifact_ok": True,
        "stage_id": work_order.node_id,
        "policy": "runtime_algorithm.tree_reduce.project_network_work_product",
        "algorithm_kind": algorithm_kind or "tree_reduce",
        "expected_product_kind": expected_kind,
        "product_count": len(products),
        "semantic_submission_count": len(raw_submissions),
        "accepted_product_count": len(accepted_products),
        "issues": _dedupe_strings(issues),
        "quality_issue_summary": "; ".join(_dedupe_strings(issues)),
        "recoverable_error": {
            "error_code": "project_network_work_product_contract_failed",
            "retryable": True,
            "recovery_action": "requeue_same_graph_node_with_contract_feedback",
            "user_message": "项目网络节点没有通过结构化语义提交通道提交合格审查事实，系统会把缺失字段回灌给同一节点重审。",
        },
        "authority": "project_network_tasks.runtime_adapter.project_network_tree_reduce",
    }
    side_effects: tuple[dict[str, Any], ...] = ()
    if accepted:
        side_effects = (
            {
                "effect_kind": "project_network_work_product_ingest",
                "domain_id": "project_network",
                "adapter_id": "project_network_work_product",
                "algorithm_kind": algorithm_kind or "tree_reduce",
                "expected_product_kind": expected_kind,
                "product_count": len(products),
                "required": True,
                "context": project_context,
                "authority": "project_network_tasks.runtime_adapter.project_network_tree_reduce.side_effect",
            },
        )
    return RuntimeAlgorithmPostprocessResult(
        quality_acceptance=quality_acceptance,
        side_effects=side_effects,
        output_patch={"graph_build_work_products": products} if products else {},
        diagnostics={
            "adapter_id": "project_network_work_product",
            "algorithm_kind": algorithm_kind,
            "expected_product_kind": expected_kind,
            "product_count": len(products),
            "semantic_submission_count": len(raw_submissions),
        },
    )


def _project_network_work_product_contract(node: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    prompt_contract = dict(metadata.get("prompt_contract") or {})
    contract = dict(prompt_contract.get("work_product_contract") or metadata.get("work_product_contract") or {})
    if str(contract.get("product_kind") or "").strip():
        return contract
    return {}


def _project_network_context(*, node: dict[str, Any], work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    semantic_shard = dict(metadata.get("semantic_shard") or {})
    assigned_scope = dict(metadata.get("assigned_scope") or semantic_shard.get("assigned_scope") or {})
    initial_inputs = _work_order_initial_inputs(work_order)
    directory_frame_id = str(
        assigned_scope.get("directory_frame_id")
        or metadata.get("directory_frame_id")
        or initial_inputs.get("directory_frame_id")
        or ""
    ).strip()
    layer_id = str(semantic_shard.get("layer_id") or metadata.get("layer_id") or "").strip()
    if not layer_id and directory_frame_id:
        layer_id = f"directory_frame:{directory_frame_id}"
    return _drop_empty(
        {
            "build_id": str(
                assigned_scope.get("build_id")
                or metadata.get("project_network_build_id")
                or initial_inputs.get("project_network_build_id")
                or ""
            ).strip(),
            "directory_frame_id": directory_frame_id,
            "default_layer_id": layer_id,
            "default_shard_id": str(semantic_shard.get("shard_id") or metadata.get("shard_id") or "").strip(),
            "folder_stable_ref": str(assigned_scope.get("folder_stable_ref") or metadata.get("folder_stable_ref") or initial_inputs.get("folder_stable_ref") or "").strip(),
            "file_stable_ref": str(assigned_scope.get("file_stable_ref") or "").strip(),
            "work_unit_kind": str(semantic_shard.get("work_unit_kind") or metadata.get("work_unit_kind") or "").strip(),
            "project_network_target_backend_dir": str(
                assigned_scope.get("project_network_target_backend_dir")
                or metadata.get("project_network_target_backend_dir")
                or initial_inputs.get("project_network_target_backend_dir")
                or ""
            ).strip(),
            "project_network_target_project_root": str(
                assigned_scope.get("project_network_target_project_root")
                or metadata.get("project_network_target_project_root")
                or initial_inputs.get("project_network_target_project_root")
                or ""
            ).strip(),
            "repair_batch_id": str(
                metadata.get("project_network_repair_batch_id")
                or initial_inputs.get("project_network_repair_batch_id")
                or ""
            ).strip(),
            "repair_item_ids": [
                str(item).strip()
                for item in list(
                    metadata.get("project_network_repair_item_ids")
                    or initial_inputs.get("project_network_repair_item_ids")
                    or ()
                )
                if str(item).strip()
            ],
        }
    )


def _semantic_network_issues(*, product_kind: str, payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    physical_binding = payload.get("physical_binding")
    if not isinstance(physical_binding, dict):
        issues.append("physical_binding_missing")
    elif not str(physical_binding.get("physical_ref") or physical_binding.get("stable_ref") or physical_binding.get("file_ref") or physical_binding.get("folder_stable_ref") or "").strip():
        issues.append("physical_binding.physical_ref_missing")
    semantic_coordinate = payload.get("semantic_coordinate")
    if not isinstance(semantic_coordinate, dict):
        issues.append("semantic_coordinate_missing")
    else:
        for field_name in ("coordinate_ref", "physical_ref", "layer", "label", "summary", "confidence"):
            if not str(semantic_coordinate.get(field_name) or "").strip():
                issues.append(f"semantic_coordinate.{field_name}_missing")
        if not _string_values(semantic_coordinate.get("tags")):
            issues.append("semantic_coordinate.tags_missing")
    if _semantic_label_missing(payload.get("semantic_label")):
        issues.append("semantic_label_missing")
    else:
        issues.extend(_semantic_label_issues(payload.get("semantic_label"), prefix="semantic_label"))
    network = payload.get("semantic_network_index")
    if product_kind == "module_index":
        if not isinstance(payload.get("module_review_report"), dict):
            issues.append("module_review_report_missing")
        if not isinstance(payload.get("io_surface"), dict):
            issues.append("io_surface_missing")
        if not isinstance(network, dict):
            issues.append("semantic_network_index_missing")
            return issues
        nodes = network.get("nodes")
        edges = network.get("edges")
        if not isinstance(nodes, list):
            issues.append("semantic_network_index.nodes_missing")
        else:
            issues.extend(_semantic_node_issues(nodes, prefix="semantic_network_index.nodes"))
        if not isinstance(edges, list):
            issues.append("semantic_network_index.edges_missing")
        else:
            issues.extend(_semantic_edge_issues(edges, prefix="semantic_network_index.edges"))
    if product_kind == "directory_summary":
        if not isinstance(payload.get("directory_review_report"), dict):
            issues.append("directory_review_report_missing")
        if not isinstance(payload.get("child_coordinate_summary"), dict):
            issues.append("child_coordinate_summary_missing")
        if not isinstance(network, dict):
            issues.append("semantic_network_index_missing")
            return issues
        for key in ("directory_nodes", "module_nodes", "edges", "external_stubs", "source_work_product_refs"):
            if not isinstance(network.get(key), list):
                issues.append(f"semantic_network_index.{key}_missing")
        if isinstance(network.get("directory_nodes"), list):
            issues.extend(_semantic_node_issues(network.get("directory_nodes"), prefix="semantic_network_index.directory_nodes"))
        if isinstance(network.get("module_nodes"), list):
            issues.extend(_semantic_node_issues(network.get("module_nodes"), prefix="semantic_network_index.module_nodes"))
        if isinstance(network.get("edges"), list):
            issues.extend(_semantic_edge_issues(network.get("edges"), prefix="semantic_network_index.edges"))
    return issues


def _semantic_node_issues(nodes: Any, *, prefix: str) -> list[str]:
    issues: list[str] = []
    for index, item in enumerate(list(nodes or []), start=1):
        if not isinstance(item, dict):
            issues.append(f"{prefix}.{index}_not_object")
            continue
        if not str(item.get("stable_ref") or item.get("node_ref") or "").strip():
            issues.append(f"{prefix}.{index}.stable_ref_missing")
        if not str(item.get("node_kind") or item.get("kind") or "").strip():
            issues.append(f"{prefix}.{index}.node_kind_missing")
        if not str(item.get("name") or item.get("label") or "").strip():
            issues.append(f"{prefix}.{index}.name_missing")
        if _semantic_label_missing(item.get("semantic_label")):
            issues.append(f"{prefix}.{index}.semantic_label_missing")
        else:
            issues.extend(_semantic_label_issues(item.get("semantic_label"), prefix=f"{prefix}.{index}.semantic_label"))
        if not _string_values(item.get("evidence_refs")):
            issues.append(f"{prefix}.{index}.evidence_refs_missing")
        if not _string_values(item.get("anchor_refs") or item.get("anchor_ref")):
            issues.append(f"{prefix}.{index}.anchor_refs_missing")
        if not str(item.get("confidence") or "").strip():
            issues.append(f"{prefix}.{index}.confidence_missing")
    return issues


def _semantic_edge_issues(edges: Any, *, prefix: str) -> list[str]:
    issues: list[str] = []
    for index, item in enumerate(list(edges or []), start=1):
        if not isinstance(item, dict):
            issues.append(f"{prefix}.{index}_not_object")
            continue
        if not str(item.get("source_ref") or item.get("source_stable_ref") or "").strip():
            issues.append(f"{prefix}.{index}.source_ref_missing")
        if not str(item.get("target_ref") or item.get("target_stable_ref") or "").strip():
            issues.append(f"{prefix}.{index}.target_ref_missing")
        if not str(item.get("edge_kind") or item.get("relation_kind") or "").strip():
            issues.append(f"{prefix}.{index}.edge_kind_missing")
        if not str(item.get("direction") or "").strip():
            issues.append(f"{prefix}.{index}.direction_missing")
        if not str(item.get("status") or "").strip():
            issues.append(f"{prefix}.{index}.status_missing")
        if not _string_values(item.get("evidence_refs")):
            issues.append(f"{prefix}.{index}.evidence_refs_missing")
        if not _string_values(item.get("anchor_refs") or item.get("anchor_ref")):
            issues.append(f"{prefix}.{index}.anchor_refs_missing")
        if not str(item.get("confidence") or "").strip():
            issues.append(f"{prefix}.{index}.confidence_missing")
        if "limitations" not in item:
            issues.append(f"{prefix}.{index}.limitations_missing")
    return issues


def _semantic_label_missing(value: Any) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if not isinstance(value, dict):
        return True
    return not str(value.get("label") or value.get("name") or value.get("summary") or "").strip()


def _semantic_label_issues(value: Any, *, prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix}_not_object"]
    issues: list[str] = []
    if not str(value.get("stable_ref") or value.get("node_ref") or "").strip():
        issues.append(f"{prefix}.stable_ref_missing")
    if not str(value.get("label") or value.get("name") or "").strip():
        issues.append(f"{prefix}.label_missing")
    if not str(value.get("summary") or "").strip():
        issues.append(f"{prefix}.summary_missing")
    if not _string_values(value.get("tags") or value.get("intent_tags")):
        issues.append(f"{prefix}.tags_missing")
    if not _string_values(value.get("evidence_refs")):
        issues.append(f"{prefix}.evidence_refs_missing")
    if not _string_values(value.get("anchor_refs") or value.get("anchor_ref")):
        issues.append(f"{prefix}.anchor_refs_missing")
    if not str(value.get("confidence") or "").strip():
        issues.append(f"{prefix}.confidence_missing")
    return issues


def _payload_field_missing(payload: dict[str, Any], field_name: str) -> bool:
    if field_name not in payload:
        return True
    value = payload.get(field_name)
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _raw_project_network_semantic_submissions(structured_outputs: dict[str, Any]) -> list[Any]:
    payload = dict(structured_outputs or {})
    candidates: list[Any] = []
    seen_source_ids: set[int] = set()
    for source in (payload, _structured_output_source(payload)):
        if not isinstance(source, dict):
            continue
        source_id = id(source)
        if source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        candidates.extend(_semantic_submissions_from_source(source))
        for nested_key in ("diagnostics", "structured_output", "node_output", "project_network", "graph_build"):
            nested = source.get(nested_key)
            if isinstance(nested, dict):
                candidates.extend(_semantic_submissions_from_source(nested))
    submissions: list[Any] = []
    for value in candidates:
        if isinstance(value, list):
            submissions.extend(value)
        elif isinstance(value, tuple):
            submissions.extend(list(value))
        elif isinstance(value, dict):
            submissions.append(value)
    return _dedupe_semantic_submissions(submissions)


def _semantic_submissions_from_source(source: dict[str, Any]) -> list[Any]:
    return [
        source.get("project_network_semantic_submissions"),
        source.get("semantic_submissions"),
        source.get("project_network_review_submissions"),
        source.get("project_network_semantic_submission"),
    ]


def _dedupe_semantic_submissions(submissions: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in submissions:
        key = stable_hash(item) if isinstance(item, (dict, list, tuple)) else repr(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _project_network_work_product_from_semantic_submission(
    submission: dict[str, Any],
    *,
    expected_kind: str,
    project_context: dict[str, Any],
    work_order: GraphNodeWorkOrder,
) -> dict[str, Any]:
    submission_kind = str(
        submission.get("submission_kind")
        or submission.get("product_kind")
        or submission.get("work_product_kind")
        or expected_kind
        or ""
    ).strip()
    if expected_kind and submission_kind and submission_kind != expected_kind:
        return {}
    if expected_kind == "module_index" or submission_kind == "module_index":
        return _module_index_product_from_semantic_submission(
            submission,
            project_context=project_context,
            work_order=work_order,
        )
    if expected_kind == "directory_summary" or submission_kind == "directory_summary":
        return _directory_summary_product_from_semantic_submission(
            submission,
            project_context=project_context,
            work_order=work_order,
        )
    return {}


def _module_index_product_from_semantic_submission(
    submission: dict[str, Any],
    *,
    project_context: dict[str, Any],
    work_order: GraphNodeWorkOrder,
) -> dict[str, Any]:
    initial_inputs = _work_order_initial_inputs(work_order)
    file_review = dict(initial_inputs.get("project_network_file_review") or {})
    file_ref = str(
        submission.get("stable_ref")
        or submission.get("file_ref")
        or submission.get("file_stable_ref")
        or file_review.get("file_ref")
        or file_review.get("file_stable_ref")
        or project_context.get("file_stable_ref")
        or ""
    ).strip()
    file_path = str(submission.get("file_path") or file_review.get("file_path") or "").strip()
    file_hash = str(submission.get("file_hash") or file_review.get("file_hash") or "").strip()
    evidence_refs = _string_values(submission.get("evidence_refs")) or ([file_ref] if file_ref else [])
    anchor_refs = _string_values(submission.get("anchor_refs")) or _string_values(submission.get("anchor_ref")) or ([file_ref] if file_ref else [])
    physical_binding = _mapping_value(submission.get("physical_binding"))
    if physical_binding:
        physical_binding.setdefault("physical_ref", file_ref)
        physical_binding.setdefault("file_ref", file_ref)
        physical_binding.setdefault("file_path", file_path)
        physical_binding.setdefault("file_hash", file_hash)
    semantic_coordinate = _mapping_value(submission.get("semantic_coordinate"))
    semantic_label = _semantic_label_from_submission(
        submission,
        stable_ref=file_ref,
        node_kind="file_module",
        evidence_refs=evidence_refs,
        anchor_refs=anchor_refs,
        semantic_coordinate=semantic_coordinate,
    )
    if semantic_coordinate:
        semantic_coordinate.setdefault("coordinate_ref", file_ref)
        declared_physical_ref = str(semantic_coordinate.get("physical_ref") or "").strip()
        if declared_physical_ref and declared_physical_ref != file_ref:
            semantic_coordinate.setdefault("declared_physical_ref", declared_physical_ref)
            semantic_coordinate["binding_warnings"] = _dedupe_strings(
                [
                    *_string_values(semantic_coordinate.get("binding_warnings")),
                    "physical_ref_normalized_to_file_ref",
                ]
            )
        semantic_coordinate["physical_ref"] = file_ref
        semantic_coordinate.setdefault("layer", "file")
        semantic_coordinate.setdefault("label", semantic_label.get("label") or file_ref)
        semantic_coordinate.setdefault("summary", semantic_label.get("summary") or "")
        semantic_coordinate.setdefault("tags", semantic_label.get("tags") or [])
        semantic_coordinate.setdefault("evidence_refs", semantic_label.get("evidence_refs") or evidence_refs)
        semantic_coordinate.setdefault("anchor_refs", semantic_label.get("anchor_refs") or anchor_refs)
        semantic_coordinate.setdefault("confidence", semantic_label.get("confidence") or "derived")
    summary = str(
        submission.get("module_summary")
        or submission.get("summary")
        or semantic_label.get("summary")
        or semantic_label.get("label")
        or ""
    ).strip()
    network = _mapping_value(submission.get("semantic_network_index"))
    review_budget = dict(file_review.get("review_budget") or {})
    max_nodes = _bounded_positive_int(review_budget.get("max_control_nodes"), default=10, ceiling=32)
    max_edges = _bounded_positive_int(review_budget.get("max_accepted_internal_edges"), default=8, ceiling=32)
    max_relation_candidates = _bounded_positive_int(review_budget.get("max_relation_candidates"), default=12, ceiling=48)
    max_external_stubs = _bounded_positive_int(review_budget.get("max_external_stubs"), default=8, ceiling=32)
    nodes = _normalize_semantic_nodes(
        _dict_values(
            submission.get("control_nodes")
            or submission.get("semantic_nodes")
            or submission.get("nodes")
            or network.get("nodes")
        )
    )
    nodes = _dedupe_records_by_ref(
        [
            *_module_label_node(
                semantic_label=semantic_label,
                stable_ref=file_ref,
                file_path=file_path,
                evidence_refs=evidence_refs,
                anchor_refs=anchor_refs,
            ),
            *nodes,
        ]
    )
    root_nodes = [item for item in nodes if str(item.get("stable_ref") or "") == file_ref or str(item.get("node_kind") or "") == "file_module"]
    symbol_nodes = [item for item in nodes if item not in root_nodes]
    nodes = _dedupe_records_by_ref([*root_nodes[:1], *symbol_nodes[:max_nodes]])
    edges = _normalize_semantic_edges(
        _dict_values(submission.get("accepted_internal_edges") or submission.get("semantic_edges") or submission.get("edges") or network.get("edges"))
    )[:max_edges]
    payload = {
        "physical_binding": physical_binding,
        "semantic_coordinate": semantic_coordinate,
        "file_ref": file_ref,
        "file_path": file_path,
        "file_hash": file_hash,
        "semantic_label": semantic_label,
        "module_summary": summary,
        "module_review_report": _mapping_value(submission.get("module_review_report")),
        "public_surface": _dict_values(submission.get("public_surface")),
        "control_nodes": list(nodes),
        "io_surface": _mapping_value(submission.get("io_surface")),
        "accepted_internal_edges": list(edges),
        "semantic_network_index": {
            "nodes": list(nodes),
            "edges": list(edges),
            "source_review_format": "typed_semantic_submission",
        },
        "relation_candidates": _dict_values(submission.get("relation_candidates"))[:max_relation_candidates],
        "external_stubs": _dict_values(submission.get("external_stubs"))[:max_external_stubs],
        "coverage": _mapping_value(submission.get("coverage")),
        "limitations": _string_values(submission.get("limitations")),
        "uncovered_refs": _string_values(submission.get("uncovered_refs")),
        "review_budget": review_budget,
    }
    return {
        "product_kind": "module_index",
        "stable_ref": file_ref,
        "payload": payload,
        "evidence_refs": evidence_refs,
        "anchor_refs": anchor_refs,
        "confidence": str(submission.get("confidence") or semantic_label.get("confidence") or "derived").strip(),
        "status": "candidate",
    }


def _directory_summary_product_from_semantic_submission(
    submission: dict[str, Any],
    *,
    project_context: dict[str, Any],
    work_order: GraphNodeWorkOrder,
) -> dict[str, Any]:
    initial_inputs = _work_order_initial_inputs(work_order)
    directory_aggregate_inputs = dict(initial_inputs.get("project_network_directory_aggregate") or {})
    folder_ref = str(
        submission.get("stable_ref")
        or submission.get("folder_stable_ref")
        or project_context.get("folder_stable_ref")
        or initial_inputs.get("folder_stable_ref")
        or directory_aggregate_inputs.get("folder_stable_ref")
        or ""
    ).strip()
    frame_id = str(
        project_context.get("directory_frame_id")
        or initial_inputs.get("directory_frame_id")
        or directory_aggregate_inputs.get("directory_frame_id")
        or ""
    ).strip()
    evidence_refs = _string_values(submission.get("evidence_refs")) or ([folder_ref] if folder_ref else [])
    anchor_refs = _string_values(submission.get("anchor_refs")) or _string_values(submission.get("anchor_ref")) or ([folder_ref] if folder_ref else [])
    physical_binding = _mapping_value(submission.get("physical_binding"))
    if physical_binding:
        physical_binding.setdefault("physical_ref", folder_ref)
        physical_binding.setdefault("folder_stable_ref", folder_ref)
        physical_binding.setdefault("directory_frame_id", frame_id)
    semantic_coordinate = _mapping_value(submission.get("semantic_coordinate"))
    semantic_label = _semantic_label_from_submission(
        submission,
        stable_ref=folder_ref,
        node_kind="directory",
        evidence_refs=evidence_refs,
        anchor_refs=anchor_refs,
        semantic_coordinate=semantic_coordinate,
    )
    if semantic_coordinate:
        semantic_coordinate.setdefault("coordinate_ref", folder_ref)
        declared_physical_ref = str(semantic_coordinate.get("physical_ref") or "").strip()
        if declared_physical_ref and declared_physical_ref != folder_ref:
            semantic_coordinate.setdefault("declared_physical_ref", declared_physical_ref)
            semantic_coordinate["binding_warnings"] = _dedupe_strings(
                [
                    *_string_values(semantic_coordinate.get("binding_warnings")),
                    "physical_ref_normalized_to_folder_ref",
                ]
            )
        semantic_coordinate["physical_ref"] = folder_ref
        semantic_coordinate.setdefault("layer", "directory")
        semantic_coordinate.setdefault("label", semantic_label.get("label") or folder_ref)
        semantic_coordinate.setdefault("summary", semantic_label.get("summary") or "")
        semantic_coordinate.setdefault("tags", semantic_label.get("tags") or [])
        semantic_coordinate.setdefault("evidence_refs", semantic_label.get("evidence_refs") or evidence_refs)
        semantic_coordinate.setdefault("anchor_refs", semantic_label.get("anchor_refs") or anchor_refs)
        semantic_coordinate.setdefault("confidence", semantic_label.get("confidence") or "derived")
    summary = str(
        submission.get("directory_summary")
        or submission.get("summary")
        or semantic_label.get("summary")
        or semantic_label.get("label")
        or ""
    ).strip()
    network = _mapping_value(submission.get("semantic_network_index"))
    directory_nodes = _dedupe_records_by_ref(
        [
            *_directory_label_node(
                semantic_label=semantic_label,
                stable_ref=folder_ref,
                evidence_refs=evidence_refs,
                anchor_refs=anchor_refs,
            ),
            *_normalize_semantic_nodes(_dict_values(submission.get("directory_nodes") or network.get("directory_nodes"))),
        ]
    )
    module_nodes = _dedupe_records_by_ref(
        [
            *_child_module_nodes_from_directory_inputs(directory_aggregate_inputs),
            *_normalize_semantic_nodes(_dict_values(submission.get("module_nodes") or network.get("module_nodes"))),
        ]
    )
    edges = _normalize_semantic_edges(
        _dict_values(submission.get("directory_control_routes") or submission.get("semantic_edges") or submission.get("edges") or network.get("edges"))
    )
    external_stubs = _dict_values(submission.get("external_stubs") or network.get("external_stubs"))
    source_work_product_refs = _dedupe_strings(
        [
            *_string_values(submission.get("source_work_product_refs") or network.get("source_work_product_refs")),
            *_string_values(directory_aggregate_inputs.get("source_work_product_refs")),
            *_string_values(directory_aggregate_inputs.get("direct_module_work_product_refs")),
            *[
                str(item.get("work_product_id") or "")
                for item in _dict_values(directory_aggregate_inputs.get("typed_work_products"))
                if str(item.get("work_product_id") or "")
            ],
        ]
    )
    accepted_relation_candidates = _dict_values(submission.get("accepted_relation_candidates"))
    conflicts = _dict_values(submission.get("conflicts"))
    parent_return_payload = dict(submission.get("parent_return_payload")) if isinstance(submission.get("parent_return_payload"), dict) else {}
    if not parent_return_payload:
        parent_return_payload = {
            "stable_ref": folder_ref,
            "semantic_label": semantic_label,
            "summary": summary,
            "coverage": _mapping_value(submission.get("coverage")),
            "accepted_relation_candidates": accepted_relation_candidates,
            "conflicts": conflicts,
            "blockers": _string_values(submission.get("blockers")),
        }
    payload = {
        "physical_binding": physical_binding,
        "semantic_coordinate": semantic_coordinate,
        "directory_frame_id": frame_id,
        "parent_frame_id": str(initial_inputs.get("directory_parent_frame_id") or "").strip(),
        "folder_stable_ref": folder_ref,
        "semantic_label": semantic_label,
        "directory_summary": summary,
        "directory_review_report": _mapping_value(submission.get("directory_review_report")),
        "child_coordinate_summary": _mapping_value(submission.get("child_coordinate_summary")),
        "directory_control_routes": list(edges),
        "source_work_product_refs": list(source_work_product_refs),
        "semantic_network_index": {
            "directory_nodes": list(directory_nodes),
            "module_nodes": list(module_nodes),
            "edges": list(edges),
            "external_stubs": list(external_stubs),
            "source_work_product_refs": list(source_work_product_refs),
            "source_review_format": "typed_semantic_submission",
        },
        "direct_module_refs": _dedupe_strings(
            [
                *_string_values(submission.get("direct_module_refs")),
                *_string_values(directory_aggregate_inputs.get("direct_file_refs")),
            ]
        ),
        "child_summary_refs": _string_values(submission.get("child_summary_refs")),
        "accepted_relation_candidates": accepted_relation_candidates,
        "conflicts": conflicts,
        "coverage": _mapping_value(submission.get("coverage")),
        "uncovered_refs": _string_values(submission.get("uncovered_refs")),
        "parent_return_payload": _drop_empty(parent_return_payload),
    }
    return {
        "product_kind": "directory_summary",
        "stable_ref": folder_ref,
        "payload": payload,
        "evidence_refs": evidence_refs,
        "anchor_refs": anchor_refs,
        "confidence": str(submission.get("confidence") or semantic_label.get("confidence") or "derived").strip(),
        "status": "candidate",
    }


def _child_module_nodes_from_directory_inputs(directory_aggregate_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for item in _dict_values(directory_aggregate_inputs.get("typed_work_products")):
        if str(item.get("product_kind") or "") != "module_index":
            continue
        stable_ref = _normalize_physical_ref_scheme(str(item.get("stable_ref") or "").strip())
        if not stable_ref:
            continue
        raw_label = item.get("semantic_label") if isinstance(item.get("semantic_label"), dict) else {}
        label = dict(raw_label or {})
        label.setdefault("stable_ref", stable_ref)
        label.setdefault("node_kind", "file_module")
        label.setdefault("label", Path(stable_ref.removeprefix("file://")).name or stable_ref)
        label.setdefault("summary", str(item.get("summary") or "").strip())
        label.setdefault("tags", _string_values(label.get("tags")) or ["child_module", "module_index"])
        label.setdefault("evidence_refs", _string_values(label.get("evidence_refs")) or _string_values(item.get("evidence_refs")) or [stable_ref])
        label.setdefault("anchor_refs", _string_values(label.get("anchor_refs") or label.get("anchor_ref")) or _string_values(item.get("anchor_refs")) or [stable_ref])
        label.setdefault("confidence", str(label.get("confidence") or item.get("confidence") or "derived").strip())
        nodes.append(
            _drop_empty(
                {
                    "stable_ref": stable_ref,
                    "node_kind": "file_module",
                    "name": str(label.get("label") or Path(stable_ref.removeprefix("file://")).name or stable_ref).strip(),
                    "semantic_label": label,
                    "summary": str(item.get("summary") or label.get("summary") or "").strip(),
                    "source_work_product_refs": _string_values(item.get("work_product_id")),
                    "evidence_refs": _string_values(item.get("evidence_refs")) or _string_values(label.get("evidence_refs")) or [stable_ref],
                    "anchor_refs": _string_values(item.get("anchor_refs")) or _string_values(label.get("anchor_refs")) or [stable_ref],
                    "confidence": str(item.get("confidence") or label.get("confidence") or "derived").strip(),
                }
            )
        )
    return _normalize_semantic_nodes(nodes)


def _semantic_label_from_submission(
    submission: dict[str, Any],
    *,
    stable_ref: str,
    node_kind: str,
    evidence_refs: list[str],
    anchor_refs: list[str],
    semantic_coordinate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = submission.get("semantic_label") or submission.get("node_label")
    if isinstance(raw, dict):
        label = dict(raw)
    elif isinstance(raw, str):
        label = {"label": raw}
    else:
        label = {}
    coordinate = dict(semantic_coordinate or {})
    if not coordinate:
        coordinate = _mapping_value(submission.get("semantic_coordinate"))
    return _drop_empty(
        {
            **label,
            "stable_ref": str(
                label.get("stable_ref")
                or label.get("node_ref")
                or coordinate.get("physical_ref")
                or coordinate.get("coordinate_ref")
                or stable_ref
                or ""
            ).strip(),
            "node_kind": str(label.get("node_kind") or node_kind or "").strip(),
            "label": str(label.get("label") or label.get("name") or coordinate.get("label") or submission.get("label") or "").strip(),
            "summary": str(
                label.get("summary")
                or coordinate.get("summary")
                or submission.get("module_summary")
                or submission.get("directory_summary")
                or submission.get("summary")
                or ""
            ).strip(),
            "tags": _string_values(
                label.get("tags")
                or label.get("intent_tags")
                or coordinate.get("tags")
                or submission.get("semantic_tags")
                or submission.get("tags")
            ),
            "role_tags": _string_values(
                label.get("role_tags")
                or submission.get("role_tags")
                or coordinate.get("role_tags")
                or coordinate.get("control_role")
            ),
            "evidence_refs": _string_values(label.get("evidence_refs")) or _string_values(coordinate.get("evidence_refs")) or evidence_refs,
            "anchor_refs": _string_values(label.get("anchor_refs") or label.get("anchor_ref")) or _string_values(coordinate.get("anchor_refs") or coordinate.get("anchor_ref")) or anchor_refs,
            "confidence": str(label.get("confidence") or coordinate.get("confidence") or submission.get("confidence") or "derived").strip(),
        }
    )


def _normalize_semantic_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_normalize_semantic_node(item) for item in nodes if isinstance(item, dict)]


def _normalize_semantic_node(item: dict[str, Any]) -> dict[str, Any]:
    node = dict(item or {})
    stable_ref = _normalize_physical_ref_scheme(str(node.get("stable_ref") or node.get("node_ref") or node.get("ref") or "").strip())
    node_kind = str(node.get("node_kind") or node.get("kind") or "").strip()
    evidence_refs = _string_values(node.get("evidence_refs"))
    declared_anchor_refs = _string_values(node.get("anchor_refs") or node.get("anchor_ref"))
    anchor_refs = declared_anchor_refs or evidence_refs or ([stable_ref] if stable_ref else [])
    semantic_label = _semantic_label_from_node(
        node,
        stable_ref=stable_ref,
        node_kind=node_kind,
        evidence_refs=evidence_refs,
        anchor_refs=anchor_refs,
    )
    return _drop_empty(
        {
            **node,
            "stable_ref": stable_ref,
            "node_kind": node_kind,
            "name": str(node.get("name") or node.get("label") or semantic_label.get("label") or stable_ref).strip(),
            "semantic_label": semantic_label,
            "evidence_refs": evidence_refs or _string_values(semantic_label.get("evidence_refs")),
            "anchor_refs": anchor_refs or _string_values(semantic_label.get("anchor_refs") or semantic_label.get("anchor_ref")),
            "confidence": str(node.get("confidence") or semantic_label.get("confidence") or "").strip(),
            "limitations": _dedupe_strings(
                [
                    *_string_values(node.get("limitations")),
                    *(["anchor_refs_derived_by_system"] if not declared_anchor_refs and anchor_refs else []),
                ]
            ),
        }
    )


def _normalize_semantic_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_normalize_semantic_edge(item) for item in edges if isinstance(item, dict)]


def _normalize_semantic_edge(item: dict[str, Any]) -> dict[str, Any]:
    edge = dict(item or {})
    source_ref = _normalize_physical_ref_scheme(str(edge.get("source_ref") or edge.get("source_stable_ref") or "").strip())
    target_ref = _normalize_physical_ref_scheme(str(edge.get("target_ref") or edge.get("target_stable_ref") or "").strip())
    evidence_refs = _string_values(edge.get("evidence_refs"))
    declared_anchor_refs = _string_values(edge.get("anchor_refs") or edge.get("anchor_ref"))
    anchor_refs = declared_anchor_refs or evidence_refs or [ref for ref in (source_ref, target_ref) if ref]
    normalized = _drop_empty(
        {
            **edge,
            "source_ref": source_ref,
            "target_ref": target_ref,
            "edge_kind": str(edge.get("edge_kind") or edge.get("relation_kind") or "").strip(),
            "direction": str(edge.get("direction") or "").strip(),
            "status": str(edge.get("status") or "").strip(),
            "evidence_refs": evidence_refs,
            "anchor_refs": anchor_refs,
            "confidence": str(edge.get("confidence") or "").strip(),
        }
    )
    limitations = _string_values(edge.get("limitations")) if "limitations" in edge else []
    normalized["limitations"] = _dedupe_strings(
        [
            *(limitations or ["not_declared_by_agent"]),
            *(["anchor_refs_derived_by_system"] if not declared_anchor_refs and anchor_refs else []),
        ]
    )
    return normalized


def _normalize_physical_ref_scheme(ref: str) -> str:
    value = str(ref or "").strip()
    if value.startswith("folder://"):
        path = value[len("folder://") :]
        path_without_anchor = path.split("#", 1)[0]
        if Path(path_without_anchor).suffix:
            return "file://" + path
    return value


def _semantic_label_from_node(
    node: dict[str, Any],
    *,
    stable_ref: str,
    node_kind: str,
    evidence_refs: list[str],
    anchor_refs: list[str],
) -> dict[str, Any]:
    raw = node.get("semantic_label") or node.get("node_label")
    if isinstance(raw, dict):
        label = dict(raw)
    elif isinstance(raw, str):
        label = {"label": raw}
    else:
        label = {}
    return _drop_empty(
        {
            **label,
            "stable_ref": str(label.get("stable_ref") or label.get("node_ref") or stable_ref or "").strip(),
            "node_kind": str(label.get("node_kind") or node_kind or "").strip(),
            "label": str(label.get("label") or label.get("name") or node.get("label") or node.get("name") or "").strip(),
            "summary": str(label.get("summary") or node.get("summary") or node.get("responsibility") or node.get("description") or "").strip(),
            "tags": _string_values(label.get("tags") or label.get("intent_tags") or node.get("tags") or node.get("semantic_tags")),
            "role_tags": _string_values(label.get("role_tags") or node.get("role_tags")),
            "evidence_refs": _string_values(label.get("evidence_refs")) or evidence_refs,
            "anchor_refs": _string_values(label.get("anchor_refs") or label.get("anchor_ref")) or anchor_refs,
            "confidence": str(label.get("confidence") or node.get("confidence") or "").strip(),
        }
    )


def _module_label_node(
    *,
    semantic_label: dict[str, Any],
    stable_ref: str,
    file_path: str,
    evidence_refs: list[str],
    anchor_refs: list[str],
) -> list[dict[str, Any]]:
    if not semantic_label and not stable_ref:
        return []
    return [
        _drop_empty(
            {
                "stable_ref": stable_ref,
                "node_kind": "file_module",
                "name": str(semantic_label.get("label") or file_path or stable_ref),
                "semantic_label": dict(semantic_label or {}),
                "responsibility": str(semantic_label.get("summary") or semantic_label.get("label") or ""),
                "evidence_refs": evidence_refs,
                "anchor_refs": anchor_refs,
                "confidence": str(semantic_label.get("confidence") or "derived"),
            }
        )
    ]


def _directory_label_node(
    *,
    semantic_label: dict[str, Any],
    stable_ref: str,
    evidence_refs: list[str],
    anchor_refs: list[str],
) -> list[dict[str, Any]]:
    if not semantic_label and not stable_ref:
        return []
    return [
        _drop_empty(
            {
                "stable_ref": stable_ref,
                "node_kind": "directory",
                "name": stable_ref,
                "semantic_label": dict(semantic_label or {}),
                "responsibility": str(semantic_label.get("summary") or semantic_label.get("label") or ""),
                "evidence_refs": evidence_refs,
                "anchor_refs": anchor_refs,
                "confidence": str(semantic_label.get("confidence") or "derived"),
            }
        )
    ]


def _dict_values(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _mapping_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in ("", None, [], {}, ()):
        return {}
    if isinstance(value, list | tuple):
        dict_items = [dict(item) for item in value if isinstance(item, dict)]
        scalar_items = [str(item).strip() for item in value if not isinstance(item, dict) and str(item).strip()]
        return _drop_empty(
            {
                "items": [*dict_items, *scalar_items],
                "source_shape": "list",
            }
        )
    return _drop_empty({"value": str(value).strip(), "source_shape": type(value).__name__})


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _dedupe_records_by_ref(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in records:
        key = str(item.get("stable_ref") or item.get("node_ref") or item.get("name") or item)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _bounded_positive_int(value: Any, *, default: int, ceiling: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return max(1, min(parsed, int(ceiling)))


def _normalize_project_network_work_product(
    product: dict[str, Any],
    *,
    expected_kind: str,
    required_payload_fields: tuple[str, ...],
    project_context: dict[str, Any],
    work_order: GraphNodeWorkOrder,
    node: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(product.get("payload") or {})
    for field_name in required_payload_fields:
        if field_name not in payload and field_name in product:
            payload[field_name] = product.get(field_name)
    product_kind = str(product.get("product_kind") or expected_kind or "").strip()
    build_id = str(product.get("build_id") or project_context.get("build_id") or "").strip()
    graph_run_id = str(product.get("graph_run_id") or work_order.graph_run_id or "").strip()
    node_id = str(product.get("node_id") or work_order.node_id or "").strip()
    stable_ref = str(product.get("stable_ref") or _default_stable_ref(project_context=project_context, product_kind=product_kind) or "").strip()
    layer_id = str(product.get("layer_id") or project_context.get("default_layer_id") or "").strip()
    shard_id = str(product.get("shard_id") or project_context.get("default_shard_id") or "").strip()
    work_product_id = str(product.get("work_product_id") or product.get("id") or "").strip()
    if not work_product_id:
        work_product_id = _stable_work_product_id(
            build_id=build_id,
            graph_run_id=graph_run_id,
            node_id=node_id,
            product_kind=product_kind,
            stable_ref=stable_ref,
            payload=payload,
        )
    return _drop_empty(
        {
            **product,
            "work_product_id": work_product_id,
            "build_id": build_id,
            "graph_run_id": graph_run_id,
            "node_id": node_id,
            "shard_id": shard_id,
            "layer_id": layer_id,
            "product_kind": product_kind,
            "contract_id": str(product.get("contract_id") or node.get("output_contract_id") or "").strip(),
            "payload": payload,
            "stable_ref": stable_ref,
            "confidence": str(product.get("confidence") or "derived").strip(),
            "status": str(product.get("status") or "candidate").strip(),
            "metadata": dict(product.get("metadata") or {}),
        }
    )


def _default_stable_ref(*, project_context: dict[str, Any], product_kind: str) -> str:
    if product_kind == "module_index":
        return str(project_context.get("file_stable_ref") or "").strip()
    if product_kind == "directory_summary":
        return str(project_context.get("folder_stable_ref") or "").strip()
    return ""


def _stable_work_product_id(
    *,
    build_id: str,
    graph_run_id: str,
    node_id: str,
    product_kind: str,
    stable_ref: str,
    payload: dict[str, Any],
) -> str:
    digest = stable_hash(
        {
            "build_id": build_id,
            "graph_run_id": graph_run_id,
            "node_id": node_id,
            "product_kind": product_kind,
            "stable_ref": stable_ref,
            "payload": payload,
        }
    )[:16]
    prefix = safe_id(f"pnwp:{build_id}:{product_kind}:{stable_ref or node_id}", limit=96)
    return f"{prefix}:{digest}"


def _structured_output_source(structured_outputs: dict[str, Any]) -> dict[str, Any]:
    payload = dict(structured_outputs or {})
    for key in ("structured_output", "node_output"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return {**payload, **dict(nested)}
    return payload

def _node_algorithm_kind(*, graph_config: ExecutableGraphConfig, node_id: str) -> str:
    target = str(node_id or "").strip()
    for frame in graph_config.loop_frames:
        payload = dict(frame or {})
        scope_ids = {str(item).strip() for item in list(payload.get("scope_node_ids") or []) if str(item).strip()}
        if target in scope_ids:
            return str(payload.get("algorithm_kind") or payload.get("kind") or "").strip()
    return ""

def _work_order_initial_inputs(work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    return {
        **dict(dict(work_order.input_package or {}).get("initial_inputs") or {}),
        **dict(work_order.explicit_inputs or {}),
    }

def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
