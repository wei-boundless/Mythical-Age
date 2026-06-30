from __future__ import annotations

from typing import Any

from runtime.context_management.context_prefix_identity import build_context_prefix_identity
from runtime.context_management.context_segment_policy import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    ContextSegmentPolicy,
    context_segment_policy_for_spec,
)
from runtime.context_management.context_segment_registry import (
    ACTION_CONTRACTS,
    ACTIVE_SKILL,
    CONTEXT_MEMORY,
    CURRENT_DYNAMIC_CONTROL,
    EVIDENCE_ALIGNMENT,
    EVIDENCE_CONTEXT,
    REASONING_PROJECTION,
    REPAIR_FEEDBACK,
    RUNTIME_CONTRACTS,
    STATIC_IDENTITY,
    TASK_RUN_CONTRACTS,
    TASK_STATE_CONTEXT,
    TOOL_CONTEXT,
    TURN_STATE_CONTROL,
    context_segment_kind_capability,
    context_segment_kind_declaration,
)
from runtime.context_management.physical_context_plan import physical_lane_for_spec


def classify_context_spec(spec: dict[str, Any], *, index: int) -> dict[str, Any]:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    kind = _kind(payload, metadata=metadata)
    source_ref = _source_ref(payload, metadata=metadata, index=index)
    policy = context_segment_policy_for_spec(payload)
    physical_lane = _physical_lane(payload, metadata=metadata, policy=policy)
    prefix_identity = _prefix_identity(payload, metadata=metadata, policy=policy, physical_lane=physical_lane)
    lifecycle_state = _first_text(prefix_identity.get("lifecycle_state"), metadata.get("context_prefix_lifecycle_state"))
    agent_domain = _agent_domain(payload, metadata=metadata, kind=kind, policy=policy, physical_lane=physical_lane)
    control_signal = _control_signal(metadata=metadata, kind=kind, policy=policy)
    feedback_route = _feedback_route(metadata=metadata, policy=policy, agent_domain=agent_domain)
    connection_contract_ref = _connection_contract_ref(
        metadata=metadata,
        kind=kind,
        policy=policy,
        physical_lane=physical_lane,
        control_signal=control_signal,
    )
    time_scope = _time_scope(metadata=metadata, lifecycle_state=lifecycle_state, physical_lane=physical_lane, policy=policy)
    visibility = _visibility(metadata=metadata, physical_lane=physical_lane)
    ttl = _ttl(policy=policy, time_scope=time_scope, visibility=visibility)
    cache_expectation = _first_text(prefix_identity.get("cache_read_expectation"), _cache_expectation(policy=policy, physical_lane=physical_lane))
    diagnostics = _diagnostics(
        payload,
        metadata=metadata,
        kind=kind,
        policy=policy,
        physical_lane=physical_lane,
        prefix_identity=prefix_identity,
        agent_domain=agent_domain,
        control_signal=control_signal,
        connection_contract_ref=connection_contract_ref,
    )
    return {
        "node_id": context_contract_node_id_for_spec(payload, index=index),
        "authority": _authority(payload, metadata=metadata, policy=policy),
        "source_ref": source_ref,
        "scope": _scope(policy=policy, visibility=visibility),
        "ttl": ttl,
        "visibility": visibility,
        "agent_use_contract": _agent_use_contract(metadata=metadata, physical_lane=physical_lane, agent_domain=agent_domain),
        "commit_policy": _first_text(metadata.get("context_commit_policy"), policy.commit_policy, _commit_policy(ttl=ttl, visibility=visibility)),
        "replay_policy": _first_text(metadata.get("context_replay_policy"), policy.replay_policy, _replay_policy(ttl=ttl, visibility=visibility)),
        "cache_tier": _cache_tier(policy=policy, visibility=visibility),
        "content_mode": _content_mode(payload),
        "agent_domain": agent_domain,
        "agent_role": _agent_role(metadata=metadata, agent_domain=agent_domain),
        "control_layer": _control_layer(policy=policy, physical_lane=physical_lane, visibility=visibility),
        "time_scope": time_scope,
        "control_signal": control_signal,
        "feedback_route": feedback_route,
        "physical_lane": physical_lane,
        "cache_expectation": cache_expectation,
        "connection_contract_ref": connection_contract_ref,
        "provider_payload_segment_ref": _provider_payload_segment_ref(metadata=metadata, prefix_identity=prefix_identity),
        "diagnostics": diagnostics,
    }


