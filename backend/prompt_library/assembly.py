from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import PromptAssemblyRequest, PromptAssemblyResult, PromptSection
from .packs import default_pack_ref_for_invocation
from .registry import PromptLibraryRegistry
from .rules import build_rule_diagnostics
from runtime.context_management.context_capability_policy import (
    context_capability_decision_for_prompt_resource,
    context_capability_profile_from_payload,
)


class PromptAssemblyService:
    def __init__(self, base_dir: Path) -> None:
        self.registry = PromptLibraryRegistry(base_dir)

    def assemble(self, request: PromptAssemblyRequest) -> PromptAssemblyResult:
        pack_refs = tuple(request.prompt_pack_refs or ())
        request_metadata = dict(request.metadata or {})
        system_wiring_manifest = _system_wiring_manifest_from_request_metadata(request_metadata)
        context_capability_profile = _context_capability_profile_from_request_metadata(
            request_metadata,
            system_wiring_manifest=system_wiring_manifest,
        )
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
            wiring_reason = _resource_context_wiring_rejection_reason(
                resource.to_dict(),
                context_capability_profile=context_capability_profile,
                system_wiring_manifest=system_wiring_manifest,
            )
            if wiring_reason:
                rejected.append({"ref": prompt_ref, "reason": wiring_reason})
                continue
            context_capability_metadata = _resource_context_wiring_metadata(
                resource.to_dict(),
                context_capability_profile=context_capability_profile,
                system_wiring_manifest=system_wiring_manifest,
            )
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
                        "authority_scope": dict(resource.metadata or {}).get("authority_scope"),
                        "prompt_rule": dict(resource.metadata or {}).get("prompt_rule"),
                        **context_capability_metadata,
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
        sections = list(enforce_prompt_authority_order(tuple(sections)))
        prompt_authority_manifest = build_prompt_authority_manifest(tuple(sections))
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
        section_fingerprint = _stable_payload_hash(_section_fingerprint_payload(tuple(sections)))
        manifest = {
            "assembly_request_fingerprint": _stable_payload_hash(
                _request_fingerprint_payload(request=request, resolved_pack_refs=pack_refs)
            ),
            "section_fingerprint": section_fingerprint,
            "stable_prompt_refs": [item.prompt_ref for item in sections if item.prompt_ref],
            "stable_contract_refs": [item.source_ref for item in sections if not item.prompt_ref],
            "prompt_pack_refs": list(pack_refs),
            "rejected_refs": [dict(item) for item in rejected],
            "cache_scope_order": [item.cache_scope for item in sections],
            "cache_boundary": _assembly_cache_boundary_report(tuple(sections)),
            "layer_summary": _assembly_layer_summary(tuple(sections)),
            "prompt_precedence": build_prompt_precedence_report(tuple(sections)),
            "prompt_authority": prompt_authority_manifest,
            "system_wiring_manifest_ref": str(system_wiring_manifest.get("manifest_id") or ""),
            "context_capability_profile": (
                context_capability_profile.to_dict() if context_capability_profile is not None else {}
            ),
            "contract_section_count": len([item for item in sections if not item.prompt_ref]),
            "authority": "prompt_library.prompt_assembly_manifest",
        }
        rule_diagnostics = build_rule_diagnostics(tuple(sections), invocation_kind=request.invocation_kind)
        if rule_diagnostics.get("rejected_rules"):
            rejected.extend(dict(item) for item in list(rule_diagnostics.get("rejected_rules") or []))
            manifest["rejected_refs"] = [dict(item) for item in rejected]
        manifest["prompt_rules"] = rule_diagnostics
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
        metadata: dict[str, Any] | None = None,
    ) -> PromptAssemblyResult:
        return self.assemble(
            PromptAssemblyRequest(
                invocation_kind=invocation_kind,
                prompt_pack_refs=(),
                prompt_refs=tuple(str(item).strip() for item in list(prompt_refs or []) if str(item).strip()),
                agent_profile_ref=agent_profile_ref,
                task_environment_ref=task_environment_ref,
                metadata=dict(metadata or {}),
            )
        )


def _system_wiring_manifest_from_request_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    manifest = metadata.get("system_wiring_manifest")
    if isinstance(manifest, dict):
        return dict(manifest)
    runtime_assembly = metadata.get("runtime_assembly")
    if isinstance(runtime_assembly, dict) and isinstance(runtime_assembly.get("system_wiring_manifest"), dict):
        return dict(runtime_assembly.get("system_wiring_manifest") or {})
    return {}


