from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from task_system.runtime_semantics.chapter_progress import (
    ChapterProgressReceiptError,
    normalize_chapter_progress_receipt,
)

from .models import ExecutableGraphConfig, GraphNodeWorkOrder, safe_id, stable_hash


@dataclass(frozen=True, slots=True)
class RuntimeAlgorithmPostprocessResult:
    progress_receipts: tuple[dict[str, Any], ...] = ()
    postprocess_errors: tuple[dict[str, Any], ...] = ()
    quality_acceptance: dict[str, Any] = field(default_factory=dict)
    side_effects: tuple[dict[str, Any], ...] = ()
    output_patch: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def postprocess_runtime_algorithm_outputs(
    structured_outputs: dict[str, Any],
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
    final_answer: str = "",
) -> RuntimeAlgorithmPostprocessResult:
    node = _graph_node_by_id(graph_config, work_order.node_id)
    if not node:
        return RuntimeAlgorithmPostprocessResult()

    results: list[RuntimeAlgorithmPostprocessResult] = []
    project_result = _project_network_tree_reduce_postprocess(
        structured_outputs,
        graph_config=graph_config,
        work_order=work_order,
        node=node,
        final_answer=final_answer,
    )
    if project_result is not None:
        results.append(project_result)

    writing_result = _writing_iteration_postprocess(
        structured_outputs,
        graph_config=graph_config,
        work_order=work_order,
        node=node,
        final_answer=final_answer,
    )
    if writing_result is not None:
        results.append(writing_result)

    if not results:
        return RuntimeAlgorithmPostprocessResult()
    return _merge_results(results)


def _project_network_tree_reduce_postprocess(
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
        "authority": "graph_system.runtime_algorithm_adapter.project_network_tree_reduce",
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
                "authority": "graph_system.runtime_algorithm_adapter.project_network_tree_reduce.side_effect",
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


def _writing_iteration_postprocess(
    structured_outputs: dict[str, Any],
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
    node: dict[str, Any],
    final_answer: str,
) -> RuntimeAlgorithmPostprocessResult | None:
    del node
    policy = _progress_receipt_policy(graph_config=graph_config, work_order=work_order)
    if not policy:
        return None
    key = str(policy.get("progress_receipt_key") or "chapter_progress_receipt").strip()
    source = _structured_output_source(structured_outputs)
    candidates = _progress_receipt_candidates(source=source, key=key, final_answer=final_answer)
    if not candidates:
        return RuntimeAlgorithmPostprocessResult(
            postprocess_errors=(
                {
                    "reason": "chapter_progress_receipt_missing",
                    "node_id": work_order.node_id,
                    "progress_receipt_key": key,
                    "authority": "graph_system.runtime_algorithm_adapter.writing_iteration",
                },
            ),
            diagnostics={"adapter_id": "writing_iteration", "progress_receipt_key": key},
        )
    errors: list[str] = []
    initial_inputs = _work_order_initial_inputs(work_order)
    for candidate in candidates:
        try:
            receipt = normalize_chapter_progress_receipt(candidate, initial_inputs=initial_inputs)
            return RuntimeAlgorithmPostprocessResult(
                progress_receipts=(receipt,),
                diagnostics={"adapter_id": "writing_iteration", "progress_receipt_key": key},
            )
        except ChapterProgressReceiptError as exc:
            errors.append(str(exc))
    detail = ",".join(dict.fromkeys(errors)) if errors else "chapter_progress_receipt_invalid"
    return RuntimeAlgorithmPostprocessResult(
        postprocess_errors=(
            {
                "reason": "chapter_progress_receipt_invalid",
                "detail": detail,
                "node_id": work_order.node_id,
                "progress_receipt_key": key,
                "authority": "graph_system.runtime_algorithm_adapter.writing_iteration",
            },
        ),
        diagnostics={"adapter_id": "writing_iteration", "progress_receipt_key": key},
    )


def _merge_results(results: list[RuntimeAlgorithmPostprocessResult]) -> RuntimeAlgorithmPostprocessResult:
    progress_receipts: list[dict[str, Any]] = []
    postprocess_errors: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {"adapters": []}
    quality_acceptances: list[dict[str, Any]] = []
    side_effects: list[dict[str, Any]] = []
    output_patch: dict[str, Any] = {}
    for result in results:
        progress_receipts.extend(dict(item) for item in result.progress_receipts)
        postprocess_errors.extend(dict(item) for item in result.postprocess_errors)
        side_effects.extend(dict(item) for item in result.side_effects)
        if result.quality_acceptance:
            quality_acceptances.append(dict(result.quality_acceptance))
        if result.diagnostics:
            diagnostics["adapters"].append(dict(result.diagnostics))
        output_patch.update(dict(result.output_patch or {}))
    quality_acceptance = _merge_quality_acceptances(quality_acceptances)
    return RuntimeAlgorithmPostprocessResult(
        progress_receipts=tuple(progress_receipts),
        postprocess_errors=tuple(postprocess_errors),
        quality_acceptance=quality_acceptance,
        side_effects=tuple(side_effects),
        output_patch=output_patch,
        diagnostics=diagnostics,
    )


def _merge_quality_acceptances(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {}
    if len(items) == 1:
        return dict(items[0])
    accepted = all(bool(item.get("accepted")) for item in items)
    issues = _dedupe_strings(
        [
            str(issue)
            for item in items
            for issue in list(item.get("issues") or [])
            if str(issue).strip()
        ]
    )
    primary = dict(items[0])
    return {
        **primary,
        "accepted": accepted,
        "business_accepted": accepted,
        "issues": issues,
        "quality_issue_summary": "; ".join(issues),
        "merged_acceptance_count": len(items),
        "authority": "graph_system.runtime_algorithm_adapter.merged_quality_acceptance",
    }


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
        }
    )


