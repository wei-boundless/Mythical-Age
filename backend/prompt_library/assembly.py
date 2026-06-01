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
        has_explicit_refs = bool(
            tuple(request.prompt_refs or ())
            or tuple(request.skill_prompt_refs or ())
            or str(request.soul_prompt_ref or "").strip()
            or dict(request.task_prompt_contract or {})
            or dict(request.graph_node_prompt_contract or {})
        )
        if not pack_refs and not has_explicit_refs:
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
            reason = _pack_rejection_reason(pack.to_dict(), request=request.to_dict())
            if reason:
                rejected.append({"ref": pack_ref, "reason": reason})
                continue
            prompt_refs.extend(pack.ordered_prompt_refs)
        prompt_refs.extend(request.prompt_refs)
        prompt_refs.extend(request.skill_prompt_refs)
        if str(request.soul_prompt_ref or "").strip():
            prompt_refs.append(str(request.soul_prompt_ref).strip())

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
        contract_order = len(sections) + 1
        if request.invocation_kind == "task_prompt_contract":
            sections.extend(
                _contract_sections(
                    contract=dict(request.task_prompt_contract or {}),
                    category="task",
                    source_ref="task_prompt_contract",
                    start_order=contract_order,
                )
            )
            contract_order = len(sections) + 1
            sections.extend(
                _contract_sections(
                    contract=dict(request.graph_node_prompt_contract or {}),
                    category="graph_node",
                    source_ref="graph_node_prompt_contract",
                    start_order=contract_order,
                )
            )
        elif request.task_prompt_contract or request.graph_node_prompt_contract:
            rejected.append(
                {
                    "ref": "task_prompt_contract",
                    "reason": "contract_sections_require_task_prompt_contract_invocation",
                }
            )
        assembly_seed = {
            "invocation_kind": request.invocation_kind,
            "pack_refs": list(pack_refs),
            "prompt_refs": [item.prompt_ref for item in sections],
            "contract_sections": [
                {"category": item.category, "subtype": item.subtype, "source_ref": item.source_ref}
                for item in sections
                if not item.prompt_ref
            ],
        }
        digest = hashlib.sha256(json.dumps(assembly_seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        manifest = {
            "stable_prompt_refs": [item.prompt_ref for item in sections if item.prompt_ref],
            "stable_contract_refs": [item.source_ref for item in sections if not item.prompt_ref],
            "prompt_pack_refs": list(pack_refs),
            "rejected_refs": [dict(item) for item in rejected],
            "cache_scope_order": [item.cache_scope for item in sections],
            "contract_section_count": len([item for item in sections if not item.prompt_ref]),
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
    ) -> PromptAssemblyResult:
        return self.assemble(
            PromptAssemblyRequest(
                invocation_kind=invocation_kind,
                prompt_pack_refs=(),
                prompt_refs=tuple(str(item).strip() for item in list(prompt_refs or []) if str(item).strip()),
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
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
    agent_ref = str(request.get("agent_profile_ref") or "")
    allowed_agent_refs = {str(item) for item in list(resource.get("allowed_agent_refs") or []) if str(item)}
    if allowed_agent_refs and agent_ref and agent_ref not in allowed_agent_refs:
        return "resource_agent_ref_mismatch"
    environment_ref = str(request.get("task_environment_ref") or "")
    allowed_environment_refs = {str(item) for item in list(resource.get("allowed_environment_refs") or []) if str(item)}
    if allowed_environment_refs and environment_ref and environment_ref not in allowed_environment_refs:
        return "resource_environment_ref_mismatch"
    return ""


def _pack_rejection_reason(pack: dict[str, Any], *, request: dict[str, Any]) -> str:
    agent_ref = str(request.get("agent_profile_ref") or "")
    allowed_agent_refs = {str(item) for item in list(pack.get("allowed_agent_refs") or []) if str(item)}
    if allowed_agent_refs and agent_ref and agent_ref not in allowed_agent_refs:
        return "pack_agent_ref_mismatch"
    environment_ref = str(request.get("task_environment_ref") or "")
    allowed_environment_refs = {str(item) for item in list(pack.get("allowed_environment_refs") or []) if str(item)}
    if allowed_environment_refs and environment_ref and environment_ref not in allowed_environment_refs:
        return "pack_environment_ref_mismatch"
    return ""


_CONTRACT_FIELD_SPECS = (
    ("role_prompt", "role", "角色职责"),
    ("task_instruction", "task_instruction", "任务说明"),
    ("output_instruction", "output_instruction", "输出要求"),
    ("forbidden_behavior", "forbidden_behavior", "禁止事项"),
    ("definition_of_done", "definition_of_done", "完成标准"),
)


def _contract_sections(
    *,
    contract: dict[str, Any],
    category: str,
    source_ref: str,
    start_order: int,
) -> list[PromptSection]:
    if not contract:
        return []
    sections: list[PromptSection] = []
    contract_id = str(contract.get("contract_id") or contract.get("prompt_contract_id") or source_ref).strip()
    for offset, (field, subtype, title) in enumerate(_CONTRACT_FIELD_SPECS):
        content = _contract_field_content(contract.get(field))
        if not content:
            continue
        sections.append(
            PromptSection(
                section_id=f"{category}.{subtype}:{start_order + offset}",
                prompt_ref="",
                category=category,
                subtype=subtype,
                title=title,
                content=content,
                owner_layer="task",
                cache_scope="task_stable",
                source_ref=f"{source_ref}:{contract_id}.{field}",
                order=start_order + offset,
                metadata={
                    "contract_id": contract_id,
                    "contract_field": field,
                    "resource_type": f"{category}.{subtype}",
                    "version": str(contract.get("version") or "v1"),
                },
            )
        )
    return sections


def _contract_field_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    items = [str(item).strip() for item in list(value or []) if str(item).strip()] if isinstance(value, (list, tuple)) else []
    if items:
        return "\n".join(f"- {item}" for item in items)
    return ""
