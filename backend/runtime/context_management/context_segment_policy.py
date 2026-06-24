from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from .context_assembly import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    classify_context_spec,
    context_physical_segment_for_section,
    context_physical_segment_rank,
    context_prefix_boundary_for_section,
    context_prefix_state_for_section,
)


DEFAULT_PROVIDER_ADAPTER_CONTRACT = "deepseek_v4_provider_visible_message_v1"

DEFAULT_CONTEXT_APPEND_SLOT_RANKS: dict[str, int] = {
    "recovery_or_recent_work_facts": 10,
    "provider_protocol_history": 15,
    "selected_memory_and_task_state_facts": 20,
    "current_user_intent": 30,
    "active_user_steer_content": 35,
    "evidence_refs_and_file_state_facts": 40,
    "tool_transcript": 70,
    "context_memory_append": 90,
    "action_contract": 95,
}

KIND_CONTEXT_APPEND_SLOT_DEFAULTS: dict[str, str] = {
    "current_turn_user_context": "current_user_intent",
    "single_agent_turn_user_steer_context": "active_user_steer_content",
    "user_steering_context_append": "active_user_steer_content",
    "provider_visible_ledger_recovery_checkpoint": "recovery_or_recent_work_facts",
    "recovery_context_package": "recovery_or_recent_work_facts",
    "recent_work_outcome": "recovery_or_recent_work_facts",
    "runtime_memory_context": "selected_memory_and_task_state_facts",
    "task_plan_context": "selected_memory_and_task_state_facts",
    "task_state_replay_entry": "selected_memory_and_task_state_facts",
    "read_evidence_context": "evidence_refs_and_file_state_facts",
    "evidence_index_cursor": "evidence_refs_and_file_state_facts",
    "attachment_context_index": "evidence_refs_and_file_state_facts",
    "editor_context_index": "evidence_refs_and_file_state_facts",
    "provider_protocol_history": "provider_protocol_history",
    "session_history": "provider_protocol_history",
    "session_history_context": "provider_protocol_history",
    "session_history_entry": "provider_protocol_history",
    "single_agent_turn_followup_action_contract": "action_contract",
    "single_agent_turn_tool_call": "tool_transcript",
    "single_agent_turn_tool_observation": "tool_transcript",
    "tool_observations": "tool_transcript",
}

STREAM_CONTEXT_APPEND_SLOT_DEFAULTS: dict[str, str] = {
    "current_user_context": "current_user_intent",
    "user_steer": "active_user_steer_content",
    "runtime_memory_context": "selected_memory_and_task_state_facts",
    "read_evidence": "evidence_refs_and_file_state_facts",
    "provider_protocol": "provider_protocol_history",
    "tool_transcript": "tool_transcript",
}


@dataclass(frozen=True, slots=True)
class ContextSegmentPolicy:
    section: str
    physical_segment: str
    physical_segment_rank: int
    prefix_state: str
    prefix_boundary: str
    prefix_cache_scope: str
    prefix_cache_role: str
    prefix_tier: str
    semantic_slot: str
    semantic_slot_rank: int
    commit_policy: str
    replay_policy: str
    provider_adapter_contract: str
    sequence: float
    identity_policy: str = "content_addressed_when_unkeyed"
    contract_slot: str = ""
    contract_ref: str = ""
    repair_feedback_slot: str = ""
    authority: str = "runtime.context_management.context_segment_policy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextSegmentPolicyDefaults:
    section: str = ""
    physical_segment: str = ""
    physical_segment_rank: int = 0
    prefix_state: str = ""
    prefix_boundary: str = ""
    prefix_cache_scope: str = ""
    prefix_cache_role: str = ""
    prefix_tier: str = ""
    semantic_slot: str = ""
    semantic_slot_rank: int = 0
    commit_policy: str = ""
    replay_policy: str = ""
    provider_adapter_contract: str = ""
    identity_policy: str = ""
    contract_slot: str = ""
    contract_ref: str = ""
    repair_feedback_slot: str = ""


_POLICY_DEFAULTS_BY_KIND: dict[str, ContextSegmentPolicyDefaults] = {}
_POLICY_DEFAULTS_BY_STREAM: dict[str, ContextSegmentPolicyDefaults] = {}


