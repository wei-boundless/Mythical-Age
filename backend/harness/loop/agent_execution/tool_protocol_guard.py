from __future__ import annotations

from typing import Any

from runtime.shared.action_request import build_tool_result_observation

from .event_translation import append_executor_observation_event, append_tool_result_received_event


TOOL_PROTOCOL_GUARD_SOURCE = "harness.loop.agent_execution.tool_protocol_guard"


def append_synthetic_tool_result_for_action_request(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    action_request: Any,
    directive_ref: str = "",
    reason: str,
    step_ref: str = "",
    refs: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> list[Any]:
    tool_call = dict(action_request.payload.get("tool_call") or {})
    tool_name = str(action_request.payload.get("tool_name") or tool_call.get("name") or "")
    observation = build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=str(action_request.request_id or ""),
        directive_ref=str(directive_ref or action_request.directive_ref or ""),
        tool_name=tool_name,
        tool_call_id=str(tool_call.get("id") or action_request.request_id or ""),
        tool_args=dict(tool_call.get("args") or {}),
        result=str(reason or "tool_call_failed"),
        result_envelope={
            "status": "error",
            "synthetic_tool_result": True,
            "source": TOOL_PROTOCOL_GUARD_SOURCE,
            "diagnostics": dict(diagnostics or {}),
        },
    )
    context_record = runtime_context_manager.record_observation(observation)
    event_refs = {
        **dict(refs or {}),
        "action_request_ref": str(action_request.request_id or ""),
        "directive_ref": str(directive_ref or action_request.directive_ref or ""),
        "task_step_ref": str(step_ref or action_request.step_id or ""),
        "tool_protocol_guard": TOOL_PROTOCOL_GUARD_SOURCE,
    }
    protocol_event = event_log.append(
        task_run_id,
        "tool_protocol_guard_synthetic_result",
        payload={
            "reason": str(reason or "tool_call_failed"),
            "observation": observation.to_dict(),
            "context_record": context_record.to_dict(),
            "diagnostics": dict(diagnostics or {}),
        },
        refs=event_refs,
    )
    return [
        protocol_event,
        append_tool_result_received_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=observation,
            context_record=context_record,
            refs=event_refs,
        ),
        append_executor_observation_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=observation,
            context_record=context_record,
            refs=event_refs,
        ),
    ]


def tool_result_event_count_for_action_request(events: list[Any], action_request_ref: str) -> int:
    target = str(action_request_ref or "")
    if not target:
        return 0
    return sum(
        1
        for event in list(events or [])
        if str(getattr(event, "event_type", "") or "") == "tool_result_received"
        and str(dict(getattr(event, "refs", {}) or {}).get("action_request_ref") or "") == target
    )


