from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RECOVERY_BOUNDARY_RECEIPT_AUTHORITY = "harness.continuation.recovery_boundary_receipt"
RECOVERY_RESUME_DECISION = "resume_recoverable_work"


@dataclass(frozen=True, slots=True)
class RecoveryResumeAvailability:
    observed: bool
    available: bool
    reason: str
    receipt_id: str = ""
    decision_id: str = ""
    boundary_decision: str = ""
    continuation_ref: str = ""
    task_run_ref: str = ""
    authority: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed": self.observed,
            "available": self.available,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "decision_id": self.decision_id,
            "boundary_decision": self.boundary_decision,
            "continuation_ref": self.continuation_ref,
            "task_run_ref": self.task_run_ref,
            "authority": self.authority,
        }


def recovery_resume_availability_from_receipt(receipt: dict[str, Any] | Any | None) -> RecoveryResumeAvailability:
    payload = _payload_from_receipt(receipt)
    operations = dict(payload.get("operation_availability") or {})
    observed = "resume_recoverable_work" in operations
    requested_available = operations.get("resume_recoverable_work") is True
    receipt_id = str(payload.get("receipt_id") or "").strip()
    decision_id = str(payload.get("decision_id") or "").strip()
    boundary_decision = str(payload.get("boundary_decision") or "").strip()
    continuation_ref = str(payload.get("continuation_ref") or "").strip()
    task_run_ref = str(payload.get("task_run_ref") or "").strip()
    authority = str(payload.get("authority") or "").strip()
    enforced = payload.get("enforced") is True
    route = str(payload.get("resume_execution_route") or "").strip()
    reason = ""
    if not observed:
        reason = "resume_recoverable_work_not_observed"
    elif not requested_available:
        reason = "resume_recoverable_work_not_available"
    elif authority != RECOVERY_BOUNDARY_RECEIPT_AUTHORITY:
        reason = "recovery_receipt_authority_invalid"
    elif boundary_decision != RECOVERY_RESUME_DECISION:
        reason = "recovery_receipt_boundary_decision_not_resumable"
    elif not receipt_id:
        reason = "recovery_receipt_id_missing"
    elif not decision_id:
        reason = "recovery_receipt_decision_id_missing"
    elif not continuation_ref:
        reason = "recovery_receipt_continuation_ref_missing"
    elif not task_run_ref:
        reason = "recovery_receipt_task_run_ref_missing"
    elif not enforced:
        reason = "recovery_receipt_not_enforced"
    elif not route:
        reason = "recovery_receipt_resume_route_missing"
    else:
        reason = "resume_recoverable_work_available"
    return RecoveryResumeAvailability(
        observed=observed,
        available=reason == "resume_recoverable_work_available",
        reason=reason,
        receipt_id=receipt_id,
        decision_id=decision_id,
        boundary_decision=boundary_decision,
        continuation_ref=continuation_ref,
        task_run_ref=task_run_ref,
        authority=authority,
    )


def recovery_boundary_receipt_allows_resume(receipt: dict[str, Any] | Any | None) -> bool:
    return recovery_resume_availability_from_receipt(receipt).available


def recovery_operation_availability_from_receipt(receipt: dict[str, Any] | Any | None) -> dict[str, Any]:
    payload = _payload_from_receipt(receipt)
    operations = dict(payload.get("operation_availability") or {})
    if "resume_recoverable_work" in operations:
        operations["resume_recoverable_work"] = recovery_boundary_receipt_allows_resume(payload)
    return operations


def _payload_from_receipt(receipt: dict[str, Any] | Any | None) -> dict[str, Any]:
    if receipt is None:
        return {}
    if hasattr(receipt, "to_dict"):
        return dict(receipt.to_dict())
    if isinstance(receipt, dict):
        return dict(receipt)
    return {}
