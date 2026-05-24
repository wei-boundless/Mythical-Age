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
        "repair_instruction": str(repair_instruction or ""),
        "diagnostics": dict(diagnostics or {}),
    }
    return build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=request_ref,
        directive_ref=directive_ref,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=dict(tool_args or {}),
        result=payload,
        execution_receipt=dict(execution_receipt or {}),
        result_envelope={
            "structured_payload": payload,
            "status": "error",
            "tool_name": tool_name,
            "tool_args": dict(tool_args or {}),
            "execution_receipt": dict(execution_receipt or {}),
        },
    )
