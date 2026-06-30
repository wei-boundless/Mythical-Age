from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .context_capability_policy import (
    ContextCapabilityDecision,
    ContextCapabilityProfile,
    context_capability_decision_for_spec,
    context_capability_profile_from_payload,
)
from .context_segment_policy import ContextSegmentPolicy, context_segment_policy_for_spec, context_segment_policy_metadata
from .provider_message_replay_contract import provider_message_byte_preservation_required, provider_message_replay_kind
from .system_asset_lines import (
    ContextInputEnvelope,
    ContextLineState,
    SystemAssetLine,
    context_line_state_for_asset_line,
    system_asset_lines_from_context_segment_registry,
)


SYSTEM_LINE_CONTROLLER_AUTHORITY = "runtime.context_management.system_line_controller"
CONTEXT_LINE_ACTIVATION_SCHEMA = "context_line_activation_report:20260701"


@dataclass(frozen=True, slots=True)
class ContextActivationInputs:
    invocation_kind: str = ""
    invocation_id: str = ""
    session_id: str = ""
    task_run_id: str = ""
    context_capability_profile: dict[str, Any] = field(default_factory=dict)
    system_wiring_manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextLineActivationResult:
    enabled_specs: tuple[dict[str, Any], ...] = ()
    context_input_envelopes: tuple[ContextInputEnvelope, ...] = ()
    line_states: tuple[ContextLineState, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled_specs": [dict(item) for item in self.enabled_specs],
            "context_input_envelopes": [item.to_dict() for item in self.context_input_envelopes],
            "line_states": [item.to_dict() for item in self.line_states],
            "diagnostics": dict(self.diagnostics),
        }


