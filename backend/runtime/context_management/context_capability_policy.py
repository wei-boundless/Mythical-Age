from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .context_segment_policy import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    context_segment_policy_for_spec,
    context_segment_policy_metadata,
)
from .context_segment_registry import (
    context_segment_kind_capability,
)


STATIC_IDENTITY = "static_identity"
RUNTIME_CONTRACTS = "runtime_contracts"
ACTION_CONTRACTS = "action_contracts"
TASK_RUN_CONTRACTS = "task_run_contracts"
TOOL_CONTEXT = "tool_context"
CONTEXT_MEMORY = "context_memory"
TASK_STATE_CONTEXT = "task_state_context"
EVIDENCE_CONTEXT = "evidence_context"
EVIDENCE_ALIGNMENT = "evidence_alignment"
CURRENT_DYNAMIC_CONTROL = "current_dynamic_control"
TURN_STATE_CONTROL = "turn_state_control"
REPAIR_FEEDBACK = "repair_feedback"
ACTIVE_SKILL = "active_skill"
MEMORY_WRITE = "memory_write"
REASONING_PROJECTION = "reasoning_projection"
SUBAGENT_SYSTEM = "subagent_system"


DEFAULT_CONTEXT_CAPABILITY_GROUPS = (
    STATIC_IDENTITY,
    RUNTIME_CONTRACTS,
    ACTION_CONTRACTS,
    TASK_RUN_CONTRACTS,
    TOOL_CONTEXT,
    CONTEXT_MEMORY,
    TASK_STATE_CONTEXT,
    EVIDENCE_CONTEXT,
    EVIDENCE_ALIGNMENT,
    CURRENT_DYNAMIC_CONTROL,
    TURN_STATE_CONTROL,
    REPAIR_FEEDBACK,
    ACTIVE_SKILL,
    MEMORY_WRITE,
    REASONING_PROJECTION,
    SUBAGENT_SYSTEM,
)

_DISABLED_TEXT = {"disabled", "disable", "off", "false", "0", "none", "omit", "omitted", "hidden"}
_ENABLED_TEXT = {"enabled", "enable", "on", "true", "1", "yes", "include", "included", "visible"}

_PROMPT_RULE_KIND_GROUPS: dict[str, str] = {
    "agent.role": STATIC_IDENTITY,
    "personality.identity_style": STATIC_IDENTITY,
    "worker.role": STATIC_IDENTITY,
    "runtime.protocol": RUNTIME_CONTRACTS,
    "runtime.system_call_protocol": ACTION_CONTRACTS,
    "runtime.turn_decision_alignment": ACTION_CONTRACTS,
    "runtime.tool_use": TOOL_CONTEXT,
    "harness.runtime.output_boundary": REPAIR_FEEDBACK,
    "runtime.error_recovery": REPAIR_FEEDBACK,
    "runtime.context_memory": CONTEXT_MEMORY,
    "runtime.permission_denial": ACTION_CONTRACTS,
    "runtime.subagent_delegation": SUBAGENT_SYSTEM,
    "runtime.subagent_invocation_protocol": SUBAGENT_SYSTEM,
    "runtime.multi_tool_scheduling": TOOL_CONTEXT,
    "runtime.plan_mode_boundary": ACTION_CONTRACTS,
    "runtime.turn_state_orientation": TURN_STATE_CONTROL,
    "tool.guidance": TOOL_CONTEXT,
    "file_management.generic": STATIC_IDENTITY,
    "coding.inspection": STATIC_IDENTITY,
    "coding.core_work_protocol": STATIC_IDENTITY,
    "coding.large_scope_exploration": STATIC_IDENTITY,
    "coding.editing": STATIC_IDENTITY,
    "coding.verification": STATIC_IDENTITY,
    "coding.debug_discipline": STATIC_IDENTITY,
    "coding.git_safety": STATIC_IDENTITY,
    "coding.windows_shell": STATIC_IDENTITY,
    "coding.task_progress": STATIC_IDENTITY,
    "environment.boundary": STATIC_IDENTITY,
    "graph.contract": RUNTIME_CONTRACTS,
    "system.foundation.local_collaboration": STATIC_IDENTITY,
    "system.foundation.current_request_authority": STATIC_IDENTITY,
    "system.foundation.truth_and_verification": STATIC_IDENTITY,
    "system.foundation.response_and_reporting": STATIC_IDENTITY,
    "system.foundation.security_and_injection": STATIC_IDENTITY,
    "system.foundation.context_memory_cache": STATIC_IDENTITY,
    "system.foundation.user_change_protection": STATIC_IDENTITY,
}

