from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


STATIC_PREFIX = "static_prefix"
SEALED_CONTEXT_PREFIX = "sealed_context_prefix"
CONTEXT_APPEND = "context_append"
DYNAMIC_TAIL = "dynamic_tail"

CONTEXT_ASSEMBLY_ORDER = (
    STATIC_PREFIX,
    SEALED_CONTEXT_PREFIX,
    CONTEXT_APPEND,
    DYNAMIC_TAIL,
)


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
    "runtime_baseline_refs",
    "task_contract_stable",
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
    "runtime_memory_context",
    "session_history",
    "session_history_context",
    "session_history_entry",
    "session_pinned_facts_context",
    "single_agent_turn_followup_message",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
    "single_agent_turn_user_steer_context",
    "task_plan_context",
    "task_start_inherited_context",
    "task_state_replay_entry",
    "tool_observations",
    "user_steering_context_append",
    "volatile_user",
}

APPEND_ONLY_CONTEXT_KINDS = {
    "incremental_context_frame",
    "provider_protocol_history",
    "read_evidence_context",
    "runtime_memory_context",
    "session_history_entry",
    "session_pinned_facts_context",
    "single_agent_turn_followup_message",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
    "single_agent_turn_user_steer_context",
    "task_state_replay_entry",
    "tool_observations",
    "user_steering_context_append",
}

CURRENT_UNCACHED_CONTEXT_APPEND_KINDS = {
    "volatile_user",
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
    "skill_candidates",
    "task_runtime_boundary_dynamic",
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
    "task_plan_context",
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
class ContextAssemblyClassification:
    kind: str
    context_cache_section: str
    fixed_context_package: str
    semantic_commit_class: str
    memory_commit_policy: str
    cache_scope: str
    cache_role: str
    prefix_tier: str
    reason: str
    authority: str = "runtime.context_management.context_assembly"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_context_spec(spec: dict[str, Any] | None) -> ContextAssemblyClassification:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    kind = str(payload.get("kind") or metadata.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
    explicit_section = str(metadata.get("context_cache_section") or payload.get("context_cache_section") or "").strip()
    if explicit_section in CONTEXT_ASSEMBLY_ORDER:
        section = explicit_section
        reason = "explicit_context_cache_section"
    elif kind in STATIC_PREFIX_KINDS:
        section = STATIC_PREFIX
        reason = "static_prefix_kind"
    elif kind in CURRENT_CONTROL_TAIL_KINDS:
        section = DYNAMIC_TAIL
        reason = "current_control_tail_kind"
    elif kind in MEMORY_CONTEXT_KINDS:
        section = CONTEXT_APPEND
        reason = "rememberable_context_kind"
    else:
        dynamic_tier = str(metadata.get("prompt_assembly_dynamic_tier") or metadata.get("dynamic_tier") or "").strip()
        if dynamic_tier in MEMORY_DYNAMIC_TIERS:
            section = CONTEXT_APPEND
            reason = "rememberable_dynamic_tier"
        elif dynamic_tier in CONTROL_DYNAMIC_TIERS:
            section = DYNAMIC_TAIL
            reason = "current_control_dynamic_tier"
        elif _is_cache_stable(payload):
            section = STATIC_PREFIX
            reason = "legacy_cache_stable_without_memory_role"
        else:
            section = DYNAMIC_TAIL
            reason = "legacy_volatile_current_control"

    semantic_commit_class = _semantic_commit_class(kind=kind, section=section)
    memory_commit_policy = _memory_commit_policy(kind=kind, section=section)
    cache_scope, cache_role, prefix_tier = _cache_policy_for_section(
        payload,
        kind=kind,
        section=section,
    )
    fixed_context_package = {
        STATIC_PREFIX: "static_prefix",
        SEALED_CONTEXT_PREFIX: "sealed_context",
        CONTEXT_APPEND: "context_append",
        DYNAMIC_TAIL: "dynamic_tail",
    }[section]
    return ContextAssemblyClassification(
        kind=kind,
        context_cache_section=section,
        fixed_context_package=fixed_context_package,
        semantic_commit_class=semantic_commit_class,
        memory_commit_policy=memory_commit_policy,
        cache_scope=cache_scope,
        cache_role=cache_role,
        prefix_tier=prefix_tier,
        reason=reason,
    )


def apply_context_assembly_classification(spec: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(spec or {})
    classification = classify_context_spec(payload)
    metadata = {
        **dict(payload.get("metadata") or {}),
        **classification.to_dict(),
        "context_assembly_order": list(CONTEXT_ASSEMBLY_ORDER),
    }
    payload["cache_scope"] = classification.cache_scope
    payload["cache_role"] = classification.cache_role
    payload["prefix_tier"] = classification.prefix_tier
    payload["metadata"] = metadata
    return payload


def is_dynamic_tail_spec(spec: dict[str, Any] | None) -> bool:
    return classify_context_spec(spec).context_cache_section == DYNAMIC_TAIL


def is_context_append_spec(spec: dict[str, Any] | None) -> bool:
    return classify_context_spec(spec).context_cache_section == CONTEXT_APPEND


def is_sealable_context_spec(spec: dict[str, Any] | None) -> bool:
    classification = classify_context_spec(spec)
    if classification.context_cache_section in {SEALED_CONTEXT_PREFIX, CONTEXT_APPEND}:
        return True
    return classification.kind in APPEND_ONLY_CONTEXT_KINDS


def _cache_policy_for_section(
    spec: dict[str, Any],
    *,
    kind: str,
    section: str,
) -> tuple[str, str, str]:
    if section == STATIC_PREFIX:
        cache_role = _cache_role(spec.get("cache_role"))
        if cache_role not in {"cacheable_prefix", "session_stable"}:
            cache_role = "session_stable"
        cache_scope = str(spec.get("cache_scope") or "").strip()
        if not cache_scope or cache_scope == "none":
            cache_scope = "global" if cache_role == "cacheable_prefix" else "session"
        return cache_scope, cache_role, _prefix_tier(spec.get("prefix_tier"), cache_scope=cache_scope, cache_role=cache_role)
    if section in {SEALED_CONTEXT_PREFIX, CONTEXT_APPEND}:
        if kind in CURRENT_UNCACHED_CONTEXT_APPEND_KINDS:
            return "none", "volatile", "volatile"
        return "task", "session_stable", "task"
    return "none", "volatile", "volatile"


def _semantic_commit_class(*, kind: str, section: str) -> str:
    if section == STATIC_PREFIX:
        return "static_protocol"
    if section == SEALED_CONTEXT_PREFIX:
        return "sealed_context_memory"
    if section == CONTEXT_APPEND:
        if kind in {"volatile_user", "single_agent_turn_user_steer_context", "user_steering_context_append"}:
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
    if kind in APPEND_ONLY_CONTEXT_KINDS or section in {SEALED_CONTEXT_PREFIX, CONTEXT_APPEND}:
        return "append_then_seal"
    return "preserve_if_stable"


def _is_cache_stable(spec: dict[str, Any]) -> bool:
    cache_role = _cache_role(spec.get("cache_role"))
    if cache_role not in {"cacheable_prefix", "session_stable"}:
        return False
    prefix_tier = _prefix_tier(
        spec.get("prefix_tier"),
        cache_scope=str(spec.get("cache_scope") or "none"),
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
