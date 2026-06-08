from __future__ import annotations

from typing import Any

from .models import PromptCompositionContentFragment


def build_content_fragments_from_model_messages(
    *,
    segment_plan: Any,
    model_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[PromptCompositionContentFragment, ...]:
    segment_payloads = _segment_payloads(segment_plan)
    messages = [dict(item) for item in list(model_messages or []) if isinstance(item, dict)]
    fragments: list[PromptCompositionContentFragment] = []
    for segment in segment_payloads:
        message_index = _int_or_default(segment.get("model_message_index"), default=-1)
        if message_index < 0 or message_index >= len(messages):
            continue
        message = dict(messages[message_index])
        metadata = dict(segment.get("metadata") or {}) if isinstance(segment.get("metadata"), dict) else {}
        fragments.append(
            PromptCompositionContentFragment(
                segment_id=str(segment.get("segment_id") or ""),
                kind=str(segment.get("kind") or ""),
                source_ref=str(segment.get("source_ref") or ""),
                ordinal=_int_or_default(segment.get("ordinal"), default=0),
                model_message_index=message_index,
                model_message_role=str(message.get("role") or segment.get("model_message_role") or "user"),
                content_hash=str(segment.get("content_hash") or ""),
                model_message_hash=str(segment.get("model_message_hash") or ""),
                model_message=message,
                content_source=str(metadata.get("content_source") or "runtime_sanitized_model_message"),
                materialized_from="sanitized_model_message",
            )
        )
    return tuple(fragments)


def build_content_fragments_from_message_specs(
    *,
    segment_plan: Any,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    fallback_model_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> tuple[PromptCompositionContentFragment, ...]:
    segment_payloads = _segment_payloads(segment_plan)
    specs = [dict(item) for item in list(message_specs or []) if isinstance(item, dict)]
    fallback_messages = [dict(item) for item in list(fallback_model_messages or []) if isinstance(item, dict)]
    fragments: list[PromptCompositionContentFragment] = []
    for segment in segment_payloads:
        message_index = _int_or_default(segment.get("model_message_index"), default=-1)
        if message_index < 0:
            continue
        metadata = dict(segment.get("metadata") or {}) if isinstance(segment.get("metadata"), dict) else {}
        content_source = str(metadata.get("content_source") or "runtime_sanitized_model_message")
        spec_message = _message_from_spec(specs[message_index]) if message_index < len(specs) else {}
        fallback_message = dict(fallback_messages[message_index]) if message_index < len(fallback_messages) else {}
        if spec_message and _prefer_message_spec_source(content_source):
            message = spec_message
            materialized_from = "message_spec"
        elif fallback_message:
            message = fallback_message
            materialized_from = "sanitized_model_message"
        elif spec_message:
            message = spec_message
            materialized_from = "message_spec"
        else:
            continue
        fragments.append(
            PromptCompositionContentFragment(
                segment_id=str(segment.get("segment_id") or ""),
                kind=str(segment.get("kind") or ""),
                source_ref=str(segment.get("source_ref") or ""),
                ordinal=_int_or_default(segment.get("ordinal"), default=0),
                model_message_index=message_index,
                model_message_role=str(message.get("role") or segment.get("model_message_role") or "user"),
                content_hash=str(segment.get("content_hash") or ""),
                model_message_hash=str(segment.get("model_message_hash") or ""),
                model_message=message,
                content_source=content_source,
                materialized_from=materialized_from,
            )
        )
    return tuple(fragments)


def _message_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    model_message = spec.get("model_message")
    if isinstance(model_message, dict) and model_message:
        return dict(model_message)
    return {
        "role": str(spec.get("role") or "user"),
        "content": str(spec.get("content") or ""),
    }


def _prefer_message_spec_source(content_source: str) -> bool:
    normalized = str(content_source or "")
    if normalized == "runtime.provider_protocol_replay":
        return False
    return (
        normalized.startswith("prompt_assembly.")
        or normalized.startswith("prompt_composition.section_renderer.")
        or normalized.startswith("runtime.")
    )


def _segment_payloads(segment_plan: Any) -> list[dict[str, Any]]:
    if hasattr(segment_plan, "segments"):
        return [
            segment.to_dict() if hasattr(segment, "to_dict") else dict(segment)
            for segment in tuple(getattr(segment_plan, "segments", ()) or ())
            if hasattr(segment, "to_dict") or isinstance(segment, dict)
        ]
    if hasattr(segment_plan, "to_dict"):
        payload = segment_plan.to_dict()
    else:
        payload = dict(segment_plan or {})
    return [dict(item) for item in list(payload.get("segments") or []) if isinstance(item, dict)]


def _int_or_default(value: Any, *, default: int) -> int:
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return int(default)
