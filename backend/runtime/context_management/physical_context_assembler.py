from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context_segment_policy import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    context_segment_policy_for_spec,
    context_segment_policy_metadata,
)
from .physical_context_plan import (
    CURRENT_TURN_TAIL,
    GLOBAL_STATIC_PREFIX,
    NEVER_REPLAY_TAIL,
    PROVIDER_VISIBLE_CONTEXT_PREFIX,
)
from .physical_prefix_frame_ledger import latest_confirmed_physical_prefix_frame
from .physical_prefix_frame_models import PhysicalPrefixFrame, PhysicalPrefixFrameSegment
from .provider_message_replay_contract import (
    PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY,
    PHYSICAL_PREFIX_FRAME_REPLAY_POLICY,
    PHYSICAL_PREFIX_FRAME_REPLAY_STATUS,
    physical_prefix_frame_replay_metadata,
    provider_message_replay_kind,
)


PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY = "runtime.context_management.physical_context_assembler"


@dataclass(frozen=True, slots=True)
class PhysicalContextInputs:
    static_prefix_specs: tuple[dict[str, Any], ...] = ()
    old_context_replay_specs: tuple[dict[str, Any], ...] = ()
    current_append_specs: tuple[dict[str, Any], ...] = ()
    current_tail_specs: tuple[dict[str, Any], ...] = ()
    storage_root: Path | None = None
    scope: str = ""
    provider: str = ""
    model: str = ""
    provider_lane: str = ""
    input_stage: str = "final"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "input_stage": str(self.input_stage or ""),
            "scope": str(self.scope or ""),
            "storage_root": str(self.storage_root or ""),
            "provider": str(self.provider or ""),
            "model": str(self.model or ""),
            "provider_lane": str(self.provider_lane or ""),
            "static_prefix_spec_count": len(self.static_prefix_specs),
            "old_context_replay_spec_count": len(self.old_context_replay_specs),
            "current_append_spec_count": len(self.current_append_specs),
            "current_tail_spec_count": len(self.current_tail_specs),
            "diagnostics": dict(self.diagnostics or {}),
            "authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        }


@dataclass(frozen=True, slots=True)
class PhysicalContextAssemblyResult:
    message_specs: tuple[dict[str, Any], ...]
    old_context_specs: tuple[dict[str, Any], ...] = ()
    current_append_specs: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_specs": [dict(item) for item in self.message_specs],
            "old_context_specs": [dict(item) for item in self.old_context_specs],
            "current_append_specs": [dict(item) for item in self.current_append_specs],
            "diagnostics": dict(self.diagnostics),
        }


