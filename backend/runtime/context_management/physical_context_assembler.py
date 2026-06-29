from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context_segment_policy import (
    CONTEXT_MEMORY_PREFIX,
    context_segment_policy_for_spec,
    context_segment_policy_metadata,
)
from .physical_context_plan import PROVIDER_VISIBLE_CONTEXT_PREFIX
from .physical_prefix_frame_ledger import latest_confirmed_physical_prefix_frame
from .physical_prefix_frame_models import PhysicalPrefixFrame, PhysicalPrefixFrameSegment


PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY = "runtime.context_management.physical_context_assembler"


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


def assemble_physical_context_spine(
    *,
    static_prefix_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    provider_visible_ledger_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    current_tail_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    storage_root: Path | None,
    scope: str,
    provider: str = "",
    model: str = "",
    provider_lane: str = "",
) -> PhysicalContextAssemblyResult:
    """Assemble the only physical order the runtime is allowed to send.

    The provider-visible ledger supplies content candidates. The physical frame
    supplies old-context order. This function is the runtime splice point:
    static prefix -> confirmed old frame -> current append -> dynamic tail.
    """

    clean_static = [dict(item) for item in list(static_prefix_specs or []) if isinstance(item, dict)]
    clean_ledger = [dict(item) for item in list(provider_visible_ledger_specs or []) if isinstance(item, dict)]
    clean_tail = [dict(item) for item in list(current_tail_specs or []) if isinstance(item, dict)]
    frame_payload = latest_confirmed_physical_prefix_frame(
        storage_root=storage_root,
        scope=scope,
        provider=provider,
        model=model,
        provider_lane=provider_lane,
    )
    frame = PhysicalPrefixFrame.from_dict(frame_payload) if frame_payload else None
    current_append_specs, ignored_provider_visible_specs = _current_append_specs(clean_ledger)
    frame_replay_specs: list[dict[str, Any]] = []
    frame_replay_diagnostics: dict[str, Any] = {}
    if frame is not None and frame.frame_id:
        frame_replay_specs, frame_replay_diagnostics = _frame_replay_specs(frame)
        old_context_specs = frame_replay_specs
        replay_source = "physical_prefix_frame"
    else:
        old_context_specs = []
        replay_source = "missing_physical_prefix_frame"
    result_specs = [
        *clean_static,
        *old_context_specs,
        *current_append_specs,
        *clean_tail,
    ]
    diagnostics = {
        "status": "applied",
        "scope": str(scope or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "provider_lane": str(provider_lane or ""),
        "latest_physical_prefix_frame_id": str(getattr(frame, "frame_id", "") or ""),
        "latest_physical_prefix_frame_request_id": str(getattr(frame, "source_request_id", "") or ""),
        "latest_physical_prefix_frame_hash": str(getattr(frame, "provider_payload_prefix_hash", "") or ""),
        "old_context_replay_source": replay_source,
        "old_context_frame_replay_spec_count": len(frame_replay_specs),
        "ignored_non_current_provider_visible_spec_count": len(ignored_provider_visible_specs),
        "ignored_non_current_provider_visible_specs": ignored_provider_visible_specs[:30],
        "current_append_spec_count": len(current_append_specs),
        "current_tail_spec_count": len(clean_tail),
        "static_prefix_spec_count": len(clean_static),
        "output_spec_count": len(result_specs),
        "frame_replay": frame_replay_diagnostics,
        "old_context_bootstrap_authority": "physical_prefix_frame_only",
        "physical_splice_rule": "static_prefix_then_confirmed_physical_frame_then_current_append_then_dynamic_tail",
        "authority": PHYSICAL_CONTEXT_ASSEMBLER_AUTHORITY,
    }
    if frame is None and ignored_provider_visible_specs:
        diagnostics["structural_gap"] = {
            "code": "physical_prefix_frame_missing_for_confirmed_provider_visible_context",
            "policy": "fail_closed_old_context_replay_until_first_confirmed_physical_frame",
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
        old_context_specs=tuple(old_context_specs),
        current_append_specs=tuple(current_append_specs),
        diagnostics=diagnostics,
    )


def _current_append_specs(
    specs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_append_specs: list[dict[str, Any]] = []
    ignored_specs: list[dict[str, Any]] = []
    for raw_spec in specs:
        spec = dict(raw_spec or {})
        metadata = dict(spec.get("metadata") or {})
        commit_stage = str(metadata.get("provider_visible_context_ledger_commit_stage") or "")
        payload_authority = str(metadata.get("provider_visible_payload_authority") or "")
        replay_policy = str(metadata.get("context_replay_policy") or "")
        history_status = str(metadata.get("provider_visible_history_status") or "")
        if (
            commit_stage == "provider_success_required"
            and payload_authority != "runtime.context_management.physical_prefix_frame.replay"
            and replay_policy != "physical_prefix_frame_replay"
            and history_status != "sealed_from_physical_prefix_frame"
        ):
            current_append_specs.append(spec)
            continue
        ignored_specs.append(
            {
                "kind": str(spec.get("kind") or ""),
                "source_ref": str(spec.get("source_ref") or ""),
                "provider_visible_payload_authority": str(metadata.get("provider_visible_payload_authority") or ""),
                "provider_visible_history_status": str(metadata.get("provider_visible_history_status") or ""),
                "context_replay_policy": str(metadata.get("context_replay_policy") or ""),
            }
        )
    return current_append_specs, ignored_specs


def _frame_replay_specs(frame: PhysicalPrefixFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for segment in sorted(frame.segments, key=lambda item: int(item.ordinal or 0)):
        if not _segment_is_old_context_message(segment):
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


def _segment_is_old_context_message(segment: PhysicalPrefixFrameSegment) -> bool:
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
        "provider_visible_context_ledger_entry_index": segment.provider_visible_entry_index,
        "provider_visible_context_ledger_item_key": segment.provider_visible_item_key,
        "provider_visible_hash": segment.provider_visible_hash,
        "provider_visible_payload_form": "provider_chat_completion_message",
        "provider_visible_payload_authority": "runtime.context_management.physical_prefix_frame.replay",
        "provider_visible_history_status": "sealed_from_physical_prefix_frame",
        "provider_visible_context_ledger_commit_stage": "sealed_from_physical_prefix_frame",
        "context_replay_policy": "physical_prefix_frame_replay",
        "context_commit_policy": "replay_only_from_physical_prefix_frame",
        "memory_commit_policy": "replay_only_from_physical_prefix_frame",
        "semantic_memory_commit_policy": "never_commit",
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
        "provider_visible_context_ledger_commit_stage": "sealed_from_physical_prefix_frame",
        "context_replay_policy": "physical_prefix_frame_replay",
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
