from __future__ import annotations

import json
import re
from typing import Any

from graph_system.adapter_registry import RuntimeAlgorithmPostprocessAdapter
from graph_system.models import ExecutableGraphConfig, GraphNodeWorkOrder
from graph_system.runtime_algorithm_types import RuntimeAlgorithmPostprocessResult
from task_system.runtime_semantics.chapter_progress import (
    ChapterProgressReceiptError,
    normalize_chapter_progress_receipt,
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
                    "resume_retryable": True,
                    "authority": "task_system.writing_graphs.runtime_adapter.writing_iteration",
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
                "resume_retryable": True,
                "authority": "task_system.writing_graphs.runtime_adapter.writing_iteration",
            },
        ),
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
