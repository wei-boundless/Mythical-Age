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


def current_followup_append_context_policy(
    base: dict[str, Any],
    *,
    message: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    origin_authority = _origin_authority(
        metadata,
        fallback="runtime.context_management.followup_context_rebase.current_append",
    )
    origin_ref = _origin_ref(base=base, metadata=metadata)
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
        "context_replay_policy": "current_append_commit_on_provider_success_then_next_physical_prefix_frame",
        "context_identity_policy": "origin_ref_stable",
        "context_origin_authority": origin_authority,
        "context_origin_ref": origin_ref,
        "provider_visible_history_status": "current_tool_round_pending_provider_success",
        "provider_visible_history_authority": origin_authority,
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


def current_turn_exact_old_context_policy(
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
                "provider_visible_history_authority": "runtime.context_management.followup_context_rebase.static_prefix",
            },
        }

    origin_authority = _origin_authority(
        metadata,
        fallback="runtime.context_management.followup_context_rebase.current_turn_exact_old_context",
    )
    origin_ref = _origin_ref(base=base, metadata=metadata)
    original_context = {
        key: value
        for key, value in dict(metadata or {}).items()
        if str(key).startswith("context_")
    }
    exact_metadata = {
        **_without_context_classification_metadata(dict(metadata or {})),
        "previous_context_structure": original_context,
        "context_cache_section": CONTEXT_MEMORY_PREFIX,
        "context_semantic_slot": str(dict(metadata or {}).get("context_semantic_slot") or "provider_visible_history"),
        "fixed_context_package": "context_memory_prefix",
        "context_commit_policy": "append_then_seal",
        "context_replay_policy": "current_turn_exact_old_context",
        "context_identity_policy": "origin_ref_stable",
        "context_origin_authority": origin_authority,
        "context_origin_ref": origin_ref,
        "current_turn_exact_old_context": True,
        "current_turn_exact_old_context_reason": "old follow-up base context is already present in the current turn model message prefix",
        "provider_visible_history_status": "current_turn_exact_old_context",
        "provider_visible_history_authority": origin_authority,
        "provider_visible_history_model_message_hash": _stable_model_message_hash(dict(message or {})),
        "cache_impact": "current_turn_exact_old_context_prefix_preserved",
        "stability_rule": (
            "this message was already sent to the provider in an earlier request; "
            "the follow-up path must preserve the exact provider message from the current turn prefix"
        ),
    }
    exact_spec = {
        **dict(base or {}),
        "cache_scope": str(base.get("cache_scope") or original_policy.prefix_cache_scope or "session"),
        "cache_role": str(base.get("cache_role") or original_policy.prefix_cache_role or "session_stable"),
        "prefix_tier": str(base.get("prefix_tier") or original_policy.prefix_tier or "session"),
        "metadata": exact_metadata,
    }
    policy = context_segment_policy_for_spec(exact_spec, default_section=CONTEXT_MEMORY_PREFIX)
    return {
        "cache_scope": str(exact_spec.get("cache_scope") or policy.prefix_cache_scope or "session"),
        "cache_role": str(exact_spec.get("cache_role") or policy.prefix_cache_role or "session_stable"),
        "prefix_tier": str(exact_spec.get("prefix_tier") or policy.prefix_tier or "session"),
        "metadata": {
            **exact_metadata,
            **context_segment_policy_metadata(policy),
            "context_cache_section": CONTEXT_MEMORY_PREFIX,
            "fixed_context_package": "context_memory_prefix",
            "context_replay_policy": "current_turn_exact_old_context",
            "current_turn_exact_old_context": True,
        },
    }


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


def _origin_authority(metadata: dict[str, Any], *, fallback: str) -> str:
    return _first_text(
        dict(metadata or {}).get("context_origin_authority"),
        dict(metadata or {}).get("prefix_origin_authority"),
        dict(metadata or {}).get("origin_authority"),
        dict(metadata or {}).get("provider_visible_history_authority"),
        fallback,
    )


def _origin_ref(*, base: dict[str, Any], metadata: dict[str, Any]) -> str:
    base_payload = dict(base or {})
    meta = dict(metadata or {})
    return _first_text(
        meta.get("context_origin_ref"),
        meta.get("prefix_origin_ref"),
        meta.get("origin_ref"),
        meta.get("stable_origin_ref"),
        meta.get("runtime_context_segment_source_ref"),
        base_payload.get("source_ref"),
        base_payload.get("kind"),
        "current_followup_context",
    )


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stable_model_message_hash(message: dict[str, Any]) -> str:
    normalized = normalize_messages([dict(message or {})])
    payload = normalized[0] if normalized else {"role": "user", "content": ""}
    text = canonical_json(payload)
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()
