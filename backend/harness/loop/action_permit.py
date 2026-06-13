from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .model_action_protocol import AnyModelActionRequest


@dataclass(frozen=True, slots=True)
class ActionPermit:
    permit_id: str
    action_request_ref: str
    action_type: str
    decision: str
    invocation_kind: str = ""
    session_id: str = ""
    turn_id: str = ""
    task_run_id: str = ""
    grant_scope: str = "turn"
    tool_name: str = ""
    operation_id: str = ""
    read_only: bool = False
    permission_mode: str = "default"
    side_effect_policy: str = ""
    risk_fingerprint: str = ""
    strict_review: bool = False
    approval_ref: str = ""
    resource_scope: dict[str, Any] = field(default_factory=dict)
    expires_at: float = 0.0
    consumed_at: float = 0.0
    allowed_action_types: tuple[str, ...] = ()
    allowed_tool_names: tuple[str, ...] = ()
    denied_reason: str = ""
    issue_category: str = ""
    issue_code: str = ""
    action_issue: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop.action_permit"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.action_permit":
            raise ValueError("ActionPermit authority must be harness.loop.action_permit")
        if not self.permit_id:
            raise ValueError("ActionPermit requires permit_id")
        if not self.action_request_ref:
            raise ValueError("ActionPermit requires action_request_ref")
        if not self.action_type:
            raise ValueError("ActionPermit requires action_type")

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_action_types"] = list(self.allowed_action_types)
        payload["allowed_tool_names"] = list(self.allowed_tool_names)
        payload["resource_scope"] = dict(self.resource_scope or {})
        payload["action_issue"] = dict(self.action_issue or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def action_permit_from_admission(
    action_request: AnyModelActionRequest,
    admission: Any,
    *,
    invocation_kind: str,
    packet_allowed_action_types: tuple[str, ...] = (),
    allowed_tool_names: set[str] | tuple[str, ...] | None = None,
    permission_mode: str = "default",
    side_effect_policy: str = "",
    session_id: str = "",
    turn_id: str = "",
    task_run_id: str = "",
    grant_scope: str = "",
    strict_review: bool | None = None,
    resource_scope: dict[str, Any] | None = None,
) -> ActionPermit:
    permission_delta = dict(getattr(admission, "permission_delta", {}) or {})
    action_issue = dict(getattr(admission, "action_issue", {}) or {})
    permission_request = dict(getattr(action_request, "permission_request", {}) or {})
    tool_call = dict(getattr(action_request, "tool_call", {}) or {})
    decision = str(getattr(admission, "decision", "") or "")
    denied_reason = "" if decision == "allow" else str(getattr(admission, "system_reason", "") or decision)
    tool_name = str(permission_delta.get("tool_name") or tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    operation_id = str(permission_delta.get("operation_id") or tool_name).strip()
    allowed_tools = tuple(sorted(str(item) for item in list(allowed_tool_names or ()) if str(item)))
    resolved_scope = str(permission_delta.get("grant_scope") or permission_request.get("grant_scope") or grant_scope or "").strip()
    if not resolved_scope:
        resolved_scope = "task_run" if str(invocation_kind or "") == "task_execution" else "turn"
    resolved_session_id = str(session_id or permission_delta.get("session_id") or permission_request.get("session_id") or "").strip()
    resolved_turn_id = str(turn_id or getattr(action_request, "turn_id", "") or permission_delta.get("turn_id") or permission_request.get("turn_id") or "").strip()
    resolved_task_run_id = str(task_run_id or permission_delta.get("task_run_id") or permission_request.get("task_run_id") or "").strip()
    resolved_resource_scope = {
        **dict(permission_delta.get("resource_scope") or {}),
        **dict(permission_request.get("resource_scope") or {}),
        **dict(resource_scope or {}),
    }
    risk_fingerprint = str(permission_delta.get("risk_fingerprint") or permission_request.get("risk_fingerprint") or "").strip()
    if not risk_fingerprint:
        risk_fingerprint = _risk_fingerprint(
            action_request_ref=str(getattr(action_request, "request_id", "") or ""),
            action_type=str(getattr(action_request, "action_type", "") or ""),
            invocation_kind=str(invocation_kind or ""),
            tool_name=tool_name,
            operation_id=operation_id,
            permission_mode=str(permission_delta.get("permission_mode") or permission_mode or "default"),
            grant_scope=resolved_scope,
        )
    return ActionPermit(
        permit_id=f"action-permit:{getattr(action_request, 'request_id', '')}",
        action_request_ref=str(getattr(action_request, "request_id", "") or ""),
        action_type=str(getattr(action_request, "action_type", "") or ""),
        decision=decision,
        invocation_kind=str(invocation_kind or ""),
        session_id=resolved_session_id,
        turn_id=resolved_turn_id,
        task_run_id=resolved_task_run_id,
        grant_scope=resolved_scope,
        tool_name=tool_name,
        operation_id=operation_id,
        read_only=bool(permission_delta.get("read_only") is True),
        permission_mode=str(permission_delta.get("permission_mode") or permission_mode or "default"),
        side_effect_policy=str(side_effect_policy or ""),
        risk_fingerprint=risk_fingerprint,
        strict_review=bool(
            permission_delta.get("strict_review")
            if strict_review is None
            else strict_review
        ),
        approval_ref=str(getattr(admission, "approval_request_ref", "") or permission_delta.get("approval_ref") or permission_request.get("approval_ref") or ""),
        resource_scope=resolved_resource_scope,
        expires_at=_safe_float(permission_delta.get("expires_at") or permission_request.get("expires_at")),
        consumed_at=_safe_float(permission_delta.get("consumed_at") or permission_request.get("consumed_at")),
        allowed_action_types=tuple(str(item) for item in packet_allowed_action_types if str(item)),
        allowed_tool_names=allowed_tools,
        denied_reason=denied_reason,
        issue_category=str(getattr(admission, "issue_category", "") or action_issue.get("category") or ""),
        issue_code=str(getattr(admission, "issue_code", "") or action_issue.get("code") or ""),
        action_issue=action_issue,
        diagnostics={
            "admission_ref": str(getattr(admission, "admission_id", "") or ""),
            "admission_authority": str(getattr(admission, "authority", "") or ""),
            "permission_delta": permission_delta,
            "action_issue": action_issue,
        },
    )


def validate_tool_invocation_permit(
    *,
    action_permit: dict[str, Any] | None,
    action_request_ref: str,
    invocation_kind: str,
    tool_name: str,
    operation_id: str,
    session_id: str = "",
    turn_id: str = "",
    task_run_id: str = "",
    approval_risk_fingerprint: str = "",
    now: float = 0.0,
) -> str:
    permit = dict(action_permit or {})
    if not permit:
        return "action_permit_missing"
    if str(permit.get("authority") or "") != "harness.loop.action_permit":
        return "action_permit_authority_invalid"
    if str(permit.get("decision") or "") != "allow":
        return "action_permit_not_allowed"
    if str(permit.get("action_type") or "") != "tool_call":
        return "action_permit_action_type_mismatch"
    if str(permit.get("action_request_ref") or "") != str(action_request_ref or ""):
        return "action_permit_request_ref_mismatch"
    if str(permit.get("invocation_kind") or "") != str(invocation_kind or ""):
        return "action_permit_invocation_kind_mismatch"
    if str(permit.get("tool_name") or "") != str(tool_name or ""):
        return "action_permit_tool_name_mismatch"
    if str(permit.get("operation_id") or "") != str(operation_id or ""):
        return "action_permit_operation_id_mismatch"
    grant_scope = str(permit.get("grant_scope") or "").strip()
    if grant_scope not in {"turn", "session", "task_run"}:
        return "action_permit_grant_scope_invalid"
    if grant_scope in {"turn", "task_run"} and not str(permit.get("turn_id") or "").strip():
        return "action_permit_turn_id_missing"
    if grant_scope in {"turn", "task_run"} and str(permit.get("turn_id") or "") != str(turn_id or ""):
        return "action_permit_turn_id_mismatch"
    if grant_scope in {"session", "task_run"} and not str(permit.get("session_id") or "").strip():
        return "action_permit_session_id_missing"
    if grant_scope in {"session", "task_run"} and str(permit.get("session_id") or "") != str(session_id or ""):
        return "action_permit_session_id_mismatch"
    if grant_scope == "task_run" and not str(permit.get("task_run_id") or "").strip():
        return "action_permit_task_run_id_missing"
    if grant_scope == "task_run" and str(permit.get("task_run_id") or "") != str(task_run_id or ""):
        return "action_permit_task_run_id_mismatch"
    if _safe_float(permit.get("consumed_at")) > 0:
        return "action_permit_already_consumed"
    expires_at = _safe_float(permit.get("expires_at"))
    if expires_at > 0 and (float(now or 0.0) > expires_at):
        return "action_permit_expired"
    if not str(permit.get("risk_fingerprint") or "").strip():
        return "action_permit_risk_fingerprint_missing"
    expected_approval_risk = str(approval_risk_fingerprint or "").strip()
    if expected_approval_risk:
        permit_resource_scope = dict(permit.get("resource_scope") or {})
        permit_approval_risk = str(
            permit.get("approval_risk_fingerprint")
            or permit_resource_scope.get("approval_risk_fingerprint")
            or ""
        ).strip()
        if not permit_approval_risk:
            return "action_permit_approval_risk_fingerprint_missing"
        if permit_approval_risk != expected_approval_risk:
            return "action_permit_approval_risk_fingerprint_mismatch"
    return ""


def _risk_fingerprint(
    *,
    action_request_ref: str,
    action_type: str,
    invocation_kind: str,
    tool_name: str,
    operation_id: str,
    permission_mode: str,
    grant_scope: str,
) -> str:
    payload = {
        "action_request_ref": action_request_ref,
        "action_type": action_type,
        "invocation_kind": invocation_kind,
        "tool_name": tool_name,
        "operation_id": operation_id,
        "permission_mode": permission_mode,
        "grant_scope": grant_scope,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"permit-risk:{digest[:24]}"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
