from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptCompositionRenderResult:
    messages: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.message_projection_renderer"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["messages"] = [dict(item) for item in self.messages]
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def render_model_messages_from_projection(
    *,
    manifest: Any,
    content_fragments: list[Any] | tuple[Any, ...] = (),
    source_messages: list[Any] | tuple[Any, ...] = (),
) -> PromptCompositionRenderResult:
    manifest_payload = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest or {})
    projection = [
        dict(item)
        for item in list(manifest_payload.get("message_projection") or [])
        if isinstance(item, dict)
    ]
    fragments = [
        _content_fragment_payload(item)
        for item in list(content_fragments or [])
    ]
    fragment_by_segment_id = {
        str(item.get("segment_id") or ""): item
        for item in fragments
        if str(item.get("segment_id") or "")
    }
    fragment_source_counts: dict[str, int] = {}
    fragment_materialized_counts: dict[str, int] = {}
    for fragment in fragments:
        source = str(fragment.get("content_source") or "unknown")
        fragment_source_counts[source] = fragment_source_counts.get(source, 0) + 1
        materialized_from = str(fragment.get("materialized_from") or "unknown")
        fragment_materialized_counts[materialized_from] = fragment_materialized_counts.get(materialized_from, 0) + 1
    source = [dict(item) if isinstance(item, dict) else {"role": getattr(item, "role", ""), "content": getattr(item, "content", item)} for item in list(source_messages or [])]
    rendered: list[dict[str, Any]] = []
    hash_mismatches: list[dict[str, Any]] = []
    content_hash_mismatches: list[dict[str, Any]] = []
    missing_indexes: list[int] = []
    missing_fragment_segment_ids: list[str] = []
    rendered_from_fragments = 0
    for item in sorted(projection, key=lambda payload: int(payload.get("ordinal") or 0)):
        segment_id = str(item.get("segment_id") or "")
        message_index = _int(item.get("model_message_index"), default=-1)
        fragment = fragment_by_segment_id.get(segment_id)
        if fragment is not None:
            message = _model_message_from_fragment(fragment, fallback_role=str(item.get("model_message_role") or "user"))
            rendered_from_fragments += 1
        else:
            missing_fragment_segment_ids.append(segment_id)
            if message_index < 0 or message_index >= len(source):
                missing_indexes.append(message_index)
            continue
        rendered.append(message)
        expected_content_hash = str(item.get("content_hash") or "")
        actual_content_hash = _stable_text_hash(str(message.get("content") or ""))
        if expected_content_hash and expected_content_hash != actual_content_hash:
            content_hash_mismatches.append(
                {
                    "segment_id": segment_id,
                    "kind": str(item.get("kind") or ""),
                    "model_message_index": message_index,
                    "expected_content_hash": expected_content_hash,
                    "actual_content_hash": actual_content_hash,
                }
            )
        expected_hash = str(item.get("model_message_hash") or "")
        actual_hash = _stable_text_hash(_canonical_json(message))
        if expected_hash and expected_hash != actual_hash:
            hash_mismatches.append(
                {
                    "segment_id": segment_id,
                    "kind": str(item.get("kind") or ""),
                    "model_message_index": message_index,
                    "expected_model_message_hash": expected_hash,
                    "actual_model_message_hash": actual_hash,
                }
            )
    fallback_reason = ""
    if missing_fragment_segment_ids:
        fallback_reason = "content_fragment_incomplete"
    elif missing_indexes:
        fallback_reason = "message_projection_incomplete"
    return PromptCompositionRenderResult(
        messages=tuple(rendered),
        diagnostics={
            "renderer": "prompt_composition.message_projection",
            "manifest_ref": str(manifest_payload.get("manifest_id") or ""),
            "projection_message_count": len(projection),
            "content_fragment_count": len(fragments),
            "content_fragment_source_counts": fragment_source_counts,
            "content_fragment_materialized_from_counts": fragment_materialized_counts,
            "source_message_count": len(source),
            "rendered_message_count": len(rendered),
            "rendered_from_content_fragment_count": rendered_from_fragments,
            "source_message_fallback_count": 0,
            "renderer_fallback_to_source_messages": False,
            "fallback_reason": fallback_reason,
            "missing_content_fragment_segment_ids": missing_fragment_segment_ids[:20],
            "missing_source_message_indexes": missing_indexes,
            "content_hash_mismatch_count": len(content_hash_mismatches),
            "content_hash_mismatch_samples": content_hash_mismatches[:5],
            "hash_mismatch_count": len(hash_mismatches),
            "hash_mismatch_samples": hash_mismatches[:5],
            "rendered_message_hash_sequence": [_stable_text_hash(_canonical_json(item)) for item in rendered],
            "authority": "prompt_composition.message_projection_renderer",
        },
    )


def _content_fragment_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    payload = {
        "segment_id": getattr(value, "segment_id", ""),
        "kind": getattr(value, "kind", ""),
        "source_ref": getattr(value, "source_ref", ""),
        "ordinal": getattr(value, "ordinal", 0),
        "model_message_index": getattr(value, "model_message_index", 0),
        "model_message_role": getattr(value, "model_message_role", ""),
        "content_hash": getattr(value, "content_hash", ""),
        "model_message_hash": getattr(value, "model_message_hash", ""),
        "content_source": getattr(value, "content_source", ""),
        "materialized_from": getattr(value, "materialized_from", ""),
        "model_message": getattr(value, "model_message", {}),
    }
    return payload


def _model_message_from_fragment(fragment: dict[str, Any], *, fallback_role: str) -> dict[str, Any]:
    message = fragment.get("model_message")
    if isinstance(message, dict) and message:
        return dict(message)
    return {
        "role": str(fragment.get("model_message_role") or fallback_role or "user"),
        "content": str(fragment.get("content") or ""),
    }


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stable_text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