def context_contract_node_id_for_spec(spec: dict[str, Any], *, index: int) -> str:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    kind = _kind(payload, metadata=metadata)
    source_ref = _source_ref(payload, metadata=metadata, index=index)
    return _node_id(kind=kind, source_ref=source_ref, index=index)


def hidden_transport_node(packet_id: str, *, source_ref: str = "provider_transport_binding") -> dict[str, Any]:
    return {
        "node_id": f"{packet_id}:l8_provider_transport",
        "authority": "runtime.model_gateway.provider_payload",
        "source_ref": source_ref,
        "scope": "provider_request",
        "ttl": "current_provider_request",
        "visibility": "provider_transport",
        "agent_use_contract": "Provider transport data is hidden from the agent prompt and must not be committed to memory.",
        "commit_policy": "never_commit",
        "replay_policy": "never_replay",
        "cache_tier": "hidden",
        "content_mode": "ref_only",
        "agent_domain": "ProviderTransportDomain",
        "agent_role": "provider_transport_binding",
        "control_layer": "provider_transport",
        "time_scope": "current_provider_request",
        "control_signal": "bind_provider_payload",
        "feedback_route": "",
        "physical_lane": "provider_transport",
        "cache_expectation": "excluded",
        "connection_contract_ref": "provider_payload:transport_binding",
        "provider_payload_segment_ref": source_ref,
    }


def _kind(payload: dict[str, Any], *, metadata: dict[str, Any]) -> str:
    return _first_text(payload.get("kind"), payload.get("visible_kind"), metadata.get("kind"), payload.get("title"), "context_fragment")


def _source_ref(payload: dict[str, Any], *, metadata: dict[str, Any], index: int) -> str:
    return _first_text(
        payload.get("source_ref"),
        metadata.get("source_ref"),
        metadata.get("runtime_prompt_source_id"),
        payload.get("id"),
        f"context_spec:{index}",
    )


def _physical_lane(payload: dict[str, Any], *, metadata: dict[str, Any], policy: ContextSegmentPolicy) -> str:
    explicit = _first_text(metadata.get("physical_prefix_lane"), payload.get("physical_prefix_lane"))
    if explicit:
        return explicit
    return physical_lane_for_spec(payload, policy=policy)


def _prefix_identity(
    payload: dict[str, Any],
    *,
    metadata: dict[str, Any],
    policy: ContextSegmentPolicy,
    physical_lane: str,
) -> dict[str, Any]:
    existing = metadata.get("context_prefix_identity") or metadata.get("prefix_identity") or payload.get("prefix_identity")
    if isinstance(existing, dict) and existing:
        return dict(existing)
    identity = build_context_prefix_identity(
        kind=_kind(payload, metadata=metadata),
        metadata=metadata,
        source_ref=_source_ref(payload, metadata=metadata, index=0),
        physical_lane=physical_lane,
        semantic_source=_first_text(metadata.get("context_semantic_source"), metadata.get("semantic_source")),
        semantic_slot=policy.semantic_slot,
        content_version_hash=_first_text(metadata.get("content_version_hash"), metadata.get("content_hash")),
        provider_serialized_hash=_first_text(metadata.get("provider_serialized_hash"), metadata.get("provider_visible_hash")),
        request_ordinal=metadata.get("context_physical_assembly_index") or 0,
        transport_location=metadata.get("transport_location") or "",
        frame_ref=metadata.get("physical_prefix_frame_id") or "",
        frame_ordinal=metadata.get("physical_prefix_frame_segment_ordinal") or 0,
    )
    return identity.to_dict()


def _agent_domain(
    payload: dict[str, Any],
    *,
    metadata: dict[str, Any],
    kind: str,
    policy: ContextSegmentPolicy,
    physical_lane: str,
) -> str:
    explicit = _first_text(metadata.get("agent_domain"), metadata.get("context_agent_domain"), payload.get("agent_domain"))
    if explicit:
        return explicit
    capability = context_segment_kind_capability(kind)
    if capability:
        group, _slot, _member = capability
        mapped = _AGENT_DOMAIN_BY_CAPABILITY_GROUP.get(group)
        if mapped:
            return mapped
    if physical_lane == "provider_transport":
        return "ProviderTransportDomain"
    section = str(policy.section or "")
    if section == STATIC_PREFIX:
        return "StablePromptDomain"
    if section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return "ContextMemoryDomain"
    if section == DYNAMIC_TAIL:
        return "RuntimeControlDomain"
    return "ContextFragmentDomain"


