from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ToolObservationStatus = Literal["ok", "error", "denied", "needs_approval", "needs_contract"]


@dataclass(frozen=True, slots=True)
class ToolObservation:
    observation_id: str
    invocation_id: str
    caller_kind: str
    caller_ref: str
    tool_name: str
    operation_id: str
    status: ToolObservationStatus
    text: str = ""
    result_ref: str = ""
    result_envelope: dict[str, Any] = field(default_factory=dict)
    operation_gate: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.tool_runtime.tool_observation"

    def __post_init__(self) -> None:
        if self.authority != "runtime.tool_runtime.tool_observation":
            raise ValueError("ToolObservation authority must be runtime.tool_runtime.tool_observation")
        if not self.observation_id:
            raise ValueError("ToolObservation requires observation_id")
        if not self.invocation_id:
            raise ValueError("ToolObservation requires invocation_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result_envelope"] = dict(self.result_envelope or {})
        payload["operation_gate"] = dict(self.operation_gate or {})
        payload["execution_receipt"] = dict(self.execution_receipt or {})
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload

    def to_task_observation(self, *, task_run_id: str, request_ref: str = "", directive_ref: str = "") -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "task_run_id": task_run_id,
            "observation_type": "tool_result" if self.status == "ok" else "executor_error",
            "source": f"tool:{self.tool_name}",
            "request_ref": request_ref,
            "directive_ref": directive_ref,
            "content_chars": len(self.text),
            "payload": self.to_dict(),
            "needs_model_followup": self.status != "ok",
            "authority": "orchestration.runtime_observation",
        }

    def to_turn_observation_event(self) -> dict[str, Any]:
        return {
            "type": "tool_observation",
            "tool_observation": self.to_dict(),
        }

    def to_model_followup_context(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "operation_id": self.operation_id,
            "status": self.status,
            "text": self.text,
            "result_ref": self.result_ref,
            "diagnostics": dict(self.diagnostics or {}),
        }
