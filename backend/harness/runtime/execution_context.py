from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    execution_context_id: str
    packet_ref: str
    action_request_ref: str
    admission_ref: str
    tool_name: str
    operation_id: str
    workspace_root: str
    permission_snapshot: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 60
    idempotency_key: str = ""
    authority: str = "harness.runtime.execution_context"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.execution_context":
            raise ValueError("ExecutionContext authority must be harness.runtime.execution_context")
        if not self.packet_ref:
            raise ValueError("ExecutionContext requires packet_ref")
        if not self.action_request_ref:
            raise ValueError("ExecutionContext requires action_request_ref")
        if not self.admission_ref:
            raise ValueError("ExecutionContext requires admission_ref")
        if not self.tool_name:
            raise ValueError("ExecutionContext requires tool_name")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_execution_context(
    *,
    packet_ref: str,
    action_request_ref: str,
    admission_ref: str,
    tool_name: str,
    operation_id: str,
    workspace_root: Path,
    permission_snapshot: dict[str, Any] | None = None,
) -> ExecutionContext:
    stable_raw = "::".join(
        [
            str(packet_ref or ""),
            str(action_request_ref or ""),
            str(tool_name or ""),
            str(operation_id or ""),
        ]
    )
    stable_digest = hashlib.sha256(stable_raw.encode("utf-8")).hexdigest()[:16]
    return ExecutionContext(
        execution_context_id=f"execctx:{stable_digest}",
        packet_ref=packet_ref,
        action_request_ref=action_request_ref,
        admission_ref=admission_ref,
        tool_name=tool_name,
        operation_id=operation_id,
        workspace_root=str(Path(workspace_root).resolve()),
        permission_snapshot=dict(permission_snapshot or {}),
        idempotency_key=f"{packet_ref}:{action_request_ref}:{tool_name}:{operation_id}",
    )