def _control_signal(*, metadata: dict[str, Any], kind: str, policy: ContextSegmentPolicy) -> str:
    explicit = _first_text(
        metadata.get("control_signal"),
        metadata.get("primary_control_signal"),
        metadata.get("context_control_signal"),
    )
    if explicit:
        return explicit
    capability = context_segment_kind_capability(kind)
    if capability:
        _group, slot, member = capability
        if slot and member:
            return f"{member}:{slot}"
        if slot:
            return slot
    if policy.contract_slot:
        return policy.contract_slot
    declaration = context_segment_kind_declaration(kind)
    if declaration and declaration.semantic_slot:
        return declaration.semantic_slot
    if declaration and declaration.kind:
        return declaration.kind
    if _metadata_declares_slot(metadata):
        return policy.semantic_slot
    return ""


def _feedback_route(*, metadata: dict[str, Any], policy: ContextSegmentPolicy, agent_domain: str) -> str:
    explicit = _first_text(metadata.get("feedback_route"), metadata.get("context_feedback_route"), policy.repair_feedback_slot)
    if explicit:
        return explicit
    if agent_domain == "RecoveryFeedbackDomain":
        return "system_repair_feedback"
    return ""


def _connection_contract_ref(
    *,
    metadata: dict[str, Any],
    kind: str,
    policy: ContextSegmentPolicy,
    physical_lane: str,
    control_signal: str,
) -> str:
    explicit = _first_text(
        metadata.get("connection_contract_ref"),
        metadata.get("context_connection_contract_ref"),
        metadata.get("context_contract_ref"),
        metadata.get("runtime_contract_ref"),
        policy.contract_ref,
    )
    if explicit:
        return explicit
    declaration = context_segment_kind_declaration(kind)
    declared_slot = str(declaration.semantic_slot if declaration else "").strip()
    declared_kind_slot = str(declaration.kind if declaration else "").strip()
    capability = context_segment_kind_capability(kind)
    capability_slot = str(capability[1] if capability else "").strip()
    slot = _first_text(
        policy.contract_slot,
        declared_slot,
        capability_slot,
        declared_kind_slot,
        policy.semantic_slot if _metadata_declares_slot(metadata) else "",
    )
    if physical_lane and slot and control_signal:
        return f"context_slot:{physical_lane}:{slot}:{control_signal}"
    return ""


def _time_scope(
    *,
    metadata: dict[str, Any],
    lifecycle_state: str,
    physical_lane: str,
    policy: ContextSegmentPolicy,
) -> str:
    explicit = _first_text(metadata.get("time_scope"), metadata.get("context_time_scope"), lifecycle_state)
    if explicit:
        return explicit
    if physical_lane == "global_static_prefix":
        return "static_prefix"
    if physical_lane == "provider_visible_context_prefix":
        return "confirmed_context_prefix"
    if physical_lane == "current_turn_tail":
        return "current_turn"
    if physical_lane == "never_replay_tail":
        return "current_turn_never_replay"
    if str(policy.section or "") == CONTEXT_APPEND:
        return "current_append_pending_provider_success"
    return "current_turn"


def _visibility(*, metadata: dict[str, Any], physical_lane: str) -> str:
    explicit = _first_text(metadata.get("visibility"), metadata.get("transport_visibility"), metadata.get("context_visibility"))
    if explicit in {"provider_transport", "runtime_hidden", "agent_visible"}:
        return explicit
    if physical_lane == "provider_transport":
        return "provider_transport"
    return "agent_visible"


def _ttl(*, policy: ContextSegmentPolicy, time_scope: str, visibility: str) -> str:
    if visibility == "provider_transport":
        return "current_provider_request"
    if time_scope == "static_prefix":
        return "stable"
    if time_scope in {"confirmed_frame_replay", "confirmed_context_prefix"}:
        return "append_only"
    if str(policy.section or "") == CONTEXT_MEMORY_PREFIX:
        return "append_only"
    return "current_turn"


def _cache_expectation(*, policy: ContextSegmentPolicy, physical_lane: str) -> str:
    if physical_lane in {"global_static_prefix", "provider_tool_schema_prefix"}:
        return "expected_read"
    if physical_lane == "provider_visible_context_prefix":
        return "expected_read"
    if str(policy.section or "") == CONTEXT_APPEND:
        return "write_candidate"
    if physical_lane == "provider_transport":
        return "excluded"
    return "excluded"


