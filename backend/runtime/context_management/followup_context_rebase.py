from __future__ import annotations

import hashlib
from typing import Any

from runtime.prompt_accounting.serializer import canonical_json, normalize_messages

from .context_segment_policy import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    STATIC_PREFIX,
    context_segment_policy_for_spec,
    context_segment_policy_metadata,
)
from .tool_transcript import is_tool_transcript_kind


def current_followup_append_context_policy(
    base: dict[str, Any],
    *,
    message: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    append_metadata = {
        **_without_context_classification_metadata(dict(metadata or {})),
        "previous_context_structure": {
            key: value
            for key, value in dict(metadata or {}).items()
            if str(key).startswith("context_")
        },
        "context_cache_section": CONTEXT_APPEND,
        "context_semantic_slot": str(dict(metadata or {}).get("context_semantic_slot") or "tool_transcript"),
        "context_prefix_cache_scope": "none",
        "context_prefix_cache_role": "volatile",
        "context_prefix_tier": "volatile",
        "context_commit_policy": "append_then_seal",
        "context_replay_policy": "current_append_commit_on_provider_success_then_next_ledger_replay",
        "provider_visible_history_status": "current_tool_round_pending_provider_success",
        "provider_visible_history_authority": "runtime.context_management.followup_context_rebase.current_append",
        "provider_visible_history_model_message_hash": _stable_model_message_hash(dict(message or {})),
        "cache_impact": "current_context_append_promotes_to_next_prefix",
        "stability_rule": (
            "this message belongs to the current tool round; it is provider-visible now, "
            "but must not be counted as cache-readable until a provider success confirms it for later replay"
        ),
    }
    append_spec = {
        **dict(base or {}),
        "cache_scope": "none",
        "cache_role": "volatile",
        "prefix_tier": "volatile",
        "metadata": append_metadata,
    }
    policy = context_segment_policy_for_spec(append_spec, default_section=CONTEXT_APPEND)
    return {
        "cache_scope": "none",
        "cache_role": "volatile",
        "prefix_tier": "volatile",
        "metadata": {
            **append_metadata,
            **context_segment_policy_metadata(policy),
        },
    }


def sealed_followup_base_context_policy(
    base: dict[str, Any],
    *,
    message: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    original_policy = context_segment_policy_for_spec(base)
    if original_policy.section == STATIC_PREFIX:
        policy = original_policy
        return {
            "cache_scope": str(base.get("cache_scope") or policy.prefix_cache_scope or "session"),
            "cache_role": str(base.get("cache_role") or policy.prefix_cache_role or "session_stable"),
            "prefix_tier": str(base.get("prefix_tier") or policy.prefix_tier or "session"),
            "metadata": {
                **dict(metadata or {}),
                **context_segment_policy_metadata(policy),
                "provider_visible_history_status": "static_context",
                "provider_visible_history_authority": "runtime.context_management.followup_context_rebase.base_replay",
            },
        }

    original_context = {
        key: value
        for key, value in dict(metadata or {}).items()
        if str(key).startswith("context_")
    }
    sealed_metadata = {
        **_without_context_classification_metadata(dict(metadata or {})),
        "previous_context_structure": original_context,
        "context_cache_section": CONTEXT_MEMORY_PREFIX,
        "context_semantic_slot": str(dict(metadata or {}).get("context_semantic_slot") or "provider_visible_history"),
        "context_commit_policy": "replay_only_already_materialized",
        "context_replay_policy": "provider_visible_history_replay",
        "provider_visible_history_status": "sealed_from_prior_model_request",
        "provider_visible_history_authority": "runtime.context_management.followup_context_rebase.base_replay",
        "provider_visible_history_model_message_hash": _stable_model_message_hash(dict(message or {})),
        "cache_impact": "sealed_provider_visible_history",
        "stability_rule": (
            "this message was already sent to the provider in an earlier request; "
            "the follow-up path must replay the exact provider-visible bytes and treat it as sealed context history"
        ),
    }
    sealed_spec = {
        **dict(base or {}),
        "cache_scope": "session",
        "cache_role": "session_stable",
        "prefix_tier": "session",
        "metadata": sealed_metadata,
    }
    policy = context_segment_policy_for_spec(sealed_spec, default_section=CONTEXT_MEMORY_PREFIX)
    return {
        "cache_scope": "session",
        "cache_role": "session_stable",
        "prefix_tier": "session",
        "metadata": {
            **sealed_metadata,
            **context_segment_policy_metadata(policy),
        },
        "kind": provider_visible_history_replay_kind(base, message=message),
    }


def provider_visible_history_replay_kind(base: dict[str, Any], *, message: dict[str, Any]) -> str:
    original_kind = str(dict(base or {}).get("kind") or "").strip()
    role = str(dict(message or {}).get("role") or "").strip()
    if is_tool_transcript_kind(original_kind, include_historical=True):
        return "provider_visible_tool_transcript_replay"
    if role == "tool" or (role == "assistant" and dict(message or {}).get("tool_calls")):
        return "provider_visible_tool_transcript_replay"
    if original_kind in {"current_turn_user_context", "single_agent_turn_user_steer_context", "user_steering_context_append"}:
        return "provider_visible_user_context_replay"
    if role == "user":
        return "provider_visible_user_message_replay"
    if role == "assistant":
        return "provider_visible_assistant_message_replay"
    return original_kind or "provider_visible_context_replay"


def _without_context_classification_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = dict(metadata or {})
    for key in (
        "authority",
        "cache_role",
        "cache_scope",
        "context_cache_section",
        "context_commit_policy",
        "context_contract_mapping_authority",
        "context_contract_ref",
        "context_contract_slot",
        "context_identity_policy",
        "context_prefix_cache_role",
        "context_prefix_cache_scope",
        "context_prefix_tier",
        "context_repair_feedback_slot",
        "context_replay_policy",
        "context_segment_policy",
        "context_semantic_slot",
        "context_semantic_slot_rank",
        "fixed_context_package",
        "memory_commit_policy",
        "prefix_tier",
        "reason",
        "semantic_commit_class",
    ):
        payload.pop(key, None)
    return payload


def _stable_model_message_hash(message: dict[str, Any]) -> str:
    normalized = normalize_messages([dict(message or {})])
    payload = normalized[0] if normalized else {"role": "user", "content": ""}
    text = canonical_json(payload)
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()