def _context_capability_profile_from_request_metadata(
    metadata: dict[str, Any],
    *,
    system_wiring_manifest: dict[str, Any],
) -> Any | None:
    profile_payload = metadata.get("context_capability_profile")
    if not isinstance(profile_payload, dict) or not profile_payload:
        compiled = dict(system_wiring_manifest.get("compiled") or {})
        profile_payload = compiled.get("context_capability_profile")
    if not isinstance(profile_payload, dict) or not profile_payload:
        return None
    return context_capability_profile_from_payload(dict(profile_payload))


def _resource_context_wiring_rejection_reason(
    resource: dict[str, Any],
    *,
    context_capability_profile: Any | None,
    system_wiring_manifest: dict[str, Any],
) -> str:
    prompt_ref = str(resource.get("prompt_id") or resource.get("resource_id") or "").strip()
    stable_contract = _resource_is_stable_prompt_contract(resource)
    gate = _prompt_resource_gate(system_wiring_manifest, prompt_ref=prompt_ref)
    if gate and gate.get("enabled") is False and not list(gate.get("system_groups") or []):
        if not stable_contract:
            disabled = ",".join(str(item) for item in list(gate.get("disabled_system_groups") or []) if str(item))
            return f"system_group_disabled:{disabled or prompt_ref}"
    if context_capability_profile is None:
        return ""
    decision = context_capability_decision_for_prompt_resource(resource, profile=context_capability_profile)
    if not decision.enabled and not stable_contract:
        return decision.reason
    return ""


def _resource_context_wiring_metadata(
    resource: dict[str, Any],
    *,
    context_capability_profile: Any | None,
    system_wiring_manifest: dict[str, Any],
) -> dict[str, Any]:
    prompt_ref = str(resource.get("prompt_id") or resource.get("resource_id") or "").strip()
    stable_contract = _resource_is_stable_prompt_contract(resource)
    gate = _prompt_resource_gate(system_wiring_manifest, prompt_ref=prompt_ref)
    metadata: dict[str, Any] = {}
    if context_capability_profile is not None:
        decision = context_capability_decision_for_prompt_resource(resource, profile=context_capability_profile)
        effective_enabled = bool(decision.enabled or stable_contract)
        metadata.update(
            {
                "context_capability_profile_id": str(getattr(context_capability_profile, "profile_id", "") or ""),
                "context_capability_group": decision.group,
                "context_capability_slot": decision.slot,
                "context_capability_member": decision.member,
                "context_capability_enabled": decision.enabled,
                "context_capability_effective_enabled": effective_enabled,
                "context_capability_reason": decision.reason,
                "context_capability_gate_applied": not stable_contract,
                "context_capability_authority": decision.source,
            }
        )
    if gate:
        metadata["system_wiring_prompt_gate"] = {
            "enabled": bool(gate.get("enabled") is True),
            "effective_enabled": bool(gate.get("enabled") is True or stable_contract),
            "gate_applied": not stable_contract,
            "system_groups": [str(item) for item in list(gate.get("system_groups") or []) if str(item)],
            "disabled_system_groups": [
                str(item) for item in list(gate.get("disabled_system_groups") or []) if str(item)
            ],
        }
    return metadata


def _resource_is_stable_prompt_contract(resource: dict[str, Any]) -> bool:
    prompt_ref = str(resource.get("prompt_id") or resource.get("resource_id") or "").strip()
    category = str(resource.get("category") or "").strip()
    metadata = dict(resource.get("metadata") or {})
    if category == "system" and prompt_ref.startswith("system.foundation."):
        return True
    if category == "runtime" and prompt_ref.startswith("runtime."):
        return True
    if bool(metadata.get("builtin_runtime_prompt") is True):
        return True
    if str(metadata.get("source_type") or "").strip() == "builtin_system_foundation_prompt":
        return True
    return False


def _prompt_resource_gate(system_wiring_manifest: dict[str, Any], *, prompt_ref: str) -> dict[str, Any]:
    if not prompt_ref:
        return {}
    compiled = dict(system_wiring_manifest.get("compiled") or {})
    gates = dict(compiled.get("prompt_resource_gates") or {})
    gate = gates.get(prompt_ref)
    return dict(gate) if isinstance(gate, dict) else {}


def _resource_rejection_reason(resource: dict[str, Any], *, request: dict[str, Any]) -> str:
    if bool(dict(resource.get("metadata") or {}).get("deprecated_for_new_runtime") is True):
        return "deprecated_for_new_runtime"
    if str(resource.get("status") or "") != "active":
        return f"resource_status_{resource.get('status')}"
    invocation_kind = str(request.get("invocation_kind") or "")
    allowed_invocation_kinds = {str(item) for item in list(resource.get("allowed_invocation_kinds") or []) if str(item)}
    if allowed_invocation_kinds and invocation_kind not in allowed_invocation_kinds:
        return "resource_invocation_kind_mismatch"
    environment_ref = str(request.get("task_environment_ref") or "")
    allowed_environment_refs = {str(item) for item in list(resource.get("allowed_environment_refs") or []) if str(item)}
    if allowed_environment_refs and environment_ref and environment_ref not in allowed_environment_refs:
        return "resource_environment_ref_mismatch"
    return ""


