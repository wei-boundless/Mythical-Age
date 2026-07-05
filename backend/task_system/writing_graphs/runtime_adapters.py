from __future__ import annotations

from typing import Any

from graph_system.adapter_registry import RuntimeAlgorithmPostprocessAdapter
from graph_system.models import ExecutableGraphConfig, GraphNodeWorkOrder
from graph_system.runtime_algorithm_types import RuntimeAlgorithmPostprocessResult
from task_system.runtime_semantics.chapter_progress import (
    ChapterProgressReceiptError,
    first_chapter_progress_receipt,
)


def register_runtime_algorithm_adapters(register) -> None:
    register(
        RuntimeAlgorithmPostprocessAdapter(
            adapter_id="writing_iteration",
            postprocess=postprocess_writing_iteration_outputs,
            priority=200,
        )
    )


def postprocess_writing_iteration_outputs(
    structured_outputs: dict[str, Any],
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
    node: dict[str, Any],
    final_answer: str,
) -> RuntimeAlgorithmPostprocessResult | None:
    del node, final_answer
    policy = _progress_receipt_policy(graph_config=graph_config, work_order=work_order)
    if not policy:
        return None
    key = str(policy.get("progress_receipt_key") or "chapter_progress_receipt").strip()
    source = _structured_output_source(structured_outputs)
    initial_inputs = _work_order_initial_inputs(work_order)
    try:
        receipt = first_chapter_progress_receipt([source], key=key, initial_inputs=initial_inputs)
    except ChapterProgressReceiptError as exc:
        detail = str(exc) or "chapter_progress_receipt_missing"
        reason = "chapter_progress_receipt_missing" if detail == "chapter_progress_receipt_missing" else "chapter_progress_receipt_invalid"
        return RuntimeAlgorithmPostprocessResult(
            postprocess_errors=(
                {
                    "reason": reason,
                    **({"detail": detail} if reason == "chapter_progress_receipt_invalid" else {}),
                    "node_id": work_order.node_id,
                    "progress_receipt_key": key,
                    "resume_retryable": True,
                    "authority": "task_system.writing_graphs.runtime_adapter.writing_iteration",
                },
            ),
            diagnostics={"adapter_id": "writing_iteration", "progress_receipt_key": key},
        )
    return RuntimeAlgorithmPostprocessResult(
        progress_receipts=(receipt,),
        diagnostics={"adapter_id": "writing_iteration", "progress_receipt_key": key},
    )


def _progress_receipt_policy(*, graph_config: ExecutableGraphConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    node = _graph_node_by_id(graph_config, work_order.node_id)
    metadata = dict(node.get("metadata") or {})
    policy = dict(node.get("progress_receipt_policy") or metadata.get("progress_receipt_policy") or {})
    if policy:
        return policy
    bindings = dict(dict(node.get("contracts") or {}).get("contract_bindings") or {})
    return dict(bindings.get("progress") or {})


def _structured_output_source(structured_outputs: dict[str, Any]) -> dict[str, Any]:
    payload = dict(structured_outputs or {})
    for key in ("structured_output", "node_output"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return {**payload, **dict(nested)}
    return payload


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
