from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .context_segment_registry import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    ContextSegmentKindDeclaration,
    context_segment_kind_declarations,
)


SYSTEM_ASSET_LINE_SCHEMA_REVISION = "system_asset_line:20260701"
CONTEXT_LINE_STATE_SCHEMA_REVISION = "context_line_state:20260701"
CONTEXT_INPUT_ENVELOPE_SCHEMA_REVISION = "context_input_envelope:20260701"
CONTROL_OUTPUT_LINE_SCHEMA_REVISION = "control_output_line:20260701"
HARNESS_CONTROL_SPINE_LINE_SCHEMA_REVISION = "harness_control_spine_line:20260701"
SYSTEM_ASSET_LINE_AUTHORITY = "runtime.context_management.system_asset_lines"


@dataclass(frozen=True, slots=True)
class SystemAssetLine:
    line_id: str
    asset_id: str
    asset_owner: str
    asset_kind: str
    producer_ref: str
    transport_or_store: str
    consumer_domain: str
    physical_segment: str
    semantic_slot: str
    capability_group: str = ""
    capability_slot: str = ""
    capability_member: str = ""
    identity_key: str = ""
    lifecycle: str = ""
    sealability: str = ""
    provider_visibility: str = ""
    activation_policy_ref: str = ""
    terminal_policy: str = ""
    schema_revision: str = SYSTEM_ASSET_LINE_SCHEMA_REVISION
    deprecation_state: str = "active"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextLineState:
    line_id: str
    invocation_id: str = ""
    session_id: str = ""
    task_run_id: str = ""
    status: str = "diagnostic_only"
    activation_authority: str = SYSTEM_ASSET_LINE_AUTHORITY
    disabled_reason: str = ""
    source_ref: str = ""
    payload_ref: str = ""
    freshness: str = ""
    budget_class: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    schema_revision: str = CONTEXT_LINE_STATE_SCHEMA_REVISION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextInputEnvelope:
    line_state: ContextLineState
    context_spec: dict[str, Any]
    source_identity: str = ""
    content_identity: str = ""
    visibility_contract: str = ""
    seal_contract: str = ""
    schema_revision: str = CONTEXT_INPUT_ENVELOPE_SCHEMA_REVISION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["line_state"] = self.line_state.to_dict()
        payload["context_spec"] = dict(self.context_spec or {})
        return payload


@dataclass(frozen=True, slots=True)
class ControlOutputLine:
    action_type: str
    model_decision_ref: str
    authority: str
    permit_policy_ref: str
    executor_ref: str
    observation_contract: str
    public_projection_policy: str
    commit_policy: str
    terminal_policy: str
    failure_feedback_policy: str
    schema_revision: str = CONTROL_OUTPUT_LINE_SCHEMA_REVISION
    diagnostics: dict[str, Any] = field(default_factory=dict)
    line_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HarnessControlSpineLine:
    control_line_id: str
    action_type: str
    model_action_ref: str
    packet_context_ref: str
    receipt_ref: str
    admission_ref: str
    permit_ref: str
    tool_plan_ref: str
    tool_invocation_ref: str
    runtime_gateway_ref: str
    commit_ref: str
    projection_ref: str
    terminal_policy: str
    schema_revision: str = HARNESS_CONTROL_SPINE_LINE_SCHEMA_REVISION
    diagnostics: dict[str, Any] = field(default_factory=dict)
    control_output_line_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def system_asset_line_from_context_segment_declaration(
    declaration: ContextSegmentKindDeclaration,
) -> SystemAssetLine:
    kind = str(declaration.kind or "").strip()
    section = str(declaration.section or "").strip()
    producer_ref = _first_text(
        declaration.content_source,
        declaration.source_kind,
        declaration.capability_group,
        f"context_segment_registry:{kind}",
    )
    owner = _first_text(
        declaration.content_source,
        declaration.source_kind,
        declaration.capability_group,
        "runtime.context_management.context_segment_registry",
    )
    diagnostics = _line_diagnostics(declaration, producer_ref=producer_ref)
    return SystemAssetLine(
        line_id=f"system_asset_line:context_segment:{_safe_token(kind)}",
        asset_id=kind,
        asset_owner=owner,
        asset_kind="context_segment",
        producer_ref=producer_ref,
        transport_or_store=_transport_for_section(section),
        consumer_domain="ContextCandidateGateway",
        physical_segment=section,
        semantic_slot=str(declaration.semantic_slot or "").strip(),
        capability_group=str(declaration.capability_group or "").strip(),
        capability_slot=str(declaration.capability_slot or "").strip(),
        capability_member=str(declaration.capability_member or "").strip(),
        identity_key=_identity_key_for_declaration(declaration),
        lifecycle=_lifecycle_for_section(section),
        sealability=_sealability_for_section(section, append_only=declaration.append_only),
        provider_visibility=_provider_visibility_for_section(section),
        activation_policy_ref=_activation_policy_ref(declaration),
        terminal_policy=_terminal_policy_for_section(section),
        diagnostics=diagnostics,
    )


