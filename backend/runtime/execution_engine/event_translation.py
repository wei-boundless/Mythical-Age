from __future__ import annotations

from typing import Any

from runtime.shared.action_request import (
    RuntimeObservation,
    build_executor_error_observation,
    build_model_response_observation,
    build_tool_result_observation,
)


def append_simple_executor_event(event_log: Any, task_run_id: str, event: dict[str, Any]) -> list[Any] | None:
    event_type = str(event.get("type") or "")
    if event_type == "runtime_directive":
        directive = dict(event.get("directive") or {})
        resource_policy = dict(event.get("resource_policy") or {})
        return [
            event_log.append(
                task_run_id,
                "runtime_directive_issued",
                payload={
                    "directive": directive,
                    "resource_policy": resource_policy,
                },
                refs={
                    "directive_ref": str(directive.get("directive_id") or ""),
                    "resource_policy_ref": str(resource_policy.get("policy_id") or ""),
                },
            )
        ]
    if event_type == "operation_gate":
        gate = dict(event.get("gate") or {})
        return [
            event_log.append(
                task_run_id,
                "operation_gate_checked",
                payload={"gate": gate},
                refs={"operation_id": str(gate.get("operation_id") or "")},
            )
        ]
    if event_type == "content_delta":
        delta_text = str(event.get("content") or "")
        delta_preview = delta_text if len(delta_text) <= 400 else delta_text[:400]
        return [
            event_log.append(
                task_run_id,
                "model_item_received",
                payload={
                    "stream_ref": str(event.get("stream_ref") or ""),
                    "delta_index": int(event.get("delta_index") or 0),
                    "delta_chars": int(event.get("delta_chars") or len(delta_text)),
                    "accumulated_chars": int(event.get("accumulated_chars") or len(delta_text)),
                    "delta_preview": delta_preview,
                    "is_final_chunk": bool(event.get("is_final_chunk") is True),
                },
                refs={"directive_ref": str(event.get("stream_ref") or "")},
            )
        ]
    if event_type == "stream_recovery":
        return [
            event_log.append(
                task_run_id,
                "model_stream_recovery",
                payload={
                    "status": str(event.get("status") or ""),
                    "reason": str(event.get("reason") or ""),
                    "code": str(event.get("code") or ""),
                    "provider": str(event.get("provider") or ""),
                    "model": str(event.get("model") or ""),
                    "detail": str(event.get("detail") or ""),
                    "partial_delta_count": int(event.get("partial_delta_count") or 0),
                    "fallback_timeout_seconds": float(event.get("fallback_timeout_seconds") or 0),
                },
                refs={"directive_ref": str(event.get("directive_ref") or "")},
            )
        ]
    if event_type == "model_protocol_violation":
        return [
            event_log.append(
                task_run_id,
                "model_protocol_violation",
                payload={
                    "content": str(event.get("content") or ""),
                    "protocol_leak": dict(event.get("protocol_leak") or {}),
                    "answer_source": str(event.get("answer_source") or ""),
                },
                refs={"directive_ref": str(event.get("directive_ref") or "")},
            )
        ]
    if event_type == "output_boundary":
        return [
            event_log.append(
                task_run_id,
                "output_boundary_applied",
                payload={"output": dict(event.get("output") or {})},
            )
        ]
    if event_type == "runtime_commit_gate":
        commit_gate = dict(event.get("commit_gate") or {})
        return [
            event_log.append(
                task_run_id,
                "commit_gate_checked",
                payload={"commit_gate": commit_gate},
                refs={
                    "commit_gate_ref": str(commit_gate.get("gate_id") or ""),
                    "commit_type": str(commit_gate.get("commit_type") or ""),
                },
            )
        ]
    return None


def append_model_answer_observation(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    event: dict[str, Any],
) -> list[Any]:
    observation = build_model_response_observation(task_run_id, event)
    context_record = runtime_context_manager.record_observation(observation)
    return [
        append_executor_observation_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=observation,
            context_record=context_record,
            refs={"directive_ref": observation.directive_ref},
        )
    ]


def append_executor_error_observation(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    event: dict[str, Any],
) -> list[Any]:
    observation = build_executor_error_observation(task_run_id, event)
    context_record = runtime_context_manager.record_observation(observation)
    return [
        event_log.append(
            task_run_id,
            "loop_error",
            payload={
                "observation": observation.to_dict(),
                "context_record": context_record.to_dict(),
                "error": str(event.get("error") or ""),
                "answer_source": str(event.get("answer_source") or ""),
            },
            refs={"observation_ref": observation.observation_id},
        )
    ]


def append_executor_observation_event(
    *,
    event_log: Any,
    task_run_id: str,
    observation: RuntimeObservation,
    context_record: Any,
    refs: dict[str, Any] | None = None,
) -> Any:
    event_refs = {
        **dict(refs or {}),
        "observation_ref": observation.observation_id,
    }
    return event_log.append(
        task_run_id,
        "executor_observation_received",
        payload={
            "observation": observation.to_dict(),
            "context_record": context_record.to_dict(),
            "source": observation.source,
            "content_chars": observation.content_chars,
        },
        refs=event_refs,
    )


def append_tool_result_received_event(
    *,
    event_log: Any,
    task_run_id: str,
    observation: RuntimeObservation,
    context_record: Any,
    refs: dict[str, Any] | None = None,
) -> Any:
    return event_log.append(
        task_run_id,
        "tool_result_received",
        payload={
            "observation": observation.to_dict(),
            "context_record": context_record.to_dict(),
        },
        refs={
            **dict(refs or {}),
            "observation_ref": observation.observation_id,
        },
    )


def build_search_policy_blocked_tool_observation(
    *,
    task_run_id: str,
    action_request: Any,
    result: str = "工具调用被本轮权限开关阻止：当前来源未授权。",
) -> RuntimeObservation:
    tool_call = dict(action_request.payload.get("tool_call") or {})
    tool_name = str(action_request.payload.get("tool_name") or "")
    return build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=action_request.request_id,
        directive_ref=action_request.directive_ref,
        tool_name=tool_name,
        tool_call_id=str(tool_call.get("id") or action_request.request_id),
        tool_args=dict(tool_call.get("args") or {}),
        result=result,
        result_envelope={
            "status": "error",
            "synthetic_tool_result": True,
            "source": "runtime.execution_engine.search_policy_guard",
        },
    )