def _pack_rejection_reason(pack: dict[str, Any], *, request: dict[str, Any]) -> str:
    environment_ref = str(request.get("task_environment_ref") or "")
    allowed_environment_refs = {str(item) for item in list(pack.get("allowed_environment_refs") or []) if str(item)}
    if allowed_environment_refs and environment_ref and environment_ref not in allowed_environment_refs:
        return "pack_environment_ref_mismatch"
    return ""


_PROMPT_LAYER_PRECEDENCE = {
    "system": 0,
    "override": 5,
    "coordinator": 10,
    "agent": 20,
    "personality": 25,
    "runtime": 30,
    "environment": 40,
    "lifecycle": 45,
    "tool": 50,
    "skill": 60,
    "project": 70,
    "contract": 80,
    "unknown": 100,
}


def enforce_prompt_authority_order(sections: tuple[PromptSection, ...]) -> tuple[PromptSection, ...]:
    ordered = sorted(
        enumerate(sections),
        key=lambda item: (
            _PROMPT_LAYER_PRECEDENCE.get(_prompt_section_layer(item[1]), _PROMPT_LAYER_PRECEDENCE["unknown"]),
            int(getattr(item[1], "order", 0) or 0),
            item[0],
        ),
    )
    result: list[PromptSection] = []
    for order, (_, section) in enumerate(ordered, start=1):
        metadata = {
            **dict(section.metadata or {}),
            "requested_order": int(getattr(section, "order", 0) or 0),
            "authority_layer": _prompt_section_layer(section),
        }
        result.append(
            replace(
                section,
                section_id=f"{section.category}.{section.subtype}:{order}",
                order=order,
                metadata=metadata,
            )
        )
    return tuple(result)


