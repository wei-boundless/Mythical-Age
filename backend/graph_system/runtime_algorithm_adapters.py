from __future__ import annotations

from typing import Any

from .adapter_registry import (
    adapter_postprocess_kwargs,
    iter_runtime_algorithm_adapters,
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

def _graph_node_by_id(graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    target = str(node_id or "").strip()
    if not target:
        return {}
    for node in graph_config.nodes:
        current = str(dict(node).get("node_id") or "").strip()
        if current == target:
            return dict(node)
    return {}
def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