def register_context_segment_policy_defaults(
    *,
    kind: str = "",
    stream: str = "",
    section: str = "",
    physical_segment: str = "",
    physical_segment_rank: int = 0,
    prefix_state: str = "",
    prefix_boundary: str = "",
    prefix_cache_scope: str = "",
    prefix_cache_role: str = "",
    prefix_tier: str = "",
    semantic_slot: str = "",
    semantic_slot_rank: int = 0,
    commit_policy: str = "",
    replay_policy: str = "",
    provider_adapter_contract: str = "",
    identity_policy: str = "",
    contract_slot: str = "",
    contract_ref: str = "",
    repair_feedback_slot: str = "",
) -> None:
    defaults = ContextSegmentPolicyDefaults(
        section=str(section or "").strip(),
        physical_segment=str(physical_segment or "").strip(),
        physical_segment_rank=_safe_int(physical_segment_rank),
        prefix_state=str(prefix_state or "").strip(),
        prefix_boundary=str(prefix_boundary or "").strip(),
        prefix_cache_scope=str(prefix_cache_scope or "").strip(),
        prefix_cache_role=str(prefix_cache_role or "").strip(),
        prefix_tier=str(prefix_tier or "").strip(),
        semantic_slot=str(semantic_slot or "").strip(),
        semantic_slot_rank=_safe_int(semantic_slot_rank),
        commit_policy=str(commit_policy or "").strip(),
        replay_policy=str(replay_policy or "").strip(),
        provider_adapter_contract=str(provider_adapter_contract or "").strip(),
        identity_policy=str(identity_policy or "").strip(),
        contract_slot=str(contract_slot or "").strip(),
        contract_ref=str(contract_ref or "").strip(),
        repair_feedback_slot=str(repair_feedback_slot or "").strip(),
    )
    normalized_kind = str(kind or "").strip()
    normalized_stream = str(stream or "").strip()
    if normalized_kind:
        _POLICY_DEFAULTS_BY_KIND[normalized_kind] = _merge_defaults(
            _POLICY_DEFAULTS_BY_KIND.get(normalized_kind, ContextSegmentPolicyDefaults()),
            defaults,
        )
    if normalized_stream:
        _POLICY_DEFAULTS_BY_STREAM[normalized_stream] = _merge_defaults(
            _POLICY_DEFAULTS_BY_STREAM.get(normalized_stream, ContextSegmentPolicyDefaults()),
            defaults,
        )


def _install_builtin_policy_defaults() -> None:
    for kind, slot in KIND_CONTEXT_APPEND_SLOT_DEFAULTS.items():
        register_context_segment_policy_defaults(kind=kind, semantic_slot=slot)
    for stream, slot in STREAM_CONTEXT_APPEND_SLOT_DEFAULTS.items():
        register_context_segment_policy_defaults(stream=stream, semantic_slot=slot)
    for kind, slot in {
        "lifecycle_runtime_guidance": "lifecycle_guidance",
        "runtime_control_signal_tail": "runtime_control_contract",
        "single_agent_turn_followup_action_contract": "action_contract",
        "partial_stream_recovery_instruction": "visible_prefix_recovery_contract",
        "partial_stream_recovery_visible_prefix": "visible_prefix_recovery_context",
        "provider_visible_ledger_recovery_checkpoint": "provider_visible_ledger_recovery",
    }.items():
        register_context_segment_policy_defaults(kind=kind, contract_slot=slot)
    for kind in {
        "partial_stream_recovery_instruction",
        "provider_visible_ledger_recovery_checkpoint",
        "runtime_control_signal_tail",
    }:
        register_context_segment_policy_defaults(kind=kind, repair_feedback_slot="system_repair_feedback")


