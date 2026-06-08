from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

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
    preamble: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    prefix: bool = False
    authority: str = "prompt_composition.runtime_fragment"

    def render_content(self) -> str:
        return _join_prompt_fragments(self.preamble, render_runtime_payload_fragment(self.title, self.payload))

    def to_message_spec(self) -> dict[str, Any]:
        metadata = {
            "runtime_fragment_title": str(self.title or "").strip(),
            "runtime_fragment_payload_keys": sorted(str(key) for key in self.payload),
            "runtime_fragment_authority": self.authority,
            **dict(self.metadata),
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


def render_runtime_payload_fragment(title: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{str(title or '').strip()}\n{body}"


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
    preamble: str = "",
    metadata: dict[str, Any] | None = None,
    prefix: bool = False,
) -> dict[str, Any]:
    return PromptCompositionRuntimeFragment(
        title=title,
        payload=dict(payload or {}),
        role=role,
        kind=kind,
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
