from __future__ import annotations

from typing import Any

from context_system.segments.declarations import context_segment_kind_content_source


def build_model_message_spec(
    *,
    role: str,
    content: str,
    kind: str,
    source_ref: str,
    cache_scope: str,
    cache_role: str,
    compression_role: str,
    metadata: dict[str, Any] | None = None,
    prefix: bool = False,
) -> dict[str, Any]:
    normalized_kind = str(kind or "unknown_unplanned")
    normalized_cache_role = str(cache_role or "volatile")
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault(
        "content_source",
        message_spec_content_source(
            kind=normalized_kind,
            cache_role=normalized_cache_role,
            source_ref=str(source_ref or ""),
        ),
    )
    payload = {
        "role": str(role or "user"),
        "content": str(content or ""),
        "kind": normalized_kind,
        "source_ref": str(source_ref or ""),
        "cache_scope": str(cache_scope or "none"),
        "cache_role": normalized_cache_role,
        "compression_role": str(compression_role or "summarize"),
        "metadata": payload_metadata,
    }
    if prefix:
        payload_metadata.setdefault("assistant_completion_prefix", True)
        payload_metadata.setdefault("completion_prefix_role", "provider_chat_prefix_completion")
        payload["prefix"] = True
    return payload


def message_spec_content_source(*, kind: str, cache_role: str, source_ref: str) -> str:
    normalized_kind = str(kind or "").strip()
    declared_source = context_segment_kind_content_source(normalized_kind)
    if declared_source:
        return declared_source
    if str(cache_role or "") in {"volatile", "never_cache"}:
        return "runtime.dynamic_context_fragment"
    if str(source_ref or "").strip():
        return "runtime.stable_boundary"
    return "runtime_sanitized_model_message"