def build_prompt_precedence_report(sections: tuple[PromptSection, ...]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for section in sections:
        layer = _prompt_section_layer(section)
        entries.append(
            {
                "prompt_ref": section.prompt_ref,
                "category": section.category,
                "subtype": section.subtype,
                "owner_layer": section.owner_layer,
                "assembly_layer": layer,
                "precedence": _PROMPT_LAYER_PRECEDENCE.get(layer, _PROMPT_LAYER_PRECEDENCE["unknown"]),
                "order": section.order,
                "requested_order": int(dict(section.metadata or {}).get("requested_order") or section.order or 0),
                "source_ref": section.source_ref,
            }
        )
    return {
        "policy": "system>override>coordinator>agent>personality>runtime>environment>lifecycle>tool>skill>project>contract",
        "behavior": "enforced_precedence_order",
        "entries": entries,
        "authority": "prompt_library.prompt_assembly_precedence",
    }


def build_prompt_authority_manifest(sections: tuple[PromptSection, ...]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    rejected_sections: list[dict[str, Any]] = []
    for section in sections:
        layer = _prompt_section_layer(section)
        precedence = _PROMPT_LAYER_PRECEDENCE.get(layer, _PROMPT_LAYER_PRECEDENCE["unknown"])
        entry = {
            "section_id": section.section_id,
            "prompt_ref": section.prompt_ref,
            "source_ref": section.source_ref,
            "authority_layer": layer,
            "owner_layer": section.owner_layer,
            "cache_scope": section.cache_scope,
            "enforced_order": section.order,
            "requested_order": int(dict(section.metadata or {}).get("requested_order") or section.order or 0),
            "precedence": precedence,
        }
        entries.append(entry)
        if layer == "unknown":
            rejected_sections.append({**entry, "reason": "unknown_prompt_authority_layer"})
    return {
        "authority": "prompt_library.prompt_authority_manifest",
        "generation_id": _stable_payload_hash(_section_fingerprint_payload(sections)) if sections else "",
        "enforcement_mode": "enforced_precedence",
        "enforced_precedence": dict(_PROMPT_LAYER_PRECEDENCE),
        "segment_order": [
            str(section.prompt_ref or section.source_ref or section.section_id)
            for section in sections
        ],
        "entries": entries,
        "rejected_sections": rejected_sections,
    }


def _prompt_section_layer(section: PromptSection) -> str:
    category = str(section.category or "").strip()
    subtype = str(section.subtype or "").strip()
    owner_layer = str(section.owner_layer or "").strip()
    resource_type = str(dict(section.metadata or {}).get("resource_type") or "").strip()
    prompt_ref = str(section.prompt_ref or "").strip()
    if category == "environment" and (subtype.startswith("lifecycle_") or ".lifecycle." in prompt_ref):
        return "lifecycle"
    if category in {"task", "graph_node"}:
        return "contract"
    if category in {"utility", "mcp"}:
        return "runtime"
    if category in _PROMPT_LAYER_PRECEDENCE:
        return category
    if owner_layer in _PROMPT_LAYER_PRECEDENCE:
        return owner_layer
    if resource_type == "tool_guidance":
        return "tool"
    if resource_type == "worker_prompt":
        return "agent"
    return "unknown"


def _request_fingerprint_payload(
    *,
    request: PromptAssemblyRequest,
    resolved_pack_refs: tuple[str, ...],
) -> dict[str, Any]:
    payload = request.to_dict()
    task_contract = dict(payload.pop("task_prompt_contract", {}) or {})
    graph_contract = dict(payload.pop("graph_node_prompt_contract", {}) or {})
    metadata = dict(payload.pop("metadata", {}) or {})
    return {
        **payload,
        "resolved_prompt_pack_refs": list(resolved_pack_refs),
        "task_prompt_contract_hash": _stable_payload_hash(task_contract) if task_contract else "",
        "graph_node_prompt_contract_hash": _stable_payload_hash(graph_contract) if graph_contract else "",
        "metadata_hash": _stable_payload_hash(metadata) if metadata else "",
    }


def _section_fingerprint_payload(sections: tuple[PromptSection, ...]) -> list[dict[str, Any]]:
    return [
        {
            "prompt_ref": section.prompt_ref,
            "source_ref": section.source_ref,
            "category": section.category,
            "subtype": section.subtype,
            "owner_layer": section.owner_layer,
            "assembly_layer": _prompt_section_layer(section),
            "cache_scope": section.cache_scope,
            "content_hash": _stable_text_hash(section.content),
            "order": section.order,
        }
        for section in sections
    ]


def _assembly_cache_boundary_report(sections: tuple[PromptSection, ...]) -> dict[str, Any]:
    cache_scope_counts: dict[str, int] = {}
    prefix_tier_counts: dict[str, int] = {}
    for section in sections:
        cache_scope = str(section.cache_scope or "static").strip() or "static"
        prefix_tier = _prefix_tier_from_cache_scope(cache_scope)
        cache_scope_counts[cache_scope] = cache_scope_counts.get(cache_scope, 0) + 1
        prefix_tier_counts[prefix_tier] = prefix_tier_counts.get(prefix_tier, 0) + 1
    return {
        "cache_scope_counts": cache_scope_counts,
        "prefix_tier_counts": prefix_tier_counts,
        "cache_scope_order": [section.cache_scope for section in sections],
        "prefix_tier_order": [_prefix_tier_from_cache_scope(section.cache_scope) for section in sections],
        "stable_section_count": len(sections),
        "global_static_section_count": prefix_tier_counts.get("provider_global", 0),
        "session_stable_section_count": prefix_tier_counts.get("session", 0),
        "task_stable_section_count": prefix_tier_counts.get("task", 0),
        "volatile_section_count": prefix_tier_counts.get("volatile", 0) + prefix_tier_counts.get("none", 0),
        "section_fingerprint": _stable_payload_hash(_section_fingerprint_payload(sections)) if sections else "",
        "authority": "prompt_library.prompt_assembly_cache_boundary",
    }


def _assembly_layer_summary(sections: tuple[PromptSection, ...]) -> dict[str, Any]:
    owner_layer_counts: dict[str, int] = {}
    assembly_layer_counts: dict[str, int] = {}
    for section in sections:
        owner_layer = str(section.owner_layer or "unknown").strip() or "unknown"
        assembly_layer = _prompt_section_layer(section)
        owner_layer_counts[owner_layer] = owner_layer_counts.get(owner_layer, 0) + 1
        assembly_layer_counts[assembly_layer] = assembly_layer_counts.get(assembly_layer, 0) + 1
    return {
        "owner_layer_counts": owner_layer_counts,
        "assembly_layer_counts": assembly_layer_counts,
        "ordered_layers": [_prompt_section_layer(section) for section in sections],
        "section_count": len(sections),
        "authority": "prompt_library.prompt_assembly_layer_summary",
    }


def _prefix_tier_from_cache_scope(cache_scope: str) -> str:
    scope = str(cache_scope or "").strip()
    if scope in {"static", "global"}:
        return "provider_global"
    if scope in {"static_environment", "session", "session_stable"}:
        return "session"
    if scope in {"task", "task_stable"}:
        return "task"
    if scope in {"none"}:
        return "none"
    return "volatile"


def _stable_payload_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _stable_text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


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