def context_segment_policy_for_spec(
    spec: dict[str, Any] | None,
    *,
    default_section: str = CONTEXT_APPEND,
) -> ContextSegmentPolicy:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    classification = classify_context_spec(payload)
    defaults = _policy_defaults(payload, metadata=metadata)
    section = _first_text(
        metadata.get("context_cache_section"),
        metadata.get("context_assembly_section"),
        payload.get("context_cache_section"),
        defaults.section,
        classification.context_cache_section,
        default_section,
    )
    section = _normalize_policy_section(section)
    if section not in {STATIC_PREFIX, CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND, DYNAMIC_TAIL}:
        section = default_section
    physical_segment = _first_text(
        metadata.get("context_physical_segment"),
        metadata.get("physical_context_segment"),
        payload.get("context_physical_segment"),
        defaults.physical_segment,
        context_physical_segment_for_section(section),
    )
    prefix_cache_scope = _first_text(
        metadata.get("context_prefix_cache_scope"),
        defaults.prefix_cache_scope,
        classification.cache_scope,
    )
    prefix_cache_role = _first_text(
        metadata.get("context_prefix_cache_role"),
        defaults.prefix_cache_role,
        classification.cache_role,
    )
    prefix_tier = _first_text(
        metadata.get("context_prefix_tier"),
        defaults.prefix_tier,
        classification.prefix_tier,
    )
    semantic_slot = _semantic_slot(payload, metadata=metadata)
    return ContextSegmentPolicy(
        section=section,
        physical_segment=physical_segment,
        physical_segment_rank=_physical_segment_rank(
            metadata,
            physical_segment=physical_segment,
            defaults=defaults,
        ),
        prefix_state=_first_text(
            metadata.get("context_prefix_state"),
            metadata.get("provider_prefix_state"),
            defaults.prefix_state,
            context_prefix_state_for_section(section),
        ),
        prefix_boundary=_first_text(
            metadata.get("context_prefix_boundary"),
            metadata.get("provider_prefix_boundary"),
            defaults.prefix_boundary,
            context_prefix_boundary_for_section(section),
        ),
        prefix_cache_scope=prefix_cache_scope,
        prefix_cache_role=prefix_cache_role,
        prefix_tier=prefix_tier,
        semantic_slot=semantic_slot,
        semantic_slot_rank=_semantic_slot_rank(metadata, semantic_slot=semantic_slot, defaults=defaults),
        commit_policy=_first_text(
            metadata.get("context_commit_policy"),
            metadata.get("memory_commit_policy"),
            defaults.commit_policy,
            classification.memory_commit_policy,
            "append_then_seal" if section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND} else "never_commit",
        ),
        replay_policy=_first_text(
            metadata.get("context_replay_policy"),
            defaults.replay_policy,
            "provider_visible_ledger_replay" if section == CONTEXT_MEMORY_PREFIX else "new_append_materialize_once",
        ),
        provider_adapter_contract=_first_text(
            metadata.get("provider_adapter_contract"),
            metadata.get("provider_visible_adapter_contract"),
            payload.get("provider_adapter_contract"),
            defaults.provider_adapter_contract,
            DEFAULT_PROVIDER_ADAPTER_CONTRACT,
        ),
        sequence=_sequence(payload, metadata=metadata),
        identity_policy=_first_text(
            metadata.get("context_identity_policy"),
            metadata.get("provider_visible_context_identity_policy"),
            defaults.identity_policy,
            "content_addressed_when_unkeyed",
        ),
        contract_slot=_first_text(
            metadata.get("context_contract_slot"),
            metadata.get("runtime_contract_slot"),
            defaults.contract_slot,
        ),
        contract_ref=_first_text(
            metadata.get("context_contract_ref"),
            metadata.get("runtime_contract_ref"),
            payload.get("contract_ref"),
            defaults.contract_ref,
        ),
        repair_feedback_slot=_first_text(
            metadata.get("context_repair_feedback_slot"),
            metadata.get("repair_feedback_slot"),
            defaults.repair_feedback_slot,
        ),
    )


