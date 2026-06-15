from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import RuntimePromptSource, RuntimePromptSourceManifest
from .tracing import runtime_source_kind_for_segment


def build_runtime_prompt_source_manifest(
    *,
    invocation_kind: str,
    packet_id: str,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> RuntimePromptSourceManifest:
    sources: list[RuntimePromptSource] = []
    for index, raw_spec in enumerate(tuple(message_specs or ()), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = _normalized_spec(raw_spec)
        model_message = dict(spec.get("model_message") or {"role": spec.get("role"), "content": spec.get("content")})
        content_hash = _stable_text_hash(str(spec.get("content") or ""))
        model_message_hash = _stable_text_hash(_stable_json(model_message))
        kind = str(spec.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
        source_kind = runtime_source_kind_for_segment(spec)
        source_ref = str(spec.get("source_ref") or "")
        source_id = _source_id(
            invocation_kind=invocation_kind,
            packet_id=packet_id,
            order=index,
            kind=kind,
            source_kind=source_kind,
            source_ref=source_ref,
            content_hash=content_hash,
            model_message_hash=model_message_hash,
        )
        sources.append(
            RuntimePromptSource(
                source_id=source_id,
                invocation_kind=str(invocation_kind or ""),
                packet_id=str(packet_id or ""),
                order=index,
                kind=kind,
                role=str(spec.get("role") or "user"),
                source_kind=source_kind,
                source_ref=source_ref,
                cache_scope=str(spec.get("cache_scope") or "none"),
                cache_role=str(spec.get("cache_role") or "volatile"),
                compression_role=str(spec.get("compression_role") or "summarize"),
                content_hash=content_hash,
                model_message_hash=model_message_hash,
                message_spec=spec,
                metadata={
                    "source_metadata": dict(spec.get("metadata") or {}),
                    "content_source": str(dict(spec.get("metadata") or {}).get("content_source") or ""),
                },
            )
        )
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "packet_id": str(packet_id or ""),
        "sources": [
            {
                "source_id": source.source_id,
                "order": source.order,
                "kind": source.kind,
                "source_kind": source.source_kind,
                "source_ref": source.source_ref,
                "content_hash": source.content_hash,
                "model_message_hash": source.model_message_hash,
            }
            for source in sources
        ],
    }
    return RuntimePromptSourceManifest(
        manifest_id="rtpromptsources:" + _stable_hash(seed)[:16],
        invocation_kind=str(invocation_kind or ""),
        packet_id=str(packet_id or ""),
        sources=tuple(sources),
        diagnostics={
            "source_count": len(sources),
            "source_kind_counts": _count_by(sources, "source_kind"),
            "kind_counts": _count_by(sources, "kind"),
            "cache_role_counts": _count_by(sources, "cache_role"),
            "authority": "prompt_composition.runtime_sources.builder",
        },
    )


def materialize_runtime_prompt_sources(source_manifest: RuntimePromptSourceManifest) -> tuple[dict[str, Any], ...]:
    specs: list[dict[str, Any]] = []
    for source in tuple(source_manifest.sources or ()):
        spec = dict(source.message_spec or {})
        metadata = dict(spec.get("metadata") or {})
        metadata.update(
            {
                "runtime_prompt_source_manifest_id": source_manifest.manifest_id,
                "runtime_prompt_source_id": source.source_id,
                "runtime_prompt_source_kind": source.source_kind,
                "runtime_prompt_source_order": source.order,
                "runtime_prompt_source_content_hash": source.content_hash,
                "runtime_prompt_source_model_message_hash": source.model_message_hash,
                "runtime_prompt_source_materialized_by": "prompt_composition.runtime_sources.materializer",
            }
        )
        spec["metadata"] = metadata
        specs.append(spec)
    return tuple(specs)


def _normalized_spec(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    payload["role"] = str(payload.get("role") or "user")
    payload["content"] = str(payload.get("content") or "")
    payload["kind"] = str(payload.get("kind") or "unknown_unplanned")
    payload["metadata"] = dict(payload.get("metadata") or {})
    if isinstance(payload.get("model_message"), dict):
        payload["model_message"] = dict(payload.get("model_message") or {})
    return payload


def _source_id(
    *,
    invocation_kind: str,
    packet_id: str,
    order: int,
    kind: str,
    source_kind: str,
    source_ref: str,
    content_hash: str,
    model_message_hash: str,
) -> str:
    digest = _stable_hash(
        {
            "invocation_kind": invocation_kind,
            "packet_id": packet_id,
            "order": order,
            "kind": kind,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "content_hash": content_hash,
            "model_message_hash": model_message_hash,
        }
    )[:12]
    return f"rtpromptsource:{invocation_kind}:{order}:{kind}:{digest}"


def _count_by(sources: list[RuntimePromptSource], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        key = str(getattr(source, field_name, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stable_text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
