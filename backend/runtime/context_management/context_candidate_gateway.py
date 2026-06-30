from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from .context_candidates import context_candidate_from_message_spec
from .system_asset_lines import ContextInputEnvelope, ContextLineState
from .system_line_controller import ContextLineActivationResult, activate_context_message_specs


CONTEXT_CANDIDATE_GATEWAY_AUTHORITY = "runtime.context_management.context_candidate_gateway"
CONTEXT_CANDIDATE_GATEWAY_SCHEMA = "context_candidate_gateway:20260701"


@dataclass(frozen=True, slots=True)
class ContextCandidateGatewayResult:
    message_specs: tuple[dict[str, Any], ...] = ()
    candidate_specs: tuple[dict[str, Any], ...] = ()
    context_input_envelopes: tuple[ContextInputEnvelope, ...] = ()
    line_states: tuple[ContextLineState, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_specs": [dict(item) for item in self.message_specs],
            "candidate_specs": [dict(item) for item in self.candidate_specs],
            "context_input_envelopes": [item.to_dict() for item in self.context_input_envelopes],
            "line_states": [item.to_dict() for item in self.line_states],
            "diagnostics": dict(self.diagnostics),
        }


def build_context_candidate_gateway(
    source_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    invocation_kind: str,
    context_capability_profile: dict[str, Any] | None = None,
    system_wiring_manifest: dict[str, Any] | None = None,
    invocation_id: str = "",
    session_id: str = "",
    task_run_id: str = "",
) -> ContextCandidateGatewayResult:
    clean_specs = annotate_context_candidate_specs(source_specs)
    candidate_trace = [context_candidate_from_message_spec(item).to_dict() for item in clean_specs]
    activation = activate_context_message_specs(
        clean_specs,
        invocation_kind=invocation_kind,
        context_capability_profile=context_capability_profile,
        system_wiring_manifest=system_wiring_manifest,
        invocation_id=invocation_id,
        session_id=session_id,
        task_run_id=task_run_id,
    )
    materialized_specs, materialization_diagnostics = materialize_context_input_envelopes(
        activation.context_input_envelopes,
    )
    activation_diagnostics = dict(activation.diagnostics or {})
    status_counts = _status_counts(activation.line_states)
    diagnostics = {
        "schema": CONTEXT_CANDIDATE_GATEWAY_SCHEMA,
        "authority": CONTEXT_CANDIDATE_GATEWAY_AUTHORITY,
        "invocation_kind": str(invocation_kind or ""),
        "source_spec_count": len(clean_specs),
        "candidate_trace": candidate_trace[:80],
        "candidate_trace_count": len(candidate_trace),
        "candidate_identity": _candidate_identity_diagnostics(clean_specs),
        "context_line_activation": activation_diagnostics,
        "context_input_envelope_count": len(activation.context_input_envelopes),
        "line_state_count": len(activation.line_states),
        "line_state_status_counts": status_counts,
        "status_counts": status_counts,
        "materialization": materialization_diagnostics,
        "message_spec_count": len(materialized_specs),
        "forbidden_downstream_route": "disabled_unavailable_or_blocked_lines_must_not_reach_PhysicalContextInputs",
    }
    return ContextCandidateGatewayResult(
        message_specs=tuple(materialized_specs),
        candidate_specs=tuple(clean_specs),
        context_input_envelopes=tuple(activation.context_input_envelopes),
        line_states=tuple(activation.line_states),
        diagnostics=diagnostics,
    )