def system_asset_lines_from_context_segment_registry() -> tuple[SystemAssetLine, ...]:
    return tuple(
        system_asset_line_from_context_segment_declaration(declaration)
        for declaration in context_segment_kind_declarations()
        if str(declaration.kind or "").strip()
    )


def system_asset_lines_by_id(lines: Iterable[SystemAssetLine] | None = None) -> dict[str, SystemAssetLine]:
    payload = tuple(lines) if lines is not None else system_asset_lines_from_context_segment_registry()
    return {line.line_id: line for line in payload if line.line_id}


def build_system_asset_line_inventory() -> dict[str, Any]:
    lines = system_asset_lines_from_context_segment_registry()
    diagnostics = diagnose_system_asset_lines(lines)
    return {
        "schema": "system_asset_line_inventory",
        "authority": SYSTEM_ASSET_LINE_AUTHORITY,
        "summary": {
            "line_count": len(lines),
            "active_line_count": sum(1 for line in lines if line.deprecation_state == "active"),
            "context_segment_line_count": sum(1 for line in lines if line.asset_kind == "context_segment"),
            "issue_count": int(diagnostics.get("issue_count") or 0),
        },
        "physical_segments": _group(lines, "physical_segment"),
        "capability_groups": _group(lines, "capability_group"),
        "asset_owners": _group(lines, "asset_owner"),
        "lines": [line.to_dict() for line in lines],
        "diagnostics": diagnostics,
    }


def diagnose_system_asset_lines(lines: Iterable[SystemAssetLine]) -> dict[str, Any]:
    payload = tuple(lines or ())
    issues: list[dict[str, Any]] = []
    line_ids = [line.line_id for line in payload if line.line_id]
    duplicate_line_ids = sorted({line_id for line_id in line_ids if line_ids.count(line_id) > 1})
    for line_id in duplicate_line_ids:
        issues.append(_issue(line_id, "duplicate_line_id", "SystemAssetLine line_id must be unique."))
    for line in payload:
        if not line.line_id:
            issues.append(_issue("", "missing_line_id", "SystemAssetLine requires line_id."))
        if not line.asset_id:
            issues.append(_issue(line.line_id, "missing_asset_id", "SystemAssetLine requires asset_id."))
        if not line.asset_owner:
            issues.append(_issue(line.line_id, "missing_asset_owner", "SystemAssetLine requires asset_owner."))
        if not line.producer_ref:
            issues.append(_issue(line.line_id, "missing_producer_ref", "SystemAssetLine requires producer_ref."))
        if not line.consumer_domain:
            issues.append(_issue(line.line_id, "missing_consumer_domain", "SystemAssetLine requires consumer_domain."))
        if line.physical_segment not in {STATIC_PREFIX, CONTEXT_MEMORY_PREFIX, CONTEXT_APPEND, DYNAMIC_TAIL}:
            issues.append(
                _issue(
                    line.line_id,
                    "invalid_physical_segment",
                    "SystemAssetLine physical_segment must map to one of the four context sections.",
                    details={"physical_segment": line.physical_segment},
                )
            )
        if not line.activation_policy_ref:
            issues.append(_issue(line.line_id, "missing_activation_policy_ref", "SystemAssetLine requires activation_policy_ref."))
        if not line.terminal_policy:
            issues.append(_issue(line.line_id, "missing_terminal_policy", "SystemAssetLine requires terminal_policy."))
    return {
        "authority": f"{SYSTEM_ASSET_LINE_AUTHORITY}.diagnostics",
        "issue_count": len(issues),
        "issues": issues,
        "duplicate_line_ids": duplicate_line_ids,
    }


