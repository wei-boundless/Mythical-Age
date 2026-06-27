from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context_envelope import CONTEXT_FRAGMENT_PROTOCOL, render_context_fragment
from .message_specs import build_model_message_spec


@dataclass(frozen=True, slots=True)
class PromptCompositionRuntimeFragment:
    title: str
    payload: dict[str, Any]
    role: str
    kind: str
    source_ref: str
    cache_scope: str
    cache_role: str
    compression_role: str
    visible_kind: str = ""
    preamble: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    prefix: bool = False
    authority: str = "prompt_composition.runtime_fragment"

    def render_content(self) -> str:
        return _join_prompt_fragments(
            self.preamble,
            render_runtime_payload_fragment(
                self.title,
                self.payload,
                role=self.role,
                kind=self.kind,
                visible_kind=self.visible_kind,
                source_ref=self.source_ref,
                cache_scope=self.cache_scope,
                cache_role=self.cache_role,
                compression_role=self.compression_role,
                metadata=self.metadata,
            ),
        )

    def to_message_spec(self) -> dict[str, Any]:
        metadata = {
            **dict(self.metadata),
            "runtime_fragment_title": str(self.title or "").strip(),
            "runtime_fragment_payload_keys": sorted(str(key) for key in self.payload),
            "runtime_fragment_authority": self.authority,
            "context_fragment_protocol": CONTEXT_FRAGMENT_PROTOCOL,
            "context_fragment_kind": str(self.kind or "").strip(),
            "context_fragment_visible_kind": str(self.visible_kind or self.kind or "").strip(),
            "context_fragment_title": str(self.title or "").strip(),
        }
        return build_model_message_spec(
            role=self.role,
            content=self.render_content(),
            kind=self.kind,
            source_ref=self.source_ref,
            cache_scope=self.cache_scope,
            cache_role=self.cache_role,
            compression_role=self.compression_role,
            metadata=metadata,
            prefix=self.prefix,
        )


def render_runtime_payload_fragment(
    title: str,
    payload: dict[str, Any],
    *,
    role: str = "",
    kind: str = "",
    visible_kind: str = "",
    source_ref: str = "",
    cache_scope: str = "",
    cache_role: str = "",
    compression_role: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    return render_context_fragment(
        kind=visible_kind or kind or "runtime_payload",
        title=title,
        payload=dict(payload or {}),
        role=role,
        source_ref=source_ref,
        cache_scope=cache_scope,
        cache_role=cache_role,
        prefix_tier=_prefix_tier(cache_scope=cache_scope, cache_role=cache_role),
        compression_role=compression_role,
        validity_scope=_validity_scope(metadata),
    )


def build_runtime_payload_message_spec(
    *,
    title: str,
    payload: dict[str, Any],
    role: str,
    kind: str,
    source_ref: str,
    cache_scope: str,
    cache_role: str,
    compression_role: str,
    visible_kind: str = "",
    preamble: str = "",
    metadata: dict[str, Any] | None = None,
    prefix: bool = False,
) -> dict[str, Any]:
    return PromptCompositionRuntimeFragment(
        title=title,
        payload=dict(payload or {}),
        role=role,
        kind=kind,
        visible_kind=visible_kind,
        source_ref=source_ref,
        cache_scope=cache_scope,
        cache_role=cache_role,
        compression_role=compression_role,
        preamble=preamble,
        metadata=dict(metadata or {}),
        prefix=prefix,
    ).to_message_spec()


def _join_prompt_fragments(*fragments: str) -> str:
    return "\n".join(str(fragment or "").strip() for fragment in fragments if str(fragment or "").strip()) + "\n"


def _prefix_tier(*, cache_scope: str, cache_role: str) -> str:
    normalized_role = str(cache_role or "").strip()
    normalized_scope = str(cache_scope or "").strip()
    if normalized_role == "cacheable_prefix":
        return "provider_global"
    if normalized_role == "session_stable":
        if normalized_scope == "global":
            return "provider_global"
        if normalized_scope == "task":
            return "task"
        return "session"
    if normalized_role == "volatile":
        return "volatile"
    if normalized_role == "never_cache":
        return "none"
    return ""


def _validity_scope(metadata: dict[str, Any] | None) -> str:
    payload = dict(metadata or {})
    for key in ("validity_scope", "context_validity_scope", "runtime_validity_scope"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""