def activate_context_message_specs(
    source_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    invocation_kind: str,
    context_capability_profile: dict[str, Any] | ContextCapabilityProfile | None = None,
    system_wiring_manifest: dict[str, Any] | None = None,
    invocation_id: str = "",
    session_id: str = "",
    task_run_id: str = "",
) -> ContextLineActivationResult:
    """Activate declared system asset lines before physical context assembly.

    This is the single input-side line controller. It decides whether a context
    spec may proceed as an enabled line, then annotates the spec with the line
    identity consumed by downstream diagnostics. The physical assembler remains
    the only authority for four-segment ordering.
    """

    clean_specs = [dict(item) for item in list(source_specs or ()) if isinstance(item, dict)]
    manifest = dict(system_wiring_manifest or {})
    activation_inputs = ContextActivationInputs(
        invocation_kind=str(invocation_kind or "").strip(),
        invocation_id=str(invocation_id or "").strip(),
        session_id=str(session_id or "").strip(),
        task_run_id=str(task_run_id or "").strip(),
        context_capability_profile=_context_capability_profile_payload(
            context_capability_profile,
            system_wiring_manifest=manifest,
        ),
        system_wiring_manifest=manifest,
    )
    resolved_profile = context_capability_profile_from_payload(activation_inputs.context_capability_profile)
    lines = tuple(system_asset_lines_from_context_segment_registry())
    lines_by_asset_id = {line.asset_id: line for line in lines if line.asset_id}
    segment_gates = _compiled_context_segment_gates(manifest)
    enabled_specs: list[dict[str, Any]] = []
    envelopes: list[ContextInputEnvelope] = []
    line_states: list[ContextLineState] = []
    rejected_context_capabilities: list[dict[str, Any]] = []
    disabled_context_lines: list[dict[str, Any]] = []
    blocked_context_lines: list[dict[str, Any]] = []
    unavailable_context_lines: list[dict[str, Any]] = []
    provider_preservation_specs: list[dict[str, Any]] = []
    capability_group_counts: dict[str, int] = {}

    for index, raw_spec in enumerate(clean_specs, start=1):
        spec = dict(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        line = _asset_line_for_spec(spec, policy=policy, lines_by_asset_id=lines_by_asset_id)
        if line is None:
            state = ContextLineState(
                line_id=f"missing_system_asset_line:{_safe_token(policy.kind)}",
                invocation_id=activation_inputs.invocation_id,
                session_id=activation_inputs.session_id,
                task_run_id=activation_inputs.task_run_id,
                status="blocked",
                activation_authority=SYSTEM_LINE_CONTROLLER_AUTHORITY,
                disabled_reason=f"undeclared_context_segment_kind:{policy.kind}",
                source_ref=str(spec.get("source_ref") or ""),
                payload_ref=_payload_ref(spec),
                freshness="current_invocation",
                diagnostics={
                    "input_index": index,
                    "kind": str(policy.kind or ""),
                    "context_cache_section": str(policy.section or ""),
                    "reason": "SystemAssetLine declaration is required before context materialization.",
                },
            )
            line_states.append(state)
            blocked_context_lines.append(_line_state_row(state, spec=spec, policy=policy))
            continue

        if provider_message_byte_preservation_required(spec):
            decision = ContextCapabilityDecision(
                enabled=True,
                group=line.capability_group,
                slot=line.capability_slot,
                member=line.capability_member or "content",
                reason="provider_message_byte_preservation_contract",
                source=SYSTEM_LINE_CONTROLLER_AUTHORITY,
            )
            state = _enabled_line_state(
                line,
                activation_inputs=activation_inputs,
                spec=spec,
                policy=policy,
                diagnostics={
                    "input_index": index,
                    "kind": policy.kind,
                    "provider_message_byte_preservation_contract": provider_message_replay_kind(spec),
                    "activation_reason": decision.reason,
                },
            )
            annotated = _annotated_enabled_spec(
                spec,
                line=line,
                state=state,
                policy=policy,
                profile=resolved_profile,
                decision=decision,
                segment_gate={},
            )
            enabled_specs.append(annotated)
            envelopes.append(_context_input_envelope(line=line, state=state, spec=annotated))
            line_states.append(state)
            provider_preservation_specs.append(
                {
                    "index": index,
                    "kind": policy.kind,
                    "source_ref": str(spec.get("source_ref") or ""),
                    "byte_preservation_contract": provider_message_replay_kind(spec),
                    "reason": decision.reason,
                }
            )
            _increment(capability_group_counts, decision.group)
            continue

        decision = context_capability_decision_for_spec(spec, profile=resolved_profile)
        _increment(capability_group_counts, decision.group)
        segment_gate_key, segment_gate = _segment_gate_for_spec(
            spec,
            policy=policy,
            line=line,
            segment_gates=segment_gates,
        )
        disabled_reason = _disabled_reason(
            line=line,
            decision=decision,
            segment_gate_key=segment_gate_key,
            segment_gate=segment_gate,
        )
        if disabled_reason:
            state = context_line_state_for_asset_line(
                line,
                invocation_id=activation_inputs.invocation_id,
                session_id=activation_inputs.session_id,
                task_run_id=activation_inputs.task_run_id,
                status="disabled",
                disabled_reason=disabled_reason,
                source_ref=str(spec.get("source_ref") or line.producer_ref or ""),
                payload_ref=_payload_ref(spec),
                freshness="current_invocation",
                diagnostics={
                    "input_index": index,
                    "kind": policy.kind,
                    "context_cache_section": policy.section,
                    "context_capability": decision.to_dict(),
                    "context_segment_gate_key": segment_gate_key,
                    "context_segment_gate": dict(segment_gate or {}),
                },
            )
            line_states.append(state)
            row = _line_state_row(state, spec=spec, policy=policy)
            disabled_context_lines.append(row)
            rejected_context_capabilities.append(
                {
                    "source_index": index,
                    "index": index,
                    "kind": policy.kind,
                    "source_ref": str(spec.get("source_ref") or ""),
                    "context_capability_group": decision.group,
                    "context_capability_slot": decision.slot,
                    "reason": disabled_reason,
                    "line_id": line.line_id,
                }
            )
            continue

        if str(line.deprecation_state or "").strip() != "active":
            state = context_line_state_for_asset_line(
                line,
                invocation_id=activation_inputs.invocation_id,
                session_id=activation_inputs.session_id,
                task_run_id=activation_inputs.task_run_id,
                status="unavailable",
                disabled_reason=f"system_asset_line_deprecated:{line.deprecation_state}",
                source_ref=str(spec.get("source_ref") or line.producer_ref or ""),
                payload_ref=_payload_ref(spec),
                freshness="current_invocation",
                diagnostics={
                    "input_index": index,
                    "kind": policy.kind,
                    "context_cache_section": policy.section,
                    "context_capability": decision.to_dict(),
                },
            )
            line_states.append(state)
            unavailable_context_lines.append(_line_state_row(state, spec=spec, policy=policy))
            continue

        state = _enabled_line_state(
            line,
            activation_inputs=activation_inputs,
            spec=spec,
            policy=policy,
            diagnostics={
                "input_index": index,
                "kind": policy.kind,
                "context_cache_section": policy.section,
                "context_capability": decision.to_dict(),
                "context_segment_gate_key": segment_gate_key,
                "context_segment_gate": dict(segment_gate or {}),
            },
        )
        annotated = _annotated_enabled_spec(
            spec,
            line=line,
            state=state,
            policy=policy,
            profile=resolved_profile,
            decision=decision,
            segment_gate=segment_gate,
        )
        enabled_specs.append(annotated)
        envelopes.append(_context_input_envelope(line=line, state=state, spec=annotated))
        line_states.append(state)

    status_counts = _status_counts(line_states)
    diagnostics = {
        "schema": CONTEXT_LINE_ACTIVATION_SCHEMA,
        "authority": SYSTEM_LINE_CONTROLLER_AUTHORITY,
        "activation_inputs": activation_inputs.to_dict(),
        "context_capability_profile": resolved_profile.to_dict(),
        "context_capability_group_counts": capability_group_counts,
        "context_segment_gate_count": len(segment_gates),
        "input_spec_count": len(clean_specs),
        "output_spec_count": len(enabled_specs),
        "enabled_spec_count": len(enabled_specs),
        "context_input_envelope_count": len(envelopes),
        "line_state_count": len(line_states),
        "status_counts": status_counts,
        "enabled_line_count": int(status_counts.get("enabled") or 0),
        "disabled_line_count": int(status_counts.get("disabled") or 0),
        "blocked_line_count": int(status_counts.get("blocked") or 0),
        "unavailable_line_count": int(status_counts.get("unavailable") or 0),
        "rejected_context_capability_count": len(rejected_context_capabilities),
        "rejected_context_capabilities": rejected_context_capabilities[:30],
        "disabled_context_line_count": len(disabled_context_lines),
        "disabled_context_lines": disabled_context_lines[:30],
        "blocked_context_line_count": len(blocked_context_lines),
        "blocked_context_lines": blocked_context_lines[:30],
        "unavailable_context_line_count": len(unavailable_context_lines),
        "unavailable_context_lines": unavailable_context_lines[:30],
        "provider_message_byte_preservation_contract_count": len(provider_preservation_specs),
        "provider_message_byte_preservation_contract_specs": provider_preservation_specs[:30],
        "enabled_groups": list(resolved_profile.enabled_groups),
        "disabled_groups": list(resolved_profile.disabled_groups),
        "invocation_kind": str(invocation_kind or resolved_profile.invocation_kind or ""),
        "line_states": [state.to_dict() for state in line_states[:80]],
        "line_state_preview_count": min(len(line_states), 80),
        "physical_splice_boundary": "activation_before_PhysicalContextInputs",
    }
    return ContextLineActivationResult(
        enabled_specs=tuple(enabled_specs),
        context_input_envelopes=tuple(envelopes),
        line_states=tuple(line_states),
        diagnostics=diagnostics,
    )


def build_context_line_state_inventory(
    *,
    invocation_id: str = "",
    session_id: str = "",
    task_run_id: str = "",
) -> dict[str, Any]:
    lines = tuple(system_asset_lines_from_context_segment_registry())
    states = tuple(
        context_line_state_for_asset_line(
            line,
            invocation_id=invocation_id,
            session_id=session_id,
            task_run_id=task_run_id,
            status="diagnostic_only",
            disabled_reason="static_inventory_not_invocation_activation",
            source_ref=line.producer_ref,
            freshness="static_inventory",
        )
        for line in lines
    )
    return {
        "schema": "context_line_state_inventory",
        "authority": SYSTEM_LINE_CONTROLLER_AUTHORITY,
        "summary": {
            "line_state_count": len(states),
            "diagnostic_only_count": len(states),
        },
        "status_counts": _status_counts(states),
        "line_states": [state.to_dict() for state in states],
    }


def _context_capability_profile_payload(
    context_capability_profile: dict[str, Any] | ContextCapabilityProfile | None,
    *,
    system_wiring_manifest: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(context_capability_profile, ContextCapabilityProfile):
        return context_capability_profile.to_dict()
    profile = dict(context_capability_profile or {})
    if profile:
        return profile
    compiled = dict(dict(system_wiring_manifest or {}).get("compiled") or {})
    compiled_profile = compiled.get("context_capability_profile")
    return dict(compiled_profile) if isinstance(compiled_profile, dict) else {}


def _compiled_context_segment_gates(system_wiring_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    compiled = dict(dict(system_wiring_manifest or {}).get("compiled") or {})
    return {
        str(key): dict(value)
        for key, value in dict(compiled.get("context_segment_gates") or {}).items()
        if str(key)
    }


def _asset_line_for_spec(
    spec: dict[str, Any],
    *,
    policy: ContextSegmentPolicy,
    lines_by_asset_id: dict[str, SystemAssetLine],
) -> SystemAssetLine | None:
    metadata = dict(spec.get("metadata") or {})
    for key in (
        spec.get("kind"),
        metadata.get("context_segment_kind"),
        metadata.get("provider_visible_append_candidate_kind"),
        policy.kind,
    ):
        asset_id = str(key or "").strip()
        if asset_id and asset_id in lines_by_asset_id:
            return lines_by_asset_id[asset_id]
    return None


def _segment_gate_for_spec(
    spec: dict[str, Any],
    *,
    policy: ContextSegmentPolicy,
    line: SystemAssetLine,
    segment_gates: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    metadata = dict(spec.get("metadata") or {})
    candidates = (
        spec.get("kind"),
        metadata.get("context_segment_kind"),
        policy.kind,
        line.asset_id,
        policy.contract_slot,
        line.capability_slot,
        policy.section,
        line.physical_segment,
    )
    for candidate in candidates:
        key = str(candidate or "").strip()
        if key and key in segment_gates:
            return key, dict(segment_gates[key] or {})
    return "", {}


def _disabled_reason(
    *,
    line: SystemAssetLine,
    decision: ContextCapabilityDecision,
    segment_gate_key: str,
    segment_gate: dict[str, Any],
) -> str:
    if not bool(decision.enabled):
        return decision.reason or f"context_capability_group_disabled:{decision.group}"
    if segment_gate_key and bool(segment_gate.get("enabled") is not True):
        disabled_groups = [
            str(item)
            for item in list(segment_gate.get("disabled_system_groups") or [])
            if str(item)
        ]
        suffix = ",".join(disabled_groups) if disabled_groups else segment_gate_key
        return f"context_segment_gate_disabled:{suffix}"
    if not line.activation_policy_ref:
        return "missing_activation_policy_ref"
    return ""


def _enabled_line_state(
    line: SystemAssetLine,
    *,
    activation_inputs: ContextActivationInputs,
    spec: dict[str, Any],
    policy: ContextSegmentPolicy,
    diagnostics: dict[str, Any],
) -> ContextLineState:
    return context_line_state_for_asset_line(
        line,
        invocation_id=activation_inputs.invocation_id,
        session_id=activation_inputs.session_id,
        task_run_id=activation_inputs.task_run_id,
        status="enabled",
        source_ref=str(spec.get("source_ref") or line.producer_ref or ""),
        payload_ref=_payload_ref(spec),
        freshness=_freshness_for_policy(policy),
        budget_class=_budget_class_for_policy(policy),
        diagnostics=diagnostics,
    )


def _annotated_enabled_spec(
    spec: dict[str, Any],
    *,
    line: SystemAssetLine,
    state: ContextLineState,
    policy: ContextSegmentPolicy,
    profile: ContextCapabilityProfile,
    decision: ContextCapabilityDecision,
    segment_gate: dict[str, Any],
) -> dict[str, Any]:
    metadata = {
        **dict(spec.get("metadata") or {}),
        **context_segment_policy_metadata(policy),
        "context_line_id": line.line_id,
        "system_asset_line_id": line.line_id,
        "system_asset_id": line.asset_id,
        "system_asset_owner": line.asset_owner,
        "context_line_state": state.status,
        "context_line_activation_authority": SYSTEM_LINE_CONTROLLER_AUTHORITY,
        "context_line_disabled_reason": state.disabled_reason,
        "context_line_payload_ref": state.payload_ref,
        "context_capability_profile_id": profile.profile_id,
        "context_capability_group": decision.group,
        "context_capability_slot": decision.slot,
        "context_capability_member": decision.member,
        "context_capability_enabled": True,
        "context_capability_reason": decision.reason,
        "context_capability_prefix_coupled": True,
        "context_capability_authority": SYSTEM_LINE_CONTROLLER_AUTHORITY,
    }
    if segment_gate:
        metadata["context_segment_gate"] = dict(segment_gate)
    payload = dict(spec)
    payload["metadata"] = metadata
    return payload


def _context_input_envelope(
    *,
    line: SystemAssetLine,
    state: ContextLineState,
    spec: dict[str, Any],
) -> ContextInputEnvelope:
    metadata = dict(spec.get("metadata") or {})
    return ContextInputEnvelope(
        line_state=state,
        context_spec=dict(spec),
        source_identity=_first_text(
            metadata.get("context_candidate_source_identity"),
            spec.get("source_ref"),
            line.identity_key,
            line.producer_ref,
        ),
        content_identity=_first_text(
            metadata.get("context_candidate_content_identity"),
            _payload_ref(spec),
        ),
        visibility_contract=line.provider_visibility,
        seal_contract=line.sealability,
    )


def _line_state_row(
    state: ContextLineState,
    *,
    spec: dict[str, Any],
    policy: ContextSegmentPolicy,
) -> dict[str, Any]:
    return {
        "line_id": state.line_id,
        "status": state.status,
        "disabled_reason": state.disabled_reason,
        "kind": policy.kind,
        "source_ref": str(spec.get("source_ref") or ""),
        "context_cache_section": policy.section,
        "semantic_slot": policy.semantic_slot,
    }


def _status_counts(states: Iterable[ContextLineState]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in states:
        status = str(state.status or "missing")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _freshness_for_policy(policy: ContextSegmentPolicy) -> str:
    if policy.section == "static_prefix":
        return "session_stable"
    if policy.section == "context_memory_prefix":
        return "confirmed_replay"
    if policy.section == "context_append":
        return "current_turn_append"
    if policy.section == "dynamic_tail":
        return "current_turn_volatile"
    return "unknown"


def _budget_class_for_policy(policy: ContextSegmentPolicy) -> str:
    if policy.section == "static_prefix":
        return "stable_prefix_budget"
    if policy.section == "context_memory_prefix":
        return "replay_prefix_budget"
    if policy.section == "context_append":
        return "current_append_budget"
    if policy.section == "dynamic_tail":
        return "volatile_tail_budget"
    return "unknown_budget"


def _payload_ref(spec: dict[str, Any]) -> str:
    metadata = dict(spec.get("metadata") or {})
    explicit = _first_text(
        metadata.get("context_candidate_content_identity"),
        metadata.get("content_version_hash"),
        metadata.get("provider_visible_hash"),
        metadata.get("provider_serialized_hash"),
        metadata.get("physical_prefix_frame_segment_id"),
        spec.get("source_ref"),
    )
    if explicit:
        return explicit
    return "ctxpayload:" + _stable_hash(
        {
            "kind": spec.get("kind"),
            "role": spec.get("role"),
            "content": spec.get("content"),
            "model_message": spec.get("model_message"),
        }
    )[:16]


def _increment(counts: dict[str, int], key: str) -> None:
    normalized = str(key or "missing")
    counts[normalized] = counts.get(normalized, 0) + 1


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_token(value: Any) -> str:
    text = str(value or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", ".", ":"} else "_" for ch in text)
    return safe[:160] or "unknown"


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
