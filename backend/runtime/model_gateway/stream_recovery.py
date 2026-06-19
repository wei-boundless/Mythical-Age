from __future__ import annotations

from dataclasses import is_dataclass, replace
from types import SimpleNamespace
from typing import Any

from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from runtime.model_gateway.model_runtime import ModelRuntimeError, stringify_content
from runtime.model_gateway.protocol_sanitizer import sanitize_messages_for_prompt
from runtime.output_boundary import (
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)


VISIBLE_PREFIX_RECOVERY_MODE = "continue_from_visible_prefix"
VISIBLE_PREFIX_RECOVERY_PROFILE_SOURCE = "partial_stream_recovery"
VISIBLE_PREFIX_RECOVERY_DEFAULT_ATTEMPTS = 2


def should_recover_partial_visible_stream(
    stream_policy: dict[str, Any],
    *,
    raw_content: str,
    emit_assistant_text_delta: bool,
    require_json_action: bool,
    error: Exception,
) -> bool:
    policy = dict(stream_policy or {})
    if policy.get("upstream_reconnect_enabled") is False:
        return False
    if str(policy.get("partial_stream_recovery") or VISIBLE_PREFIX_RECOVERY_MODE).strip().lower() in {"", "disabled", "off", "false"}:
        return False
    if require_json_action or not emit_assistant_text_delta:
        return False
    if not meaningful_visible_answer(raw_content):
        return False
    if isinstance(error, ModelRuntimeError):
        return bool(error.retryable)
    return True


def build_visible_prefix_recovery_messages(
    model_messages: list[Any],
    *,
    visible_prefix: str,
    turn_id: str = "",
    source: str = VISIBLE_PREFIX_RECOVERY_PROFILE_SOURCE,
) -> list[dict[str, Any]]:
    prefix = str(visible_prefix or "")
    instruction = (
        "上一条助手回复的模型流在网络层中断。下面这段文字已经公开显示给用户：\n\n"
        f"{prefix}\n\n"
        "你仍然是同一个助手，继续完成同一条回复。"
        "不要重复已经公开的文字，不要从头改写，不要解释网络错误。"
        "从断点之后直接续写用户应当看到的正文。"
    )
    prefix_message = {
        "role": "assistant",
        "content": prefix,
        "turn_id": str(turn_id or ""),
        "prefix": True,
        "additional_kwargs": {"prefix": True},
    }
    messages = [
        *_normalize_recovery_input_messages(model_messages),
        {"role": "system", "content": instruction, "turn_id": str(turn_id or "")},
        prefix_message,
    ]
    return [
        dict(item)
        for item in sanitize_messages_for_prompt(
            messages,
            turn_id=str(turn_id or ""),
            source=str(source or VISIBLE_PREFIX_RECOVERY_PROFILE_SOURCE),
        ).messages
    ]


def build_visible_prefix_recovery_segment_plan(
    *,
    base_segment_plan: dict[str, Any],
    recovery_messages: list[dict[str, Any]],
    packet_id: str,
    recovery_attempt: int,
    source: str = VISIBLE_PREFIX_RECOVERY_PROFILE_SOURCE,
) -> dict[str, Any]:
    base_segments = _base_segments_by_message_index(base_segment_plan)
    specs: list[dict[str, Any]] = []
    last_base_index = max(base_segments) if base_segments else -1
    for index, message in enumerate([dict(item) for item in list(recovery_messages or []) if isinstance(item, dict)]):
        base = dict(base_segments.get(index) or {})
        if base:
            specs.append(
                {
                    "role": str(message.get("role") or "user"),
                    "content": str(message.get("content") or ""),
                    "kind": str(base.get("kind") or "visible_prefix_recovery_base"),
                    "source_ref": str(base.get("source_ref") or base.get("source") or "visible_prefix_recovery_base"),
                    "cache_scope": str(base.get("cache_scope") or "none"),
                    "cache_role": str(base.get("cache_role") or "volatile"),
                    "prefix_tier": str(base.get("prefix_tier") or "volatile"),
                    "compression_role": str(base.get("compression_role") or "summarize"),
                    "metadata": dict(base.get("metadata") or {}),
                    "model_message": dict(message),
                }
            )
            continue
        specs.append(
            _visible_prefix_recovery_message_spec(
                message,
                recovery_attempt=recovery_attempt,
                source=source,
                suffix_index=max(1, index - last_base_index),
            )
        )
    return build_prompt_segment_plan(
        packet_id=f"{packet_id}:partial-stream-recovery:{max(1, int(recovery_attempt or 1))}",
        invocation_kind="visible_prefix_stream_recovery",
        message_specs=specs,
    ).to_dict()


