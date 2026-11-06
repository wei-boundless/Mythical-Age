from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from .declarations import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    context_segment_declared_kinds,
    context_segment_kind_declarations,
    context_segment_semantic_slot_defaults,
)
from .metadata import (
    physical_prefix_frame_replay_metadata,
    provider_protocol_append_candidate_metadata,
    provider_protocol_replay_metadata,
)

DEFAULT_PROVIDER_ADAPTER_CONTRACT = "deepseek_v4_1_provider_visible_message"

DEFAULT_CONTEXT_APPEND_SLOT_RANKS: dict[str, int] = {
    "recovery_or_recent_work_facts": 10,
    "previous_incomplete_output_memory": 12,
    "provider_protocol_history": 15,
    "selected_memory_and_task_state_facts": 20,
    "task_goal_context": 21,
    "task_plan_context": 22,
    "task_todo_context": 23,
    "task_state_cursor": 24,
    "graph_node_runtime_context": 25,
    "active_execution_lease": 24,
    "current_user_intent": 30,
    "active_user_steer_content": 35,
    "active_user_steer_consumption_state": 36,
    "evidence_acquisition_horizon": 36,
    "evidence_refs_and_file_state_facts": 40,
    "current_exact_evidence": 41,
    "current_editor_evidence_delta": 41,
    "evidence_semantic_summary": 42,
    "read_coverage_projection": 43,
    "execution_action_evidence": 44,
    "tool_transcript": 70,
    "context_memory_append": 90,
    "action_contract": 95,
}

KIND_CONTEXT_APPEND_SLOT_DEFAULTS: dict[str, str] = context_segment_semantic_slot_defaults()

STREAM_CONTEXT_APPEND_SLOT_DEFAULTS: dict[str, str] = {
    "current_user_context": "current_user_intent",
    "user_steer": "active_user_steer_content",
    "runtime_memory_context": "selected_memory_and_task_state_facts",
    "read_evidence": "evidence_refs_and_file_state_facts",
    "provider_protocol": "provider_protocol_history",
    "tool_transcript": "tool_transcript",
}

STATIC_PREFIX_KINDS = set(context_segment_declared_kinds(section=STATIC_PREFIX))
MEMORY_CONTEXT_KINDS = set(context_segment_declared_kinds(section=CONTEXT_APPEND)) | set(
    context_segment_declared_kinds(section=CONTEXT_MEMORY_PREFIX)
)
APPEND_ONLY_CONTEXT_KINDS = set(context_segment_declared_kinds(append_only=True))
CURRENT_CONTROL_TAIL_KINDS = set(context_segment_declared_kinds(section=DYNAMIC_TAIL))
DECLARED_CONTEXT_SEGMENT_KINDS = set(context_segment_declared_kinds())
CURRENT_PRESENT_ONLY_CONTEXT_KINDS = {
    "current_turn_user_context",
    "single_agent_turn_user_steer_context",
}
CURRENT_ONLY_REPLAY_POLICIES = {
    "current_dynamic_tail_only",
    "current_turn_present_only",
    "current_turn_semantic_history_tail_only",
}
CURRENT_ONLY_IDENTITY_POLICIES = {
    "current_invocation_only",
    "turn_scope_runtime_tail",
    "current_turn_only",
}

