from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .message_specs import message_spec_content_source
from .tracing import runtime_source_kind_for_segment


@dataclass(frozen=True, slots=True)
class PromptSource:
    source_id: str
    invocation_kind: str
    packet_id: str
    source_order: int
    kind: str
    role: str
    source_kind: str
    source_ref: str = ""
    cache_scope: str = "none"
    cache_role: str = "volatile"
    prefix_tier: str = ""
    compression_role: str = "summarize"
    content_hash: str = ""
    model_message_hash: str = ""
    message_spec: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.source_bundle.source"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["message_spec"] = dict(self.message_spec)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptSourceBundle:
    bundle_id: str
    invocation_kind: str
    packet_id: str
    sources: tuple[PromptSource, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.source_bundle"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "invocation_kind": self.invocation_kind,
            "packet_id": self.packet_id,
            "sources": [source.to_dict() for source in self.sources],
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


def build_prompt_source_bundle(
    *,
    invocation_kind: str,
    packet_id: str,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> PromptSourceBundle:
    sources: list[PromptSource] = []
    for index, raw_spec in enumerate(tuple(message_specs or ()), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = _normalized_spec(raw_spec)
        if not _has_model_message_payload(spec):
            continue
        kind = str(spec.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
        role = str(spec.get("role") or "user").strip() or "user"
        source_ref = str(spec.get("source_ref") or "")
        content = str(spec.get("content") or "")
        model_message = dict(spec.get("model_message") or {"role": role, "content": content})
        content_hash = _stable_text_hash(content)
        model_message_hash = _stable_text_hash(_stable_json(model_message))
        source_kind = runtime_source_kind_for_segment(spec)
        source_id = _source_id(
            invocation_kind=invocation_kind,
            packet_id=packet_id,
            source_order=index,
            kind=kind,
            source_kind=source_kind,
            source_ref=source_ref,
            content_hash=content_hash,
            model_message_hash=model_message_hash,
        )
        metadata = dict(spec.get("metadata") or {})
        metadata.setdefault(
            "content_source",
            message_spec_content_source(
                kind=kind,
                cache_role=str(spec.get("cache_role") or "volatile"),
                source_ref=source_ref,
            ),
        )
        sources.append(
            PromptSource(
                source_id=source_id,
                invocation_kind=str(invocation_kind or ""),
                packet_id=str(packet_id or ""),
                source_order=index,
                kind=kind,
                role=role,
                source_kind=source_kind,
                source_ref=source_ref,
                cache_scope=str(spec.get("cache_scope") or "none"),
                cache_role=str(spec.get("cache_role") or "volatile"),
                prefix_tier=str(spec.get("prefix_tier") or ""),
                compression_role=str(spec.get("compression_role") or "summarize"),
                content_hash=content_hash,
                model_message_hash=model_message_hash,
                message_spec={**spec, "metadata": metadata},
                metadata=metadata,
            )
        )
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "packet_id": str(packet_id or ""),
        "sources": [
            {
                "source_id": source.source_id,
                "order": source.source_order,
                "kind": source.kind,
                "source_kind": source.source_kind,
                "source_ref": source.source_ref,
                "content_hash": source.content_hash,
                "model_message_hash": source.model_message_hash,
            }
            for source in sources
        ],
    }
    return PromptSourceBundle(
        bundle_id="psbundle:" + _stable_hash(seed)[:16],
        invocation_kind=str(invocation_kind or ""),
        packet_id=str(packet_id or ""),
        sources=tuple(sources),
        diagnostics={
            "source_count": len(sources),
            "source_kind_counts": _count_by(sources, "source_kind"),
            "kind_counts": _count_by(sources, "kind"),
            "cache_role_counts": _count_by(sources, "cache_role"),
            "authority": "prompt_composition.source_bundle.builder",
        },
    )


def _normalized_spec(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    payload["role"] = str(payload.get("role") or "user").strip() or "user"
    payload["content"] = str(payload.get("content") or "")
    payload["kind"] = str(payload.get("kind") or "unknown_unplanned")
    payload["source_ref"] = str(payload.get("source_ref") or "")
    payload["cache_scope"] = str(payload.get("cache_scope") or "none")
    payload["cache_role"] = str(payload.get("cache_role") or "volatile")
    payload["compression_role"] = str(payload.get("compression_role") or "summarize")
    payload["metadata"] = dict(payload.get("metadata") or {})
    if isinstance(payload.get("model_message"), dict):
        payload["model_message"] = dict(payload.get("model_message") or {})
    return payload


def _has_model_message_payload(spec: dict[str, Any]) -> bool:
    model_message = dict(spec.get("model_message") or spec)
    role = str(model_message.get("role") or spec.get("role") or "")
    if role == "assistant" and (model_message.get("tool_calls") or model_message.get("reasoning_content")):
        return True
    if role == "tool" and model_message.get("tool_call_id"):
        return True
    return bool(str(model_message.get("content") or spec.get("content") or "").strip())


def _source_id(
    *,
    invocation_kind: str,
    packet_id: str,
    source_order: int,
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
            "source_order": source_order,
            "kind": kind,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "content_hash": content_hash,
            "model_message_hash": model_message_hash,
        }
    )[:12]
    return f"psource:{invocation_kind}:{source_order}:{kind}:{digest}"


def _count_by(sources: list[PromptSource], field_name: str) -> dict[str, int]:
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
