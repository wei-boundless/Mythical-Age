from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CURRENT_WORK_BOUNDARY_RECEIPT_AUTHORITY = "harness.entrypoint.current_work_boundary_receipt"
CURRENT_WORK_CONTROL_REQUIRED_DECISION = "current_work_control_required"


@dataclass(frozen=True, slots=True)
class CurrentWorkControlAvailability:
    observed: bool
    available: bool
    reason: str
    receipt_id: str = ""
    decision_id: str = ""
    boundary_decision: str = ""
    task_run_ref: str = ""
    active_turn_ref: str = ""
    authority: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed": self.observed,
            "available": self.available,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "decision_id": self.decision_id,
            "boundary_decision": self.boundary_decision,
            "task_run_ref": self.task_run_ref,
            "active_turn_ref": self.active_turn_ref,
            "authority": self.authority,
        }


def current_work_control_availability_from_receipt(
    receipt: dict[str, Any] | Any | None,
) -> CurrentWorkControlAvailability:
    payload = _payload_from_receipt(receipt)
    operations = dict(payload.get("operation_availability") or {})
    observed = "active_work_control" in operations
    requested_available = operations.get("active_work_control") is True
    refs = dict(payload.get("active_work_ref") or {})
    receipt_id = str(payload.get("receipt_id") or "").strip()
    decision_id = str(payload.get("decision_id") or "").strip()
    boundary_decision = str(payload.get("boundary_decision") or "").strip()
    authority = str(payload.get("authority") or "").strip()
    task_run_ref = str(payload.get("task_run_ref") or refs.get("task_run_id") or "").strip()
    active_turn_ref = str(
        payload.get("actual_active_turn_id")
        or refs.get("actual_active_turn_id")
        or refs.get("active_work_id")
        or ""
    ).strip()
    reason = ""
    if not observed:
        reason = "active_work_control_not_observed"
    elif not requested_available:
        reason = "active_work_control_not_available"
    elif authority != CURRENT_WORK_BOUNDARY_RECEIPT_AUTHORITY:
        reason = "current_work_receipt_authority_invalid"
    elif boundary_decision != CURRENT_WORK_CONTROL_REQUIRED_DECISION:
        reason = "current_work_receipt_boundary_decision_not_controllable"
    elif not receipt_id:
        reason = "current_work_receipt_id_missing"
    elif not decision_id:
        reason = "current_work_receipt_decision_id_missing"
    elif not task_run_ref:
        reason = "current_work_receipt_task_run_ref_missing"
    elif not active_turn_ref:
        reason = "current_work_receipt_active_turn_ref_missing"
    else:
        reason = "active_work_control_available"
    return CurrentWorkControlAvailability(
        observed=observed,
        available=reason == "active_work_control_available",
        reason=reason,
        receipt_id=receipt_id,
        decision_id=decision_id,
        boundary_decision=boundary_decision,
        task_run_ref=task_run_ref,
        active_turn_ref=active_turn_ref,
        authority=authority,
    )


def current_work_boundary_receipt_allows_active_work_control(
    receipt: dict[str, Any] | Any | None,
) -> bool:
    return current_work_control_availability_from_receipt(receipt).available


def current_work_operation_availability_from_receipt(
    receipt: dict[str, Any] | Any | None,
) -> dict[str, Any]:
    payload = _payload_from_receipt(receipt)
    operations = dict(payload.get("operation_availability") or {})
    if "active_work_control" in operations:
        operations["active_work_control"] = current_work_boundary_receipt_allows_active_work_control(payload)
    return operations


def _payload_from_receipt(receipt: dict[str, Any] | Any | None) -> dict[str, Any]:
    if receipt is None:
        return {}
    if hasattr(receipt, "to_dict"):
        return dict(receipt.to_dict())
    if isinstance(receipt, dict):
        return dict(receipt)
    return {}