@dataclass(frozen=True, slots=True)
class ContextSegmentPolicy:
    kind: str
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
    identity_policy: str = "origin_ref_stable"
    contract_slot: str = ""
    contract_ref: str = ""
    repair_feedback_slot: str = ""
    authority: str = "context_system.segments.policy"

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
    for declaration in context_segment_kind_declarations():
        defaults = declaration.policy_defaults()
        if not any(defaults.values()):
            continue
        register_context_segment_policy_defaults(kind=declaration.kind, **defaults)
    register_context_segment_policy_defaults(
        kind="runtime_memory_context",
        section=CONTEXT_APPEND,
        prefix_cache_scope="none",
        prefix_cache_role="volatile",
        prefix_tier="volatile",
        commit_policy="append_then_seal",
        replay_policy="current_append_commit_on_provider_success_then_next_physical_prefix_frame",
        identity_policy="origin_ref_stable",
    )
    for stream, slot in STREAM_CONTEXT_APPEND_SLOT_DEFAULTS.items():
        register_context_segment_policy_defaults(stream=stream, semantic_slot=slot)
    for kind, slot, rank in (
        ("bound_task_runtime_context", "bound_task_runtime_context", 40),
        ("task_goal_context", "task_goal_context", 21),
        ("task_plan_context", "task_plan_context", 22),
        ("task_todo_context", "task_todo_context", 23),
        ("volatile_task_state", "task_state_cursor", 24),
        ("graph_node_runtime_context", "graph_node_runtime_context", 25),
        ("user_steering_consumption_tail", "active_user_steer_consumption_state", 36),
        ("recovery_context_package", "recovery_or_recent_work_facts", 10),
        ("previous_incomplete_output_memory", "previous_incomplete_output_memory", 12),
        ("session_history_tail_context", "recovery_or_recent_work_facts", 10),
        ("recent_work_outcome", "recovery_or_recent_work_facts", 10),
        ("evidence_delta_summary", "evidence_semantic_summary", 42),
        ("evidence_semantic_summary", "evidence_semantic_summary", 42),
        ("read_evidence_injection", "current_exact_evidence", 41),
        ("current_editor_evidence_delta", "current_editor_evidence_delta", 41),
        ("read_coverage_projection", "read_coverage_projection", 43),
        ("execution_action_evidence", "execution_action_evidence", 44),
    ):
        register_context_segment_policy_defaults(
            kind=kind,
            section=CONTEXT_APPEND,
            prefix_cache_scope="none",
            prefix_cache_role="volatile",
            prefix_tier="volatile",
            semantic_slot=slot,
            semantic_slot_rank=rank,
            commit_policy="append_then_seal",
            replay_policy="current_append_commit_on_provider_success_then_next_physical_prefix_frame",
            identity_policy="origin_ref_stable",
        )
    for kind, rank in {
        "evidence_acquisition_horizon": 36,
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
            identity_policy="task_run_contract_ref_stable",
        )
    register_context_segment_policy_defaults(
        kind="active_execution_lease",
        section=DYNAMIC_TAIL,
        prefix_cache_scope="none",
        prefix_cache_role="volatile",
        prefix_tier="volatile",
        semantic_slot="active_execution_lease",
        semantic_slot_rank=24,
        commit_policy="never_commit",
        replay_policy="current_dynamic_tail_only",
        identity_policy="current_invocation_only",
        contract_slot="active_execution_lease",
    )
    register_context_segment_policy_defaults(
        kind="runtime_control_signal_tail",
        section=DYNAMIC_TAIL,
        prefix_cache_scope="none",
        prefix_cache_role="volatile",
        prefix_tier="volatile",
        semantic_slot="runtime_control_contract",
        semantic_slot_rank=25,
        commit_policy="never_commit",
        replay_policy="current_dynamic_tail_only",
        identity_policy="current_invocation_only",
        contract_slot="runtime_control_contract",
        repair_feedback_slot="system_repair_feedback",
    )
    register_context_segment_policy_defaults(
        kind="session_history",
        section=CONTEXT_APPEND,
        prefix_cache_scope="none",
        prefix_cache_role="never_cache",
        prefix_tier="none",
        semantic_slot="semantic_history_tail",
        semantic_slot_rank=18,
        commit_policy="never_commit",
        replay_policy="current_turn_semantic_history_tail_only",
        identity_policy="origin_ref_stable",
    )
    for kind, slot in {
        "turn_state_guidance": "turn_state_guidance",
        "turn_operating_contract": "turn_operating_contract",
        "runtime_control_signal_tail": "runtime_control_contract",
        "single_agent_turn_followup_action_contract": "action_contract",
        "single_agent_turn_followup_message": "runtime_followup_contract",
        "partial_stream_recovery_instruction": "visible_prefix_recovery_contract",
        "partial_stream_recovery_visible_prefix": "visible_prefix_recovery_context",
        "provider_visible_ledger_recovery_checkpoint": "provider_visible_ledger_recovery",
    }.items():
        register_context_segment_policy_defaults(kind=kind, contract_slot=slot)
    for kind, slot in {
        "single_agent_turn_followup_action_contract": "action_contract",
        "single_agent_turn_followup_message": "runtime_followup_contract",
    }.items():
        register_context_segment_policy_defaults(
            kind=kind,
            section=DYNAMIC_TAIL,
            prefix_cache_scope="none",
            prefix_cache_role="volatile",
            prefix_tier="volatile",
            semantic_slot=slot,
            commit_policy="never_commit",
            replay_policy="current_dynamic_tail_only",
            identity_policy="current_invocation_only",
        )
    for kind in {
        "partial_stream_recovery_instruction",
        "provider_visible_ledger_recovery_checkpoint",
        "runtime_control_signal_tail",
    }:
        register_context_segment_policy_defaults(kind=kind, repair_feedback_slot="system_repair_feedback")
    for kind in context_segment_declared_kinds(section=DYNAMIC_TAIL):
        register_context_segment_policy_defaults(
            kind=kind,
            section=DYNAMIC_TAIL,
            prefix_cache_scope="none",
            prefix_cache_role="volatile",
            prefix_tier="volatile",
            commit_policy="never_commit",
            replay_policy="current_dynamic_tail_only",
            identity_policy="current_invocation_only",
        )


