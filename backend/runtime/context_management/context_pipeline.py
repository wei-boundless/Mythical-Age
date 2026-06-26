from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context_candidates import context_candidate_from_message_spec
from .context_capability_policy import apply_context_capability_profile
from .context_segment_policy import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    context_segment_policy_for_spec,
    context_segment_policy_is_provider_visible_sealable,
    context_segment_policy_metadata,
)
from .physical_context_plan import annotate_specs_with_physical_context_plan
from .provider_visible_context_ledger import assemble_provider_visible_context_specs


@dataclass(frozen=True, slots=True)
class ContextPipelineResult:
    message_specs: tuple[dict[str, Any], ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_specs": [dict(item) for item in self.message_specs],
            "diagnostics": dict(self.diagnostics),
        }


PROVIDER_VISIBLE_CONTEXT_LEDGER_INVOCATIONS = frozenset(
    {
        "single_agent_turn",
        "single_agent_turn_tool_followup",
        "task_execution",
        "tool_observation_followup",
    }
)


def build_context_pipeline(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    invocation_kind: str,
    provider_visible_context_scope: str = "",
    provider_visible_context_inheritance: dict[str, Any] | None = None,
    compaction_generation: str = "",
    storage_root: Path | None = None,
    model_selection: dict[str, Any] | None = None,
    context_capability_profile: dict[str, Any] | None = None,
    system_wiring_manifest: dict[str, Any] | None = None,
    apply_capability_profile_stage: bool = True,
) -> ContextPipelineResult:
    clean_specs = [dict(item) for item in list(specs or ()) if isinstance(item, dict)]
    candidate_trace = [context_candidate_from_message_spec(item).to_dict() for item in clean_specs]
    capability_diagnostics: dict[str, Any] = {}
    if apply_capability_profile_stage:
        clean_specs, capability_diagnostics = apply_context_capability_profile_to_specs(
            clean_specs,
            invocation_kind=invocation_kind,
            context_capability_profile=context_capability_profile,
            system_wiring_manifest=system_wiring_manifest,
        )
    clean_specs = specs_with_context_compaction_generation(
        clean_specs,
        compaction_generation=compaction_generation,
    )
    clean_specs, ledger_diagnostics = apply_provider_visible_context_ledger_to_specs(
        clean_specs,
        invocation_kind=invocation_kind,
        provider_visible_context_scope=provider_visible_context_scope,
        provider_visible_context_inheritance=provider_visible_context_inheritance,
        compaction_generation=compaction_generation,
        storage_root=storage_root,
        model_selection=model_selection,
    )
    clean_specs, physical_diagnostics = apply_physical_context_plan_to_specs(
        clean_specs,
        compaction_generation=compaction_generation,
    )
    return ContextPipelineResult(
        message_specs=tuple(clean_specs),
        diagnostics={
            "candidate_trace": candidate_trace[:80],
            "candidate_trace_count": len(candidate_trace),
            "context_capability": capability_diagnostics,
            "provider_visible_context_ledger": ledger_diagnostics,
            "physical_context": physical_diagnostics,
            "authority": "runtime.context_management.context_pipeline",
        },
    )


