from __future__ import annotations

from typing import Any


_AGENT_VISIBLE_DROP_KEYS = {
    "authority",
    "source_authority",
    "origin_authority",
    "prompt_authority",
    "control_schema_authority",
    "context_origin_authority",
    "cache_impact",
    "cache_policy",
    "cache_read_expectation",
    "cache_role",
    "cache_scope",
    "context_cache_section",
    "context_commit_policy",
    "context_identity_policy",
    "context_policy_section",
    "context_prefix_cache_role",
    "context_prefix_cache_scope",
    "context_prefix_lifecycle_state",
    "context_prefix_tier",
    "context_provider_visible_boundary",
    "context_provider_visible_state",
    "context_replay_policy",
    "fixed_context_package",
    "lifecycle_state",
    "memory_commit_policy",
    "physical_lane",
    "physical_prefix_lane",
    "prefix_family",
    "prefix_identity",
    "prefix_policy",
    "prefix_tier",
    "stability_rule",
    "volatility_reason",
    "runtime_fragment_role",
    "runtime_envelope",
    "invocation_kind",
    "turn_id",
    "contract_ref",
    "action_surface_ref",
}

_AGENT_VISIBLE_KEY_REPLACEMENTS = {
    "runtime_context": "request_context",
    "runtime_projection": "request_context",
    "runtime_delta": "current_request_context",
    "runtime_baseline_refs": "stable_context_refs",
    "runtime_memory_context": "selected_memory_context",
    "runtime_observations": "work_observations",
    "turn_input_facts": "request_input_facts",
    "current_turn_context": "current_request_context",
    "current_turn_delta": "current_user_request",
    "turn_state_attention": "current_work_attention",
    "turn_state_attention_context": "current_work_attention_context",
    "turn_contract": "current_action_contract",
    "turn_sequence": "request_sequence",
    "active_turn": "current_work",
    "active_turn_input_policy": "current_work_input_policy",
    "actual_active_turn_id": "active_work_ref",
    "single_lifecycle": "current_request_lifecycle",
    "single_turn_tool_call_boundary": "current_request_tool_call_boundary",
    "single_model_lifecycle": "model_work_lifecycle",
}

_INTERNAL_CONTEXT_LABEL_MARKERS = (
    "context_append",
    "context_memory_prefix",
    "current_dynamic_tail",
    "current_turn_tail",
    "dynamic_tail",
    "global_static_prefix",
    "never_replay_tail",
    "physical_prefix_lane",
    "provider_global_static_prefix",
    "provider_visible_context_prefix",
    "static_prefix",
)

_USER_AUTHORED_TEXT_KEYS = {
    "body",
    "content",
    "description",
    "final_answer",
    "message",
    "query",
    "summary",
    "text",
    "title",
    "user_message",
}


def sanitize_agent_visible_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            key = _agent_visible_key(raw_key)
            if not key:
                continue
            item = _agent_visible_value_for_key(key, sanitize_agent_visible_payload(raw_item))
            if item in (None, "", [], {}):
                continue
            if key in result:
                result[key] = _merge_agent_visible_value(result[key], item)
            else:
                result[key] = item
        return result
    if isinstance(value, list):
        return [
            item
            for item in (sanitize_agent_visible_payload(raw_item) for raw_item in value)
            if item not in (None, "", [], {})
        ]
    if isinstance(value, tuple):
        return [
            item
            for item in (sanitize_agent_visible_payload(raw_item) for raw_item in value)
            if item not in (None, "", [], {})
        ]
    return value


def sanitize_agent_visible_kind(value: str) -> str:
    text = str(value or "").strip() or "context_payload"
    text = text.replace("single_agent_turn", "current_request")
    text = text.replace("current_turn", "current_request")
    text = text.replace("turn_state", "current_work")
    text = text.replace("active_turn", "current_work")
    parts = text.split("_")
    normalized_parts = [
        "request" if part == "turn" else "context" if part == "runtime" else part
        for part in parts
    ]
    return "_".join(normalized_parts) or "context_payload"


def sanitize_agent_visible_title(value: str) -> str:
    text = str(value or "").strip()
    replacements = (
        ("Bound Runtime Context", "Bound Work Context"),
        ("bound runtime context", "bound work context"),
        ("Runtime Context", "Request Context"),
        ("runtime context", "request context"),
        ("Current turn", "Current request"),
        ("Current Turn", "Current Request"),
        ("current turn", "current request"),
        ("Turn State", "Current Work"),
        ("turn state", "current work"),
        ("Turn ", "Current Work "),
        ("turn ", "current work "),
        ("Runtime", "Context"),
        ("runtime", "context"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _agent_visible_key(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or raw in _AGENT_VISIBLE_DROP_KEYS:
        return ""
    if _looks_like_internal_context_metadata_key(raw):
        return ""
    if raw in _AGENT_VISIBLE_KEY_REPLACEMENTS:
        return _AGENT_VISIBLE_KEY_REPLACEMENTS[raw]
    parts = raw.split("_")
    if not parts:
        return raw
    normalized_parts = [
        "request" if part == "turn" else "request" if part == "runtime" else part
        for part in parts
    ]
    return "_".join(normalized_parts)


def _agent_visible_value_for_key(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if _ref_or_source_key(key) and _looks_like_internal_runtime_ref(value):
        return ""
    if not _user_authored_text_key(key) and _contains_internal_context_label(value):
        return ""
    return value


def _looks_like_internal_context_metadata_key(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    if normalized.startswith(("cache_", "context_prefix_", "provider_cache_", "prefix_")):
        return True
    if normalized.endswith(("_cache_role", "_cache_scope", "_prefix_tier", "_prefix_family")):
        return True
    if normalized in {
        "cache",
        "cache_status",
        "context_section",
        "history_policy",
        "lane",
        "memory_source",
        "physical_order",
        "prefix",
        "section",
    }:
        return True
    return False


def _user_authored_text_key(key: str) -> bool:
    normalized = str(key or "").strip()
    return normalized in _USER_AUTHORED_TEXT_KEYS or normalized.endswith(("_text", "_message", "_summary"))


def _contains_internal_context_label(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _INTERNAL_CONTEXT_LABEL_MARKERS)


def _ref_or_source_key(key: str) -> bool:
    normalized = str(key or "").strip()
    return (
        normalized in {"source", "content_source", "policy_source", "request_ref", "context_ref"}
        or normalized.endswith("_ref")
        or normalized.endswith("_refs")
        or normalized.endswith("_id")
        or normalized.endswith("_ids")
    )


def _looks_like_internal_runtime_ref(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    markers = (
        "harness.runtime",
        "runtime.",
        "runtime_",
        "runtime:",
        "turn:",
        "turn-",
        "single_agent_turn",
        "model_turn_action",
        "turn_operating_contract",
        "turn_action_surface",
        "turn_action_transport",
    )
    return any(marker in text for marker in markers)


def _merge_agent_visible_value(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        merged = dict(left)
        for key, value in right.items():
            merged[key] = _merge_agent_visible_value(merged[key], value) if key in merged else value
        return merged
    if isinstance(left, list) and isinstance(right, list):
        return [*left, *right]
    return right