def context_segment_policy_for_spec(
    spec: dict[str, Any] | None,
    *,
    default_section: str = CONTEXT_APPEND,
) -> ContextSegmentPolicy:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    defaults = _policy_defaults(payload, metadata=metadata)
    kind = str(
        payload.get("kind")
        or metadata.get("context_segment_kind")
        or metadata.get("provider_visible_append_candidate_kind")
        or metadata.get("kind")
        or "unknown_unplanned"
    ).strip() or "unknown_unplanned"
    if kind not in DECLARED_CONTEXT_SEGMENT_KINDS:
        return _undeclared_context_segment_policy(kind, payload, metadata=metadata)
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
        defaults.prefix_cache_scope,
        metadata.get("context_prefix_cache_scope"),
        payload.get("cache_scope"),
    )
    prefix_cache_role = _first_text(
        defaults.prefix_cache_role,
        metadata.get("context_prefix_cache_role"),
        payload.get("cache_role"),
    )
    prefix_tier = _first_text(
        defaults.prefix_tier,
        metadata.get("context_prefix_tier"),
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
        kind=kind,
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
            _default_replay_policy(section),
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
            "origin_ref_stable",
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


def _undeclared_context_segment_policy(
    kind: str,
    payload: dict[str, Any],
    *,
    metadata: dict[str, Any],
) -> ContextSegmentPolicy:
    return ContextSegmentPolicy(
        kind=str(kind or "unknown_unplanned").strip() or "unknown_unplanned",
        section=DYNAMIC_TAIL,
        prefix_cache_scope="none",
        prefix_cache_role="never_cache",
        prefix_tier="none",
        semantic_slot="undeclared_context_segment",
        semantic_slot_rank=9999,
        commit_policy="never_commit",
        replay_policy="undeclared_context_segment_blocked",
        provider_adapter_contract=_first_text(
            metadata.get("provider_adapter_contract"),
            metadata.get("provider_visible_adapter_contract"),
            payload.get("provider_adapter_contract"),
            DEFAULT_PROVIDER_ADAPTER_CONTRACT,
        ),
        sequence=_sequence(payload, metadata=metadata),
        semantic_commit_class="undeclared_context_segment",
        identity_policy="current_invocation_only",
        contract_slot="undeclared_context_segment",
        contract_ref="runtime.context_management.system_asset_lines.required",
        repair_feedback_slot="structural_context_line_gap",
    )


def context_append_order_key(item: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
    original_order, spec = item
    policy = context_segment_policy_for_spec(spec, default_section=CONTEXT_APPEND)
    return (int(policy.semantic_slot_rank or 0), float(policy.sequence or 0.0), int(original_order or 0))


def context_segment_policy_metadata(policy: ContextSegmentPolicy) -> dict[str, Any]:
    provider_visible_boundary = _provider_visible_boundary_for_policy(policy)
    return {
        "context_segment_policy": policy.to_dict(),
        "context_segment_kind": policy.kind,
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
    if str(policy.section or "").strip() not in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return False
    kind = str(policy.kind or "").strip()
    if kind in CURRENT_PRESENT_ONLY_CONTEXT_KINDS or kind in CURRENT_CONTROL_TAIL_KINDS:
        return False
    commit_policy = str(policy.commit_policy or "").strip()
    if commit_policy == "never_commit":
        return False
    replay_policy = str(policy.replay_policy or "").strip()
    if replay_policy in CURRENT_ONLY_REPLAY_POLICIES:
        return False
    identity_policy = str(policy.identity_policy or "").strip()
    if identity_policy in CURRENT_ONLY_IDENTITY_POLICIES:
        return False
    semantic_commit_class = str(policy.semantic_commit_class or "").strip()
    if semantic_commit_class == "current_runtime_control":
        return False
    if str(policy.section or "").strip() == CONTEXT_MEMORY_PREFIX:
        return True
    return commit_policy == "append_then_seal"


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
    explicit_section = str(
        metadata.get("context_cache_section")
        or metadata.get("context_policy_section")
        or ""
    ).strip()
    if explicit_section in {STATIC_PREFIX, CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND, DYNAMIC_TAIL}:
        return explicit_section
    if str(metadata.get("context_commit_policy") or metadata.get("memory_commit_policy") or "").strip() == "never_commit":
        return DYNAMIC_TAIL
    replay_policy = str(metadata.get("context_replay_policy") or "").strip()
    if replay_policy == "current_dynamic_tail_only":
        return DYNAMIC_TAIL
    if physical_prefix_frame_replay_metadata(metadata) or provider_protocol_replay_metadata(metadata):
        return CONTEXT_MEMORY_PREFIX
    if provider_protocol_append_candidate_metadata(metadata):
        return CONTEXT_APPEND
    if str(metadata.get("provider_visible_append_commit_stage") or "").strip() == "provider_success_required":
        return CONTEXT_APPEND
    history_status = str(metadata.get("provider_visible_history_status") or "").strip()
    if history_status == "current_tool_round_pending_provider_success":
        return CONTEXT_APPEND
    fixed_package = str(metadata.get("fixed_context_package") or payload.get("fixed_context_package") or "").strip()
    if fixed_package == "context_memory_prefix":
        return CONTEXT_MEMORY_PREFIX
    if fixed_package in {"context_memory_append", "context_append"}:
        return CONTEXT_APPEND
    if metadata.get("provider_visible_replay_only") is True:
        return CONTEXT_MEMORY_PREFIX
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
    return ""


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
        scope = _cache_scope(cache_scope, default="global" if role == "cacheable_prefix" else "session")
        if scope == "none":
            scope = "global" if role == "cacheable_prefix" else "session"
        return scope, role, _prefix_tier(prefix_tier, cache_scope=scope, cache_role=role)
    if section == CONTEXT_MEMORY_PREFIX:
        role = _cache_role(cache_role)
        if role == "never_cache":
            return "none", "never_cache", "none"
        if role not in {"cacheable_prefix", "session_stable"}:
            role = "session_stable"
        scope = _cache_scope(cache_scope, default="session")
        if scope == "none":
            scope = "session"
        return scope, role, _prefix_tier(prefix_tier, cache_scope=scope, cache_role=role)
    if section == CONTEXT_APPEND:
        role = _cache_role(cache_role)
        if role in {"volatile", "never_cache"}:
            scope = _cache_scope(cache_scope, default="none")
            if role == "never_cache":
                return "none", "never_cache", "none"
            if scope == "none":
                return "none", "volatile", _prefix_tier(prefix_tier, cache_scope="none", cache_role="volatile")
            return scope, "volatile", _prefix_tier(prefix_tier, cache_scope=scope, cache_role="volatile")
        scope = _cache_scope(cache_scope, default="session")
        if scope == "none":
            scope = "session"
        if role not in {"cacheable_prefix", "session_stable"}:
            role = "session_stable"
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
        if kind in {"single_agent_turn_tool_call", "tool_transcript_delta"}:
            return "tool_transcript"
        return "context_memory_append"
    return "current_runtime_control"


def _default_replay_policy(section: str) -> str:
    normalized = str(section or "").strip()
    if normalized == CONTEXT_MEMORY_PREFIX:
        return "physical_prefix_frame_replay"
    if normalized == DYNAMIC_TAIL:
        return "current_dynamic_tail_only"
    return "new_append_materialize_once"


def _memory_commit_policy(*, kind: str, section: str) -> str:
    if section == DYNAMIC_TAIL:
        return "never_commit"
    if section == STATIC_PREFIX:
        return "static_not_memory"
    if kind in APPEND_ONLY_CONTEXT_KINDS or section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return "append_then_seal"
    return "preserve_if_stable"


def _cache_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"cacheable_prefix", "session_stable", "volatile", "never_cache"}:
        return normalized
    return "volatile"


def _prefix_tier(value: Any, *, cache_scope: str, cache_role: str) -> str:
    explicit = str(value or "").strip()
    if explicit in {"provider_global", "session", "volatile", "none"}:
        return explicit
    if explicit:
        return "none" if cache_role == "never_cache" else "volatile"
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        scope = str(cache_scope or "").strip()
        if scope == "global":
            return "provider_global"
        return "session"
    if cache_role == "never_cache":
        return "none"
    return "volatile"


def _cache_scope(value: Any, *, default: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"global", "session", "none"}:
        return normalized
    if normalized:
        return "none"
    return str(default or "session")


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