def _authority(payload: dict[str, Any], *, metadata: dict[str, Any], policy: ContextSegmentPolicy) -> str:
    return _first_text(
        metadata.get("authority"),
        metadata.get("context_origin_authority"),
        metadata.get("prefix_origin_authority"),
        metadata.get("origin_authority"),
        metadata.get("physical_context_plan_authority"),
        payload.get("authority"),
        policy.authority,
        "runtime.context_management.context_segment_policy",
    )


def _scope(*, policy: ContextSegmentPolicy, visibility: str) -> str:
    if visibility == "provider_transport":
        return "provider_request"
    scope = str(policy.prefix_cache_scope or "").strip()
    if scope in {"global", "session", "none"}:
        return "turn" if scope == "none" else scope
    return "turn"


def _commit_policy(*, ttl: str, visibility: str) -> str:
    if visibility == "provider_transport" or ttl == "current_provider_request":
        return "never_commit"
    if ttl == "append_only":
        return "seal_on_provider_success"
    if ttl == "stable":
        return "append_once"
    return "never_commit"


def _replay_policy(*, ttl: str, visibility: str) -> str:
    if visibility == "provider_transport":
        return "never_replay"
    if ttl in {"stable", "append_only"}:
        return "physical_prefix_frame_replay"
    return "current_only"


def _cache_tier(*, policy: ContextSegmentPolicy, visibility: str) -> str:
    if visibility == "provider_transport":
        return "hidden"
    tier = str(policy.prefix_tier or "").strip()
    if tier:
        return tier
    if str(policy.prefix_cache_scope or "") == "session":
        return "session"
    return "volatile"


def _agent_use_contract(*, metadata: dict[str, Any], physical_lane: str, agent_domain: str) -> str:
    explicit = _first_text(metadata.get("agent_use_contract"), metadata.get("context_agent_use_contract"))
    if explicit:
        return explicit
    if physical_lane == "global_static_prefix":
        return "Use this as stable operating context for the current turn. Keep it separate from current user instructions."
    if physical_lane == "provider_visible_context_prefix":
        return "Use this as confirmed prior context. Preserve chronology and verify old facts against current evidence when needed."
    if physical_lane == "current_turn_tail":
        return "Use this as current-turn task context. Treat it as pending until the provider-visible ledger commits it."
    if physical_lane == "never_replay_tail":
        return "Use this only for the current model decision. Do not commit it to memory or rely on it after this turn."
    if agent_domain == "ProviderTransportDomain":
        return "Provider transport data is hidden from the agent prompt and must not be committed to memory."
    return "Use this context according to its declared domain, time scope, and connection contract."


def _agent_role(*, metadata: dict[str, Any], agent_domain: str) -> str:
    explicit = _first_text(metadata.get("agent_role"), metadata.get("context_agent_role"))
    if explicit:
        return explicit
    return _AGENT_ROLE_BY_DOMAIN.get(agent_domain, "context_consumer")


def _control_layer(*, policy: ContextSegmentPolicy, physical_lane: str, visibility: str) -> str:
    if visibility == "provider_transport":
        return "provider_transport"
    if physical_lane == "global_static_prefix":
        return "stable_prefix"
    if physical_lane == "provider_visible_context_prefix":
        return "confirmed_context_prefix"
    if physical_lane == "current_turn_tail":
        return "current_turn_append"
    if physical_lane == "never_replay_tail":
        return "current_control_tail"
    section = str(policy.section or "")
    if section == STATIC_PREFIX:
        return "stable_prefix"
    if section == CONTEXT_MEMORY_PREFIX:
        return "confirmed_context_prefix"
    if section == CONTEXT_APPEND:
        return "current_turn_append"
    return "current_control_tail"


def _provider_payload_segment_ref(*, metadata: dict[str, Any], prefix_identity: dict[str, Any]) -> str:
    return _first_text(
        metadata.get("provider_payload_segment_ref"),
        metadata.get("physical_prefix_frame_segment_id"),
        metadata.get("prefix_segment_ref"),
        metadata.get("logical_segment_ref"),
        metadata.get("provider_visible_append_item_key"),
        prefix_identity.get("logical_segment_ref"),
    )