def classify_physical_context_inputs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    storage_root: Path | None,
    scope: str,
    provider: str = "",
    model: str = "",
    provider_lane: str = "",
    input_stage: str = "draft",
) -> PhysicalContextInputs:
    """Classify logical context specs into the four physical splice inputs."""

    static_prefix_specs: list[dict[str, Any]] = []
    old_context_replay_specs: list[dict[str, Any]] = []
    current_append_specs: list[dict[str, Any]] = []
    current_tail_specs: list[dict[str, Any]] = []
    section_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    trace: list[dict[str, Any]] = []

    for index, raw_spec in enumerate(list(specs or ()), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = _spec_with_context_policy_metadata(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        section = str(policy.section or "")
        section_counts[section or "missing"] = section_counts.get(section or "missing", 0) + 1
        if section == STATIC_PREFIX:
            route = "static_prefix_specs"
            static_prefix_specs.append(spec)
        elif section == CONTEXT_MEMORY_PREFIX:
            route = "old_context_replay_specs"
            old_context_replay_specs.append(spec)
        elif section == CONTEXT_APPEND:
            route = "current_append_specs"
            current_append_specs.append(spec)
        else:
            route = "current_tail_specs"
            current_tail_specs.append(spec)
        route_counts[route] = route_counts.get(route, 0) + 1
        trace.append(
            {
                "input_index": index,
                "kind": str(spec.get("kind") or ""),
                "source_ref": str(spec.get("source_ref") or ""),
                "context_cache_section": section,
                "route": route,
                "semantic_slot": str(policy.semantic_slot or ""),
            }
        )

    diagnostics = {
        "status": "classified",
        "input_stage": str(input_stage or "draft"),
        "input_spec_count": len([item for item in list(specs or ()) if isinstance(item, dict)]),
        "section_counts": section_counts,
        "route_counts": route_counts,
        "classification_trace": trace[:80],
        "classification_trace_count": len(trace),
        "authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
    }
    return PhysicalContextInputs(
        static_prefix_specs=tuple(static_prefix_specs),
        old_context_replay_specs=tuple(old_context_replay_specs),
        current_append_specs=tuple(current_append_specs),
        current_tail_specs=tuple(current_tail_specs),
        storage_root=storage_root,
        scope=str(scope or "").strip(),
        provider=str(provider or "").strip(),
        model=str(model or "").strip(),
        provider_lane=str(provider_lane or "").strip(),
        input_stage=str(input_stage or "draft"),
        diagnostics=diagnostics,
    )


def assemble_physical_context_spine(
    inputs: PhysicalContextInputs,
) -> PhysicalContextAssemblyResult:
    """Assemble the only physical order the runtime is allowed to send.

    The provider-visible ledger supplies current append candidates. Explicit old
    context input or the physical frame supplies confirmed replay order. This function is the runtime splice point:
    static prefix -> confirmed old frame -> current append -> dynamic tail.
    """

    clean_static = [dict(item) for item in list(inputs.static_prefix_specs or []) if isinstance(item, dict)]
    clean_old_context = [dict(item) for item in list(inputs.old_context_replay_specs or []) if isinstance(item, dict)]
    clean_append_specs = [dict(item) for item in list(inputs.current_append_specs or []) if isinstance(item, dict)]
    clean_tail = [dict(item) for item in list(inputs.current_tail_specs or []) if isinstance(item, dict)]
    current_append_specs, ignored_provider_visible_specs = _current_append_specs(clean_append_specs)
    current_tail_specs, never_replay_tail_specs = _split_current_tail_specs(clean_tail)
    frame: PhysicalPrefixFrame | None = None
    frame_replay_specs: list[dict[str, Any]] = []
    frame_replay_diagnostics: dict[str, Any] = {}
    if clean_old_context:
        replay_specs = clean_old_context
        replay_source = "confirmed_old_context_input"
    else:
        frame_payload = latest_confirmed_physical_prefix_frame(
            storage_root=inputs.storage_root,
            scope=inputs.scope,
            provider=inputs.provider,
            model=inputs.model,
            provider_lane=inputs.provider_lane,
        )
        frame = PhysicalPrefixFrame.from_dict(frame_payload) if frame_payload else None
        if frame is not None and frame.frame_id:
            frame_replay_specs, frame_replay_diagnostics = _frame_replay_specs(frame)
            replay_specs = frame_replay_specs
            replay_source = "physical_prefix_frame"
        else:
            replay_specs = []
            replay_source = "missing_physical_prefix_frame"
    physical_static_specs = _with_physical_lane_specs(clean_static, lane=GLOBAL_STATIC_PREFIX)
    physical_replay_specs = _with_physical_lane_specs(replay_specs, lane=PROVIDER_VISIBLE_CONTEXT_PREFIX)
    physical_current_append_specs = _with_physical_lane_specs(current_append_specs, lane=CURRENT_TURN_TAIL)
    physical_current_tail_specs = _with_physical_lane_specs(current_tail_specs, lane=CURRENT_TURN_TAIL)
    physical_tail_specs = _with_physical_lane_specs(never_replay_tail_specs, lane=NEVER_REPLAY_TAIL)
    result_specs = _with_physical_assembly_indexes(
        [
            *physical_static_specs,
            *physical_replay_specs,
            *physical_current_append_specs,
            *physical_current_tail_specs,
            *physical_tail_specs,
        ]
    )
    diagnostics = {
        "status": "applied",
        "scope": str(inputs.scope or ""),
        "provider": str(inputs.provider or ""),
        "model": str(inputs.model or ""),
        "provider_lane": str(inputs.provider_lane or ""),
        "physical_context_inputs": inputs.to_diagnostics(),
        "latest_physical_prefix_frame_id": str(getattr(frame, "frame_id", "") or ""),
        "latest_physical_prefix_frame_request_id": str(getattr(frame, "source_request_id", "") or ""),
        "latest_physical_prefix_frame_hash": str(getattr(frame, "provider_payload_prefix_hash", "") or ""),
        "provider_message_replay_source": replay_source,
        "input_old_context_replay_spec_count": len(clean_old_context),
        "old_context_replay_spec_count": len(replay_specs),
        "physical_prefix_frame_replay_spec_count": len(frame_replay_specs),
        "ignored_non_current_provider_visible_spec_count": len(ignored_provider_visible_specs),
        "ignored_non_current_provider_visible_specs": ignored_provider_visible_specs[:30],
        "current_append_spec_count": len(current_append_specs),
        "current_tail_spec_count": len(current_tail_specs),
        "never_replay_tail_spec_count": len(never_replay_tail_specs),
        "static_prefix_spec_count": len(clean_static),
        "output_spec_count": len(result_specs),
        "frame_replay": frame_replay_diagnostics,
        "provider_message_replay_authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        "physical_splice_rule": "static_prefix_then_confirmed_old_context_then_current_append_then_dynamic_tail",
        "authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
    }
    if not clean_old_context and frame is None and ignored_provider_visible_specs:
        diagnostics["structural_gap"] = {
            "code": "physical_prefix_frame_missing_for_confirmed_provider_visible_context",
            "policy": "fail_closed_provider_message_replay_until_first_confirmed_physical_frame",
            "ignored_provider_visible_spec_count": len(ignored_provider_visible_specs),
            "authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        }
    if frame is not None and frame_replay_diagnostics.get("missing_provider_message_count"):
        diagnostics["structural_gap"] = {
            "code": "physical_prefix_frame_segment_message_missing",
            "missing_provider_message_count": frame_replay_diagnostics.get("missing_provider_message_count"),
            "missing_segments": list(frame_replay_diagnostics.get("missing_segments") or []),
            "authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        }
    return PhysicalContextAssemblyResult(
        message_specs=tuple(result_specs),
        old_context_specs=tuple(physical_replay_specs),
        current_append_specs=tuple(physical_current_append_specs),
        diagnostics=diagnostics,
    )


def _split_current_tail_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_tail: list[dict[str, Any]] = []
    never_replay_tail: list[dict[str, Any]] = []
    for raw_spec in list(specs or []):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        if policy.section == CONTEXT_MEMORY_PREFIX:
            current_tail.append(spec)
            continue
        if policy.section == DYNAMIC_TAIL:
            never_replay_tail.append(spec)
            continue
        current_tail.append(spec)
    return current_tail, never_replay_tail


def _with_physical_lane_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    lane: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_spec in list(specs or []):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        metadata = {
            **dict(spec.get("metadata") or {}),
            "physical_prefix_lane": str(lane or ""),
            "physical_context_assembler_authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        }
        spec["metadata"] = metadata
        spec["physical_prefix_lane"] = str(lane or "")
        result.append(spec)
    return result


def _with_physical_assembly_indexes(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw_spec in enumerate(list(specs or []), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        metadata = {
            **dict(spec.get("metadata") or {}),
            "context_physical_assembly_index": index,
            "physical_context_assembler_authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        }
        spec["metadata"] = metadata
        result.append(spec)
    return result


def _spec_with_context_policy_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    payload = _without_physical_assembly_metadata(dict(spec or {}))
    policy = context_segment_policy_for_spec(payload)
    metadata = {
        **dict(payload.get("metadata") or {}),
        **context_segment_policy_metadata(policy),
    }
    payload["metadata"] = metadata
    payload["cache_scope"] = policy.prefix_cache_scope
    payload["cache_role"] = policy.prefix_cache_role
    payload["prefix_tier"] = policy.prefix_tier
    return payload


def _without_physical_assembly_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    payload.pop("physical_prefix_lane", None)
    metadata = dict(payload.get("metadata") or {})
    for key in (
        "physical_prefix_lane",
        "context_physical_assembly_index",
        "physical_context_assembler_authority",
        "physical_context_plan_ref",
        "physical_context_plan_authority",
    ):
        metadata.pop(key, None)
    payload["metadata"] = metadata
    return payload


def _current_append_specs(
    specs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_append_specs: list[dict[str, Any]] = []
    ignored_specs: list[dict[str, Any]] = []
    for raw_spec in specs:
        spec = dict(raw_spec or {})
        metadata = dict(spec.get("metadata") or {})
        if not physical_prefix_frame_replay_metadata(metadata):
            current_append_specs.append(spec)
            continue
        ignored_specs.append(
            {
                "kind": str(spec.get("kind") or ""),
                "source_ref": str(spec.get("source_ref") or ""),
                "provider_visible_payload_authority": str(metadata.get("provider_visible_payload_authority") or ""),
                "provider_visible_history_status": str(metadata.get("provider_visible_history_status") or ""),
                "context_replay_policy": str(metadata.get("context_replay_policy") or ""),
                "provider_message_replay_contract": provider_message_replay_kind(spec),
            }
        )
    return current_append_specs, ignored_specs


def _frame_replay_specs(frame: PhysicalPrefixFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for segment in sorted(frame.segments, key=lambda item: int(item.ordinal or 0)):
        if not _segment_is_physical_prefix_frame_message(segment):
            continue
        message = dict(segment.provider_message or {})
        if not message:
            missing.append(
                {
                    "ordinal": segment.ordinal,
                    "segment_id": segment.segment_id,
                    "provider_visible_entry_index": segment.provider_visible_entry_index,
                    "provider_visible_hash": segment.provider_visible_hash,
                }
            )
            continue
        result.append(_spec_from_frame_segment(segment, frame=frame, message=message))
    return result, {
        "frame_id": frame.frame_id,
        "source_request_id": frame.source_request_id,
        "input_segment_count": len(frame.segments),
        "output_spec_count": len(result),
        "missing_provider_message_count": len(missing),
        "missing_segments": missing[:30],
        "authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
    }


def _segment_is_physical_prefix_frame_message(segment: PhysicalPrefixFrameSegment) -> bool:
    return (
        str(segment.transport_location or "") == "messages"
        and str(segment.physical_prefix_lane or "") == PROVIDER_VISIBLE_CONTEXT_PREFIX
    )


def _spec_from_frame_segment(
    segment: PhysicalPrefixFrameSegment,
    *,
    frame: PhysicalPrefixFrame,
    message: dict[str, Any],
) -> dict[str, Any]:
    replay_semantic_slot = _frame_replay_semantic_slot(segment)
    metadata = {
        **dict(segment.metadata or {}),
        "context_cache_section": CONTEXT_MEMORY_PREFIX,
        "fixed_context_package": "context_memory_prefix",
        "physical_prefix_lane": PROVIDER_VISIBLE_CONTEXT_PREFIX,
        "physical_prefix_frame_id": frame.frame_id,
        "physical_prefix_frame_source_request_id": frame.source_request_id,
        "physical_prefix_frame_segment_id": segment.segment_id,
        "physical_prefix_frame_segment_ordinal": segment.ordinal,
        "physical_prefix_frame_replay_authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        "context_origin_authority": str(dict(segment.prefix_identity or {}).get("origin_authority") or ""),
        "context_origin_ref": str(dict(segment.prefix_identity or {}).get("origin_ref") or segment.source_ref or segment.segment_id),
        "context_prefix_identity": dict(segment.prefix_identity or {}),
        "context_prefix_lifecycle_state": "confirmed_frame_replay",
        "context_semantic_slot": replay_semantic_slot,
        "logical_segment_ref": segment.logical_segment_ref,
        "prefix_segment_ref": segment.prefix_segment_ref,
        "content_version_hash": segment.content_version_hash,
        "provider_serialized_hash": segment.provider_serialized_hash,
        "provider_visible_append_entry_index": segment.provider_visible_entry_index,
        "provider_visible_append_item_key": segment.provider_visible_item_key,
        "provider_visible_hash": segment.provider_visible_hash,
        "provider_visible_payload_form": "provider_chat_completion_message",
        "provider_visible_payload_authority": PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY,
        "provider_visible_history_status": PHYSICAL_PREFIX_FRAME_REPLAY_STATUS,
        "provider_visible_append_commit_stage": PHYSICAL_PREFIX_FRAME_REPLAY_STATUS,
        "context_replay_policy": PHYSICAL_PREFIX_FRAME_REPLAY_POLICY,
        "context_commit_policy": "replay_only_from_physical_prefix_frame",
        "memory_commit_policy": "replay_only_from_physical_prefix_frame",
        "content_source": "runtime.context_management.physical_prefix_frame.replay",
    }
    spec = {
        "role": str(message.get("role") or segment.role or "system"),
        "content": str(message.get("content") if message.get("content") is not None else ""),
        "kind": _frame_replay_kind(segment),
        "source_ref": segment.source_ref or segment.segment_id,
        "cache_scope": segment.cache_scope or "session",
        "cache_role": segment.cache_role or "session_stable",
        "prefix_tier": segment.prefix_tier or "session",
        "compression_role": "preserve",
        "metadata": metadata,
        "model_message": dict(message),
    }
    policy = context_segment_policy_for_spec(spec, default_section=CONTEXT_MEMORY_PREFIX)
    spec["metadata"] = {
        **metadata,
        **context_segment_policy_metadata(policy),
        "context_cache_section": CONTEXT_MEMORY_PREFIX,
        "physical_prefix_lane": PROVIDER_VISIBLE_CONTEXT_PREFIX,
        "physical_prefix_frame_id": frame.frame_id,
        "physical_prefix_frame_replay_authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
        "provider_visible_append_commit_stage": PHYSICAL_PREFIX_FRAME_REPLAY_STATUS,
        "context_replay_policy": PHYSICAL_PREFIX_FRAME_REPLAY_POLICY,
        "context_commit_policy": "replay_only_from_physical_prefix_frame",
        "memory_commit_policy": "replay_only_from_physical_prefix_frame",
    }
    spec["cache_scope"] = policy.prefix_cache_scope
    spec["cache_role"] = policy.prefix_cache_role
    spec["prefix_tier"] = policy.prefix_tier
    return spec


def _frame_replay_kind(segment: PhysicalPrefixFrameSegment) -> str:
    metadata = dict(segment.metadata or {})
    semantic_slot = str(metadata.get("context_semantic_slot") or metadata.get("semantic_slot") or "").strip()
    original_kind = str(segment.kind or "").strip()
    role = str(segment.role or dict(segment.provider_message or {}).get("role") or "").strip()
    if role == "tool" or semantic_slot == "tool_transcript" or original_kind in {
        "single_agent_turn_tool_call",
        "tool_transcript_delta",
        "single_agent_turn_tool_observation",
        "tool_observations",
    }:
        return "physical_prefix_frame_tool_transcript_replay"
    if semantic_slot == "current_user_intent" or original_kind in {
        "current_turn_user_context",
        "single_agent_turn_user_steer_context",
        "user_steering_context_append",
    }:
        return "physical_prefix_frame_user_context_replay"
    if role == "user":
        return "physical_prefix_frame_user_message_replay"
    if role == "assistant":
        return "physical_prefix_frame_assistant_message_replay"
    return "physical_prefix_frame_context_replay"


def _frame_replay_semantic_slot(segment: PhysicalPrefixFrameSegment) -> str:
    metadata = dict(segment.metadata or {})
    semantic_slot = str(metadata.get("context_semantic_slot") or metadata.get("semantic_slot") or segment.semantic_slot or "").strip()
    replay_kind = _frame_replay_kind(segment)
    if replay_kind == "physical_prefix_frame_tool_transcript_replay":
        return "tool_transcript"
    if replay_kind in {
        "physical_prefix_frame_user_context_replay",
        "physical_prefix_frame_user_message_replay",
        "physical_prefix_frame_assistant_message_replay",
        "physical_prefix_frame_context_replay",
    }:
        return "provider_protocol_history"
    return semantic_slot or "provider_protocol_history"
