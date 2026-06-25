from __future__ import annotations

from typing import Any

from .models import PromptCompositionSegmentBinding, PromptCompositionSlot
from runtime.context_management.context_assembly import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    classify_context_spec,
)

RUNTIME_SOURCE_KIND_BY_SEGMENT_KIND = {
    "action_schema_static": "runtime_action_schema",
    "artifact_scope_stable": "runtime_artifact_scope",
    "bound_task_context_stable": "runtime_bound_task_context",
    "environment_stable": "runtime_environment_boundary",
    "file_evidence_policy_stable": "runtime_file_evidence_policy",
    "lifecycle_stable": "runtime_lifecycle",
    "project_instructions_stable": "runtime_project_instructions",
    "semantic_compaction_stable_boundary": "semantic_compaction_boundary",
    "task_contract_stable": "runtime_contract",
    "task_prompt_contract": "runtime_contract",
    "task_runtime_boundary_stable": "runtime_task_boundary",
    "task_state_replay_entry": "runtime_task_state_replay",
    "task_stable": "runtime_contract",
    "tool_schema_catalog": "tool_catalog",
    "tool_index_stable": "tool_catalog",
    "turn_stable": "runtime_protocol",
    "attachment_context_index": "runtime_attachment_context_index",
    "evidence_index_cursor": "runtime_evidence_index_cursor",
    "task_goal_context": "runtime_task_goal_context",
    "task_plan_context": "runtime_task_plan_context",
    "task_todo_context": "runtime_task_todo_context",
    "editor_context_index": "runtime_editor_context_index",
    "current_editor_evidence_delta": "runtime_editor_evidence_delta",
    "runtime_memory_context": "runtime_memory_context",
    "runtime_baseline_refs": "runtime_baseline_refs",
    "incremental_context_frame": "runtime_incremental_context_frame",
    "incremental_context_cursor": "runtime_incremental_context_cursor",
    "read_evidence_context": "runtime_read_evidence_context",
    "read_evidence_injection": "runtime_read_evidence",
    "bound_task_runtime_context": "runtime_bound_task_context",
    "task_runtime_boundary_dynamic": "runtime_dynamic_boundary",
    "active_skills": "runtime_active_skills",
    "session_history_tail_context": "runtime_session_history_tail_context",
    "provider_protocol_history": "runtime_append_only_context",
    "session_history_entry": "runtime_append_only_context",
    "single_agent_turn_tool_call": "runtime_append_only_context",
    "single_agent_turn_tool_observation": "runtime_append_only_context",
    "single_agent_turn_user_steer_context": "runtime_append_only_context",
    "session_pinned_facts_context": "runtime_append_only_context",
    "tool_observations": "runtime_append_only_context",
    "user_steering_context_append": "runtime_append_only_context",
    "user_steering_consumption_tail": "dynamic_context_fragment",
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
    metadata = dict(segment.get("metadata") or {}) if isinstance(segment.get("metadata"), dict) else {}
    prompt_slot_id = str(metadata.get("prompt_slot_id") or "").strip()
    if prompt_slot_id:
        exact_matches = [slot for slot in slots if str(slot.slot_id or "") == prompt_slot_id]
        if exact_matches:
            return tuple(exact_matches)
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
    return runtime_source_kind_for_segment(segment)


def runtime_source_kind_for_segment(segment: dict[str, Any]) -> str:
    kind = str(segment.get("kind") or "").strip()
    source_kind = RUNTIME_SOURCE_KIND_BY_SEGMENT_KIND.get(kind)
    if source_kind:
        return source_kind
    classification = classify_context_spec(segment)
    if classification.context_cache_section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return "runtime_append_only_context"
    if classification.context_cache_section == DYNAMIC_TAIL:
        return "dynamic_context_fragment"
    return "legacy_runtime_text"


def _binding_status(*, segment: dict[str, Any], matching_slots: tuple[PromptCompositionSlot, ...]) -> str:
    if not matching_slots:
        return _fallback_status(segment)
    if any(slot.source_kind == "registered_prompt" for slot in matching_slots):
        return "registered_prompt_bound"
    runtime_matches = [
        str(slot.source_kind or "")
        for slot in matching_slots
        if str(slot.source_kind or "") != "registered_prompt"
    ]
    if runtime_matches:
        return runtime_matches[0]
    return _fallback_status(segment)


def _binding_reason(*, status: str, kind: str, source_ref: str) -> str:
    if status == "registered_prompt_bound":
        return "segment source or message kind maps to registered prompt slot"
    if status == "dynamic_context_fragment":
        return "segment is runtime dynamic or volatile context and is not a stable prompt asset"
    if status == "runtime_action_schema":
        return "segment is compiler-generated action schema and should become a registered capability slot"
    if status == "runtime_artifact_scope":
        return "segment is compiler-generated artifact scope and should become a registered task-boundary slot"
    if status == "runtime_environment_boundary":
        return "segment is compiler-generated environment boundary and should become a registered environment slot"
    if status == "runtime_file_evidence_policy":
        return "segment is compiler-generated file evidence policy and should become a registered file evidence slot"
    if status == "runtime_lifecycle":
        return "segment is compiler-generated lifecycle protocol and should become a registered lifecycle slot"
    if status == "runtime_project_instructions":
        return "segment is scoped project instruction content collected from project instruction files"
    if status == "runtime_contract":
        return "segment is compiler-generated task/runtime contract and should become a registered contract slot"
    if status == "runtime_task_state_replay":
        return "segment is compiler-generated append-only task state replay evidence"
    if status == "runtime_append_only_context":
        return "segment is accumulated provider-visible context that must preserve append-only prefix order"
    if status == "runtime_read_evidence":
        return "segment is current exact read evidence plus historical evidence refs"
    if status == "runtime_editor_context_index":
        return "segment is the current editor open-file index; it must not carry full editor buffer text"
    if status == "runtime_attachment_context_index":
        return "segment is the current turn attachment index; it must not carry extracted attachment text"
    if status == "runtime_evidence_index_cursor":
        return "segment is evidence refs, hashes, ranges, freshness, and rehydration hints without exact historical content"
    if status == "runtime_task_goal_context":
        return "segment is the active goal mode boundary projected into the current dynamic tail"
    if status == "runtime_task_plan_context":
        return "segment is the active plan mode baseline projected into the current dynamic tail"
    if status == "runtime_task_todo_context":
        return "segment is the active todo execution cursor projected into the current dynamic tail"
    if status == "runtime_editor_evidence_delta":
        return "segment is current editor selection or preview exact evidence visible for this invocation"
    if status == "runtime_memory_context":
        return "segment is selected runtime memory context; it belongs in context memory and must not be treated as volatile execution tail"
    if status == "runtime_incremental_context_frame":
        return "segment is an append-only tool follow-up delta frame"
    if status == "runtime_incremental_context_cursor":
        return "segment points at current invocation delta refs and control signals; it belongs in the volatile tail"
    if status == "runtime_bound_task_context":
        return "segment is bound runtime context refs and recovery handles"
    if status == "runtime_dynamic_boundary":
        return "segment is current runtime facts and action boundary state"
    if status == "runtime_active_skills":
        return "segment is active skill body content selected for this invocation"
    if status == "runtime_task_boundary":
        return "segment is compiler-generated task runtime boundary and authorization summary"
    if status == "runtime_protocol":
        return "segment is compiler-generated runtime protocol and should become a registered protocol slot"
    if status == "semantic_compaction_boundary":
        return "segment is compiler-generated semantic compaction boundary and should become a registered lifecycle slot"
    if status == "tool_catalog":
        return "segment is compiler-generated tool catalog and should be owned by ToolCatalogManifest"
    return f"segment is compiler-generated stable text without a registered prompt slot: kind={kind} source_ref={source_ref}"


def _source_tokens(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}
