from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from permissions import ApprovalState, ApprovalToken


APPROVAL_GRANT_KIND = "task_tool_approval_grant"


@dataclass(frozen=True, slots=True)
class TaskToolApprovalGrant:
    grant_id: str
    task_run_id: str
    action_request_ref: str
    tool_call_id: str
    tool_name: str
    operation_id: str
    directive_ref: str
    approval_risk_fingerprint: str
    tool_args_hash: str
    granted: bool
    requested_by: str = "user"
    granted_at: float = 0.0
    expires_at: float = 0.0
    source: str = "task_tool_approval_api"
    pending_approval_ref: str = ""
    consumed: bool = False
    consumed_at: float = 0.0
    token_id: str = ""
    authority: str = "harness.loop.task_tool_approval"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.task_tool_approval":
            raise ValueError("TaskToolApprovalGrant authority must be harness.loop.task_tool_approval")
        if not self.grant_id:
            raise ValueError("TaskToolApprovalGrant requires grant_id")
        if not self.task_run_id:
            raise ValueError("TaskToolApprovalGrant requires task_run_id")
        if not self.operation_id:
            raise ValueError("TaskToolApprovalGrant requires operation_id")
        if not self.directive_ref:
            raise ValueError("TaskToolApprovalGrant requires directive_ref")
        if not self.approval_risk_fingerprint:
            raise ValueError("TaskToolApprovalGrant requires approval_risk_fingerprint")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload

    def to_token(self) -> ApprovalToken:
        return ApprovalToken(
            token_id=self.token_id or f"approval-token:{self.grant_id}",
            operation_id=self.operation_id,
            directive_ref=self.directive_ref,
            granted=self.granted and not self.consumed,
            source=self.source,
            risk_fingerprint=self.approval_risk_fingerprint,
        )


