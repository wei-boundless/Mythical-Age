from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import PromptAssemblyResult


@dataclass(frozen=True, slots=True)
class RuntimePromptManifest:
    manifest_id: str
    invocation_kind: str
    prompt_pack_refs: tuple[str, ...] = ()
    stable_prompt_refs: tuple[str, ...] = ()
    stable_contract_refs: tuple[str, ...] = ()
    rejected_refs: tuple[dict[str, Any], ...] = ()
    dynamic_projection_refs: tuple[str, ...] = ()
    volatile_state_refs: tuple[str, ...] = ()
    cache_boundary: dict[str, Any] = field(default_factory=dict)
    token_estimate: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_manifest"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prompt_pack_refs"] = list(self.prompt_pack_refs)
        payload["stable_prompt_refs"] = list(self.stable_prompt_refs)
        payload["stable_contract_refs"] = list(self.stable_contract_refs)
        payload["rejected_refs"] = [dict(item) for item in self.rejected_refs]
        payload["dynamic_projection_refs"] = list(self.dynamic_projection_refs)
        payload["volatile_state_refs"] = list(self.volatile_state_refs)
        payload["cache_boundary"] = dict(self.cache_boundary)
        payload["token_estimate"] = dict(self.token_estimate)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def build_runtime_prompt_manifest(
    *,
    invocation_kind: str,
    assembly: PromptAssemblyResult,
    packet_id: str = "",
    dynamic_projection_refs: tuple[str, ...] = (),
    volatile_state_refs: tuple[str, ...] = (),
) -> RuntimePromptManifest:
    refs = tuple(item.prompt_ref for item in assembly.sections if item.prompt_ref)
    contract_refs = tuple(item.source_ref for item in assembly.sections if not item.prompt_ref and item.source_ref)
    projection_refs = tuple(str(item).strip() for item in dynamic_projection_refs if str(item).strip()) or assembly.dynamic_projection_refs
    volatile_refs = tuple(str(item).strip() for item in volatile_state_refs if str(item).strip()) or assembly.volatile_state_refs
    manifest_seed = {
        "invocation_kind": invocation_kind,
        "packet_id": packet_id,
        "prompt_pack_refs": list(assembly.prompt_pack_refs),
        "stable_prompt_refs": list(refs),
        "stable_contract_refs": list(contract_refs),
        "dynamic_projection_refs": list(projection_refs),
        "volatile_state_refs": list(volatile_refs),
    }
    digest = hashlib.sha256(json.dumps(manifest_seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    cache_scope_counts = _cache_scope_counts(assembly)
    static_count = sum(
        count
        for scope, count in cache_scope_counts.items()
        if _is_static_cache_scope(scope)
    )
    return RuntimePromptManifest(
        manifest_id=f"rtprompt:{digest}",
        invocation_kind=invocation_kind,
        prompt_pack_refs=assembly.prompt_pack_refs,
        stable_prompt_refs=refs,
        stable_contract_refs=contract_refs,
        rejected_refs=assembly.rejected_refs,
        dynamic_projection_refs=projection_refs,
        volatile_state_refs=volatile_refs,
        cache_boundary={
            "static_section_count": static_count,
            "stable_prompt_section_count": len(assembly.sections),
            "cache_scope_counts": cache_scope_counts,
            "static_cache_scopes": sorted(scope for scope in cache_scope_counts if _is_static_cache_scope(scope)),
            "volatile_state_after_stable_sections": True,
        },
        token_estimate={
            "prompt_chars": sum(len(item.content) for item in assembly.sections),
        },
        diagnostics={
            "packet_id": packet_id,
            "prompt_assembly_id": assembly.assembly_id,
        },
    )


def _cache_scope_counts(assembly: PromptAssemblyResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for section in assembly.sections:
        scope = str(section.cache_scope or "static").strip() or "static"
        counts[scope] = counts.get(scope, 0) + 1
    return counts


def _is_static_cache_scope(scope: str) -> bool:
    return str(scope or "").strip() in {"static", "static_environment"}
