from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from .decision_models import PermissionDecision


@dataclass(frozen=True, slots=True)
class PermissionReceipt:
    receipt_id: str
    task_run_id: str
    agent_run_id: str
    tool_call_id: str
    operation_id: str
    behavior: str
    tool_name: str = ""
    approval_fingerprint: str = ""
    risk_level: str = "none"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "permissions.permission_receipt"

    @classmethod
    def from_decision(
        cls,
        *,
        task_run_id: str,
        agent_run_id: str,
        tool_call_id: str,
        decision: PermissionDecision,
        metadata: dict[str, Any] | None = None,
    ) -> "PermissionReceipt":
        receipt_id = _receipt_id(
            task_run_id,
            agent_run_id,
            tool_call_id,
            decision.operation_id,
            decision.behavior,
            decision.approval_fingerprint,
        )
        return cls(
            receipt_id=receipt_id,
            task_run_id=str(task_run_id or ""),
            agent_run_id=str(agent_run_id or ""),
            tool_call_id=str(tool_call_id or ""),
            operation_id=decision.operation_id,
            tool_name=decision.tool_name,
            behavior=decision.behavior,
            approval_fingerprint=decision.approval_fingerprint,
            risk_level=decision.risk_level,
            reason=decision.reason,
            metadata={**dict(metadata or {}), "decision_authority": decision.authority},
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "task_run_id": self.task_run_id,
            "agent_run_id": self.agent_run_id,
            "tool_call_id": self.tool_call_id,
            "operation_id": self.operation_id,
            "tool_name": self.tool_name,
            "behavior": self.behavior,
            "approval_fingerprint": self.approval_fingerprint,
            "risk_level": self.risk_level,
            "authority": self.authority,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _receipt_id(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"permrec:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