def _semantic_network_issues(*, product_kind: str, payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if _semantic_label_missing(payload.get("semantic_label")):
        issues.append("semantic_label_missing")
    else:
        issues.extend(_semantic_label_issues(payload.get("semantic_label"), prefix="semantic_label"))
    network = payload.get("semantic_network_index")
    if product_kind == "module_index":
        if not isinstance(network, dict):
            return ["semantic_network_index_missing"]
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
        if not isinstance(network, dict):
            return ["semantic_network_index_missing"]
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
    semantic_label = _semantic_label_from_submission(
        submission,
        stable_ref=file_ref,
        node_kind="file_module",
        evidence_refs=evidence_refs,
        anchor_refs=anchor_refs,
    )
    summary = str(
        submission.get("module_summary")
        or submission.get("summary")
        or semantic_label.get("summary")
        or semantic_label.get("label")
        or ""
    ).strip()
    network = _mapping_value(submission.get("semantic_network_index"))
    nodes = _dict_values(
        submission.get("semantic_nodes")
        or submission.get("nodes")
        or network.get("nodes")
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
    edges = _dict_values(submission.get("semantic_edges") or submission.get("edges") or network.get("edges"))
    payload = {
        "file_ref": file_ref,
        "file_path": file_path,
        "file_hash": file_hash,
        "semantic_label": semantic_label,
        "module_summary": summary,
        "public_surface": _dict_values(submission.get("public_surface")),
        "semantic_network_index": {
            "nodes": list(nodes),
            "edges": list(edges),
            "source_review_format": "typed_semantic_submission",
        },
        "relation_candidates": _dict_values(submission.get("relation_candidates")),
        "coverage": _mapping_value(submission.get("coverage")),
        "limitations": _string_values(submission.get("limitations")),
        "uncovered_refs": _string_values(submission.get("uncovered_refs")),
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
    folder_ref = str(submission.get("stable_ref") or submission.get("folder_stable_ref") or project_context.get("folder_stable_ref") or initial_inputs.get("folder_stable_ref") or "").strip()
    frame_id = str(project_context.get("directory_frame_id") or initial_inputs.get("directory_frame_id") or "").strip()
    evidence_refs = _string_values(submission.get("evidence_refs")) or ([folder_ref] if folder_ref else [])
    anchor_refs = _string_values(submission.get("anchor_refs")) or _string_values(submission.get("anchor_ref")) or ([folder_ref] if folder_ref else [])
    semantic_label = _semantic_label_from_submission(
        submission,
        stable_ref=folder_ref,
        node_kind="directory",
        evidence_refs=evidence_refs,
        anchor_refs=anchor_refs,
    )
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
            *_dict_values(submission.get("directory_nodes") or network.get("directory_nodes")),
        ]
    )
    module_nodes = _dict_values(submission.get("module_nodes") or network.get("module_nodes"))
    edges = _dict_values(submission.get("semantic_edges") or submission.get("edges") or network.get("edges"))
    external_stubs = _dict_values(submission.get("external_stubs") or network.get("external_stubs"))
    source_work_product_refs = _string_values(submission.get("source_work_product_refs") or network.get("source_work_product_refs"))
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
        "directory_frame_id": frame_id,
        "parent_frame_id": str(initial_inputs.get("directory_parent_frame_id") or "").strip(),
        "folder_stable_ref": folder_ref,
        "semantic_label": semantic_label,
        "directory_summary": summary,
        "semantic_network_index": {
            "directory_nodes": list(directory_nodes),
            "module_nodes": list(module_nodes),
            "edges": list(edges),
            "external_stubs": list(external_stubs),
            "source_work_product_refs": list(source_work_product_refs),
            "source_review_format": "typed_semantic_submission",
        },
        "direct_module_refs": _string_values(submission.get("direct_module_refs")),
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


def _semantic_label_from_submission(
    submission: dict[str, Any],
    *,
    stable_ref: str,
    node_kind: str,
    evidence_refs: list[str],
    anchor_refs: list[str],
) -> dict[str, Any]:
    raw = submission.get("semantic_label") or submission.get("node_label")
    if isinstance(raw, dict):
        label = dict(raw)
    elif isinstance(raw, str):
        label = {"label": raw}
    else:
        label = {}
    return _drop_empty(
        {
            **label,
            "stable_ref": str(label.get("stable_ref") or stable_ref or "").strip(),
            "node_kind": str(label.get("node_kind") or node_kind or "").strip(),
            "label": str(label.get("label") or "").strip(),
            "summary": str(label.get("summary") or "").strip(),
            "tags": _string_values(label.get("tags") or label.get("intent_tags") or submission.get("semantic_tags")),
            "role_tags": _string_values(label.get("role_tags") or submission.get("role_tags")),
            "evidence_refs": _string_values(label.get("evidence_refs")) or evidence_refs,
            "anchor_refs": _string_values(label.get("anchor_refs")) or anchor_refs,
            "confidence": str(label.get("confidence") or submission.get("confidence") or "derived").strip(),
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
                "name": file_path or stable_ref,
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


def _progress_receipt_policy(*, graph_config: ExecutableGraphConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    node = _graph_node_by_id(graph_config, work_order.node_id)
    metadata = dict(node.get("metadata") or {})
    policy = dict(node.get("progress_receipt_policy") or metadata.get("progress_receipt_policy") or {})
    if policy:
        return policy
    bindings = dict(dict(node.get("contracts") or {}).get("contract_bindings") or {})
    return dict(bindings.get("progress") or {})


def _progress_receipt_candidates(*, source: dict[str, Any], key: str, final_answer: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    direct = source.get(key)
    if isinstance(direct, dict):
        candidates.append(direct)
    for alternate_key in ("progress_receipt", "receipt"):
        value = source.get(alternate_key)
        if isinstance(value, dict):
            candidates.append(value)
    if str(source.get("authority") or "").strip() == "harness.writing.chapter_progress_receipt":
        candidates.append(source)
    for payload in _json_objects_from_text(final_answer):
        if isinstance(payload.get(key), dict):
            candidates.append(dict(payload.get(key) or {}))
        if str(payload.get("authority") or "").strip() == "harness.writing.chapter_progress_receipt":
            candidates.append(payload)
    return candidates


def _structured_output_source(structured_outputs: dict[str, Any]) -> dict[str, Any]:
    payload = dict(structured_outputs or {})
    for key in ("structured_output", "node_output"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return {**payload, **dict(nested)}
    return payload


def _json_objects_from_text(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", str(text or ""), flags=re.IGNORECASE | re.DOTALL):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def _node_algorithm_kind(*, graph_config: ExecutableGraphConfig, node_id: str) -> str:
    target = str(node_id or "").strip()
    for frame in graph_config.loop_frames:
        payload = dict(frame or {})
        scope_ids = {str(item).strip() for item in list(payload.get("scope_node_ids") or []) if str(item).strip()}
        if target in scope_ids:
            return str(payload.get("algorithm_kind") or payload.get("kind") or "").strip()
    return ""


def _graph_node_by_id(graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    target = str(node_id or "").strip()
    if not target:
        return {}
    for node in graph_config.nodes:
        current = str(dict(node).get("node_id") or "").strip()
        if current == target:
            return dict(node)
    return {}


def _work_order_initial_inputs(work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    return {
        **dict(dict(work_order.input_package or {}).get("initial_inputs") or {}),
        **dict(work_order.explicit_inputs or {}),
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