def annotate_context_candidate_specs(
    source_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for index, raw_spec in enumerate(list(source_specs or ()), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        metadata = dict(spec.get("metadata") or {})
        candidate = context_candidate_from_message_spec(spec)
        source_identity = _first_text(
            metadata.get("context_candidate_source_identity"),
            metadata.get("source_identity"),
            metadata.get("origin_ref"),
            metadata.get("context_origin_ref"),
            spec.get("source_ref"),
            candidate.source_ref,
            candidate.identity,
        )
        content_identity = _first_text(
            metadata.get("context_candidate_content_identity"),
            metadata.get("content_identity"),
            metadata.get("content_version_hash"),
            metadata.get("content_hash"),
            candidate.content_hash,
        )
        metadata.update(
            {
                "context_candidate_ref": _first_text(metadata.get("context_candidate_ref"), candidate.candidate_id),
                "context_candidate_source_identity": source_identity,
                "context_candidate_content_identity": content_identity,
                "context_candidate_source_route": _first_text(
                    metadata.get("context_candidate_source_route"),
                    metadata.get("source_route"),
                    metadata.get("content_source"),
                    candidate.source_route,
                ),
                "context_candidate_kind": candidate.canonical_kind,
                "context_candidate_gateway_schema": CONTEXT_CANDIDATE_GATEWAY_SCHEMA,
                "context_candidate_identity_authority": f"{CONTEXT_CANDIDATE_GATEWAY_AUTHORITY}.candidate_identity",
                "context_candidate_input_index": index,
            }
        )
        metadata.setdefault("content_version_hash", content_identity)
        spec["metadata"] = metadata
        annotated.append(spec)
    return annotated


def materialize_context_input_envelopes(
    envelopes: Iterable[ContextInputEnvelope | dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    envelope_values = list(envelopes or ())
    specs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    duplicate_refs: list[str] = []
    refs: list[str] = []
    for index, raw_envelope in enumerate(envelope_values, start=1):
        envelope = _coerce_context_input_envelope(raw_envelope)
        if envelope is None:
            skipped.append({"index": index, "reason": "invalid_context_input_envelope"})
            continue
        state = envelope.line_state
        if str(state.status or "") != "enabled":
            skipped.append(
                {
                    "index": index,
                    "line_id": state.line_id,
                    "status": state.status,
                    "reason": state.disabled_reason or "line_not_enabled",
                }
            )
            continue
        spec = _materialized_spec_from_envelope(envelope)
        envelope_ref = str(dict(spec.get("metadata") or {}).get("context_input_envelope_ref") or "")
        if envelope_ref:
            if envelope_ref in refs and envelope_ref not in duplicate_refs:
                duplicate_refs.append(envelope_ref)
            refs.append(envelope_ref)
        specs.append(spec)
    diagnostics = {
        "authority": f"{CONTEXT_CANDIDATE_GATEWAY_AUTHORITY}.materialize_context_input_envelopes",
        "input_envelope_count": len(envelope_values),
        "output_spec_count": len(specs),
        "skipped_envelope_count": len(skipped),
        "skipped_envelopes": skipped[:30],
        "duplicate_context_input_envelope_refs": duplicate_refs,
        "all_specs_have_line_id": all(
            bool(str(dict(spec.get("metadata") or {}).get("context_line_id") or "").strip())
            for spec in specs
        ),
    }
    return specs, diagnostics


def _materialized_spec_from_envelope(envelope: ContextInputEnvelope) -> dict[str, Any]:
    state = envelope.line_state
    spec = dict(envelope.context_spec or {})
    metadata = {
        **dict(spec.get("metadata") or {}),
        "context_candidate_gateway_authority": CONTEXT_CANDIDATE_GATEWAY_AUTHORITY,
        "context_input_envelope_schema_revision": envelope.schema_revision,
        "context_input_envelope_materialized": True,
        "context_input_envelope_ref": _context_input_envelope_ref(envelope),
        "context_input_envelope_line_id": state.line_id,
        "context_input_envelope_source_identity": envelope.source_identity,
        "context_input_envelope_content_identity": envelope.content_identity,
        "context_input_envelope_visibility_contract": envelope.visibility_contract,
        "context_input_envelope_seal_contract": envelope.seal_contract,
        "context_line_id": state.line_id,
        "system_asset_line_id": state.line_id,
        "context_line_state": state.status,
        "context_line_payload_ref": state.payload_ref,
        "context_line_source_ref": state.source_ref,
        "context_line_activation_authority": state.activation_authority,
    }
    spec["metadata"] = metadata
    return spec


def _coerce_context_input_envelope(value: ContextInputEnvelope | dict[str, Any]) -> ContextInputEnvelope | None:
    if isinstance(value, ContextInputEnvelope):
        return value
    if not isinstance(value, dict):
        return None
    line_state_payload = value.get("line_state")
    if not isinstance(line_state_payload, dict):
        return None
    state = _context_line_state_from_dict(line_state_payload)
    if state is None:
        return None
    context_spec = value.get("context_spec")
    if not isinstance(context_spec, dict):
        return None
    return ContextInputEnvelope(
        line_state=state,
        context_spec=dict(context_spec),
        source_identity=str(value.get("source_identity") or ""),
        content_identity=str(value.get("content_identity") or ""),
        visibility_contract=str(value.get("visibility_contract") or ""),
        seal_contract=str(value.get("seal_contract") or ""),
        schema_revision=str(value.get("schema_revision") or "context_input_envelope:unknown"),
    )


def _context_line_state_from_dict(payload: dict[str, Any]) -> ContextLineState | None:
    line_id = str(payload.get("line_id") or "").strip()
    if not line_id:
        return None
    return ContextLineState(
        line_id=line_id,
        invocation_id=str(payload.get("invocation_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        status=str(payload.get("status") or "diagnostic_only"),
        activation_authority=str(payload.get("activation_authority") or ""),
        disabled_reason=str(payload.get("disabled_reason") or ""),
        source_ref=str(payload.get("source_ref") or ""),
        payload_ref=str(payload.get("payload_ref") or ""),
        freshness=str(payload.get("freshness") or ""),
        budget_class=str(payload.get("budget_class") or ""),
        diagnostics=dict(payload.get("diagnostics") or {}),
        schema_revision=str(payload.get("schema_revision") or "context_line_state:unknown"),
    )


def _context_input_envelope_ref(envelope: ContextInputEnvelope) -> str:
    seed = {
        "line_id": envelope.line_state.line_id,
        "source_identity": envelope.source_identity,
        "content_identity": envelope.content_identity,
        "payload_ref": envelope.line_state.payload_ref,
    }
    return "ctxenvelope:" + _stable_hash(seed)[:16]


def _candidate_identity_diagnostics(specs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payload = [dict(item) for item in list(specs or ()) if isinstance(item, dict)]
    missing_candidate_ref = 0
    missing_source_identity = 0
    missing_content_identity = 0
    producer_counts: dict[str, int] = {}
    for spec in payload:
        metadata = dict(spec.get("metadata") or {})
        if not str(metadata.get("context_candidate_ref") or "").strip():
            missing_candidate_ref += 1
        if not str(metadata.get("context_candidate_source_identity") or "").strip():
            missing_source_identity += 1
        if not str(metadata.get("context_candidate_content_identity") or "").strip():
            missing_content_identity += 1
        producer_id = str(metadata.get("context_message_producer_id") or "inline_or_unknown").strip() or "inline_or_unknown"
        producer_counts[producer_id] = producer_counts.get(producer_id, 0) + 1
    return {
        "authority": f"{CONTEXT_CANDIDATE_GATEWAY_AUTHORITY}.candidate_identity",
        "input_spec_count": len(payload),
        "missing_candidate_ref_count": missing_candidate_ref,
        "missing_source_identity_count": missing_source_identity,
        "missing_content_identity_count": missing_content_identity,
        "all_specs_have_candidate_ref": missing_candidate_ref == 0,
        "all_specs_have_source_identity": missing_source_identity == 0,
        "all_specs_have_content_identity": missing_content_identity == 0,
        "producer_counts": producer_counts,
    }


def _status_counts(states: Iterable[ContextLineState]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in states:
        status = str(state.status or "missing")
        counts[status] = counts.get(status, 0) + 1
    return counts


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


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
