from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


DEFAULT_PROVIDER_ADAPTER_CONTRACT = "deepseek_v4_provider_visible_message_v1"

STATIC_PREFIX = "static_prefix"
CONTEXT_MEMORY_PREFIX = "context_memory_prefix"
CONTEXT_APPEND = "context_append"
DYNAMIC_TAIL = "dynamic_tail"

DEFAULT_CONTEXT_APPEND_SLOT_RANKS: dict[str, int] = {
    "recovery_or_recent_work_facts": 10,
    "provider_protocol_history": 15,
    "selected_memory_and_task_state_facts": 20,
    "task_goal_context": 21,
    "task_plan_context": 22,
    "task_todo_context": 23,
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
    "task_state_replay_entry": "selected_memory_and_task_state_facts",
    "read_evidence_context": "evidence_refs_and_file_state_facts",
    "evidence_index_cursor": "evidence_refs_and_file_state_facts",
    "attachment_context_index": "evidence_refs_and_file_state_facts",
    "editor_context_index": "evidence_refs_and_file_state_facts",
    "provider_protocol_history": "provider_protocol_history",
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

STATIC_PREFIX_KINDS = {
    "action_schema_static",
    "agent_function_shared_stable",
    "agent_stable",
    "artifact_scope_stable",
    "bound_task_context_stable",
    "environment_stable",
    "file_evidence_policy_stable",
    "global_static",
    "graph_task_shared_stable",
    "lifecycle_stable",
    "personality_stable",
    "project_instructions_stable",
    "task_run_contract_stable",
    "task_prompt_contract",
    "task_stable",
    "tool_index_stable",
    "tool_schema_catalog",
    "turn_stable",
}

MEMORY_CONTEXT_KINDS = {
    "attachment_context_index",
    "bound_task_runtime_context",
    "editor_context_index",
    "evidence_index_cursor",
    "incremental_context_frame",
    "provider_protocol_history",
    "read_evidence_context",
    "runtime_baseline_refs",
    "runtime_memory_context",
    "session_pinned_facts_context",
    "current_turn_user_context",
    "single_agent_turn_followup_action_contract",
    "single_agent_turn_followup_message",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
    "single_agent_turn_user_steer_context",
    "task_start_inherited_context",
    "task_state_replay_entry",
    "tool_observations",
    "user_steering_context_append",
}

APPEND_ONLY_CONTEXT_KINDS = {
    "incremental_context_frame",
    "provider_protocol_history",
    "read_evidence_context",
    "runtime_memory_context",
    "session_pinned_facts_context",
    "current_turn_user_context",
    "single_agent_turn_followup_action_contract",
    "single_agent_turn_followup_message",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
    "single_agent_turn_user_steer_context",
    "task_state_replay_entry",
    "tool_observations",
    "user_steering_context_append",
}

CURRENT_CONTROL_TAIL_KINDS = {
    "accumulated_context_boundary",
    "active_skills",
    "current_editor_evidence_delta",
    "dynamic_projection",
    "graph_node_completion_prefix",
    "graph_node_runtime_context",
    "incremental_context_cursor",
    "lifecycle_runtime_guidance",
    "partial_stream_recovery_instruction",
    "partial_stream_recovery_visible_prefix",
    "read_evidence_injection",
    "runtime_control_signal_tail",
    "semantic_compaction_request",
    "session_history_tail_context",
    "task_goal_context",
    "task_plan_context",
    "task_runtime_boundary_dynamic",
    "task_todo_context",
    "user_steering_consumption_tail",
    "volatile_runtime_state",
    "volatile_task_state",
}

MEMORY_DYNAMIC_TIERS = {
    "append_only_runtime_evidence",
    "attachment_context_index",
    "editor_context_index",
    "evidence_index_cursor",
    "history_replay",
    "runtime_memory_context",
}

CONTROL_DYNAMIC_TIERS = {
    "active_skills",
    "assistant_completion_prefix",
    "current_exact_evidence",
    "current_runtime_cursor",
    "dynamic_context_tail",
    "runtime_cursor",
    "runtime_cursor_prefix",
    "runtime_delta_tail",
    "user_editor_volatile",
}


@dataclass(frozen=True, slots=True)
class ContextSegmentPolicy:
    section: str
    prefix_cache_scope: str
    prefix_cache_role: str
    prefix_tier: str
    semantic_slot: str
    semantic_slot_rank: int
    commit_policy: str
    replay_policy: str
    provider_adapter_contract: str
    sequence: float
    semantic_commit_class: str = ""
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
    for kind, rank in {
        "task_goal_context": 21,
        "task_plan_context": 22,
        "task_todo_context": 23,
    }.items():
        register_context_segment_policy_defaults(
            kind=kind,
            section=DYNAMIC_TAIL,
            prefix_cache_scope="none",
            prefix_cache_role="volatile",
            prefix_tier="volatile",
            semantic_slot=kind,
            semantic_slot_rank=rank,
            commit_policy="never_commit",
            replay_policy="current_dynamic_tail_only",
            identity_policy="task_run_contract_ref_plus_content_hash",
        )
    for kind in {"session_history", "session_history_context"}:
        register_context_segment_policy_defaults(
            kind=kind,
            section=CONTEXT_APPEND,
            prefix_cache_scope="none",
            prefix_cache_role="never_cache",
            prefix_tier="none",
            semantic_slot="semantic_history_tail",
            semantic_slot_rank=18,
            commit_policy="never_commit",
            replay_policy="current_turn_semantic_history_tail_only",
            identity_policy="content_addressed_when_unkeyed",
        )
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
    defaults = _policy_defaults(payload, metadata=metadata)
    kind = str(payload.get("kind") or metadata.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
    section = _first_text(
        _section_from_authoritative_context_metadata(payload, metadata=metadata),
        defaults.section,
        _section_for_payload(payload, metadata=metadata, defaults=defaults),
        metadata.get("context_policy_section"),
        default_section,
    )
    section = _normalize_policy_section(section)
    if section not in {STATIC_PREFIX, CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND, DYNAMIC_TAIL}:
        section = default_section
    prefix_cache_scope = _first_text(
        metadata.get("context_prefix_cache_scope"),
        defaults.prefix_cache_scope,
        payload.get("cache_scope"),
    )
    prefix_cache_role = _first_text(
        metadata.get("context_prefix_cache_role"),
        defaults.prefix_cache_role,
        payload.get("cache_role"),
    )
    prefix_tier = _first_text(
        metadata.get("context_prefix_tier"),
        defaults.prefix_tier,
        payload.get("prefix_tier"),
    )
    resolved_scope, resolved_role, resolved_tier = _cache_policy_for_section(
        payload,
        kind=kind,
        section=section,
        cache_scope=prefix_cache_scope,
        cache_role=prefix_cache_role,
        prefix_tier=prefix_tier,
    )
    semantic_slot = _semantic_slot(payload, metadata=metadata)
    return ContextSegmentPolicy(
        section=section,
        prefix_cache_scope=resolved_scope,
        prefix_cache_role=resolved_role,
        prefix_tier=resolved_tier,
        semantic_slot=semantic_slot,
        semantic_slot_rank=_semantic_slot_rank(metadata, semantic_slot=semantic_slot, defaults=defaults),
        commit_policy=_first_text(
            metadata.get("context_commit_policy"),
            metadata.get("memory_commit_policy"),
            defaults.commit_policy,
            _memory_commit_policy(kind=kind, section=section),
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
        semantic_commit_class=_first_text(
            metadata.get("semantic_commit_class"),
            metadata.get("context_semantic_commit_class"),
            _semantic_commit_class(kind=kind, section=section),
        ),
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
    provider_visible_boundary = _provider_visible_boundary_for_policy(policy)
    return {
        "context_segment_policy": policy.to_dict(),
        "context_cache_section": policy.section,
        "context_prefix_cache_scope": policy.prefix_cache_scope,
        "context_prefix_cache_role": policy.prefix_cache_role,
        "context_prefix_tier": policy.prefix_tier,
        "context_provider_visible_boundary": provider_visible_boundary,
        "context_provider_visible_state": _provider_visible_state_for_policy(policy),
        "context_semantic_slot": policy.semantic_slot,
        "context_semantic_slot_rank": policy.semantic_slot_rank,
        "context_commit_policy": policy.commit_policy,
        "context_replay_policy": policy.replay_policy,
        "semantic_commit_class": policy.semantic_commit_class,
        "memory_commit_policy": policy.commit_policy,
        "provider_adapter_contract": policy.provider_adapter_contract,
        "context_identity_policy": policy.identity_policy,
        "context_contract_slot": policy.contract_slot,
        "context_contract_ref": policy.contract_ref,
        "context_repair_feedback_slot": policy.repair_feedback_slot,
    }


def context_segment_routes_to_dynamic_tail(spec: dict[str, Any] | None) -> bool:
    return context_segment_policy_for_spec(spec).section == DYNAMIC_TAIL


def context_segment_routes_to_context_append(spec: dict[str, Any] | None) -> bool:
    return context_segment_policy_for_spec(spec).section == CONTEXT_APPEND


def context_segment_is_provider_visible_sealable_spec(spec: dict[str, Any] | None) -> bool:
    return context_segment_policy_is_provider_visible_sealable(context_segment_policy_for_spec(spec))


def context_segment_policy_is_provider_visible_sealable(policy: ContextSegmentPolicy) -> bool:
    if str(policy.commit_policy or "").strip() == "never_commit":
        return False
    if str(policy.section or "").strip() not in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return False
    cache_role = str(policy.prefix_cache_role or "").strip()
    prefix_tier = str(policy.prefix_tier or "").strip()
    if cache_role not in {"cacheable_prefix", "session_stable"}:
        return False
    return prefix_tier not in {"volatile", "none"}


def _provider_visible_boundary_for_policy(policy: ContextSegmentPolicy) -> str:
    section = str(policy.section or "").strip()
    if section == STATIC_PREFIX:
        return "static_provider_context"
    if section == CONTEXT_MEMORY_PREFIX:
        return "sealed_provider_visible_context"
    if section == CONTEXT_APPEND:
        return "current_append_context"
    if section == DYNAMIC_TAIL:
        return "current_dynamic_tail"
    return "provider_visible_boundary_unknown"


def _provider_visible_state_for_policy(policy: ContextSegmentPolicy) -> str:
    section = str(policy.section or "").strip()
    if section == STATIC_PREFIX:
        return "static_context"
    if section == CONTEXT_MEMORY_PREFIX:
        return "replayed_context_memory"
    if section == CONTEXT_APPEND:
        return "current_context_append"
    if section == DYNAMIC_TAIL:
        return "current_control_tail"
    return "provider_visible_state_unknown"


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


def _policy_defaults(payload: dict[str, Any], *, metadata: dict[str, Any]) -> ContextSegmentPolicyDefaults:
    stream = _first_text(metadata.get("append_only_context_stream"), metadata.get("context_stream"))
    kind = str(payload.get("kind") or metadata.get("kind") or "").strip()
    stream_defaults = _POLICY_DEFAULTS_BY_STREAM.get(stream, ContextSegmentPolicyDefaults())
    kind_defaults = _POLICY_DEFAULTS_BY_KIND.get(kind, ContextSegmentPolicyDefaults())
    return _merge_defaults(stream_defaults, kind_defaults)


def _section_from_authoritative_context_metadata(payload: dict[str, Any], *, metadata: dict[str, Any]) -> str:
    if metadata.get("provider_visible_context_ledger_entry_index"):
        return CONTEXT_MEMORY_PREFIX
    if str(metadata.get("provider_visible_context_ledger_commit_stage") or "").strip() == "provider_success_required":
        return CONTEXT_APPEND
    history_status = str(metadata.get("provider_visible_history_status") or "").strip()
    if history_status == "sealed_from_prior_model_request":
        return CONTEXT_MEMORY_PREFIX
    if history_status == "current_tool_round_pending_provider_success":
        return CONTEXT_APPEND
    if metadata.get("provider_visible_replay_only") is True:
        return CONTEXT_APPEND if str(metadata.get("provider_visible_context_ledger_commit_stage") or "").strip() else CONTEXT_MEMORY_PREFIX
    fixed_package = str(metadata.get("fixed_context_package") or payload.get("fixed_context_package") or "").strip()
    if fixed_package == "context_memory_prefix":
        return CONTEXT_MEMORY_PREFIX
    if fixed_package in {"context_memory_append", "context_append"}:
        return CONTEXT_APPEND
    return ""


def _section_for_payload(
    payload: dict[str, Any],
    *,
    metadata: dict[str, Any],
    defaults: ContextSegmentPolicyDefaults,
) -> str:
    if defaults.section:
        return defaults.section
    kind = str(payload.get("kind") or metadata.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
    if kind in STATIC_PREFIX_KINDS:
        return STATIC_PREFIX
    if kind in CURRENT_CONTROL_TAIL_KINDS:
        return DYNAMIC_TAIL
    if kind in MEMORY_CONTEXT_KINDS:
        return CONTEXT_APPEND
    dynamic_tier = str(metadata.get("prompt_assembly_dynamic_tier") or metadata.get("dynamic_tier") or "").strip()
    if dynamic_tier in MEMORY_DYNAMIC_TIERS:
        return CONTEXT_APPEND
    if dynamic_tier in CONTROL_DYNAMIC_TIERS:
        return DYNAMIC_TAIL
    if _is_cache_stable(payload):
        return STATIC_PREFIX
    return DYNAMIC_TAIL


def _cache_policy_for_section(
    payload: dict[str, Any],
    *,
    kind: str,
    section: str,
    cache_scope: str,
    cache_role: str,
    prefix_tier: str,
) -> tuple[str, str, str]:
    if section == STATIC_PREFIX:
        role = _cache_role(cache_role)
        if role not in {"cacheable_prefix", "session_stable"}:
            role = "session_stable"
        scope = str(cache_scope or "").strip()
        if not scope or scope == "none":
            scope = "global" if role == "cacheable_prefix" else "session"
        return scope, role, _prefix_tier(prefix_tier, cache_scope=scope, cache_role=role)
    if section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        role = _cache_role(cache_role)
        if role == "never_cache":
            return "none", "never_cache", "none"
        if kind in {
            "evidence_index_cursor",
            "attachment_context_index",
            "editor_context_index",
            "runtime_memory_context",
            "read_evidence_context",
        }:
            return "task", "volatile", "volatile"
        if role not in {"cacheable_prefix", "session_stable"}:
            role = "session_stable"
        scope = str(cache_scope or "").strip() or "task"
        return scope, role, _prefix_tier(prefix_tier, cache_scope=scope, cache_role=role)
    return "none", "volatile", "volatile"


def _semantic_commit_class(*, kind: str, section: str) -> str:
    if section == STATIC_PREFIX:
        return "static_protocol"
    if section == CONTEXT_MEMORY_PREFIX:
        return "provider_visible_context_memory"
    if section == CONTEXT_APPEND:
        if kind in {"current_turn_user_context", "single_agent_turn_user_steer_context", "user_steering_context_append"}:
            return "current_user_context"
        if kind == "runtime_memory_context":
            return "selected_memory_context"
        if kind == "provider_protocol_history":
            return "provider_protocol_transcript"
        if kind in {"single_agent_turn_tool_call", "single_agent_turn_tool_observation", "tool_observations"}:
            return "tool_transcript"
        return "context_memory_append"
    return "current_runtime_control"


def _memory_commit_policy(*, kind: str, section: str) -> str:
    if section == DYNAMIC_TAIL:
        return "never_commit"
    if section == STATIC_PREFIX:
        return "static_not_memory"
    if kind in APPEND_ONLY_CONTEXT_KINDS or section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return "append_then_seal"
    return "preserve_if_stable"


def _is_cache_stable(payload: dict[str, Any]) -> bool:
    cache_role = _cache_role(payload.get("cache_role"))
    if cache_role not in {"cacheable_prefix", "session_stable"}:
        return False
    prefix_tier = _prefix_tier(
        payload.get("prefix_tier"),
        cache_scope=str(payload.get("cache_scope") or "none"),
        cache_role=cache_role,
    )
    return prefix_tier not in {"volatile", "none"}


def _cache_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"cacheable_prefix", "session_stable", "volatile", "never_cache"}:
        return normalized
    return "volatile"


def _prefix_tier(value: Any, *, cache_scope: str, cache_role: str) -> str:
    explicit = str(value or "").strip()
    if explicit in {"provider_global", "session", "task", "volatile", "none"}:
        return explicit
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        scope = str(cache_scope or "").strip()
        if scope == "global":
            return "provider_global"
        if scope == "task":
            return "task"
        return "session"
    if cache_role == "never_cache":
        return "none"
    return "volatile"


def _merge_defaults(
    base: ContextSegmentPolicyDefaults,
    override: ContextSegmentPolicyDefaults,
) -> ContextSegmentPolicyDefaults:
    payload = base
    for field_name in (
        "section",
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
    return str(value or "").strip()


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
