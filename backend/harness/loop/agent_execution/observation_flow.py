from __future__ import annotations

from typing import Any

from context_system.projection.projection import projection_from_file_work
from runtime.memory.observation_aggregator import ObservationAggregation, ObservationAggregator

from .observation_projection import project_file_work_context_from_tool_observation


def record_tool_observation_projection(
    *,
    observation_aggregator: ObservationAggregator,
    observation_payload: dict[str, Any],
    observation_ref: str,
    current_bundle_items: list[dict[str, Any]],
    executed_bundle_ordinals: list[int],
) -> tuple[ObservationAggregation, int]:
    observation_aggregator.add_tool_observation(
        observation_payload,
        observation_ref=observation_ref,
    )
    matched_ordinal = match_bundle_ordinal_for_tool_observation(
        bundle_items=current_bundle_items,
        tool_name=str(observation_payload.get("tool_name") or ""),
        tool_args=dict(observation_payload.get("tool_args") or {}),
        executed_ordinals=executed_bundle_ordinals,
    )
    projected_main_context, projected_task_summary_refs = project_file_work_context_from_tool_observation(
        observation_payload
    )
    if projected_main_context or projected_task_summary_refs:
        projection = projection_from_file_work(
            projected_main_context,
            projected_task_summary_refs,
            bundle_items=current_bundle_items,
        )
        return (
            observation_aggregator.add_projection(
                projection,
                tool_name=str(observation_payload.get("tool_name") or ""),
            ),
            matched_ordinal,
        )
    return observation_aggregator.snapshot(), matched_ordinal


def apply_observation_aggregation(
    aggregation: ObservationAggregation,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        dict(aggregation.projection.main_context),
        [dict(item) for item in aggregation.projection.task_summary_refs],
        [dict(item) for item in aggregation.projection.bundle_summary_refs],
    )


def match_bundle_ordinal_for_tool_observation(
    *,
    bundle_items: list[dict[str, Any]],
    tool_name: str,
    tool_args: dict[str, Any],
    executed_ordinals: list[int],
) -> int:
    normalized_tool = str(tool_name or "").strip()
    if not normalized_tool or not bundle_items:
        return 0
    normalized_path = str(tool_args.get("path") or "").strip()
    normalized_query = str(tool_args.get("query") or "").strip().lower()
    matching_items = [
        dict(item)
        for item in bundle_items
        if str(item.get("required_tool") or "").strip() == normalized_tool
    ]
    if not matching_items:
        return 0
    if normalized_path:
        for item in matching_items:
            binding = item.get("target_binding")
            if not isinstance(binding, dict):
                continue
            binding_path = str(dict(binding.get("metadata") or {}).get("path") or "").strip()
            if binding_path and binding_path == normalized_path:
                return _safe_int(item.get("ordinal"))
    if normalized_query:
        for item in matching_items:
            user_text = str(item.get("user_text") or "").strip().lower()
            if user_text and (user_text in normalized_query or normalized_query in user_text):
                return _safe_int(item.get("ordinal"))
    executed = {value for value in executed_ordinals if _safe_int(value) > 0}
    for item in matching_items:
        ordinal = _safe_int(item.get("ordinal"))
        if ordinal > 0 and ordinal not in executed:
            return ordinal
    return _safe_int(matching_items[0].get("ordinal"))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
