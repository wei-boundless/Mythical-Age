from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import ExecutableGraphConfig, GraphLoopState, NodeResultEnvelope


def apply_runtime_algorithm_side_effects(
    *,
    services: Any,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
) -> NodeResultEnvelope:
    requests = _side_effect_requests(result)
    if not requests or dict(result.diagnostics or {}).get("runtime_algorithm_side_effect_receipts"):
        return result
    sink = getattr(services, "runtime_algorithm_effect_sink", None)
    if not callable(sink):
        receipts = tuple(_missing_sink_receipt(request) for request in requests)
        return _result_with_effect_receipts(result, receipts)
    try:
        response = sink(
            effect_requests=requests,
            graph_config=graph_config,
            graph_state=state,
            node_result=result,
        )
        receipts = _normalize_sink_receipts(response, requests=requests)
    except Exception as exc:  # pragma: no cover - defensive boundary; smoke checks cover success path.
        receipts = tuple(
            {
                "effect_kind": str(request.get("effect_kind") or ""),
                "status": "failed",
                "reason": type(exc).__name__,
                "detail": str(exc),
                "required": bool(request.get("required", False)),
                "authority": "graph_system.runtime_algorithm_effects.sink_exception",
            }
            for request in requests
        )
    return _result_with_effect_receipts(result, receipts)


def _side_effect_requests(result: NodeResultEnvelope) -> tuple[dict[str, Any], ...]:
    diagnostics = dict(result.diagnostics or {})
    return tuple(
        dict(item)
        for item in list(diagnostics.get("runtime_algorithm_side_effects") or [])
        if isinstance(item, dict) and str(item.get("effect_kind") or "").strip()
    )


def _missing_sink_receipt(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "effect_kind": str(request.get("effect_kind") or ""),
        "status": "failed" if bool(request.get("required", False)) else "skipped",
        "reason": "runtime_algorithm_effect_sink_missing",
        "required": bool(request.get("required", False)),
        "authority": "graph_system.runtime_algorithm_effects.missing_sink",
    }


def _normalize_sink_receipts(response: Any, *, requests: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    if isinstance(response, dict):
        raw_receipts = response.get("receipts")
        if isinstance(raw_receipts, list | tuple):
            return tuple(dict(item) for item in raw_receipts if isinstance(item, dict))
        if response.get("effect_kind") or response.get("status"):
            return (dict(response),)
    if isinstance(response, list | tuple):
        return tuple(dict(item) for item in response if isinstance(item, dict))
    return tuple(
        {
            "effect_kind": str(request.get("effect_kind") or ""),
            "status": "failed" if bool(request.get("required", False)) else "skipped",
            "reason": "sink_returned_no_receipt",
            "required": bool(request.get("required", False)),
            "authority": "graph_system.runtime_algorithm_effects.default_receipt",
        }
        for request in requests
    )


def _result_with_effect_receipts(
    result: NodeResultEnvelope,
    receipts: tuple[dict[str, Any], ...],
) -> NodeResultEnvelope:
    diagnostics = {
        **dict(result.diagnostics or {}),
        "runtime_algorithm_side_effect_receipts": [dict(item) for item in receipts],
    }
    failed_required = [
        dict(item)
        for item in receipts
        if bool(item.get("required", False)) and str(item.get("status") or "").strip() not in {"completed", "ok", "accepted"}
    ]
    if not failed_required:
        return replace(result, diagnostics=diagnostics)
    issues = [
        str(item.get("reason") or item.get("status") or item.get("effect_kind") or "runtime_algorithm_side_effect_failed")
        for item in failed_required
    ]
    return replace(
        result,
        status="blocked",
        error={
            "reason": "runtime_algorithm_side_effect_failed",
            "issues": issues,
            "side_effect_receipts": [dict(item) for item in failed_required],
            "authority": "graph_system.runtime_algorithm_effects.required_effect_gate",
        },
        diagnostics=diagnostics,
    )
