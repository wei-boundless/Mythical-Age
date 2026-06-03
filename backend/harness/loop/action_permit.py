from __future__ import annotations

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
    tool_name: str = ""
    operation_id: str = ""
    read_only: bool = False
    permission_mode: str = "default"
    side_effect_policy: str = ""
    allowed_action_types: tuple[str, ...] = ()
    allowed_tool_names: tuple[str, ...] = ()
    denied_reason: str = ""
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
) -> ActionPermit:
    permission_delta = dict(getattr(admission, "permission_delta", {}) or {})
    tool_call = dict(getattr(action_request, "tool_call", {}) or {})
    decision = str(getattr(admission, "decision", "") or "")
    denied_reason = "" if decision == "allow" else str(getattr(admission, "system_reason", "") or decision)
    tool_name = str(permission_delta.get("tool_name") or tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    operation_id = str(permission_delta.get("operation_id") or tool_name).strip()
    allowed_tools = tuple(sorted(str(item) for item in list(allowed_tool_names or ()) if str(item)))
    return ActionPermit(
        permit_id=f"action-permit:{getattr(action_request, 'request_id', '')}",
        action_request_ref=str(getattr(action_request, "request_id", "") or ""),
        action_type=str(getattr(action_request, "action_type", "") or ""),
        decision=decision,
        invocation_kind=str(invocation_kind or ""),
        tool_name=tool_name,
        operation_id=operation_id,
        read_only=bool(permission_delta.get("read_only") is True),
        permission_mode=str(permission_delta.get("permission_mode") or permission_mode or "default"),
        side_effect_policy=str(side_effect_policy or ""),
        allowed_action_types=tuple(str(item) for item in packet_allowed_action_types if str(item)),
        allowed_tool_names=allowed_tools,
        denied_reason=denied_reason,
        diagnostics={
            "admission_ref": str(getattr(admission, "admission_id", "") or ""),
            "admission_authority": str(getattr(admission, "authority", "") or ""),
            "permission_delta": permission_delta,
        },
    )


def validate_tool_invocation_permit(
    *,
    action_permit: dict[str, Any] | None,
    action_request_ref: str,
    invocation_kind: str,
    tool_name: str,
    operation_id: str,
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
    return ""
