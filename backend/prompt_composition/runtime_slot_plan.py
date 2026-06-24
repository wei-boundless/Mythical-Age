from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import PromptCompositionSlot, RuntimePromptSlot, RuntimePromptSlotPlan
from .tracing import runtime_source_kind_for_segment
from runtime.context_management.context_assembly import CONTEXT_APPEND, CONTEXT_MEMORY_PREFIX, DYNAMIC_TAIL, classify_context_spec


def build_runtime_prompt_slot_plan(
    *,
    invocation_kind: str,
    packet_id: str,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> RuntimePromptSlotPlan:
    slots: list[RuntimePromptSlot] = []
    for index, raw_spec in enumerate(list(message_specs or []), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = _normalized_spec(raw_spec)
        kind = str(spec.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
        source_kind = runtime_source_kind_for_segment(spec)
        classification = classify_context_spec(spec)
        layer = _layer_for_source_kind(source_kind)
        if classification.context_cache_section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
            layer = "context_memory"
        elif classification.context_cache_section == DYNAMIC_TAIL:
            layer = "runtime_dynamic"
        metadata = dict(spec.get("metadata") or {})
        prompt_source_manifest_id = str(metadata.get("runtime_prompt_source_manifest_id") or "")
        prompt_source_id = str(metadata.get("runtime_prompt_source_id") or "")
        content_hash = _stable_text_hash(str(spec.get("content") or ""))
        slot_id = _slot_id(
            invocation_kind=invocation_kind,
            packet_id=packet_id,
            order=index,
            kind=kind,
            source_ref=str(spec.get("source_ref") or ""),
            content_hash=content_hash,
        )
        slots.append(
            RuntimePromptSlot(
                slot_id=slot_id,
                invocation_kind=str(invocation_kind or ""),
                packet_id=str(packet_id or ""),
                order=index,
                layer=layer,
                slot_kind=kind,
                target_role=str(spec.get("role") or "user"),
                source_kind=source_kind,
                source_ref=str(spec.get("source_ref") or ""),
                cache_scope=classification.cache_scope,
                cache_role=classification.cache_role,
                cache_tier=classification.prefix_tier,
                dynamic_tier=_dynamic_tier(kind=kind, source_kind=source_kind, cache_role=classification.cache_role, classification=classification.to_dict()),
                compression_role=str(spec.get("compression_role") or "summarize"),
                authority_class=str(metadata.get("authority_class") or _authority_class_for_source_kind(source_kind)),
                render_contract=_render_contract(spec, source_kind=source_kind),
                message_spec=spec,
                content_hash=content_hash,
                metadata={
                    "source_metadata": metadata,
                    "prompt_source_manifest_id": prompt_source_manifest_id,
                    "prompt_source_id": prompt_source_id,
                    "slot_source": "runtime_prompt_source_manifest",
                    **classification.to_dict(),
                },
            )
        )
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "packet_id": str(packet_id or ""),
        "slots": [
            {
                "slot_id": slot.slot_id,
                "order": slot.order,
                "kind": slot.slot_kind,
                "layer": slot.layer,
                "source_kind": slot.source_kind,
                "source_ref": slot.source_ref,
                "content_hash": slot.content_hash,
            }
            for slot in slots
        ],
    }
    return RuntimePromptSlotPlan(
        plan_id="rtpromptslots:" + _stable_hash(seed)[:16],
        invocation_kind=str(invocation_kind or ""),
        packet_id=str(packet_id or ""),
        slots=tuple(slots),
        diagnostics={
            "slot_count": len(slots),
            "layer_counts": _count_by(slots, "layer"),
            "dynamic_tier_counts": _count_by(slots, "dynamic_tier"),
            "source_kind_counts": _count_by(slots, "source_kind"),
            "authority": "prompt_composition.runtime_slot_plan.builder",
        },
    )


def composition_slots_from_runtime_slot_plan(slot_plan: RuntimePromptSlotPlan) -> tuple[PromptCompositionSlot, ...]:
    slots: list[PromptCompositionSlot] = []
    for slot in tuple(slot_plan.slots or ()):
        slots.append(
            PromptCompositionSlot(
                slot_id=slot.slot_id,
                invocation_kind=slot.invocation_kind,
                layer=slot.layer,
                slot_kind=slot.slot_kind,
                target_role=slot.target_role,
                lifecycle=_lifecycle_for_slot(slot),
                cache_scope=slot.cache_scope,
                cache_role=slot.cache_role,
                prefix_tier=slot.cache_tier,
                source_kind=slot.source_kind,
                source_ref=slot.source_ref,
                content_hash=slot.content_hash,
                order=slot.order,
                required=True,
                message_kinds=(slot.slot_kind,),
                metadata={
                    "runtime_prompt_slot_plan_id": slot_plan.plan_id,
                    "authority_class": slot.authority_class,
                    "dynamic_tier": slot.dynamic_tier,
                    "render_contract": dict(slot.render_contract),
                },
            )
        )
    return tuple(slots)


def _normalized_spec(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    payload["role"] = str(payload.get("role") or "user")
    payload["content"] = str(payload.get("content") or "")
    payload["kind"] = str(payload.get("kind") or "unknown_unplanned")
    payload["metadata"] = dict(payload.get("metadata") or {})
    return payload


def _render_contract(spec: dict[str, Any], *, source_kind: str) -> dict[str, Any]:
    metadata = dict(spec.get("metadata") or {})
    return _drop_empty(
        {
            "render_kind": "model_message_spec",
            "message_role": str(spec.get("role") or "user"),
            "message_kind": str(spec.get("kind") or ""),
            "content_source": str(metadata.get("content_source") or ""),
            "runtime_fragment_title": str(metadata.get("runtime_fragment_title") or ""),
            "runtime_fragment_payload_keys": list(metadata.get("runtime_fragment_payload_keys") or []),
            "source_kind": source_kind,
        }
    )


def _layer_for_source_kind(source_kind: str) -> str:
    if source_kind == "runtime_baseline_refs":
        return "runtime_protocol_stable"
    if source_kind == "dynamic_context_fragment":
        return "runtime_dynamic"
    if source_kind in {
        "runtime_read_evidence",
        "runtime_bound_task_context",
        "runtime_dynamic_boundary",
        "runtime_active_skills",
        "runtime_attachment_context_index",
        "runtime_evidence_index_cursor",
        "runtime_task_plan_context",
        "runtime_editor_context_index",
        "runtime_editor_evidence_delta",
        "runtime_memory_context",
    }:
        return "runtime_dynamic"
    if source_kind in {"runtime_action_schema", "tool_catalog"}:
        return "capability_stable"
    if source_kind in {"semantic_compaction_boundary", "runtime_lifecycle"}:
        return "lifecycle_stable"
    if source_kind == "runtime_file_evidence_policy":
        return "file_evidence_policy_stable"
    if source_kind == "runtime_artifact_scope":
        return "artifact_scope_stable"
    if source_kind == "runtime_project_instructions":
        return "project_stable"
    if source_kind == "runtime_contract":
        return "task_contract_stable"
    if source_kind == "runtime_task_boundary":
        return "task_runtime_boundary_stable"
    if source_kind in {"runtime_task_state_replay", "runtime_append_only_context"}:
        return "append_only_task_evidence"
    if source_kind == "runtime_read_evidence_context":
        return "append_only_task_evidence"
    if source_kind == "runtime_evidence_index_cursor":
        return "runtime_dynamic"
    if source_kind == "runtime_task_plan_context":
        return "runtime_dynamic"
    if source_kind == "runtime_protocol":
        return "runtime_protocol_stable"
    return "legacy_runtime_stable"


def _authority_class_for_source_kind(source_kind: str) -> str:
    return {
        "dynamic_context_fragment": "runtime_dynamic_context",
        "runtime_action_schema": "runtime_action_schema",
        "runtime_artifact_scope": "runtime_artifact_scope",
        "runtime_bound_task_context": "bound_task_context",
        "runtime_contract": "task_contract",
        "runtime_environment_boundary": "environment_boundary",
        "runtime_file_evidence_policy": "file_evidence_policy",
        "runtime_lifecycle": "runtime_lifecycle_protocol",
        "runtime_project_instructions": "project_instruction_boundary",
        "runtime_task_boundary": "runtime_boundary",
        "runtime_task_state_replay": "runtime_task_state_replay",
        "runtime_append_only_context": "append_only_context",
        "runtime_attachment_context_index": "attachment_context_index",
        "runtime_evidence_index_cursor": "evidence_index_cursor",
        "runtime_task_plan_context": "task_plan_context",
        "runtime_editor_context_index": "editor_context_index",
        "runtime_editor_evidence_delta": "editor_evidence_delta",
        "runtime_memory_context": "runtime_memory_context",
        "runtime_baseline_refs": "runtime_baseline_refs",
        "runtime_read_evidence_context": "read_evidence_context",
        "runtime_protocol": "runtime_protocol",
        "tool_catalog": "tool_catalog",
    }.get(source_kind, "runtime_prompt_slot")


def _dynamic_tier(*, kind: str, source_kind: str, cache_role: str, classification: dict[str, Any] | None = None) -> str:
    assembly = dict(classification or {})
    section = str(assembly.get("context_cache_section") or "")
    if section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        if kind == "runtime_memory_context":
            return "runtime_memory_context"
        if kind in {"current_turn_user_context", "single_agent_turn_user_steer_context", "user_steering_context_append"}:
            return "user_context_append"
        if kind in {"provider_protocol_history", "single_agent_turn_tool_call", "single_agent_turn_tool_observation", "tool_observations"}:
            return "append_only_task_evidence"
        return "context_memory_append"
    if section == DYNAMIC_TAIL:
        if kind == "read_evidence_injection":
            return "current_exact_evidence"
        if kind in {"active_skills", "skill_candidates"}:
            return "active_skills"
        if kind == "graph_node_completion_prefix":
            return "assistant_completion_prefix"
        return "dynamic_context_tail"
    if source_kind in {"runtime_task_state_replay", "runtime_append_only_context"} or kind == "task_state_replay_entry":
        return "append_only_task_evidence"
    if source_kind == "runtime_read_evidence_context" or kind == "read_evidence_context":
        return "append_only_task_evidence"
    if kind == "lifecycle_runtime_guidance":
        return "dynamic_context_tail"
    if kind in {"task_start_inherited_context", "task_runtime_boundary_dynamic"}:
        return "runtime_cursor_prefix"
    if source_kind == "runtime_attachment_context_index" or kind == "attachment_context_index":
        return "attachment_context_index"
    if source_kind == "runtime_evidence_index_cursor" or kind == "evidence_index_cursor":
        return "evidence_index_cursor"
    if source_kind == "runtime_task_plan_context" or kind == "task_plan_context":
        return "task_plan_context"
    if source_kind == "runtime_editor_context_index" or kind == "editor_context_index":
        return "editor_context_index"
    if kind == "graph_node_completion_prefix":
        return "assistant_completion_prefix"
    if kind in {"active_skills", "skill_candidates"}:
        return "active_skills"
    if kind in {"bound_task_runtime_context"}:
        return "file_evidence_cursor"
    if source_kind == "runtime_memory_context" or kind == "runtime_memory_context":
        return "runtime_memory_context"
    if source_kind == "runtime_baseline_refs" or kind == "runtime_baseline_refs":
        return "runtime_baseline_refs"
    if kind == "dynamic_projection":
        return "runtime_delta_tail"
    if source_kind in {"runtime_incremental_context_frame", "runtime_incremental_context_cursor"} or kind in {
        "incremental_context_frame",
        "incremental_context_cursor",
    }:
        return "dynamic_context_tail"
    if source_kind == "runtime_editor_evidence_delta" or kind == "current_editor_evidence_delta":
        return "current_exact_evidence"
    if kind == "read_evidence_injection":
        return "current_exact_evidence"
    if kind in {"session_history", "session_history_context"}:
        return "history_replay"
    if kind == "session_history_tail_context":
        return "dynamic_context_tail"
    if kind == "current_turn_user_context":
        return "user_context_append"
    if kind == "semantic_compaction_request":
        return "user_editor_volatile"
    if str(cache_role or "") not in {"volatile", "never_cache"}:
        return "stable_prefix"
    return "current_runtime_cursor"


def _cache_tier(spec: dict[str, Any]) -> str:
    explicit = str(spec.get("prefix_tier") or "").strip()
    if explicit:
        return explicit
    cache_role = str(spec.get("cache_role") or "").strip()
    cache_scope = str(spec.get("cache_scope") or "").strip()
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        if cache_scope == "task":
            return "task"
        if cache_scope == "global":
            return "provider_global"
        return "session"
    if cache_role == "volatile":
        return "volatile"
    return "none"


def _lifecycle_for_slot(slot: RuntimePromptSlot) -> str:
    if slot.cache_role in {"volatile", "never_cache"} or slot.cache_tier in {"volatile", "none"}:
        return "runtime_dynamic"
    if slot.cache_tier == "provider_global":
        return "global_static"
    if slot.cache_tier == "task":
        return "task_stable"
    return "session_stable"


def _count_by(slots: list[RuntimePromptSlot], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slot in slots:
        key = str(getattr(slot, field_name, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _slot_id(
    *,
    invocation_kind: str,
    packet_id: str,
    order: int,
    kind: str,
    source_ref: str,
    content_hash: str,
) -> str:
    digest = _stable_hash(
        {
            "invocation_kind": invocation_kind,
            "packet_id": packet_id,
            "order": order,
            "kind": kind,
            "source_ref": source_ref,
            "content_hash": content_hash,
        }
    )[:12]
    return f"rtpromptslot:{invocation_kind}:{order}:{kind}:{digest}"


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _stable_text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
