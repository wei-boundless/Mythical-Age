from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import PromptPack, PromptResource, PromptSet
from .registry import PromptLibraryRegistry


@dataclass(frozen=True, slots=True)
class PromptDescriptor:
    ref: str
    descriptor_kind: str
    owner_kind: str = ""
    owner_ref: str = ""
    owner_layer: str = ""
    contract_priority: str = ""
    conflict_policy: str = ""
    scope: str = ""
    visibility: str = "model_visible"
    locked: bool = False
    title: str = ""
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_descriptor"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


class PromptDescriptorResolver:
    """Normalizes prompt refs from owner domains without deciding injection."""

    def __init__(self, base_dir: Path) -> None:
        self.registry = PromptLibraryRegistry(base_dir)

    def resolve_prompt_ref(self, prompt_ref: str) -> PromptDescriptor | None:
        ref = str(prompt_ref or "").strip()
        if not ref:
            return None
        resource = self.registry.get_resource(ref) or self.registry.get_active_resource(ref)
        if resource is not None:
            return descriptor_from_resource(resource)
        pack = self.registry.get_pack(ref)
        if pack is not None:
            return descriptor_from_pack(pack)
        prompt_set = self.registry.get_prompt_set(ref)
        if prompt_set is not None:
            return descriptor_from_prompt_set(prompt_set)
        return None

    def resolve_prompt_refs(self, prompt_refs: tuple[str, ...] | list[str]) -> tuple[PromptDescriptor, ...]:
        descriptors: list[PromptDescriptor] = []
        seen: set[str] = set()
        for prompt_ref in list(prompt_refs or []):
            ref = str(prompt_ref or "").strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            descriptor = self.resolve_prompt_ref(ref)
            if descriptor is not None:
                descriptors.append(descriptor)
        return tuple(descriptors)


def descriptor_from_resource(resource: PromptResource) -> PromptDescriptor:
    return PromptDescriptor(
        ref=resource.prompt_id,
        descriptor_kind="prompt_resource",
        owner_kind=resource.owner_kind,
        owner_ref=resource.owner_ref,
        owner_layer=resource.owner_layer,
        contract_priority=resource.contract_priority,
        conflict_policy=resource.conflict_policy,
        scope=resource.scope,
        visibility="model_visible" if resource.model_visible else "metadata_only",
        locked=resource.contract_priority == "core_contract",
        title=resource.title,
        source_ref=resource.source_ref,
        metadata={
            "category": resource.category,
            "subtype": resource.subtype,
            "resource_type": resource.resource_type,
            "version": resource.version,
            **dict(resource.metadata or {}),
        },
    )


def descriptor_from_prompt_set(prompt_set: PromptSet) -> PromptDescriptor:
    priority = str(prompt_set.metadata.get("contract_priority") or "owner_guidance")
    return PromptDescriptor(
        ref=prompt_set.prompt_set_id,
        descriptor_kind="prompt_set",
        owner_kind=prompt_set.owner_kind,
        owner_ref=prompt_set.owner_ref,
        owner_layer=str(prompt_set.metadata.get("owner_layer") or prompt_set.owner_kind or ""),
        contract_priority=priority,
        conflict_policy=str(prompt_set.metadata.get("conflict_policy") or "scoped_guidance"),
        scope=str(prompt_set.metadata.get("scope") or prompt_set.owner_ref or prompt_set.owner_kind or "runtime"),
        visibility=str(prompt_set.metadata.get("visibility") or "model_visible"),
        locked=bool(prompt_set.metadata.get("locked") is True),
        title=prompt_set.title,
        source_ref=str(prompt_set.metadata.get("source_ref") or ""),
        metadata={
            "status": prompt_set.status,
            "extends": list(prompt_set.extends),
            "allowed_agent_refs": list(prompt_set.allowed_agent_refs),
            "allowed_environment_refs": list(prompt_set.allowed_environment_refs),
        },
    )


def descriptor_from_pack(pack: PromptPack) -> PromptDescriptor:
    return PromptDescriptor(
        ref=pack.pack_id,
        descriptor_kind="prompt_pack",
        owner_kind=str(pack.metadata.get("owner_kind") or "runtime"),
        owner_ref=str(pack.metadata.get("owner_ref") or ""),
        owner_layer=str(pack.metadata.get("owner_layer") or "runtime"),
        contract_priority=str(pack.metadata.get("contract_priority") or "owner_guidance"),
        conflict_policy=str(pack.metadata.get("conflict_policy") or "scoped_guidance"),
        scope=str(pack.metadata.get("scope") or pack.invocation_kind or "runtime"),
        visibility=str(pack.metadata.get("visibility") or "model_visible"),
        locked=bool(pack.metadata.get("locked") is True),
        title=pack.title,
        source_ref=str(pack.metadata.get("source_ref") or ""),
        metadata={
            "invocation_kind": pack.invocation_kind,
            "status": pack.status,
            "ordered_prompt_refs": list(pack.ordered_prompt_refs),
            "allowed_agent_refs": list(pack.allowed_agent_refs),
            "allowed_environment_refs": list(pack.allowed_environment_refs),
        },
    )