def _metadata_declares_slot(metadata: dict[str, Any]) -> bool:
    return bool(
        _first_text(
            metadata.get("context_semantic_slot"),
            metadata.get("semantic_slot"),
            metadata.get("context_slot"),
            metadata.get("context_contract_slot"),
            metadata.get("runtime_contract_slot"),
        )
    )


def _content_mode(spec: dict[str, Any]) -> str:
    if spec.get("payload") is not None:
        return "full"
    if spec.get("content"):
        return "full"
    return "ref_only"


def _node_id(*, kind: str, source_ref: str, index: int) -> str:
    safe_kind = _safe_token(kind)[:80]
    safe_ref = _safe_token(source_ref)[:80]
    return f"ctx:{index}:{safe_kind}:{safe_ref}"


def _diagnostics(
    payload: dict[str, Any],
    *,
    metadata: dict[str, Any],
    kind: str,
    policy: ContextSegmentPolicy,
    physical_lane: str,
    prefix_identity: dict[str, Any],
    agent_domain: str,
    control_signal: str,
    connection_contract_ref: str,
) -> dict[str, Any]:
    missing: list[str] = []
    if not agent_domain:
        missing.append("agent_domain")
    if not control_signal:
        missing.append("control_signal")
    if not physical_lane:
        missing.append("physical_lane")
    if not connection_contract_ref:
        missing.append("connection_contract_ref")
    return {
        "classification_authority": "explicit_context_segment_policy",
        "policy_authority": policy.authority,
        "policy_section": policy.section,
        "policy_semantic_slot": policy.semantic_slot,
        "policy_contract_slot": policy.contract_slot,
        "registry_kind_declared": context_segment_kind_declaration(kind) is not None,
        "prefix_identity_authority": str(prefix_identity.get("authority") or ""),
        "prefix_identity_schema": str(prefix_identity.get("schema") or ""),
        "explicit_contract_missing_fields": missing,
        "missing_connection_contract": "connection_contract_ref" in missing,
        "input_role": str(payload.get("role") or ""),
        "input_kind": kind,
        "input_cache_scope": str(payload.get("cache_scope") or ""),
        "input_cache_role": str(payload.get("cache_role") or ""),
        "metadata_context_cache_section": str(metadata.get("context_cache_section") or ""),
        "metadata_physical_prefix_lane": str(metadata.get("physical_prefix_lane") or ""),
    }


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_token(value: Any) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", ".", ":"} else "_" for ch in str(value or "").strip()) or "unknown"


_AGENT_DOMAIN_BY_CAPABILITY_GROUP = {
    STATIC_IDENTITY: "StablePromptDomain",
    RUNTIME_CONTRACTS: "RuntimeBoundaryDomain",
    ACTION_CONTRACTS: "ActionContractDomain",
    TASK_RUN_CONTRACTS: "TaskRunContractDomain",
    TOOL_CONTEXT: "ToolContextDomain",
    CONTEXT_MEMORY: "ContextMemoryDomain",
    TASK_STATE_CONTEXT: "TaskStateDomain",
    EVIDENCE_CONTEXT: "EvidenceDomain",
    EVIDENCE_ALIGNMENT: "EvidenceAlignmentDomain",
    CURRENT_DYNAMIC_CONTROL: "RuntimeControlDomain",
    TURN_STATE_CONTROL: "TurnStateControlDomain",
    REPAIR_FEEDBACK: "RecoveryFeedbackDomain",
    ACTIVE_SKILL: "SkillActivationDomain",
    REASONING_PROJECTION: "ReasoningProjectionDomain",
}

_AGENT_ROLE_BY_DOMAIN = {
    "StablePromptDomain": "stable_context_consumer",
    "RuntimeBoundaryDomain": "runtime_boundary_consumer",
    "ActionContractDomain": "action_contract_consumer",
    "TaskRunContractDomain": "task_run_contract_consumer",
    "ToolContextDomain": "tool_context_consumer",
    "ContextMemoryDomain": "context_memory_consumer",
    "TaskStateDomain": "task_state_consumer",
    "EvidenceDomain": "evidence_consumer",
    "EvidenceAlignmentDomain": "evidence_alignment_consumer",
    "RuntimeControlDomain": "runtime_control_consumer",
    "TurnStateControlDomain": "turn_state_consumer",
    "RecoveryFeedbackDomain": "recovery_feedback_consumer",
    "SkillActivationDomain": "skill_activation_consumer",
    "ReasoningProjectionDomain": "reasoning_projection_consumer",
    "ProviderTransportDomain": "provider_transport_binding",
}
