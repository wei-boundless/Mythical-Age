from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RuntimeActionRequestType = Literal[
    "model_response",
    "tool_call",
    "mcp_call",
    "agent_call",
]

RuntimeObservationType = Literal[
    "model_response",
    "tool_result",
    "mcp_result",
    "agent_result",
    "executor_error",
]


@dataclass(frozen=True, slots=True)
class RuntimeActionRequest:
    """A request produced inside the loop before any executor dispatch."""

    request_id: str
    task_run_id: str
    request_type: RuntimeActionRequestType
    step_id: str = ""
    directive_ref: str = ""
    operation_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "orchestration.runtime_action_request"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_action_request":
            raise ValueError("RuntimeActionRequest authority must be orchestration.runtime_action_request")
        if not self.request_id:
            raise ValueError("RuntimeActionRequest requires request_id")
        if not self.task_run_id:
            raise ValueError("RuntimeActionRequest requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    """Executor output normalized for loop continuation."""

    observation_id: str
    task_run_id: str
    observation_type: RuntimeObservationType
    source: str
    request_ref: str = ""
    directive_ref: str = ""
    content_chars: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    needs_model_followup: bool = False
    created_at: float = 0.0
    authority: str = "orchestration.runtime_observation"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_observation":
            raise ValueError("RuntimeObservation authority must be orchestration.runtime_observation")
        if not self.observation_id:
            raise ValueError("RuntimeObservation requires observation_id")
        if not self.task_run_id:
            raise ValueError("RuntimeObservation requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_model_response_observation(task_run_id: str, event: dict[str, Any]) -> RuntimeObservation:
    content = str(event.get("content") or "")
    directive_ref = str(event.get("directive_ref") or "")
    return RuntimeObservation(
        observation_id=f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        task_run_id=task_run_id,
        observation_type="model_response",
        source=str(event.get("source") or "runtime_directive:model_response"),
        directive_ref=directive_ref,
        content_chars=len(content),
        payload={
            "content_chars": len(content),
            "answer_channel": str(event.get("answer_channel") or ""),
            "answer_source": str(event.get("answer_source") or ""),
        },
        needs_model_followup=False,
        created_at=time.time(),
    )


def build_executor_error_observation(task_run_id: str, event: dict[str, Any]) -> RuntimeObservation:
    error = str(event.get("error") or "")
    code = str(event.get("code") or "")
    provider = str(event.get("provider") or "")
    model = str(event.get("model") or "")
    detail = str(event.get("detail") or "")
    return RuntimeObservation(
        observation_id=f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        task_run_id=task_run_id,
        observation_type="executor_error",
        source=str(event.get("answer_source") or "runtime_executor"),
        content_chars=len(error),
        payload={
            "error": error,
            "code": code,
            "provider": provider,
            "model": model,
            "detail": detail,
            "answer_source": str(event.get("answer_source") or ""),
        },
        needs_model_followup=False,
        created_at=time.time(),
    )


def build_tool_result_observation(
    *,
    task_run_id: str,
    request_ref: str,
    directive_ref: str,
    tool_name: str,
    result: Any,
    tool_args: dict[str, Any] | None = None,
    tool_call_id: str = "",
    truncated: bool = False,
    execution_receipt: dict[str, Any] | None = None,
    result_ref: str = "",
    result_envelope: dict[str, Any] | None = None,
) -> RuntimeObservation:
    content = str(result or "")
    receipt = dict(execution_receipt or {})
    envelope = dict(result_envelope or {})
    structured_payload = dict(envelope.get("structured_payload") or {})
    observed_paths = [
        str(item).strip()
        for item in list(envelope.get("observed_paths") or structured_payload.get("observed_paths") or [])
        if str(item).strip()
    ]
    matched_paths = [
        str(item).strip()
        for item in list(envelope.get("matched_paths") or structured_payload.get("matched_paths") or [])
        if str(item).strip()
    ]
    artifact_refs = [
        dict(item)
        for item in list(envelope.get("artifact_refs") or structured_payload.get("artifact_refs") or [])
        if isinstance(item, dict)
    ]
    command_receipt = dict(envelope.get("command_receipt") or structured_payload.get("command_receipt") or {})
    return RuntimeObservation(
        observation_id=f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        task_run_id=task_run_id,
        observation_type="tool_result",
        source=f"tool:{tool_name}",
        request_ref=request_ref,
        directive_ref=directive_ref,
        content_chars=len(content),
        payload={
            "tool_name": str(tool_name or ""),
            "tool_call_id": str(tool_call_id or ""),
            "tool_args": dict(tool_args or {}),
            "result": content,
            "result_chars": len(content),
            "truncated": truncated,
            "execution_receipt": receipt,
            "execution_id": str(receipt.get("execution_id") or ""),
            "result_ref": str(result_ref or receipt.get("result_ref") or ""),
            "result_envelope": envelope,
            "structured_payload": structured_payload,
            "observed_paths": observed_paths,
            "matched_paths": matched_paths,
            "artifact_refs": artifact_refs,
            "command_receipt": command_receipt,
        },
        needs_model_followup=True,
        created_at=time.time(),
    )


def build_tool_execution_error_observation(
    *,
    task_run_id: str,
    request_ref: str,
    directive_ref: str,
    tool_name: str,
    error: str,
    tool_args: dict[str, Any] | None = None,
    tool_call_id: str = "",
    execution_receipt: dict[str, Any] | None = None,
) -> RuntimeObservation:
    message = str(error or "").strip() or "tool_execution_failed"
    receipt = dict(execution_receipt or {})
    return RuntimeObservation(
        observation_id=f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        task_run_id=task_run_id,
        observation_type="executor_error",
        source=f"tool:{tool_name}",
        request_ref=request_ref,
        directive_ref=directive_ref,
        content_chars=len(message),
        payload={
            "tool_name": str(tool_name or ""),
            "tool_call_id": str(tool_call_id or ""),
            "tool_args": dict(tool_args or {}),
            "error": message,
            "execution_receipt": receipt,
            "execution_id": str(receipt.get("execution_id") or ""),
        },
        needs_model_followup=False,
        created_at=time.time(),
    )


def build_recoverable_tool_invocation_observation(
    *,
    task_run_id: str,
    request_ref: str,
    directive_ref: str,
    tool_name: str,
    error: str,
    tool_args: dict[str, Any] | None = None,
    tool_call_id: str = "",
    execution_receipt: dict[str, Any] | None = None,
    invocation_validation: dict[str, Any] | None = None,
) -> RuntimeObservation:
    message = str(error or "").strip() or "tool_invocation_validation_error"
    validation = dict(invocation_validation or {})
    required_inputs = [
        str(item).strip()
        for item in list(dict(validation.get("contract") or {}).get("required_inputs") or [])
        if str(item).strip()
    ]
    missing_inputs = [
        str(item).strip()
        for item in list(validation.get("missing_inputs") or [])
        if str(item).strip()
    ]
    repair_lines = [
        f"Tool call rejected by invocation validation for `{tool_name}`.",
        message,
    ]
    if missing_inputs:
        repair_lines.append("Missing required input(s): " + ", ".join(missing_inputs) + ".")
    if required_inputs:
        repair_lines.append("Retry the same tool using exactly these argument names: " + ", ".join(required_inputs) + ".")
    repair_lines.append("Do not finish the task until the corrected tool call succeeds or a non-recoverable blocker is observed.")
    receipt = dict(execution_receipt or {})
    return RuntimeObservation(
        observation_id=f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        task_run_id=task_run_id,
        observation_type="tool_result",
        source=f"tool:{tool_name}:invocation_validation_repair",
        request_ref=request_ref,
        directive_ref=directive_ref,
        content_chars=len("\n".join(repair_lines)),
        payload={
            "tool_name": str(tool_name or ""),
            "tool_call_id": str(tool_call_id or ""),
            "tool_args": dict(tool_args or {}),
            "result": "\n".join(repair_lines),
            "result_chars": len("\n".join(repair_lines)),
            "truncated": False,
            "execution_receipt": receipt,
            "execution_id": str(receipt.get("execution_id") or ""),
            "recoverable": True,
            "repair_kind": "tool_invocation_validation",
            "invocation_validation": validation,
            "missing_inputs": missing_inputs,
            "required_inputs": required_inputs,
        },
        needs_model_followup=True,
        created_at=time.time(),
    )


def build_tool_action_request(task_run_id: str, event: dict[str, Any], *, step_id: str = "") -> RuntimeActionRequest:
    payload = dict(event.get("tool_call") or event.get("payload") or {})
    tool_name = str(payload.get("tool_name") or payload.get("name") or event.get("tool_name") or "")
    assistant_content_preview = str(event.get("assistant_content") or "").strip()
    return RuntimeActionRequest(
        request_id=f"rtact:{task_run_id}:{uuid.uuid4().hex[:8]}",
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id=str(step_id or ""),
        directive_ref=str(event.get("directive_ref") or ""),
        operation_id=str(event.get("operation_id") or ""),
        payload={
            "tool_name": tool_name,
            "tool_call": payload,
            "execution_state": "requested_not_dispatched",
            "assistant_content_preview": assistant_content_preview,
        },
        created_at=time.time(),
    )


