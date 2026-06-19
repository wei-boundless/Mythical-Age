from __future__ import annotations

from typing import Any


def model_stream_policy_from_task_execution_assembly(
    task_execution_assembly: dict[str, Any],
    *,
    current_turn_context: dict[str, Any] | None = None,
    runtime_assembly: dict[str, Any] | None = None,
    runtime_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assembly_payload = dict(task_execution_assembly or {})
    assembly_metadata = dict(assembly_payload.get("metadata") or {})
    assembly_diagnostics = dict(assembly_payload.get("diagnostics") or {})
    runtime_payload = dict(runtime_assembly or {})
    turn_context = dict(current_turn_context or {})
    policy: dict[str, Any] = {}
    for candidate in (
        assembly_metadata.get("stream_policy"),
        assembly_diagnostics.get("stream_policy"),
        runtime_payload.get("stream_policy"),
        runtime_policy,
        turn_context.get("stream_policy"),
    ):
        candidate_dict = dict(candidate or {})
        if candidate_dict:
            policy = {**policy, **candidate_dict}
    return {
        "enabled": bool(policy.get("enabled") is True),
        "mode": str(policy.get("mode") or "disabled"),
        "monitor_visibility": str(policy.get("monitor_visibility") or "none"),
        "chunk_event_type": str(policy.get("chunk_event_type") or ""),
        "emit_text_preview": bool(policy.get("emit_text_preview") is True),
        "preview_char_limit": _safe_int(policy.get("preview_char_limit")),
        "persist_full_stream_text": bool(policy.get("persist_full_stream_text") is True),
        "fallback_to_non_stream_on_error": bool(policy.get("fallback_to_non_stream_on_error", True) is not False),
        "model_response_timeout_seconds": float(policy.get("model_response_timeout_seconds") or 0),
        "non_stream_fallback_timeout_seconds": float(policy.get("non_stream_fallback_timeout_seconds") or 0),
        "stream_recovery_timeout_seconds": float(policy.get("stream_recovery_timeout_seconds") or 0),
        "fallback_timeout_seconds": float(policy.get("fallback_timeout_seconds") or 0),
        "forced_tool_timeout_seconds": float(policy.get("forced_tool_timeout_seconds") or 0),
        "chunk_strategy": str(policy.get("chunk_strategy") or ""),
        "first_flush_delay_ms": _safe_int(policy.get("first_flush_delay_ms")),
        "target_buffer_delay_ms": _safe_int(policy.get("target_buffer_delay_ms")),
        "adaptive_min_buffer_delay_ms": _safe_int(policy.get("adaptive_min_buffer_delay_ms")),
        "adaptive_max_buffer_delay_ms": _safe_int(policy.get("adaptive_max_buffer_delay_ms")),
        "release_tick_ms": _safe_int(policy.get("release_tick_ms")),
        "max_buffer_delay_ms": _safe_int(policy.get("max_buffer_delay_ms")),
        "max_flush_interval_ms": _safe_int(policy.get("max_flush_interval_ms")),
        "max_pending_utf8_bytes": _safe_int(policy.get("max_pending_utf8_bytes")),
        "max_release_utf8_bytes": _safe_int(policy.get("max_release_utf8_bytes")),
        "max_pending_line_count": _safe_int(policy.get("max_pending_line_count")),
        "min_event_interval_ms": _safe_int(policy.get("min_event_interval_ms")),
        "event_budget_per_second": _safe_int(policy.get("event_budget_per_second")),
        "authority": "harness.runtime.agent_stream_policy",
    }


def artifact_policy_from_task_execution_assembly(
    *,
    selected_recipe_payload: dict[str, Any],
    task_execution_assembly: dict[str, Any],
    current_turn_context: dict[str, Any] | None = None,
    runtime_assembly: dict[str, Any] | None = None,
    runtime_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assembly_payload = dict(task_execution_assembly or {})
    assembly_metadata = dict(assembly_payload.get("metadata") or {})
    assembly_diagnostics = dict(assembly_payload.get("diagnostics") or {})
    runtime_payload = dict(runtime_assembly or {})
    turn_context = dict(current_turn_context or {})
    policy: dict[str, Any] = {}
    for candidate in (
        dict(selected_recipe_payload or {}).get("artifact_policy"),
        assembly_metadata.get("artifact_policy"),
        assembly_diagnostics.get("artifact_policy"),
        runtime_payload.get("artifact_policy"),
        runtime_policy,
        turn_context.get("artifact_policy"),
    ):
        candidate_dict = dict(candidate or {})
        if candidate_dict:
            policy = {**policy, **candidate_dict}
    return policy


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
