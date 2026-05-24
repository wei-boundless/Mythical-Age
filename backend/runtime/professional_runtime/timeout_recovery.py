from __future__ import annotations

from typing import Any

from runtime.shared.action_request import RuntimeObservation, build_tool_result_observation


def build_timeout_recovery_observation(
    *,
    task_run_id: str,
    directive_ref: str,
    stage_summary: dict[str, Any],
    suggested_tool_names: list[str] | tuple[str, ...] = (),
) -> RuntimeObservation:
    payload = {
        "type": "runtime_timeout_observation",
        "reason": "model_response_timeout",
        "stage_summary": dict(stage_summary or {}),
        "suggested_tool_names": [str(item) for item in list(suggested_tool_names or []) if str(item).strip()],
        "repair_instruction": (
            "上一轮模型响应超时。请根据阶段总结继续推进真实任务；如果需要工具，请自主选择合适工具，"
            "不要重复已经失败或无推进的动作。"
        ),
    }
    return build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=f"timeout:{task_run_id}",
        directive_ref=directive_ref,
        tool_name="runtime_timeout",
        tool_call_id=f"timeout:{task_run_id}",
        tool_args={},
        result=payload,
        result_envelope={
            "status": "error",
            "tool_name": "runtime_timeout",
            "tool_args": {},
            "structured_payload": payload,
        },
    )


def timeout_recovery_messages(
    *,
    user_message: str,
    timeout_observation: RuntimeObservation,
) -> list[dict[str, Any]]:
    payload = dict(timeout_observation.payload or {})
    return [
        {
            "role": "system",
            "content": (
                "上一轮在等待模型输出时超时。你需要继续当前专业任务。"
                "下面是运行时给出的结构化 timeout observation；它只包含真实观察和缺口，不替你决定工具。"
            ),
        },
        {"role": "user", "content": str(user_message or "")},
        {"role": "system", "content": "runtime_timeout_observation=" + repr(payload)},
    ]