_CONTRACT_SLOT_GROUPS: dict[str, str] = {
    "action_contract": ACTION_CONTRACTS,
    "answer_evidence_alignment_contract": EVIDENCE_ALIGNMENT,
    "capability_catalog": TOOL_CONTEXT,
    "evidence_alignment_contract": EVIDENCE_ALIGNMENT,
    "provider_visible_ledger_recovery": REPAIR_FEEDBACK,
    "runtime_control_contract": TURN_STATE_CONTROL,
    "runtime_followup_contract": ACTION_CONTRACTS,
    "tool_context_contract": TOOL_CONTEXT,
    "tool_dispatch": TOOL_CONTEXT,
    "tool_index": TOOL_CONTEXT,
    "tool_observation_recovery": REPAIR_FEEDBACK,
    "tool_transcript": TOOL_CONTEXT,
    "turn_operating_contract": TURN_STATE_CONTROL,
    "turn_state_guidance": TURN_STATE_CONTROL,
    "visible_prefix_recovery_context": REPAIR_FEEDBACK,
    "visible_prefix_recovery_contract": REPAIR_FEEDBACK,
}


@dataclass(frozen=True, slots=True)
class ContextCapabilityDecision:
    enabled: bool
    group: str
    slot: str = ""
    member: str = "content"
    reason: str = ""
    source: str = "runtime.context_management.context_capability_policy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextCapabilityProfile:
    profile_id: str
    invocation_kind: str = ""
    enabled_groups: tuple[str, ...] = DEFAULT_CONTEXT_CAPABILITY_GROUPS
    disabled_groups: tuple[str, ...] = ()
    group_config: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.context_management.context_capability_policy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["enabled_groups"] = list(self.enabled_groups)
        payload["disabled_groups"] = list(self.disabled_groups)
        payload["group_config"] = dict(self.group_config)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def build_context_capability_profile(
    *,
    invocation_kind: str = "",
    profile_payload: dict[str, Any] | None = None,
    override: dict[str, Any] | None = None,
) -> ContextCapabilityProfile:
    profile = dict(profile_payload or {})
    raw_profile = _merge_dicts(
        profile,
        profile.get("context_capability_profile"),
        override,
    )
    group_config = _group_config_from_policy(raw_profile)
    explicit_enabled = _string_set(
        raw_profile.get("enabled_groups")
        or raw_profile.get("enabled_context_capability_groups")
    )
    explicit_disabled = _string_set(
        raw_profile.get("disabled_groups")
        or raw_profile.get("disabled_context_capability_groups")
    )
    enabled = set(DEFAULT_CONTEXT_CAPABILITY_GROUPS)
    if explicit_enabled:
        enabled.update(item for item in explicit_enabled if item in DEFAULT_CONTEXT_CAPABILITY_GROUPS)
    disabled = set(explicit_disabled)
    for group, value in group_config.items():
        group_id = str(group or "").strip()
        if group_id not in DEFAULT_CONTEXT_CAPABILITY_GROUPS:
            continue
        if _policy_value_enabled(value, default=True):
            enabled.add(group_id)
            disabled.discard(group_id)
        else:
            disabled.add(group_id)
            enabled.discard(group_id)
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "enabled_groups": sorted(enabled),
        "disabled_groups": sorted(disabled),
    }
    return ContextCapabilityProfile(
        profile_id="ctxcap:" + _stable_hash(seed)[:16],
        invocation_kind=str(invocation_kind or ""),
        enabled_groups=tuple(group for group in DEFAULT_CONTEXT_CAPABILITY_GROUPS if group in enabled and group not in disabled),
        disabled_groups=tuple(group for group in DEFAULT_CONTEXT_CAPABILITY_GROUPS if group in disabled),
        group_config=dict(group_config),
        diagnostics={
            "default_enabled": True,
            "physical_plan_note": "capability switches only connect or omit semantic groups before PhysicalContextPlan",
            "authority": "runtime.context_management.context_capability_policy.profile_builder",
        },
    )


