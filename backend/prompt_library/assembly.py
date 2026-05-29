from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import PromptAssemblyRequest, PromptAssemblyResult, PromptSection
from .packs import default_pack_ref_for_invocation
from .registry import PromptLibraryRegistry


class PromptAssemblyService:
    def __init__(self, base_dir: Path) -> None:
        self.registry = PromptLibraryRegistry(base_dir)

    def assemble(self, request: PromptAssemblyRequest) -> PromptAssemblyResult:
        pack_refs = tuple(request.prompt_pack_refs or ())
        if not pack_refs:
            default_ref = default_pack_ref_for_invocation(request.invocation_kind)
            pack_refs = (default_ref,) if default_ref else ()
        prompt_refs: list[str] = []
        rejected: list[dict[str, Any]] = []
        for pack_ref in pack_refs:
            pack = self.registry.get_pack(pack_ref)
            if pack is None:
                rejected.append({"ref": pack_ref, "reason": "pack_not_found"})
                continue
            if pack.status != "active":
                rejected.append({"ref": pack_ref, "reason": f"pack_status_{pack.status}"})
                continue
            if pack.invocation_kind != request.invocation_kind:
                rejected.append({"ref": pack_ref, "reason": "invocation_kind_mismatch"})
                continue
            prompt_refs.extend(pack.ordered_prompt_refs)
        prompt_refs.extend(request.prompt_refs)

        sections: list[PromptSection] = []
        seen: set[str] = set()
        for order, prompt_ref in enumerate(prompt_refs, start=1):
            if prompt_ref in seen:
                continue
            seen.add(prompt_ref)
            resource = self.registry.get_active_resource(prompt_ref)
            if resource is None:
                rejected.append({"ref": prompt_ref, "reason": "prompt_not_found_or_inactive"})
                continue
            reason = _resource_rejection_reason(resource.to_dict(), request=request.to_dict())
            if reason:
                rejected.append({"ref": prompt_ref, "reason": reason})
                continue
            sections.append(
                PromptSection(
                    section_id=f"{resource.category}.{resource.subtype}:{order}",
                    prompt_ref=resource.prompt_id,
                    category=resource.category,
                    subtype=resource.subtype,
                    title=resource.title,
                    content=resource.content.strip(),
                    owner_layer=resource.owner_layer,
                    cache_scope=resource.cache_scope,
                    source_ref=resource.source_ref,
                    order=order,
                    metadata={
                        "version": resource.version,
                        "resource_type": resource.resource_type,
                    },
                )
            )
        assembly_seed = {
            "invocation_kind": request.invocation_kind,
            "pack_refs": list(pack_refs),
            "prompt_refs": [item.prompt_ref for item in sections],
        }
        digest = hashlib.sha256(json.dumps(assembly_seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        manifest = {
            "stable_prompt_refs": [item.prompt_ref for item in sections],
            "prompt_pack_refs": list(pack_refs),
            "rejected_refs": [dict(item) for item in rejected],
            "cache_scope_order": [item.cache_scope for item in sections],
            "authority": "prompt_library.prompt_assembly_manifest",
        }
        return PromptAssemblyResult(
            assembly_id=f"promptasm:{digest}",
            invocation_kind=request.invocation_kind,
            sections=tuple(sections),
            prompt_pack_refs=pack_refs,
            rejected_refs=tuple(rejected),
            manifest=manifest,
        )

    def assemble_refs(
        self,
        *,
        invocation_kind: str,
        prompt_refs: tuple[str, ...] | list[str],
        agent_profile_ref: str = "",
        task_environment_ref: str = "",
        runtime_mode: str = "",
    ) -> PromptAssemblyResult:
        return self.assemble(
            PromptAssemblyRequest(
                invocation_kind=invocation_kind,
                prompt_pack_refs=(),
                prompt_refs=tuple(str(item).strip() for item in list(prompt_refs or []) if str(item).strip()),
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
                runtime_mode=runtime_mode,
            )
        )


def _resource_rejection_reason(resource: dict[str, Any], *, request: dict[str, Any]) -> str:
    if bool(dict(resource.get("metadata") or {}).get("deprecated_for_new_runtime") is True):
        return "deprecated_for_new_runtime"
    if str(resource.get("status") or "") != "active":
        return f"resource_status_{resource.get('status')}"
    invocation_kind = str(request.get("invocation_kind") or "")
    allowed_invocation_kinds = {str(item) for item in list(resource.get("allowed_invocation_kinds") or []) if str(item)}
    if allowed_invocation_kinds and invocation_kind not in allowed_invocation_kinds:
        return "resource_invocation_kind_mismatch"
    runtime_mode = str(request.get("runtime_mode") or "")
    allowed_runtime_modes = {str(item) for item in list(resource.get("allowed_runtime_modes") or []) if str(item)}
    if allowed_runtime_modes and runtime_mode and runtime_mode not in allowed_runtime_modes:
        return "resource_runtime_mode_mismatch"
    agent_ref = str(request.get("agent_profile_ref") or "")
    allowed_agent_refs = {str(item) for item in list(resource.get("allowed_agent_refs") or []) if str(item)}
    if allowed_agent_refs and agent_ref and agent_ref not in allowed_agent_refs:
        return "resource_agent_ref_mismatch"
    environment_ref = str(request.get("task_environment_ref") or "")
    allowed_environment_refs = {str(item) for item in list(resource.get("allowed_environment_refs") or []) if str(item)}
    if allowed_environment_refs and environment_ref and environment_ref not in allowed_environment_refs:
        return "resource_environment_ref_mismatch"
    return ""
