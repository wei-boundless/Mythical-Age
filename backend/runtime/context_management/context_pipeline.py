from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from runtime.prompt_accounting.provider_lane import normalize_provider_lane

from .context_candidates import context_candidate_from_message_spec
from .context_candidate_gateway import build_context_candidate_gateway
from context_system.segments.policy import (
    context_segment_policy_for_spec,
    context_segment_policy_is_provider_visible_sealable,
)
from .physical_context_plan import build_physical_context_plan
from .physical_context_assembler import (
    PhysicalContextInputs,
    assemble_physical_context_spine,
    classify_physical_context_inputs,
)
from .provider_visible_append_ledger import assemble_provider_visible_append_specs


@dataclass(frozen=True, slots=True)
class ContextPipelineResult:
    message_specs: tuple[dict[str, Any], ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_specs": [dict(item) for item in self.message_specs],
            "diagnostics": dict(self.diagnostics),
        }


PROVIDER_VISIBLE_APPEND_STAGE_INVOCATIONS = frozenset(
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
    provider_visible_append_scope: str = "",
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
    candidate_gateway_diagnostics: dict[str, Any] = {}
    if apply_capability_profile_stage:
        gateway_result = build_context_candidate_gateway(
            clean_specs,
            invocation_kind=invocation_kind,
            context_capability_profile=context_capability_profile,
            system_wiring_manifest=system_wiring_manifest,
        )
        clean_specs = [dict(item) for item in gateway_result.message_specs]
        candidate_gateway_diagnostics = dict(gateway_result.diagnostics or {})
        capability_diagnostics = dict(candidate_gateway_diagnostics.get("context_line_activation") or {})
    clean_specs = specs_with_context_compaction_generation(
        clean_specs,
        compaction_generation=compaction_generation,
    )
    provider, model = provider_model_from_selection(model_selection)
    provider_lane = provider_lane_from_model_selection(model_selection)
    draft_inputs = classify_physical_context_inputs(
        clean_specs,
        storage_root=storage_root,
        scope=provider_visible_append_scope,
        provider=provider,
        model=model,
        provider_lane=provider_lane,
        input_stage="draft",
    )
    final_inputs, append_stage_diagnostics = enrich_physical_context_inputs_with_provider_visible_append_ledger(
        draft_inputs,
        invocation_kind=invocation_kind,
        provider_visible_context_inheritance=provider_visible_context_inheritance,
        compaction_generation=compaction_generation,
    )
    physical_assembly = assemble_physical_context_spine(final_inputs)
    clean_specs = [dict(item) for item in physical_assembly.message_specs]
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
            "context_candidate_gateway": candidate_gateway_diagnostics,
            "provider_visible_append_stage": append_stage_diagnostics,
            "physical_context_inputs": final_inputs.to_diagnostics(),
            "physical_context_assembly": dict(physical_assembly.diagnostics or {}),
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
    gateway_result = build_context_candidate_gateway(
        source_specs,
        invocation_kind=invocation_kind,
        context_capability_profile=context_capability_profile,
        system_wiring_manifest=system_wiring_manifest,
    )
    diagnostics = dict(dict(gateway_result.diagnostics or {}).get("context_line_activation") or {})
    diagnostics["context_candidate_gateway"] = dict(gateway_result.diagnostics or {})
    return [dict(item) for item in gateway_result.message_specs], diagnostics


def enrich_physical_context_inputs_with_provider_visible_append_ledger(
    inputs: PhysicalContextInputs,
    *,
    invocation_kind: str,
    provider_visible_context_inheritance: dict[str, Any] | None,
    compaction_generation: str,
) -> tuple[PhysicalContextInputs, dict[str, Any]]:
    scope = str(inputs.scope or "").strip()
    current_append_inputs = [
        (index, dict(spec))
        for index, spec in enumerate(list(inputs.current_append_specs or ()), start=1)
        if isinstance(spec, dict)
    ]
    if not current_append_inputs:
        return replace(inputs, input_stage="final"), {
            "status": "skipped",
            "reason": "no_current_append_inputs",
            "authority": "runtime.context_management.context_pipeline.provider_visible_append_ledger_enrichment",
        }
    if not scope or inputs.storage_root is None:
        return replace(inputs, input_stage="final"), {
            "status": "skipped",
            "reason": "missing_scope_or_storage_root",
            "current_append_spec_count": len(current_append_inputs),
            "authority": "runtime.context_management.context_pipeline.provider_visible_append_ledger_enrichment",
        }
    if str(invocation_kind or "") not in PROVIDER_VISIBLE_APPEND_STAGE_INVOCATIONS:
        return replace(inputs, input_stage="final"), {
            "status": "skipped",
            "reason": "invocation_kind_not_provider_visible_append_stage_managed",
            "invocation_kind": str(invocation_kind or ""),
            "current_append_spec_count": len(current_append_inputs),
            "authority": "runtime.context_management.context_pipeline.provider_visible_append_ledger_enrichment",
        }

    inheritance_contract = provider_visible_context_inheritance_contract(
        provider_visible_context_inheritance,
        write_scope=scope,
    )
    provider_visible_append_candidates: list[tuple[int, dict[str, Any]]] = []
    non_sealable_context_append_count = 0
    context_candidate_count = 0

    for original_order, raw_spec in current_append_inputs:
        spec = dict(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        if not context_segment_policy_is_provider_visible_sealable(policy):
            non_sealable_context_append_count += 1
            continue
        provider_visible_append_candidates.append((original_order, spec))
        context_candidate_count += 1

    current_append_specs_with_order = assemble_provider_visible_append_specs(
        provider_visible_append_candidates,
        storage_root=inputs.storage_root,
        scope=scope,
        inherited_scope=str(inheritance_contract.get("inherited_scope") or ""),
        inherited_anchor=dict(inheritance_contract.get("inherited_anchor") or {}),
        compaction_generation=normalize_context_compaction_generation(compaction_generation),
        provider=inputs.provider,
        model=inputs.model,
    )
    current_append_specs_by_order = {
        int(order or 0): dict(spec)
        for order, spec in list(current_append_specs_with_order or [])
        if isinstance(spec, dict)
    }
    provider_visible_candidate_orders = {
        int(order or 0)
        for order, _spec in list(provider_visible_append_candidates or [])
    }
    provider_visible_returned_orders = set(current_append_specs_by_order)
    omitted_provider_visible_candidates = [
        _omitted_provider_visible_candidate_diagnostic(order, spec)
        for order, spec in list(provider_visible_append_candidates or [])
        if int(order or 0) not in provider_visible_returned_orders
    ]
    current_append_specs: list[dict[str, Any]] = []
    for order, spec in sorted(current_append_inputs, key=lambda item: int(item[0] or 0)):
        order_index = int(order or 0)
        if order_index in provider_visible_candidate_orders:
            enriched_spec = current_append_specs_by_order.get(order_index)
            if enriched_spec:
                current_append_specs.append(dict(enriched_spec))
            continue
        current_append_specs.append(dict(spec))
    final_inputs = replace(
        inputs,
        current_append_specs=tuple(current_append_specs),
        input_stage="final",
        diagnostics={
            **dict(inputs.diagnostics or {}),
            "provider_visible_append_ledger_enrichment": {
                "status": "applied",
                "scope": scope,
                "invocation_kind": str(invocation_kind or ""),
                "current_append_input_count": len(current_append_inputs),
                "provider_visible_candidate_count": len(provider_visible_append_candidates),
                "provider_visible_enriched_count": len(current_append_specs_with_order),
                "provider_visible_omitted_already_visible_count": len(omitted_provider_visible_candidates),
                "provider_visible_omitted_already_visible_candidates": omitted_provider_visible_candidates[:80],
                "authority": "runtime.context_management.context_pipeline.provider_visible_append_ledger_enrichment",
            },
        },
    )
    return final_inputs, {
        "status": "applied",
        "scope": scope,
        "invocation_kind": str(invocation_kind or ""),
        "provider": inputs.provider,
        "model": inputs.model,
        "provider_lane": inputs.provider_lane,
        "compaction_generation": normalize_context_compaction_generation(compaction_generation),
        "context_candidate_count": context_candidate_count,
        "non_sealable_context_append_tail_count": non_sealable_context_append_count,
        "provider_visible_current_append_spec_count": len(current_append_specs_with_order),
        "provider_visible_omitted_already_visible_count": len(omitted_provider_visible_candidates),
        "provider_visible_omitted_already_visible_candidates": omitted_provider_visible_candidates[:80],
        "current_append_spec_count": len(current_append_specs),
        "fork_inherited_provider_visible_append_spec_count": 0,
        "fork_inherited_provider_visible_append_scope": str(inheritance_contract.get("inherited_scope") or ""),
        "fork_inherited_provider_visible_append_anchor_id": str(
            dict(inheritance_contract.get("inherited_anchor") or {}).get("anchor_id") or ""
        ),
        "fork_inherited_provider_visible_append_terminal_entry_index": _safe_int(
            dict(inheritance_contract.get("inherited_anchor") or {}).get("terminal_entry_index")
        ),
        "fork_point_provider_request_commit_id": str(inheritance_contract.get("fork_point_provider_request_commit_id") or ""),
        "fork_point_provider_request_cache_spine_hash": str(inheritance_contract.get("fork_point_provider_request_cache_spine_hash") or ""),
        "fork_point_provider_payload_prefix_hash": str(inheritance_contract.get("fork_point_provider_payload_prefix_hash") or ""),
        "fork_point_physical_cache_spine_message_subtotal_hash": str(inheritance_contract.get("fork_point_physical_cache_spine_message_subtotal_hash") or ""),
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
        "current_turn_tail_spec_count": len(current_append_specs),
        "physical_input_stage": "final",
        "physical_replay_rule": "ledger_returns_only_new_provider_visible_append; already_visible_candidates_replay_from_physical_prefix_frame",
        "authority": "runtime.context_management.context_pipeline.provider_visible_append_ledger_enrichment",
    }


def _omitted_provider_visible_candidate_diagnostic(order: int, spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    return {
        "original_order": int(order or 0),
        "kind": str(payload.get("kind") or metadata.get("canonical_kind") or ""),
        "source_ref": str(payload.get("source_ref") or metadata.get("source_ref") or ""),
        "context_cache_section": str(metadata.get("context_cache_section") or ""),
        "context_replay_policy": str(metadata.get("context_replay_policy") or ""),
        "context_origin_ref": str(metadata.get("context_origin_ref") or metadata.get("append_only_context_item_key") or ""),
        "reason": "provider_visible_append_ledger_did_not_return_candidate; confirmed_or_filtered_context_must_replay_from_physical_prefix_frame",
    }


def apply_physical_context_plan_to_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    compaction_generation: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clean_specs = [dict(item) for item in list(specs or ()) if isinstance(item, dict)]
    section_counts: dict[str, int] = {}
    for raw_spec in clean_specs:
        spec = dict(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        section = policy.section
        section_counts[section] = section_counts.get(section, 0) + 1
    physical_plan = build_physical_context_plan(
        clean_specs,
        compaction_generation=normalize_context_compaction_generation(compaction_generation),
    )
    diagnostics = {
        "input_spec_count": len(list(specs or ())),
        "output_spec_count": len(clean_specs),
        "context_cache_section_counts": section_counts,
        "physical_context_plan": physical_plan.to_dict(),
        "cache_spine_hash": physical_plan.cache_spine_hash,
        "cache_spine_generation": physical_plan.cache_spine_generation,
        "stable_after_tail_violations": [dict(item) for item in physical_plan.stable_after_tail_violations],
        "stable_after_tail_violation_count": len(physical_plan.stable_after_tail_violations),
        "blocked_segments": [dict(item) for item in physical_plan.blocked_segments],
        "blocked_segment_count": len(physical_plan.blocked_segments),
        "authority": "runtime.context_management.context_pipeline.physical_context_diagnostics",
    }
    return clean_specs, diagnostics


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
        else dict(payload.get("fork_point_provider_visible_append_anchor") or {})
        if isinstance(payload.get("fork_point_provider_visible_append_anchor"), dict)
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
        "fork_point_physical_cache_spine_message_subtotal_hash": str(payload.get("fork_point_physical_cache_spine_message_subtotal_hash") or ""),
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


def provider_lane_from_model_selection(
    model_selection: dict[str, Any] | None,
) -> str:
    selection = dict(model_selection or {})
    return normalize_provider_lane(selection.get("provider_lane"))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
