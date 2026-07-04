from __future__ import annotations

import json
import re
from typing import Any

from task_system.runtime_semantics.chapter_progress import (
    ChapterProgressReceiptError,
    normalize_chapter_progress_receipt,
)

from .adapter_registry import (
    RuntimeAlgorithmPostprocessAdapter,
    adapter_postprocess_kwargs,
    iter_runtime_algorithm_adapters,
    register_runtime_algorithm_adapter,
)
from .models import ExecutableGraphConfig, GraphNodeWorkOrder
from .runtime_algorithm_types import RuntimeAlgorithmPostprocessResult


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
    postprocess_kwargs = adapter_postprocess_kwargs(
        structured_outputs=structured_outputs,
        graph_config=graph_config,
        work_order=work_order,
        node=node,
        final_answer=final_answer,
    )
    for adapter in iter_runtime_algorithm_adapters():
        result = adapter.postprocess(**postprocess_kwargs)
        if result is not None:
            results.append(result)

    if not results:
        return RuntimeAlgorithmPostprocessResult()
    return _merge_results(results)


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


register_runtime_algorithm_adapter(
    RuntimeAlgorithmPostprocessAdapter(
        adapter_id='writing_iteration',
        postprocess=_writing_iteration_postprocess,
        priority=200,
    )
)