def apply_context_capability_profile_to_specs(
    source_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    invocation_kind: str,
    context_capability_profile: dict[str, Any] | None,
    system_wiring_manifest: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    profile = dict(context_capability_profile or {})
    if not profile:
        compiled = dict(dict(system_wiring_manifest or {}).get("compiled") or {})
        profile = dict(compiled.get("context_capability_profile") or {})
    if not profile:
        return [dict(item) for item in list(source_specs or []) if isinstance(item, dict)], {}

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    group_counts: dict[str, int] = {}
    bypassed: list[dict[str, Any]] = []
    for index, spec in enumerate([dict(item) for item in list(source_specs or []) if isinstance(item, dict)], start=1):
        if sealed_provider_visible_replay_spec(spec):
            kept.append(_annotated_context_capability_bypass_spec(spec))
            bypassed.append(
                {
                    "index": index,
                    "kind": str(spec.get("kind") or ""),
                    "source_ref": str(spec.get("source_ref") or ""),
                    "reason": "sealed_provider_visible_replay_is_not_reclassified",
                }
            )
            continue
        filtered, diagnostics = apply_context_capability_profile(
            [dict(spec)],
            profile=profile,
            invocation_kind=invocation_kind,
        )
        for group, count in dict(diagnostics.get("context_capability_group_counts") or {}).items():
            group_id = str(group or "")
            group_counts[group_id] = group_counts.get(group_id, 0) + int(count or 0)
        if filtered:
            kept.extend(filtered)
            continue
        for item in list(diagnostics.get("rejected_context_capabilities") or []):
            if isinstance(item, dict):
                rejected.append({"source_index": index, **dict(item)})
    return kept, {
        "context_capability_profile": profile,
        "context_capability_group_counts": group_counts,
        "rejected_context_capability_count": len(rejected),
        "rejected_context_capabilities": rejected[:30],
        "bypassed_sealed_replay_count": len(bypassed),
        "bypassed_sealed_replay_specs": bypassed[:30],
        "input_spec_count": len(list(source_specs or [])),
        "output_spec_count": len(kept),
        "invocation_kind": str(invocation_kind or ""),
        "authority": "runtime.context_management.context_pipeline.context_capability_filter",
    }


def apply_provider_visible_context_ledger_to_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    invocation_kind: str,
    provider_visible_context_scope: str,
    provider_visible_context_inheritance: dict[str, Any] | None,
    compaction_generation: str,
    storage_root: Path | None,
    model_selection: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clean_specs = [dict(item) for item in list(specs or ()) if isinstance(item, dict)]
    scope = str(provider_visible_context_scope or "").strip()
    if not clean_specs or not scope or storage_root is None:
        return clean_specs, {
            "status": "skipped",
            "reason": "missing_scope_or_storage_root",
            "authority": "runtime.context_management.context_pipeline.provider_visible_context_ledger",
        }
    if str(invocation_kind or "") not in PROVIDER_VISIBLE_CONTEXT_LEDGER_INVOCATIONS:
        return clean_specs, {
            "status": "skipped",
            "reason": "invocation_kind_not_provider_visible_context_ledger_managed",
            "invocation_kind": str(invocation_kind or ""),
            "authority": "runtime.context_management.context_pipeline.provider_visible_context_ledger",
        }

    inheritance_contract = provider_visible_context_inheritance_contract(
        provider_visible_context_inheritance,
        write_scope=scope,
    )
    provider, model = provider_model_from_selection(model_selection)
    static_prefix: list[dict[str, Any]] = []
    provider_visible_candidates: list[tuple[int, dict[str, Any]]] = []
    current_turn_tail_specs: list[dict[str, Any]] = []
    blocked_dynamic_tail_replay_count = 0
    non_sealable_context_append_count = 0
    context_candidate_count = 0

    for original_order, raw_spec in enumerate(clean_specs, start=1):
        spec = dict(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        section = policy.section
        metadata = {
            **dict(spec.get("metadata") or {}),
            **context_segment_policy_metadata(policy),
        }
        spec["metadata"] = metadata
        spec["cache_scope"] = policy.prefix_cache_scope
        spec["cache_role"] = policy.prefix_cache_role
        spec["prefix_tier"] = policy.prefix_tier
        if section == STATIC_PREFIX:
            static_prefix.append(spec)
            continue
        if section in {CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND}:
            if not context_segment_policy_is_provider_visible_sealable(policy):
                current_turn_tail_specs.append(spec)
                non_sealable_context_append_count += 1
                continue
            provider_visible_candidates.append((original_order, spec))
            context_candidate_count += 1
            continue
        if section == DYNAMIC_TAIL:
            current_turn_tail_specs.append(spec)
            blocked_dynamic_tail_replay_count += 1
            continue
        current_turn_tail_specs.append(spec)

    ledger_specs_with_order = assemble_provider_visible_context_specs(
        provider_visible_candidates,
        storage_root=storage_root,
        scope=scope,
        inherited_scope=str(inheritance_contract.get("inherited_scope") or ""),
        inherited_anchor=dict(inheritance_contract.get("inherited_anchor") or {}),
        compaction_generation=normalize_context_compaction_generation(compaction_generation),
        provider=provider,
        model=model,
    )
    ledger_specs = [dict(spec) for _order, spec in list(ledger_specs_with_order or []) if isinstance(spec, dict)]
    inherited_ledger_spec_count = sum(
        1
        for spec in ledger_specs
        if str(dict(dict(spec).get("metadata") or {}).get("provider_visible_context_inherited_from_scope") or "").strip()
    )
    if not provider_visible_candidates and not ledger_specs:
        return clean_specs, {
            "status": "skipped",
            "reason": "no_provider_visible_context_candidates_or_confirmed_ledger_entries",
            "invocation_kind": str(invocation_kind or ""),
            "authority": "runtime.context_management.context_pipeline.provider_visible_context_ledger",
        }
    return [*static_prefix, *ledger_specs, *current_turn_tail_specs], {
        "status": "applied",
        "scope": scope,
        "invocation_kind": str(invocation_kind or ""),
        "provider": provider,
        "model": model,
        "compaction_generation": normalize_context_compaction_generation(compaction_generation),
        "context_candidate_count": context_candidate_count,
        "converted_dynamic_tail_replay_only_count": 0,
        "blocked_dynamic_tail_replay_count": blocked_dynamic_tail_replay_count,
        "non_sealable_context_append_tail_count": non_sealable_context_append_count,
        "ledger_materialized_spec_count": len(ledger_specs),
        "fork_inherited_provider_visible_spec_count": inherited_ledger_spec_count,
        "fork_inherited_provider_visible_scope": str(inheritance_contract.get("inherited_scope") or ""),
        "fork_inherited_provider_visible_anchor_id": str(
            dict(inheritance_contract.get("inherited_anchor") or {}).get("anchor_id") or ""
        ),
        "fork_inherited_provider_visible_terminal_entry_index": _safe_int(
            dict(inheritance_contract.get("inherited_anchor") or {}).get("terminal_entry_index")
        ),
        "fork_point_provider_request_commit_id": str(inheritance_contract.get("fork_point_provider_request_commit_id") or ""),
        "fork_point_provider_request_cache_spine_hash": str(inheritance_contract.get("fork_point_provider_request_cache_spine_hash") or ""),
        "fork_point_provider_payload_prefix_hash": str(inheritance_contract.get("fork_point_provider_payload_prefix_hash") or ""),
        "fork_point_provider_payload_message_prefix_hash": str(inheritance_contract.get("fork_point_provider_payload_message_prefix_hash") or ""),
        "fork_point_provider_payload_messages_hash": str(inheritance_contract.get("fork_point_provider_payload_messages_hash") or ""),
        "fork_point_transport_contract_hash": str(inheritance_contract.get("fork_point_transport_contract_hash") or ""),
        "fork_point_cache_sensitive_params_hash": str(inheritance_contract.get("fork_point_cache_sensitive_params_hash") or ""),
        "provider_cache_scope_id": str(inheritance_contract.get("provider_cache_scope_id") or ""),
        "fork_point_tool_context_anchor": str(inheritance_contract.get("fork_point_tool_context_anchor") or ""),
        "fork_point_tool_context_segment_count": _safe_int(
            dict(inheritance_contract.get("fork_point_tool_context_projection") or {}).get("tool_context_segment_count")
        ),
        "fork_point_read_evidence_state_ref": str(inheritance_contract.get("fork_point_read_evidence_state_ref") or ""),
        "fork_point_read_evidence_file_count": _safe_int(inheritance_contract.get("fork_point_read_evidence_file_count")),
        "fork_file_state_materialization_status": str(
            dict(inheritance_contract.get("fork_file_state_materialization") or {}).get("status") or ""
        ),
        "fork_point_content_replacement_state_ref": str(inheritance_contract.get("fork_point_content_replacement_state_ref") or ""),
        "fork_point_content_replacement_count": _safe_int(
            dict(inheritance_contract.get("fork_point_content_replacement_state") or {}).get("replacement_count")
        ),
        "current_turn_tail_spec_count": len(current_turn_tail_specs),
        "physical_replay_rule": "static_prefix_then_confirmed_provider_visible_context_then_current_turn_tail",
        "authority": "runtime.context_management.context_pipeline.provider_visible_context_ledger",
    }


def apply_physical_context_plan_to_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    compaction_generation: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    policy_specs: list[dict[str, Any]] = []
    section_counts: dict[str, int] = {}
    for original_order, raw_spec in enumerate(list(specs or ()), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        section = policy.section
        section_counts[section] = section_counts.get(section, 0) + 1
        metadata = {
            **dict(spec.get("metadata") or {}),
            **context_segment_policy_metadata(policy),
            "context_physical_bucket_original_order": original_order,
        }
        spec["metadata"] = metadata
        spec["cache_scope"] = policy.prefix_cache_scope
        spec["cache_role"] = policy.prefix_cache_role
        spec["prefix_tier"] = policy.prefix_tier
        policy_specs.append(spec)
    assembled, physical_plan = annotate_specs_with_physical_context_plan(
        policy_specs,
        compaction_generation=normalize_context_compaction_generation(compaction_generation),
    )
    diagnostics = {
        "input_spec_count": len(list(specs or ())),
        "output_spec_count": len(assembled),
        "context_cache_section_counts": section_counts,
        "physical_context_plan": physical_plan.to_dict(),
        "cache_spine_hash": physical_plan.cache_spine_hash,
        "cache_spine_generation": physical_plan.cache_spine_generation,
        "stable_after_tail_violations": [dict(item) for item in physical_plan.stable_after_tail_violations],
        "stable_after_tail_violation_count": len(physical_plan.stable_after_tail_violations),
        "authority": "runtime.context_management.context_pipeline.physical_context_assembly",
    }
    return assembled, diagnostics


def specs_with_context_compaction_generation(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    compaction_generation: str,
) -> list[dict[str, Any]]:
    generation = normalize_context_compaction_generation(compaction_generation)
    result: list[dict[str, Any]] = []
    for raw_spec in list(specs or ()):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        metadata = {
            **dict(spec.get("metadata") or {}),
            "compaction_generation": str(dict(spec.get("metadata") or {}).get("compaction_generation") or generation),
            "context_compaction_generation": str(
                dict(spec.get("metadata") or {}).get("context_compaction_generation")
                or dict(spec.get("metadata") or {}).get("compaction_generation")
                or generation
            ),
        }
        spec["metadata"] = metadata
        result.append(spec)
    return result


def normalize_context_compaction_generation(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return text or "0"


def provider_visible_context_inheritance_contract(
    value: dict[str, Any] | None,
    *,
    write_scope: str,
) -> dict[str, Any]:
    payload = dict(value or {})
    inherited_scope = str(
        payload.get("inherited_scope")
        or payload.get("parent_session_id")
        or payload.get("scope")
        or ""
    ).strip()
    normalized_write_scope = str(write_scope or "").strip()
    if not inherited_scope or inherited_scope == normalized_write_scope:
        return {}
    anchor = (
        dict(payload.get("inherited_anchor") or {})
        if isinstance(payload.get("inherited_anchor"), dict)
        else dict(payload.get("fork_point_provider_visible_ledger_anchor") or {})
        if isinstance(payload.get("fork_point_provider_visible_ledger_anchor"), dict)
        else {}
    )
    if not anchor:
        return {}
    return {
        "inherited_scope": inherited_scope,
        "write_scope": normalized_write_scope,
        "inherited_anchor": anchor,
        "fork_id": str(payload.get("fork_id") or ""),
        "fork_point_context_commit_id": str(payload.get("fork_point_context_commit_id") or ""),
        "fork_point_cache_spine_hash": str(payload.get("fork_point_cache_spine_hash") or ""),
        "fork_point_provider_request_commit_id": str(payload.get("fork_point_provider_request_commit_id") or ""),
        "fork_point_provider_request_cache_spine_hash": str(payload.get("fork_point_provider_request_cache_spine_hash") or ""),
        "fork_point_provider_payload_prefix_hash": str(payload.get("fork_point_provider_payload_prefix_hash") or ""),
        "fork_point_provider_payload_message_prefix_hash": str(payload.get("fork_point_provider_payload_message_prefix_hash") or ""),
        "fork_point_provider_payload_messages_hash": str(payload.get("fork_point_provider_payload_messages_hash") or ""),
        "fork_point_transport_contract_hash": str(payload.get("fork_point_transport_contract_hash") or ""),
        "fork_point_cache_sensitive_params_hash": str(payload.get("fork_point_cache_sensitive_params_hash") or ""),
        "provider_cache_scope_id": str(payload.get("provider_cache_scope_id") or ""),
        "fork_point_tool_context_anchor": str(payload.get("fork_point_tool_context_anchor") or ""),
        "fork_point_tool_context_projection": (
            dict(payload.get("fork_point_tool_context_projection") or {})
            if isinstance(payload.get("fork_point_tool_context_projection"), dict)
            else {}
        ),
        "fork_point_read_evidence_scope": (
            dict(payload.get("fork_point_read_evidence_scope") or {})
            if isinstance(payload.get("fork_point_read_evidence_scope"), dict)
            else {}
        ),
        "fork_child_read_evidence_scope": (
            dict(payload.get("fork_child_read_evidence_scope") or {})
            if isinstance(payload.get("fork_child_read_evidence_scope"), dict)
            else {}
        ),
        "fork_point_read_evidence_state_ref": str(payload.get("fork_point_read_evidence_state_ref") or ""),
        "fork_point_read_evidence_file_count": _safe_int(payload.get("fork_point_read_evidence_file_count")),
        "fork_file_state_materialization": (
            dict(payload.get("fork_file_state_materialization") or {})
            if isinstance(payload.get("fork_file_state_materialization"), dict)
            else {}
        ),
        "fork_point_content_replacement_state_ref": str(payload.get("fork_point_content_replacement_state_ref") or ""),
        "fork_point_content_replacement_state": (
            dict(payload.get("fork_point_content_replacement_state") or {})
            if isinstance(payload.get("fork_point_content_replacement_state"), dict)
            else {}
        ),
        "fork_point_compaction_generation": str(payload.get("fork_point_compaction_generation") or ""),
        "authority": "runtime.context_management.context_pipeline.provider_visible_context_inheritance_contract",
    }


def provider_model_from_selection(model_selection: dict[str, Any] | None) -> tuple[str, str]:
    selection = dict(model_selection or {})
    return (
        str(selection.get("provider") or selection.get("llm_provider") or "").strip(),
        str(selection.get("model") or selection.get("llm_model") or "").strip(),
    )


def sealed_provider_visible_replay_spec(spec: dict[str, Any]) -> bool:
    metadata = dict(spec.get("metadata") or {})
    if metadata.get("provider_protocol_replay") is True:
        return True
    payload_authority = str(metadata.get("provider_visible_payload_authority") or "").strip()
    if payload_authority.endswith(".replay"):
        return True
    replay_policy = str(metadata.get("context_replay_policy") or "").strip()
    if replay_policy == "provider_visible_ledger_replay":
        return True
    if (
        metadata.get("provider_visible_context_ledger_authority")
        and metadata.get("provider_visible_context_ledger_commit_stage") != "provider_success_required"
    ):
        return True
    return str(metadata.get("provider_visible_history_status") or "") == "sealed_from_prior_model_request"


def _annotated_context_capability_bypass_spec(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    metadata = {
        **dict(payload.get("metadata") or {}),
        "context_capability_filter": "bypassed_for_sealed_provider_visible_replay",
    }
    payload["metadata"] = metadata
    return payload


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
