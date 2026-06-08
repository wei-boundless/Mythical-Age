from __future__ import annotations

from typing import Any

from .models import PromptCompositionSegmentBinding, PromptCompositionSlot


DYNAMIC_SEGMENT_KINDS = {
    "dynamic_projection",
    "graph_node_completion_prefix",
    "graph_node_runtime_context",
    "provider_protocol_history",
    "semantic_compaction_request",
    "session_history",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
    "tool_observations",
    "user_steering_updates",
    "volatile_task_state",
    "volatile_user",
}


def bind_segments_to_slots(
    *,
    segments: tuple[dict[str, Any], ...],
    slots: tuple[PromptCompositionSlot, ...],
) -> tuple[PromptCompositionSegmentBinding, ...]:
    bindings: list[PromptCompositionSegmentBinding] = []
    for segment in segments:
        kind = str(segment.get("kind") or "").strip()
        source_ref = str(segment.get("source_ref") or "").strip()
        matching_slots = _matching_slots(segment=segment, slots=slots)
        status = _binding_status(segment=segment, matching_slots=matching_slots)
        bindings.append(
            PromptCompositionSegmentBinding(
                segment_id=str(segment.get("segment_id") or ""),
                kind=kind,
                source_ref=source_ref,
                model_message_index=int(segment.get("model_message_index") or 0),
                cache_role=str(segment.get("cache_role") or "volatile"),
                prefix_tier=str(segment.get("prefix_tier") or "volatile"),
                bound_slot_ids=tuple(slot.slot_id for slot in matching_slots),
                binding_status=status,
                binding_reason=_binding_reason(status=status, kind=kind, source_ref=source_ref),
                metadata={
                    "model_message_role": str(segment.get("model_message_role") or ""),
                    "cache_scope": str(segment.get("cache_scope") or ""),
                    "compression_role": str(segment.get("compression_role") or ""),
                    "byte_length": int(segment.get("byte_length") or 0),
                },
            )
        )
    return tuple(bindings)


def _matching_slots(*, segment: dict[str, Any], slots: tuple[PromptCompositionSlot, ...]) -> tuple[PromptCompositionSlot, ...]:
    kind = str(segment.get("kind") or "").strip()
    source_tokens = _source_tokens(str(segment.get("source_ref") or ""))
    matches: list[PromptCompositionSlot] = []
    for slot in slots:
        slot_tokens = {
            token
            for token in (
                slot.prompt_ref,
                slot.source_ref,
                *slot.prompt_pack_refs,
            )
            if token
        }
        message_kind_match = kind and kind in set(slot.message_kinds or ())
        source_match = bool(source_tokens and source_tokens.intersection(slot_tokens))
        if source_match or message_kind_match:
            matches.append(slot)
    return tuple(matches)


def _fallback_status(segment: dict[str, Any]) -> str:
    kind = str(segment.get("kind") or "").strip()
    cache_role = str(segment.get("cache_role") or "").strip()
    if kind in DYNAMIC_SEGMENT_KINDS or cache_role in {"volatile", "never_cache"}:
        return "dynamic_context_fragment"
    return "legacy_runtime_text"


def _binding_status(*, segment: dict[str, Any], matching_slots: tuple[PromptCompositionSlot, ...]) -> str:
    if not matching_slots:
        return _fallback_status(segment)
    if any(slot.source_kind == "registered_prompt" for slot in matching_slots):
        return "registered_prompt_bound"
    if any(slot.source_kind == "dynamic_context_fragment" for slot in matching_slots):
        return "dynamic_context_fragment"
    if any(slot.source_kind == "legacy_runtime_text" for slot in matching_slots):
        return "legacy_runtime_text"
    return _fallback_status(segment)


def _binding_reason(*, status: str, kind: str, source_ref: str) -> str:
    if status == "registered_prompt_bound":
        return "segment source or message kind maps to registered prompt slot"
    if status == "dynamic_context_fragment":
        return "segment is runtime dynamic or volatile context and is not a stable prompt asset"
    return f"segment is compiler-generated stable text without a registered prompt slot: kind={kind} source_ref={source_ref}"


def _source_tokens(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}