def context_line_state_for_asset_line(
    line: SystemAssetLine,
    *,
    invocation_id: str = "",
    session_id: str = "",
    task_run_id: str = "",
    status: str = "diagnostic_only",
    disabled_reason: str = "",
    source_ref: str = "",
    payload_ref: str = "",
    freshness: str = "",
    budget_class: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> ContextLineState:
    normalized_status = str(status or "").strip() or "diagnostic_only"
    if normalized_status not in {"enabled", "disabled", "unavailable", "blocked", "diagnostic_only"}:
        normalized_status = "diagnostic_only"
    return ContextLineState(
        line_id=line.line_id,
        invocation_id=str(invocation_id or "").strip(),
        session_id=str(session_id or "").strip(),
        task_run_id=str(task_run_id or "").strip(),
        status=normalized_status,
        disabled_reason=str(disabled_reason or "").strip(),
        source_ref=str(source_ref or line.producer_ref or "").strip(),
        payload_ref=str(payload_ref or "").strip(),
        freshness=str(freshness or "").strip(),
        budget_class=str(budget_class or "").strip(),
        diagnostics=dict(diagnostics or {}),
    )


def _line_diagnostics(
    declaration: ContextSegmentKindDeclaration,
    *,
    producer_ref: str,
) -> dict[str, Any]:
    return {
        "missing_explicit_producer_ref": not bool(str(producer_ref or "").strip()),
        "missing_semantic_slot": not bool(str(declaration.semantic_slot or "").strip()),
        "missing_capability_group": not bool(str(declaration.capability_group or "").strip()),
        "missing_source_kind": not bool(str(declaration.source_kind or "").strip()),
        "missing_content_source": not bool(str(declaration.content_source or "").strip()),
    }


def _transport_for_section(section: str) -> str:
    return {
        STATIC_PREFIX: "static_prompt_prefix",
        CONTEXT_MEMORY_PREFIX: "physical_prefix_frame_replay",
        CONTEXT_APPEND: "current_append_context",
        DYNAMIC_TAIL: "current_dynamic_tail",
    }.get(str(section or "").strip(), "unknown_context_transport")


def _lifecycle_for_section(section: str) -> str:
    return {
        STATIC_PREFIX: "session_stable",
        CONTEXT_MEMORY_PREFIX: "confirmed_provider_replay",
        CONTEXT_APPEND: "current_turn_append",
        DYNAMIC_TAIL: "current_turn_volatile",
    }.get(str(section or "").strip(), "unknown_lifecycle")


def _sealability_for_section(section: str, *, append_only: bool) -> str:
    if section == STATIC_PREFIX:
        return "static_not_memory"
    if section == CONTEXT_MEMORY_PREFIX:
        return "sealed_replay"
    if section == CONTEXT_APPEND:
        return "append_then_seal" if append_only else "append_candidate"
    if section == DYNAMIC_TAIL:
        return "never_seal"
    return "unknown_sealability"


def _provider_visibility_for_section(section: str) -> str:
    return {
        STATIC_PREFIX: "static_provider_context",
        CONTEXT_MEMORY_PREFIX: "sealed_provider_visible_context",
        CONTEXT_APPEND: "current_append_context",
        DYNAMIC_TAIL: "current_dynamic_tail",
    }.get(str(section or "").strip(), "provider_visibility_unknown")


def _terminal_policy_for_section(section: str) -> str:
    return {
        STATIC_PREFIX: "missing static line fails packet assembly or emits structural diagnostic",
        CONTEXT_MEMORY_PREFIX: "missing confirmed frame does not fabricate old context",
        CONTEXT_APPEND: "unavailable current append is omitted with diagnostic, not replayed as old context",
        DYNAMIC_TAIL: "dynamic tail expires at turn boundary unless re-emitted as observation",
    }.get(str(section or "").strip(), "unknown section emits structural diagnostic")


def _identity_key_for_declaration(declaration: ContextSegmentKindDeclaration) -> str:
    return _first_text(
        declaration.content_source,
        declaration.source_kind,
        declaration.semantic_slot,
        declaration.kind,
    )


def _activation_policy_ref(declaration: ContextSegmentKindDeclaration) -> str:
    if declaration.capability_group:
        return f"context_capability:{declaration.capability_group}:{declaration.capability_slot or 'default'}"
    if declaration.contract_slot:
        return f"context_contract_slot:{declaration.contract_slot}"
    return f"context_segment_policy:{declaration.kind}"


def _group(lines: Iterable[SystemAssetLine], attr: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for line in lines:
        key = str(getattr(line, attr) or "missing")
        grouped.setdefault(key, []).append(line.line_id)
    return grouped


def _issue(
    line_id: str,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": str(code or "").strip(),
        "message": str(message or "").strip(),
        "line_id": str(line_id or "").strip(),
        "authority": f"{SYSTEM_ASSET_LINE_AUTHORITY}.diagnostics",
        "details": dict(details or {}),
    }


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
