from __future__ import annotations

from typing import Any

from runtime.shared.action_request import RuntimeObservation, build_tool_result_observation


def build_policy_rejection_observation(
    *,
    task_run_id: str,
    request_ref: str,
    directive_ref: str,
    tool_name: str,
    tool_call_id: str = "",
    tool_args: dict[str, Any] | None = None,
    policy: str,
    reason: str,
    repair_instruction: str = "",
    diagnostics: dict[str, Any] | None = None,
    execution_receipt: dict[str, Any] | None = None,
) -> RuntimeObservation:
    payload = {
        "type": "tool_policy_rejection",
        "policy": str(policy or ""),
        "reason": str(reason or ""),
        "requested_tool": str(tool_name or ""),
        "requested_args": dict(tool_args or {}),
        "tool_executed": False,
        "is_tool_execution_failure": False,
        "evidence_semantics": (
            "This observation means the runtime policy blocked the requested tool call before execution. "
            "It is not evidence that the requested file, command, or external resource failed."
        ),
        "repair_instruction": str(repair_instruction or ""),
        "diagnostics": dict(diagnostics or {}),
    }
    result_text = (
        "tool_policy_rejection: "
        f"Policy rejected before execution: requested_tool={tool_name}; "
        f"policy={policy}; reason={reason}. "
        "No tool side effect occurred; do not treat this as a file read, command, or resource failure. "
        f"Repair: {repair_instruction or reason}"
    )
    return build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=request_ref,
        directive_ref=directive_ref,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=dict(tool_args or {}),
        result=result_text,
        execution_receipt=dict(execution_receipt or {}),
        result_envelope={
            "structured_payload": payload,
            "status": "error",
            "tool_name": tool_name,
            "tool_args": dict(tool_args or {}),
            "execution_receipt": dict(execution_receipt or {}),
        },
    )