def pending_approval_from_task_run(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    pending = diagnostics.get("pending_approval")
    return dict(pending or {}) if isinstance(pending, dict) else {}


def build_task_tool_approval_grant(
    *,
    task_run: Any,
    pending_approval: dict[str, Any],
    requested_by: str,
    ttl_seconds: float = 3600.0,
    reason: str = "",
) -> TaskToolApprovalGrant | None:
    pending = dict(pending_approval or {})
    task_run_id = str(getattr(task_run, "task_run_id", "") or pending.get("task_run_id") or "")
    action_request_ref = str(pending.get("action_request_ref") or "").strip()
    tool_call_id = str(pending.get("tool_call_id") or action_request_ref).strip()
    tool_name = str(pending.get("tool_name") or "").strip()
    operation_id = str(pending.get("operation_id") or "").strip()
    directive_ref = str(pending.get("directive_ref") or "").strip()
    fingerprint = str(pending.get("approval_risk_fingerprint") or "").strip()
    if not (task_run_id and operation_id and directive_ref and fingerprint):
        return None
    now = time.time()
    identity = _stable_hash(
        {
            "task_run_id": task_run_id,
            "action_request_ref": action_request_ref,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "operation_id": operation_id,
            "directive_ref": directive_ref,
            "approval_risk_fingerprint": fingerprint,
        }
    )[:24]
    grant_id = f"approval-grant:{task_run_id}:{identity}"
    return TaskToolApprovalGrant(
        grant_id=grant_id,
        task_run_id=task_run_id,
        action_request_ref=action_request_ref,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        operation_id=operation_id,
        directive_ref=directive_ref,
        approval_risk_fingerprint=fingerprint,
        tool_args_hash=str(pending.get("tool_args_hash") or "").strip(),
        granted=True,
        requested_by=str(requested_by or "user"),
        granted_at=now,
        expires_at=now + max(1.0, float(ttl_seconds or 3600.0)),
        source="task_tool_approval_api",
        pending_approval_ref=str(pending.get("approval_request_id") or pending.get("observation_ref") or "").strip(),
        token_id=f"approval-token:{identity}:{uuid.uuid4().hex[:8]}",
        diagnostics={
            "reason": str(reason or ""),
            "pending_approval": _public_pending_approval(pending),
        },
    )


def approval_state_for_task_run(task_run: Any) -> ApprovalState:
    grants = task_tool_approval_grants(task_run)
    tokens = tuple(grant.to_token() for grant in grants if grant.granted and not grant.consumed and not grant_expired(grant))
    return ApprovalState(tokens=tokens)


def matching_approval_grant_for_pending(task_run: Any) -> TaskToolApprovalGrant | None:
    pending = pending_approval_from_task_run(task_run)
    if str(pending.get("status") or "") not in {"pending", "approved"}:
        return None
    for grant in task_tool_approval_grants(task_run):
        if not grant_matches_pending(grant, pending):
            continue
        if grant.granted and not grant.consumed and not grant_expired(grant):
            return grant
    return None


def task_tool_approval_grants(task_run: Any) -> tuple[TaskToolApprovalGrant, ...]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    approvals = diagnostics.get("approval_state")
    if not isinstance(approvals, dict):
        return ()
    grants: list[TaskToolApprovalGrant] = []
    for item in list(approvals.get("grants") or []):
        if not isinstance(item, dict):
            continue
        try:
            grants.append(_grant_from_payload(item))
        except Exception:
            continue
    return tuple(grants)


def append_task_tool_approval_grant(task_run: Any, grant: TaskToolApprovalGrant) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    state = dict(diagnostics.get("approval_state") or {}) if isinstance(diagnostics.get("approval_state"), dict) else {}
    grants = [
        dict(item)
        for item in list(state.get("grants") or [])
        if isinstance(item, dict) and str(item.get("grant_id") or "") != grant.grant_id
    ]
    grants.append(grant.to_dict())
    state = {
        **state,
        "status": "approved",
        "latest_grant_id": grant.grant_id,
        "grants": grants,
        "authority": "harness.loop.task_tool_approval",
    }
    return {**diagnostics, "approval_state": state}


def consume_matching_task_tool_approval(task_run: Any, *, operation_id: str, directive_ref: str, approval_risk_fingerprint: str) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    state = dict(diagnostics.get("approval_state") or {}) if isinstance(diagnostics.get("approval_state"), dict) else {}
    changed = False
    grants: list[dict[str, Any]] = []
    now = time.time()
    for item in list(state.get("grants") or []):
        if not isinstance(item, dict):
            continue
        grant = _grant_from_payload(item)
        if (
            not changed
            and grant.granted
            and not grant.consumed
            and not grant_expired(grant)
            and grant.operation_id == str(operation_id or "")
            and grant.directive_ref == str(directive_ref or "")
            and grant.approval_risk_fingerprint == str(approval_risk_fingerprint or "")
        ):
            item = {**dict(item), "consumed": True, "consumed_at": now}
            changed = True
        grants.append(dict(item))
    if not changed:
        return diagnostics
    state = {
        **state,
        "status": "consumed",
        "grants": grants,
        "consumed_at": now,
        "authority": "harness.loop.task_tool_approval",
    }
    payload = {**diagnostics, "approval_state": state}
    pending = dict(payload.get("pending_approval") or {}) if isinstance(payload.get("pending_approval"), dict) else {}
    if pending and str(pending.get("operation_id") or "") == str(operation_id or ""):
        payload["pending_approval"] = {**pending, "status": "consumed", "consumed_at": now}
    return payload


def grant_matches_pending(grant: TaskToolApprovalGrant, pending_approval: dict[str, Any]) -> bool:
    pending = dict(pending_approval or {})
    return (
        grant.task_run_id == str(pending.get("task_run_id") or "")
        and grant.action_request_ref == str(pending.get("action_request_ref") or "")
        and grant.operation_id == str(pending.get("operation_id") or "")
        and grant.directive_ref == str(pending.get("directive_ref") or "")
        and grant.approval_risk_fingerprint == str(pending.get("approval_risk_fingerprint") or "")
    )


def grant_expired(grant: TaskToolApprovalGrant) -> bool:
    return bool(grant.expires_at and grant.expires_at < time.time())


def tool_args_hash(tool_args: dict[str, Any]) -> str:
    return "sha256:" + _stable_hash(tool_args)


def _grant_from_payload(payload: dict[str, Any]) -> TaskToolApprovalGrant:
    data = dict(payload or {})
    return TaskToolApprovalGrant(
        grant_id=str(data.get("grant_id") or ""),
        task_run_id=str(data.get("task_run_id") or ""),
        action_request_ref=str(data.get("action_request_ref") or ""),
        tool_call_id=str(data.get("tool_call_id") or ""),
        tool_name=str(data.get("tool_name") or ""),
        operation_id=str(data.get("operation_id") or ""),
        directive_ref=str(data.get("directive_ref") or ""),
        approval_risk_fingerprint=str(data.get("approval_risk_fingerprint") or ""),
        tool_args_hash=str(data.get("tool_args_hash") or ""),
        granted=bool(data.get("granted") is True),
        requested_by=str(data.get("requested_by") or "user"),
        granted_at=float(data.get("granted_at") or 0.0),
        expires_at=float(data.get("expires_at") or 0.0),
        source=str(data.get("source") or "task_tool_approval_api"),
        pending_approval_ref=str(data.get("pending_approval_ref") or ""),
        consumed=bool(data.get("consumed") is True),
        consumed_at=float(data.get("consumed_at") or 0.0),
        token_id=str(data.get("token_id") or ""),
        authority=str(data.get("authority") or "harness.loop.task_tool_approval"),
        diagnostics=dict(data.get("diagnostics") or {}) if isinstance(data.get("diagnostics"), dict) else {},
    )


def _public_pending_approval(pending: dict[str, Any]) -> dict[str, Any]:
    return {
        key: pending.get(key)
        for key in (
            "task_run_id",
            "action_request_ref",
            "tool_call_id",
            "tool_name",
            "operation_id",
            "directive_ref",
            "approval_risk_fingerprint",
            "tool_args_hash",
            "created_at",
        )
        if pending.get(key) is not None
    }


def _stable_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