def model_selection_for_visible_prefix_recovery(
    model_selection: Any,
    *,
    source: str = VISIBLE_PREFIX_RECOVERY_PROFILE_SOURCE,
) -> Any:
    profile_source = str(source or VISIBLE_PREFIX_RECOVERY_PROFILE_SOURCE)
    if model_selection is None or isinstance(model_selection, dict):
        selection = dict(model_selection or {})
        selection.pop("structured_output", None)
        selection.pop("response_format", None)
        completion_profile = dict(selection.get("completion_profile") or {})
        completion_profile.setdefault("mode", "chat_prefix")
        completion_profile.setdefault("provider_mode", "deepseek_chat_prefix")
        completion_profile.setdefault("source", profile_source)
        selection["completion_profile"] = completion_profile
        stream_policy = dict(selection.get("stream_policy") or {})
        stream_policy["enabled"] = False
        selection["stream_policy"] = stream_policy
        return selection

    completion_profile = dict(getattr(model_selection, "completion_profile", {}) or {})
    completion_profile.setdefault("mode", "chat_prefix")
    completion_profile.setdefault("provider_mode", "deepseek_chat_prefix")
    completion_profile.setdefault("source", profile_source)
    stream_policy = dict(getattr(model_selection, "stream_policy", {}) or {})
    stream_policy["enabled"] = False
    updates = {
        "completion_profile": completion_profile,
        "stream_policy": stream_policy,
        "response_format": None,
        "structured_output": None,
    }
    if is_dataclass(model_selection):
        try:
            return replace(model_selection, **updates)
        except TypeError:
            pass
    payload = {
        key: getattr(model_selection, key)
        for key in (
            "provider",
            "model",
            "api_key",
            "base_url",
            "max_output_tokens",
            "timeout_seconds",
            "long_output_timeout_seconds",
            "max_retries",
            "temperature",
            "thinking_mode",
            "reasoning_effort",
            "provider_extensions",
            "source_chain",
            "diagnostics",
        )
        if hasattr(model_selection, key)
    }
    payload.update(updates)
    return SimpleNamespace(**payload)


def recovery_attempts_from_policy(stream_policy: dict[str, Any], *, default: int = VISIBLE_PREFIX_RECOVERY_DEFAULT_ATTEMPTS) -> int:
    try:
        attempts = int(dict(stream_policy or {}).get("partial_stream_recovery_attempts") or default)
    except (TypeError, ValueError):
        attempts = int(default)
    return max(1, attempts)


def continuation_after_visible_prefix(visible_prefix: str, recovered_text: str) -> str:
    prefix = str(visible_prefix or "")
    recovered = str(recovered_text or "")
    if not recovered:
        return ""
    if recovered.startswith(prefix):
        return recovered[len(prefix):]
    max_overlap = min(len(prefix), len(recovered))
    for overlap in range(max_overlap, 0, -1):
        if prefix.endswith(recovered[:overlap]):
            return recovered[overlap:]
    return recovered


def stream_error_code(error: Exception) -> str:
    if isinstance(error, ModelRuntimeError):
        return str(error.code or "model_stream_error")
    return error.__class__.__name__ or "model_stream_error"


def meaningful_visible_answer(content: str) -> bool:
    visible = sanitize_visible_assistant_content(str(content or "")).strip()
    if not visible:
        return False
    if visible in {">", "<", "...", "…", "---", "----"}:
        return False
    if contains_internal_protocol(visible) or contains_inline_pseudo_tool_call(visible):
        return False
    return any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in visible)


def visible_prefix_utf8_bytes(value: str) -> int:
    return len(str(value or "").encode("utf-8"))


def _normalize_recovery_input_messages(messages: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in list(messages or []):
        item = _message_to_recovery_dict(message)
        if item:
            normalized.append(item)
    return normalized


def _base_segments_by_message_index(segment_plan: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for segment in list(dict(segment_plan or {}).get("segments") or []):
        if not isinstance(segment, dict):
            continue
        try:
            index = int(segment.get("model_message_index"))
        except (TypeError, ValueError):
            continue
        if index >= 0:
            result[index] = dict(segment)
    return result


def _visible_prefix_recovery_message_spec(
    message: dict[str, Any],
    *,
    recovery_attempt: int,
    source: str,
    suffix_index: int,
) -> dict[str, Any]:
    role = str(message.get("role") or "user")
    is_assistant_prefix = role == "assistant" and bool(message.get("prefix") is True)
    kind = "partial_stream_recovery_visible_prefix" if is_assistant_prefix else "partial_stream_recovery_instruction"
    return {
        "role": role,
        "content": str(message.get("content") or ""),
        "kind": kind,
        "source_ref": f"{source}:{max(1, int(recovery_attempt or 1))}:{max(1, int(suffix_index or 1))}",
        "cache_scope": "none",
        "cache_role": "volatile",
        "prefix_tier": "volatile",
        "compression_role": "preserve" if is_assistant_prefix else "summarize",
        "metadata": {
            "recovery_attempt": max(1, int(recovery_attempt or 1)),
            "visible_prefix_recovery": True,
            "volatility_reason": "partial stream recovery appends current visible prefix state and must remain outside the cacheable prefix",
            **(
                {
                    "completion_mode": "chat_prefix",
                    "provider_protocol": "deepseek_chat_prefix_completion",
                }
                if is_assistant_prefix
                else {}
            ),
        },
    }


def _message_to_recovery_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        item = dict(message)
        role = _normalize_role(item.get("role") or item.get("type"))
        if not role:
            return {}
        item["role"] = role
        item["content"] = stringify_content(item.get("content") or "")
        return item

    role = _normalize_role(getattr(message, "role", "") or getattr(message, "type", ""))
    if not role:
        return {}
    item: dict[str, Any] = {
        "role": role,
        "content": stringify_content(getattr(message, "content", "") or ""),
    }
    for key in ("name", "tool_call_id", "turn_id"):
        value = str(getattr(message, key, "") or "").strip()
        if value:
            item[key] = value
    if role == "assistant":
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            item["additional_kwargs"] = dict(additional_kwargs)
        tool_calls = getattr(message, "tool_calls", None)
        if isinstance(tool_calls, (list, tuple)):
            item["tool_calls"] = [dict(call) for call in tool_calls if isinstance(call, dict)]
    return item


def _normalize_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role in {"human"}:
        return "user"
    if role in {"ai", "model"}:
        return "assistant"
    if role in {"system", "user", "assistant", "tool"}:
        return role
    return ""