def context_capability_profile_from_payload(value: dict[str, Any] | ContextCapabilityProfile | None) -> ContextCapabilityProfile:
    if isinstance(value, ContextCapabilityProfile):
        return value
    payload = dict(value or {})
    if payload.get("authority") == "runtime.context_management.context_capability_policy" or payload.get("profile_id"):
        enabled = tuple(
            group
            for group in _string_sequence(payload.get("enabled_groups"))
            if group in DEFAULT_CONTEXT_CAPABILITY_GROUPS
        )
        disabled = tuple(
            group
            for group in _string_sequence(payload.get("disabled_groups"))
            if group in DEFAULT_CONTEXT_CAPABILITY_GROUPS
        )
        seed = {
            "invocation_kind": str(payload.get("invocation_kind") or ""),
            "enabled_groups": sorted(enabled),
            "disabled_groups": sorted(disabled),
        }
        return ContextCapabilityProfile(
            profile_id=str(payload.get("profile_id") or "ctxcap:" + _stable_hash(seed)[:16]),
            invocation_kind=str(payload.get("invocation_kind") or ""),
            enabled_groups=enabled or DEFAULT_CONTEXT_CAPABILITY_GROUPS,
            disabled_groups=disabled,
            group_config=dict(payload.get("group_config") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
        )
    return build_context_capability_profile(override=payload)


def apply_context_capability_profile(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    profile: dict[str, Any] | ContextCapabilityProfile | None = None,
    invocation_kind: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved = context_capability_profile_from_payload(profile)
    enabled_groups = set(resolved.enabled_groups)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for index, raw_spec in enumerate(list(specs or []), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        decision = context_capability_decision_for_spec(spec, profile=resolved)
        counts[decision.group] = counts.get(decision.group, 0) + 1
        if not decision.enabled:
            rejected.append(
                {
                    "index": index,
                    "kind": str(spec.get("kind") or ""),
                    "source_ref": str(spec.get("source_ref") or ""),
                    "context_capability_group": decision.group,
                    "context_capability_slot": decision.slot,
                    "reason": decision.reason,
                }
            )
            continue
        kept.append(_annotated_spec(spec, profile=resolved, decision=decision))
    return kept, {
        "context_capability_profile": resolved.to_dict(),
        "context_capability_group_counts": counts,
        "rejected_context_capability_count": len(rejected),
        "rejected_context_capabilities": rejected[:30],
        "input_spec_count": len([item for item in list(specs or []) if isinstance(item, dict)]),
        "output_spec_count": len(kept),
        "enabled_groups": sorted(enabled_groups),
        "disabled_groups": list(resolved.disabled_groups),
        "invocation_kind": str(invocation_kind or resolved.invocation_kind or ""),
        "authority": "runtime.context_management.context_capability_policy.spec_filter",
    }


def context_capability_decision_for_spec(
    spec: dict[str, Any],
    *,
    profile: dict[str, Any] | ContextCapabilityProfile | None = None,
) -> ContextCapabilityDecision:
    resolved = context_capability_profile_from_payload(profile)
    group, slot, member, reason = _capability_group_for_spec(spec)
    enabled = group in set(resolved.enabled_groups) and group not in set(resolved.disabled_groups)
    return ContextCapabilityDecision(
        enabled=enabled,
        group=group,
        slot=slot,
        member=member,
        reason=reason if enabled else f"context_capability_group_disabled:{group}",
    )


def context_capability_decision_for_prompt_resource(
    resource: dict[str, Any],
    *,
    profile: dict[str, Any] | ContextCapabilityProfile | None = None,
) -> ContextCapabilityDecision:
    resolved = context_capability_profile_from_payload(profile)
    group, slot, member, reason = _capability_group_for_prompt_resource(resource)
    enabled = group in set(resolved.enabled_groups) and group not in set(resolved.disabled_groups)
    return ContextCapabilityDecision(
        enabled=enabled,
        group=group,
        slot=slot,
        member=member,
        reason=reason if enabled else f"context_capability_group_disabled:{group}",
    )


def prompt_context_capability_metadata(*, group: str, slot: str = "", member: str = "contract") -> dict[str, Any]:
    return {
        "context_capability_group": str(group or "").strip(),
        "context_capability_slot": str(slot or "").strip(),
        "context_capability_member": str(member or "contract").strip(),
        "context_capability_authority": "runtime.context_management.context_capability_policy.prompt_metadata",
    }


def _annotated_spec(
    spec: dict[str, Any],
    *,
    profile: ContextCapabilityProfile,
    decision: ContextCapabilityDecision,
) -> dict[str, Any]:
    policy = context_segment_policy_for_spec(spec)
    metadata = {
        **dict(spec.get("metadata") or {}),
        **context_segment_policy_metadata(policy),
        "context_capability_profile_id": profile.profile_id,
        "context_capability_group": decision.group,
        "context_capability_slot": decision.slot,
        "context_capability_member": decision.member,
        "context_capability_enabled": True,
        "context_capability_reason": decision.reason,
        "context_capability_prefix_coupled": True,
        "context_capability_authority": "runtime.context_management.context_capability_policy",
    }
    payload = dict(spec)
    payload["metadata"] = metadata
    return payload


def _capability_group_for_spec(spec: dict[str, Any]) -> tuple[str, str, str, str]:
    metadata = dict(spec.get("metadata") or {})
    explicit = _first_text(
        metadata.get("context_capability_group"),
        spec.get("context_capability_group"),
    )
    explicit_slot = _first_text(metadata.get("context_capability_slot"), spec.get("context_capability_slot"))
    explicit_member = _first_text(metadata.get("context_capability_member"), spec.get("context_capability_member"), "content")
    if explicit:
        return _normalize_group(explicit), explicit_slot, explicit_member, "explicit_context_capability_group"
    kind = str(spec.get("kind") or metadata.get("kind") or "").strip()
    policy = context_segment_policy_for_spec(spec)
    if policy.repair_feedback_slot:
        return REPAIR_FEEDBACK, policy.repair_feedback_slot, "feedback", "policy_repair_feedback_slot"
    if policy.contract_slot:
        return _contract_group_for_slot(policy.contract_slot, kind=kind), policy.contract_slot, "contract", "policy_contract_slot"
    registry_capability = context_segment_kind_capability(kind)
    if registry_capability:
        group, slot, member = registry_capability
        return group, slot, member, "kind_capability_registry"
    semantic_slot = str(policy.semantic_slot or "").strip()
    if semantic_slot in _SEMANTIC_SLOT_GROUPS:
        group, member = _SEMANTIC_SLOT_GROUPS[semantic_slot]
        return group, semantic_slot, member, "semantic_slot_capability_catalog"
    section = str(policy.section or "").strip()
    if section == STATIC_PREFIX:
        return STATIC_IDENTITY, semantic_slot or "static_prefix", "prefix", "context_static_section"
    if section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
        return CONTEXT_MEMORY, semantic_slot or "context_memory", "content", "context_memory_section"
    if section == DYNAMIC_TAIL:
        return CURRENT_DYNAMIC_CONTROL, semantic_slot or "dynamic_tail", "control", "context_dynamic_tail_section"
    return CURRENT_DYNAMIC_CONTROL, semantic_slot or "unknown", "content", "fallback_current_dynamic_control"


def _capability_group_for_prompt_resource(resource: dict[str, Any]) -> tuple[str, str, str, str]:
    metadata = dict(resource.get("metadata") or {})
    explicit = _first_text(metadata.get("context_capability_group"), resource.get("context_capability_group"))
    explicit_slot = _first_text(metadata.get("context_capability_slot"), resource.get("context_capability_slot"))
    explicit_member = _first_text(metadata.get("context_capability_member"), resource.get("context_capability_member"), "contract")
    if explicit:
        return _normalize_group(explicit), explicit_slot, explicit_member, "explicit_prompt_context_capability_group"
    category = str(resource.get("category") or "").strip()
    subtype = str(resource.get("subtype") or "").strip()
    prompt_rule = dict(metadata.get("prompt_rule") or {})
    rule_kind = str(prompt_rule.get("rule_kind") or "").strip()
    if rule_kind:
        group = _group_for_rule_kind(rule_kind)
        if group:
            return group, rule_kind, "contract", "prompt_rule_kind_capability_catalog"
    if category == "system" and subtype == "foundation":
        return STATIC_IDENTITY, subtype, "contract", "stable_system_foundation_prompt"
    if category == "runtime":
        return RUNTIME_CONTRACTS, subtype or "runtime", "contract", "runtime_prompt_category"
    environment_guidance_slot = str(metadata.get("environment_guidance_slot") or "").strip()
    if category == "environment" and environment_guidance_slot:
        slot = environment_guidance_slot
        return _group_for_environment_guidance_slot(slot), slot, "contract", "environment_guidance_slot"
    if category == "agent":
        return STATIC_IDENTITY, "agent_role", "contract", "agent_prompt"
    if category == "personality":
        return STATIC_IDENTITY, "personality", "contract", "personality_prompt"
    if category == "environment":
        return STATIC_IDENTITY, subtype or "environment", "contract", "environment_prompt"
    if category in {"task", "graph_node"}:
        return TASK_RUN_CONTRACTS, subtype or "task_run_contract", "contract", "task_run_contract_prompt"
    return STATIC_IDENTITY, subtype or category or "prompt", "contract", "fallback_static_prompt"


def _contract_group_for_slot(slot: str, *, kind: str) -> str:
    normalized = str(slot or "").strip()
    if normalized in _CONTRACT_SLOT_GROUPS:
        return _CONTRACT_SLOT_GROUPS[normalized]
    semantic_group = _SEMANTIC_SLOT_GROUPS.get(normalized)
    if semantic_group:
        return semantic_group[0]
    registry_capability = context_segment_kind_capability(kind)
    if registry_capability:
        group, _slot, member = registry_capability
        if str(member or "").strip() in {"contract", "control", "feedback"}:
            return group
    return ACTION_CONTRACTS


def _group_for_rule_kind(rule_kind: str) -> str:
    value = str(rule_kind or "").strip()
    return _PROMPT_RULE_KIND_GROUPS.get(value, "")


def _group_for_environment_guidance_slot(slot: str) -> str:
    value = str(slot or "").strip()
    if value in {"memory_read_context"}:
        return CONTEXT_MEMORY
    if value in {"memory_write_handoff"}:
        return MEMORY_WRITE
    if value in {"subagent_delegation", "subagent_result_integration"}:
        return SUBAGENT_SYSTEM
    if value in {"tool_dispatch"}:
        return TOOL_CONTEXT
    if value in {"tool_observation_recovery", "verification_gate", "compaction_handoff", "finalization"}:
        return REPAIR_FEEDBACK
    if value in {"active_work_control", "action_boundary", "task_run_handoff", "user_steer_contract_revision", "plan_gate", "request_judgment"}:
        return ACTION_CONTRACTS
    return TURN_STATE_CONTROL

_SEMANTIC_SLOT_GROUPS: dict[str, tuple[str, str]] = {
    "recovery_or_recent_work_facts": (REPAIR_FEEDBACK, "feedback"),
    "provider_protocol_history": (CONTEXT_MEMORY, "content"),
    "selected_memory_and_task_state_facts": (CONTEXT_MEMORY, "content"),
    "task_goal_context": (TASK_STATE_CONTEXT, "content"),
    "task_plan_context": (TASK_STATE_CONTEXT, "content"),
    "task_todo_context": (TASK_STATE_CONTEXT, "content"),
    "current_user_intent": (CONTEXT_MEMORY, "content"),
    "active_user_steer_content": (CONTEXT_MEMORY, "content"),
    "evidence_refs_and_file_state_facts": (EVIDENCE_CONTEXT, "content"),
    "evidence_semantic_summary": (EVIDENCE_ALIGNMENT, "content"),
    "read_coverage_projection": (EVIDENCE_ALIGNMENT, "content"),
    "provider_usage_truth_source": (EVIDENCE_ALIGNMENT, "content"),
    "execution_action_evidence": (EVIDENCE_ALIGNMENT, "content"),
    "answer_evidence_alignment_contract": (EVIDENCE_ALIGNMENT, "contract"),
    "answer_alignment_feedback": (EVIDENCE_ALIGNMENT, "feedback"),
    "reasoning_trace_projection": (REASONING_PROJECTION, "content"),
    "provider_reasoning_projection": (REASONING_PROJECTION, "content"),
    "tool_transcript": (TOOL_CONTEXT, "content"),
    "action_contract": (ACTION_CONTRACTS, "contract"),
    "capability_catalog": (TOOL_CONTEXT, "contract"),
    "turn_state_guidance": (TURN_STATE_CONTROL, "contract"),
    "turn_attention_index": (TASK_STATE_CONTEXT, "content"),
    "turn_operating_contract": (TURN_STATE_CONTROL, "contract"),
    "runtime_control_contract": (TURN_STATE_CONTROL, "control"),
    "visible_prefix_recovery_contract": (REPAIR_FEEDBACK, "feedback"),
    "visible_prefix_recovery_context": (REPAIR_FEEDBACK, "feedback"),
    "provider_visible_ledger_recovery": (REPAIR_FEEDBACK, "feedback"),
}


def _group_config_from_policy(
    raw_profile: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in (
        raw_profile.get("groups"),
        raw_profile.get("context_capability_groups"),
    ):
        if isinstance(value, dict):
            result.update(value)
    for group in DEFAULT_CONTEXT_CAPABILITY_GROUPS:
        for key in (group, f"include_{group}", f"{group}_enabled"):
            if key in raw_profile:
                result[group] = raw_profile[key]
    return result


def _policy_value_enabled(value: Any, *, default: bool) -> bool:
    if isinstance(value, dict):
        if "enabled" in value:
            return _policy_value_enabled(value.get("enabled"), default=default)
        if "mode" in value:
            return _policy_value_enabled(value.get("mode"), default=default)
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if not normalized or normalized in {"default", "inherit"}:
        return default
    if normalized in _DISABLED_TEXT:
        return False
    if normalized in _ENABLED_TEXT:
        return True
    return default


def _normalize_group(value: str) -> str:
    group = str(value or "").strip()
    aliases = {
        "memory": CONTEXT_MEMORY,
        "context": CONTEXT_MEMORY,
        "contract": ACTION_CONTRACTS,
        "contracts": ACTION_CONTRACTS,
        "tool": TOOL_CONTEXT,
        "tools": TOOL_CONTEXT,
        "subagent": SUBAGENT_SYSTEM,
        "subagents": SUBAGENT_SYSTEM,
        "subagent_delegation": SUBAGENT_SYSTEM,
        "dynamic_tail": CURRENT_DYNAMIC_CONTROL,
        "dynamic": CURRENT_DYNAMIC_CONTROL,
        "evidence": EVIDENCE_CONTEXT,
        "evidence_alignment": EVIDENCE_ALIGNMENT,
        "answer_evidence_alignment": EVIDENCE_ALIGNMENT,
        "reasoning": REASONING_PROJECTION,
        "reasoning_projection": REASONING_PROJECTION,
        "feedback": REPAIR_FEEDBACK,
        "recovery": REPAIR_FEEDBACK,
        "static": STATIC_IDENTITY,
    }
    return aliases.get(group, group if group in DEFAULT_CONTEXT_CAPABILITY_GROUPS else CURRENT_DYNAMIC_CONTROL)


def _merge_dicts(*values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            result.update(value)
    return result


def _string_sequence(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value or [])
    return tuple(str(item).strip() for item in values if str(item).strip())


def _string_set(value: Any) -> set[str]:
    return {_normalize_group(item) for item in _string_sequence(value)}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)