def context_append_order_key(item: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
    original_order, spec = item
    policy = context_segment_policy_for_spec(spec, default_section=CONTEXT_APPEND)
    return (int(policy.semantic_slot_rank or 0), float(policy.sequence or 0.0), int(original_order or 0))


def context_segment_policy_metadata(policy: ContextSegmentPolicy) -> dict[str, Any]:
    return {
        "context_segment_policy": policy.to_dict(),
        "context_cache_section": policy.section,
        "context_assembly_section": policy.section,
        "context_physical_segment": policy.physical_segment,
        "context_physical_segment_rank": policy.physical_segment_rank,
        "context_prefix_state": policy.prefix_state,
        "context_prefix_boundary": policy.prefix_boundary,
        "context_prefix_cache_scope": policy.prefix_cache_scope,
        "context_prefix_cache_role": policy.prefix_cache_role,
        "context_prefix_tier": policy.prefix_tier,
        "context_semantic_slot": policy.semantic_slot,
        "context_semantic_slot_rank": policy.semantic_slot_rank,
        "context_commit_policy": policy.commit_policy,
        "context_replay_policy": policy.replay_policy,
        "provider_adapter_contract": policy.provider_adapter_contract,
        "context_identity_policy": policy.identity_policy,
        "context_contract_slot": policy.contract_slot,
        "context_contract_ref": policy.contract_ref,
        "context_repair_feedback_slot": policy.repair_feedback_slot,
    }


def _semantic_slot(payload: dict[str, Any], *, metadata: dict[str, Any]) -> str:
    explicit = _first_text(
        metadata.get("context_semantic_slot"),
        metadata.get("semantic_slot"),
        metadata.get("context_slot"),
        payload.get("context_semantic_slot"),
    )
    if explicit:
        return explicit
    defaults = _policy_defaults(payload, metadata=metadata)
    if defaults.semantic_slot:
        return defaults.semantic_slot
    stream = _first_text(metadata.get("append_only_context_stream"), metadata.get("context_stream"))
    if stream in STREAM_CONTEXT_APPEND_SLOT_DEFAULTS:
        return STREAM_CONTEXT_APPEND_SLOT_DEFAULTS[stream]
    kind = str(payload.get("kind") or metadata.get("kind") or "").strip()
    return KIND_CONTEXT_APPEND_SLOT_DEFAULTS.get(kind, "context_memory_append")


def _semantic_slot_rank(
    metadata: dict[str, Any],
    *,
    semantic_slot: str,
    defaults: ContextSegmentPolicyDefaults,
) -> int:
    explicit = _safe_int(
        metadata.get("context_semantic_slot_rank")
        or metadata.get("semantic_slot_rank")
        or metadata.get("context_slot_rank")
    )
    if explicit > 0:
        return explicit
    if defaults.semantic_slot_rank > 0:
        return defaults.semantic_slot_rank
    return DEFAULT_CONTEXT_APPEND_SLOT_RANKS.get(str(semantic_slot or ""), DEFAULT_CONTEXT_APPEND_SLOT_RANKS["context_memory_append"])


def _physical_segment_rank(
    metadata: dict[str, Any],
    *,
    physical_segment: str,
    defaults: ContextSegmentPolicyDefaults,
) -> int:
    explicit = _safe_int(
        metadata.get("context_physical_segment_rank")
        or metadata.get("physical_context_segment_rank")
        or metadata.get("context_prefix_rank")
    )
    if explicit > 0:
        return explicit
    if defaults.physical_segment_rank > 0:
        return defaults.physical_segment_rank
    return context_physical_segment_rank(str(physical_segment or ""))


def _policy_defaults(payload: dict[str, Any], *, metadata: dict[str, Any]) -> ContextSegmentPolicyDefaults:
    stream = _first_text(metadata.get("append_only_context_stream"), metadata.get("context_stream"))
    kind = str(payload.get("kind") or metadata.get("kind") or "").strip()
    stream_defaults = _POLICY_DEFAULTS_BY_STREAM.get(stream, ContextSegmentPolicyDefaults())
    kind_defaults = _POLICY_DEFAULTS_BY_KIND.get(kind, ContextSegmentPolicyDefaults())
    return _merge_defaults(stream_defaults, kind_defaults)


def _merge_defaults(
    base: ContextSegmentPolicyDefaults,
    override: ContextSegmentPolicyDefaults,
) -> ContextSegmentPolicyDefaults:
    payload = base
    for field_name in (
        "section",
        "physical_segment",
        "physical_segment_rank",
        "prefix_state",
        "prefix_boundary",
        "prefix_cache_scope",
        "prefix_cache_role",
        "prefix_tier",
        "semantic_slot",
        "semantic_slot_rank",
        "commit_policy",
        "replay_policy",
        "provider_adapter_contract",
        "identity_policy",
        "contract_slot",
        "contract_ref",
        "repair_feedback_slot",
    ):
        value = getattr(override, field_name)
        if value:
            payload = replace(payload, **{field_name: value})
    return payload


def _sequence(payload: dict[str, Any], *, metadata: dict[str, Any]) -> float:
    for value in (
        metadata.get("context_sequence"),
        metadata.get("append_only_created_at"),
        metadata.get("append_only_ledger_order"),
        metadata.get("append_only_event_offset"),
        payload.get("created_at"),
        dict(payload.get("model_message") or {}).get("created_at") if isinstance(payload.get("model_message"), dict) else None,
    ):
        parsed = _safe_float(value)
        if parsed > 0:
            return parsed
    return 0.0


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_policy_section(value: Any) -> str:
    section = str(value or "").strip()
    if section == "sealed_context_prefix":
        return CONTEXT_MEMORY_PREFIX
    return section


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


_install_builtin_policy_defaults()
